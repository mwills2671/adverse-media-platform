"""v2 screenshots (desktop 1280 + mobile 390): login, new screening, results tabs, related parties, child screening.
Usage: python scripts/screenshots_v2.py BASE USER PWFILE IDS_JSON [OUTDIR]
IDS_JSON maps label -> screening id. The password is read from PWFILE and never printed."""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

base, user, pwfile, idsf = sys.argv[1:5]
out = Path(sys.argv[5] if len(sys.argv) > 5 else "shots"); out.mkdir(exist_ok=True)
ids = json.load(open(idsf))
pw = Path(pwfile).read_text().strip()
slug = lambda s: "".join(ch.lower() if ch.isalnum() else "_" for ch in s).strip("_")

with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    for w, h, tag in ((1280, 900, "desktop"), (390, 844, "mobile")):
        ctx = b.new_context(viewport={"width": w, "height": h}, device_scale_factor=1)
        pg = ctx.new_page()
        shot = lambda name, full=True: pg.screenshot(path=str(out / f"v2_{name}_{tag}.png"), full_page=full)
        pg.goto(base + "/"); pg.wait_for_selector("input[type=password]"); shot("01_login", full=False)
        pg.fill("input[autocomplete=username]", user); pg.fill("input[type=password]", pw)
        pg.click("form button"); pg.wait_for_selector("text=Sources that will be searched", timeout=15000)
        shot("02_new_screening")
        for label, sid in ids.items():
            pg.goto(f"{base}/screenings/{sid}"); pg.wait_for_selector("text=Consolidated summary", timeout=30000)
            pg.wait_for_timeout(400); n = slug(label)
            shot(f"10_{n}_overview_top", full=False); shot(f"11_{n}_overview")
            for t, key in (("Findings", "findings"), ("Related parties", "related"), ("Sources", "sources"), ("Audit / decision", "audit")):
                pg.get_by_role("tab", name=t, exact=False).first.click(); pg.wait_for_timeout(400)
                shot(f"1{2 + ['findings', 'related', 'sources', 'audit'].index(key)}_{n}_{key}")
        ctx.close()
    b.close()
print("screenshots written to", out)
