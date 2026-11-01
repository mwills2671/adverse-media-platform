"""End-to-end smoke test against a running instance.
Usage: python scripts/smoke.py BASE_URL USERNAME PASSWORD_FILE [subject_type] [name] [identifiers_json]
The password is read from a file and never printed."""
import json
import sys
import time

import httpx

base, user, pwfile = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3]
stype = sys.argv[4] if len(sys.argv) > 4 else "entity"
name = sys.argv[5] if len(sys.argv) > 5 else "Wirecard AG"
ids = json.loads(sys.argv[6]) if len(sys.argv) > 6 else {}
pw = open(pwfile).read().strip()
c = httpx.Client(base_url=base, timeout=60, follow_redirects=True)
ok = lambda cond, msg: print(("PASS " if cond else "FAIL ") + msg)

r = c.get("/")
ok(r.status_code == 200 and "<div id=\"root\"" in r.text, f"SPA/login page served ({r.status_code})")
r = c.get("/api/screenings")
ok(r.status_code == 401, f"unauthenticated list rejected ({r.status_code})")
r = c.post("/api/screenings", json={"subject_type": "entity", "name": "x"})
ok(r.status_code in (401, 403), f"unauthenticated create rejected ({r.status_code})")
r = c.post("/api/auth/login", json={"username": user, "password": "wrong-password"})
ok(r.status_code == 401, f"bad password rejected ({r.status_code})")
r = c.post("/api/auth/login", json={"username": user, "password": pw}, headers={"Origin": base})
ok(r.status_code == 200, f"admin login ({r.status_code})")
csrf = r.json()["csrf"]
r = c.post("/api/screenings", json={"subject_type": stype, "name": name, "identifiers": ids})
ok(r.status_code == 403, f"POST without CSRF header rejected ({r.status_code})")
H = {"X-CSRF-Token": csrf, "Origin": base}
r = c.post("/api/screenings", json={"subject_type": stype, "name": name, "identifiers": ids}, headers=H)
ok(r.status_code == 200, f"screening created ({r.status_code})")
sid = r.json()["id"]
t0 = time.time()
while True:
    pr = c.get(f"/api/screenings/{sid}/progress").json()
    if pr["job_status"] in ("completed", "failed"):
        break
    if time.time() - t0 > 400:
        print("TIMEOUT");
        sys.exit(1)
    time.sleep(3)
s = c.get(f"/api/screenings/{sid}").json()
print(f"{sid}: {s['job_status']} auto={s['auto_status']} final={s['final_status']} incomplete={s['incomplete']} "
      f"in {time.time() - t0:.0f}s counts={s['counts']}")
for r_ in s["provider_runs"]:
    print(f"   {r_['id']:15} {r_['status']:16} {r_.get('results', 0):4} {r_.get('error') or ''}")
for reason in s["auto_reasons"]:
    print("   reason:", reason)
urls = [f["url"] for f in s["findings"]]
ok(all(u.startswith("https://") or u.startswith("http://") for u in urls) and len(urls) > 0, f"{len(urls)} findings with real URLs")
for f in s["findings"][:5]:
    print(f"   [{f['bucket']}/{f['identity_level']}/{f['event_status']}] {f['title'][:90]} <{f['url'][:90]}>")
r = c.get(f"/api/screenings/{sid}/report.pdf")
ok(r.status_code == 200 and r.content[:4] == b"%PDF", f"PDF export ({len(r.content)} bytes)")
open(f"/tmp/{sid}.pdf", "wb").write(r.content)
v = c.get("/api/audit/verify").json()
ok(v["valid"], f"audit chain verifies ({v})")
print("PDF saved to", f"/tmp/{sid}.pdf")
