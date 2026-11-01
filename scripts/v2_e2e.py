"""v2 end-to-end check: screening verdict + summary + date window + related-party discovery, child screening, PDF.
Usage: python scripts/v2_e2e.py BASE USER PWFILE "Name|{json ids}" [...] [--screen-child]
The password is read from PWFILE and never printed."""
import json
import subprocess
import sys
import time

import httpx

base, user, pwfile = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3]
subjects = [a for a in sys.argv[4:] if not a.startswith("--")]
child = "--screen-child" in sys.argv
c = httpx.Client(base_url=base, timeout=90, follow_redirects=True)
r = c.post("/api/auth/login", json={"username": user, "password": open(pwfile).read().strip()}, headers={"Origin": base})
assert r.status_code == 200, f"login {r.status_code}"
H = {"X-CSRF-Token": r.json()["csrf"], "Origin": base}


def wait(sid, limit=420):
    t0 = time.time()
    while c.get(f"/api/screenings/{sid}/progress").json()["job_status"] not in ("completed", "failed"):
        if time.time() - t0 > limit:
            raise SystemExit(f"TIMEOUT {sid}")
        time.sleep(3)
    return c.get(f"/api/screenings/{sid}").json(), time.time() - t0


out = {}
for spec in subjects:
    name, _, ids = spec.partition("|")
    r = c.post("/api/screenings", json={"subject_type": "entity", "name": name, "identifiers": json.loads(ids or "{}")}, headers=H)
    assert r.status_code == 200, r.text
    s, dt = wait(r.json()["id"])
    sm = s["metrics"].get("summary") or {}
    print(f"\n=== {name} → {s['id']} {s['final_status']} in {dt:.0f}s counts={s['counts']}")
    print("   label:", sm.get("label"), "|", sm.get("one_line"))
    print("   window:", s["metrics"].get("lookback_years"), "since", s["metrics"].get("window_start"), "| summary mode:", sm.get("mode"))
    print("   providers:", [(p["id"], p["status"], p.get("results")) for p in s["provider_runs"]])
    rel = s["related_parties"]
    print(f"   related parties: {len(rel)}")
    for p in rel:
        print(f"     - {p['name']} | {p['party_type']} | {p['role_label']}{' ' + p['ownership_pct'] + '%' if p['ownership_pct'] else ''}"
              f"{' via ' + p['via'] if p['via'] else ''} | {p['confidence']} | {p['evidence'][0]['source'] if p['evidence'] else ''}")
    disc = s["metrics"].get("related_discovery") or {}
    print("   discovery sources:", [(x.get("source"), x.get("status")) for x in disc.get("sources", [])])
    out[name] = s
    if child:
        cand = next((p for p in rel if p["party_type"] == "individual" and not p["partial_name"] and len(p["name"].split()) >= 2), None)
        if cand:
            r = c.post(f"/api/related-parties/{cand['id']}/screen", json={}, headers=H)
            print(f"   child screen of {cand['name']}: {r.status_code}")
            if r.status_code == 200:
                cs, cdt = wait(r.json()["id"])
                print(f"   child {cs['id']} → {cs['final_status']} in {cdt:.0f}s parent={cs.get('parent')}")
                s = c.get(f"/api/screenings/{s['id']}").json()
                print("   parent related_summary:", {k: s["related_summary"][k] for k in ("total", "completed", "highest", "overall_note")})
    pdf = c.get(f"/api/screenings/{s['id']}/report.pdf")
    open(f"/tmp/{s['id']}.pdf", "wb").write(pdf.content)
    txt = subprocess.run(["pdftotext", "-layout", f"/tmp/{s['id']}.pdf", "-"], capture_output=True, text=True).stdout
    print("   PDF:", len(pdf.content), "bytes; has summary:", "Consolidated summary" in txt, "| window:", "Date window" in txt,
          "| related table:", "Related parties" in txt)
json.dump({k: v["id"] for k, v in out.items()}, open("/tmp/v2_ids.json", "w"))
