"""Live acceptance runs (genuine searches) against a running instance.
Usage: python scripts/live_acceptance.py BASE_URL USERNAME PASSWORD_FILE OUT_JSON [case_ids,comma,separated]
The password is read from a file and never printed. Results are real provider output on the run date."""
import json
import sys
import time

import httpx

CASES = [
    {"id": "T1_madoff", "subject_type": "individual", "name": "Bernard Madoff",
     "identifiers": {"dob": "1938-04-29", "nationality": "United States"}, "expect": "RED"},
    {"id": "T2_wirecard", "subject_type": "entity", "name": "Wirecard AG", "identifiers": {"jurisdiction": "Germany"}, "expect": "RED"},
    {"id": "T3_john_smith", "subject_type": "individual", "name": "John Smith", "identifiers": {}, "expect": "AMBER"},
    {"id": "T4_obscure", "subject_type": "individual", "name": "Quillon Dravenmoor-Tesk", "identifiers": {}, "expect": "GREEN"},
    {"id": "T5a_ids_before", "subject_type": "individual", "name": "Nick Leeson", "identifiers": {}, "expect": "AMBER|RED"},
    {"id": "T5b_ids_after", "subject_type": "individual", "name": "Nick Leeson",
     "identifiers": {"dob": "1967-02-25", "nationality": "United Kingdom", "employer": "Barings"}, "expect": "RED"},
]

base, user, pwfile, out = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3], sys.argv[4]
only = set(sys.argv[5].split(",")) if len(sys.argv) > 5 else None
pw = open(pwfile).read().strip()
c = httpx.Client(base_url=base, timeout=90, follow_redirects=True)
r = c.post("/api/auth/login", json={"username": user, "password": pw}, headers={"Origin": base})
r.raise_for_status()
H = {"X-CSRF-Token": r.json()["csrf"], "Origin": base}
results = []
for case in CASES:
    if only and case["id"] not in only:
        continue
    t0 = time.time()
    sid = c.post("/api/screenings", json={k: case[k] for k in ("subject_type", "name", "identifiers")}, headers=H).json()["id"]
    while c.get(f"/api/screenings/{sid}/progress").json()["job_status"] not in ("completed", "failed"):
        if time.time() - t0 > 600:
            break
        time.sleep(3)
    s = c.get(f"/api/screenings/{sid}").json()
    mat = [f for f in s["findings"] if f["material"]]
    rev = [f for f in s["findings"] if f["bucket"] == "review"]
    res = {"case": case["id"], "name": case["name"], "identifiers": case["identifiers"], "expected": case["expect"],
           "screening_id": sid, "status": s["auto_status"], "incomplete": s["incomplete"], "duration_s": round(time.time() - t0),
           "pass": s["auto_status"] in case["expect"].split("|"), "counts": s["counts"],
           "providers": [{"id": p["id"], "status": p["status"], "results": p.get("results", 0), "error": p.get("error")}
                         for p in s["provider_runs"]],
           "reasons": s["auto_reasons"],
           "identity_levels_in_review": sorted({f["identity_level"] for f in rev}),
           "top_material": [{"title": f["title"], "url": f["url"], "domain": f["domain"], "tier": f["credibility_tier"],
                             "status": f["event_status"], "identity": f["identity_level"], "sources": f["independent_sources"]}
                            for f in mat[:5]],
           "top_review": [{"title": f["title"], "url": f["url"], "identity": f["identity_level"], "status": f["event_status"]}
                          for f in rev[:3]]}
    pdf = c.get(f"/api/screenings/{sid}/report.pdf")
    res["pdf_ok"] = pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    open(f"/tmp/{sid}.pdf", "wb").write(pdf.content)
    results.append(res)
    print(f"{case['id']:16} {sid} {res['status']:6} expected={case['expect']:9} {'PASS' if res['pass'] else 'FAIL'} "
          f"{res['duration_s']}s counts={res['counts']} pdf={res['pdf_ok']}")
    for p in res["providers"]:
        print(f"      {p['id']:15} {p['status']:10} {p['results']:4} {(p['error'] or '')[:80]}")
    for m in res["top_material"][:3]:
        print(f"      RED-item [{m['status']}/{m['identity']}/t{m['tier']}/{m['sources']}src] {m['title'][:80]} <{m['url'][:100]}>")
v = c.get("/api/audit/verify").json()
print("audit chain:", v.get("valid"), v.get("entries"))
json.dump({"base": base, "run_at": time.strftime("%Y-%m-%d %H:%M %Z"), "results": results, "audit": v}, open(out, "w"), indent=1)
