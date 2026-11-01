"""API-level tests: workflow, fixtures, fault injection, hallucination guard, PDF, audit chain, RBAC/auth/CSRF."""
import subprocess
import tempfile

from conftest import ALL_PROVIDERS_DOWN, ADMIN_PW, login, wait_done

HQB = {"subject_type": "individual", "name": "Halvard Quennell-Broome", "identifiers": {"dob": "1971-03-14", "nationality": "United Kingdom"}}


def screen(s, body):
    r = s.post("/api/screenings", json=body)
    assert r.status_code == 200, r.text
    return wait_done(s, r.json()["id"])


# ---------- tests 1/2/4 analogues on controlled fixtures ----------
def test_fixture_red_with_corroboration_and_mitigation(admin):
    d = screen(admin, HQB | {"test_fixture_set": "mixed_individual"})
    assert d["job_status"] == "completed" and d["test_mode"]
    assert d["auto_status"] == "RED", d["auto_reasons"]
    mat = [f for f in d["findings"] if f["material"]]
    assert mat and all(f["identity_level"] in ("probable", "confirmed") for f in mat)
    assert mat[0]["independent_sources"] >= 2  # syndicated copies clustered and counted as corroboration
    assert any(f["bucket"] == "mitigating" for f in d["findings"])           # acquittal
    assert any(f["bucket"] == "low" and f["implication"] == "bystander" for f in d["findings"])  # victim
    assert all(".example/" in f["url"] for f in d["findings"])               # fixtures are never real-looking sources


def test_fixture_green_clean(admin):
    d = screen(admin, HQB | {"test_fixture_set": "clean_individual"})
    assert d["auto_status"] == "GREEN", d["auto_reasons"]


def test_common_name_is_amber_unresolved(admin):
    d = screen(admin, {"subject_type": "individual", "name": "John Smith", "identifiers": {}, "test_fixture_set": "common_name"})
    assert d["auto_status"] == "AMBER"
    assert not any(f["material"] for f in d["findings"])
    assert all(f["identity_level"] in ("possible", "unlikely") for f in d["findings"] if f["relevant"])


# ---------- test 9: dedupe ----------
def test_dedupe_syndication(admin):
    d = screen(admin, {"subject_type": "entity", "name": "Corvina Holdings Ltd", "identifiers": {"jurisdiction": "United Kingdom"},
                       "test_fixture_set": "dedupe_syndication"})
    assert len(d["findings"]) == 2, [f["title"] for f in d["findings"]]
    top = max(d["findings"], key=lambda f: f["independent_sources"])
    assert top["independent_sources"] == 3  # news-t2 (2 urls incl. utm variant), wire-t2b, trade-t3
    assert len(top["corroborating"]) >= 2


# ---------- test 8: fault injection ----------
def test_all_core_down_is_failed_never_green(admin):
    d = screen(admin, HQB | {"fault_injection": ALL_PROVIDERS_DOWN})
    assert d["auto_status"] == "FAILED" and d["final_status"] == "FAILED"
    assert d["findings"] == []
    r = admin.post(f"/api/screenings/{d['id']}/override", json={"status": "GREEN", "reason": "trying to clear a failed run"})
    assert r.status_code == 409
    r = admin.post(f"/api/screenings/{d['id']}/close", json={"disposition": "cleared_no_adverse_media"})
    assert r.status_code == 409


def test_partial_outage_never_green(admin):
    """Only the required core provider (google_news) is up; everything else injected as failed -> incomplete, never GREEN."""
    down = {k: v for k, v in ALL_PROVIDERS_DOWN.items() if k != "google_news"}
    d = screen(admin, {"subject_type": "individual", "name": "Xqvzt Plorbanek", "identifiers": {}, "fault_injection": down}, )
    assert d["auto_status"] in ("AMBER", "FAILED"), d["auto_reasons"]
    assert d["incomplete"]


def test_fixtures_rejected_outside_test_mode(admin, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "test_mode", False)
    r = admin.post("/api/screenings", json=HQB | {"test_fixture_set": "mixed_individual"})
    assert r.status_code == 400
    r = admin.post("/api/screenings", json=HQB | {"fault_injection": {"google_news": "x"}})
    assert r.status_code == 400


# ---------- test 14: no URL that did not come from a provider ----------
def test_finding_urls_subset_of_raw_index(admin):
    from app.db import SessionLocal
    from app.models import Screening
    d = screen(admin, HQB | {"test_fixture_set": "mixed_individual"})
    with SessionLocal() as db:
        raw = {r["url"] for r in db.get(Screening, d["id"]).metrics["raw_index"]}
    for f in d["findings"]:
        assert f["url"] in raw
        for c in f["corroborating"]:
            assert c["url"] in raw
    assert "raw_index" not in d["metrics"]  # not exposed via the API


# ---------- workflow ----------
def test_workflow_decisions_close_reopen(admin):
    d = screen(admin, HQB | {"test_fixture_set": "mixed_individual"})
    sid = d["id"]
    assert admin.post(f"/api/screenings/{sid}/close", json={"disposition": "escalated_edd"}).status_code == 409
    mat = [f["id"] for f in d["findings"] if f["material"]]
    others = [f["id"] for f in d["findings"] if f["bucket"] == "review" and not f["material"]]
    r = admin.post(f"/api/screenings/{sid}/bulk-decision", json={"finding_ids": mat, "decision": "false_positive", "reason": "bulk"})
    assert r.status_code == 409  # material findings must be decided individually
    for fid in mat:
        assert admin.post(f"/api/findings/{fid}/decision", json={"decision": "true_match", "reason": "DOB and town match"}).status_code == 200
    if others:
        assert admin.post(f"/api/screenings/{sid}/bulk-decision",
                          json={"finding_ids": others, "decision": "false_positive", "reason": "not subject"}).status_code == 200
    assert admin.post(f"/api/screenings/{sid}/close", json={"disposition": "escalated_edd", "notes": "EDD"}).status_code == 200
    assert admin.post(f"/api/findings/{mat[0]}/decision", json={"decision": "unresolved", "reason": "x y z"}).status_code == 409
    assert admin.post(f"/api/screenings/{sid}/reopen", json={"reason": "new information"}).status_code == 200
    r = admin.post(f"/api/screenings/{sid}/override", json={"status": "AMBER", "reason": "analyst judgement documented"})
    assert r.status_code == 200
    assert admin.get(f"/api/screenings/{sid}").json()["final_status"] == "AMBER"


# ---------- test 11: PDF ----------
def test_pdf_report(admin):
    d = screen(admin, HQB | {"test_fixture_set": "mixed_individual"})
    r = admin.get(f"/api/screenings/{d['id']}/report.pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content[:5] == b"%PDF-" and len(r.content) > 5000
    with tempfile.NamedTemporaryFile(suffix=".pdf") as fh:
        fh.write(r.content)
        fh.flush()
        txt = subprocess.run(["pdftotext", fh.name, "-"], capture_output=True, text=True).stdout
    assert d["id"] in txt and "RED" in txt and "TEST" in txt.upper()
    assert ".fixture.example" in txt


# ---------- test 12: audit chain + tamper detection ----------
def test_audit_chain_and_tamper_detection(admin):
    v = admin.get("/api/audit/verify").json()
    assert v["valid"] and v["entries"] > 0
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models import AuditEntry
    with SessionLocal() as db:
        row = db.execute(select(AuditEntry).order_by(AuditEntry.seq.desc()).limit(1)).scalar_one()
        orig = row.details
        row.details = {**(orig or {}), "tampered": True}
        db.commit()
        bad = admin.get("/api/audit/verify").json()
        assert not bad["valid"] and bad["broken_at"] == row.seq
        row.details = orig
        db.commit()
    assert admin.get("/api/audit/verify").json()["valid"]


# ---------- test 13: RBAC / auth / CSRF ----------
def test_unauthenticated_rejected(client):
    client.cookies.clear()
    for path in ("/api/screenings", "/api/audit", "/api/admin/users", "/api/meta", "/api/auth/me"):
        assert client.get(path).status_code == 401, path
    assert client.post("/api/screenings", json=HQB).status_code in (401, 403)


def test_bad_password_and_no_password_echo(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"username": "admin", "password": "wrong-password"})
    assert r.status_code == 401 and "wrong-password" not in r.text
    r = client.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PW})
    assert r.status_code == 200 and ADMIN_PW not in r.text
    assert "httponly" in r.headers["set-cookie"].lower() and "samesite=strict" in r.headers["set-cookie"].lower()


def test_csrf_required_and_origin_checked(admin):
    c = admin.c
    assert c.post("/api/screenings", json=HQB | {"test_fixture_set": "clean_individual"}).status_code == 403
    r = c.post("/api/screenings", json=HQB | {"test_fixture_set": "clean_individual"},
               headers={"X-CSRF-Token": admin.csrf, "Origin": "https://evil.example"})
    assert r.status_code == 403


def test_rbac_roles(client):
    a = login(client, "admin", ADMIN_PW)
    for u, role in (("reader1", "readonly"), ("analyst1", "analyst")):
        r = a.post("/api/admin/users", json={"username": u, "password": "Str0ng-Passw0rd-123!", "role": role})
        assert r.status_code in (200, 409), r.text
    ro = login(client, "reader1", "Str0ng-Passw0rd-123!")
    assert ro.get("/api/screenings").status_code == 200
    assert ro.post("/api/screenings", json=HQB | {"test_fixture_set": "clean_individual"}).status_code == 403
    assert ro.get("/api/admin/users").status_code == 403
    an = login(client, "analyst1", "Str0ng-Passw0rd-123!")
    assert an.get("/api/admin/users").status_code == 403
    assert an.put("/api/admin/policy", json={"historical_years": 1}).status_code == 403
    r = an.post("/api/screenings", json=HQB | {"test_fixture_set": "clean_individual"})
    assert r.status_code == 200
    wait_done(an, r.json()["id"])


def test_weak_password_rejected(admin):
    r = admin.post("/api/admin/users", json={"username": "weakling", "password": "password", "role": "analyst"})
    assert r.status_code in (400, 422)


def test_account_lockout(client):
    a = login(client, "admin", ADMIN_PW)
    a.post("/api/admin/users", json={"username": "lockme", "password": "Str0ng-Passw0rd-123!", "role": "analyst"})
    client.cookies.clear()
    for _ in range(5):
        assert client.post("/api/auth/login", json={"username": "lockme", "password": "nope"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "lockme", "password": "Str0ng-Passw0rd-123!"}).status_code == 423


def test_security_headers(client):
    r = client.get("/api/health")
    assert r.headers["x-frame-options"] == "DENY" and "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"


def test_ssrf_guard_blocks_private_hosts():
    import asyncio
    from app.research import fetcher
    for u in ("http://127.0.0.1/", "http://169.254.169.254/latest/meta-data", "http://10.0.0.1/", "file:///etc/passwd",
              "http://localhost:8000/"):
        try:
            asyncio.run(fetcher.check_url(u))
            raise AssertionError(f"not blocked: {u}")
        except AssertionError:
            raise
        except Exception:
            pass


def test_audit_never_contains_password(admin):
    rows = admin.get("/api/audit?page_size=200").json()
    assert ADMIN_PW not in str(rows) and "Str0ng-Passw0rd-123!" not in str(rows)
