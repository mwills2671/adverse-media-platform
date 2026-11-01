"""Capture UI screenshots at desktop (1280) and mobile (390) widths.
Usage: python scripts/screenshots.py BASE USER PWFILE SCREENING_ID [OUTDIR] [PREFIX]
The password is read from PWFILE and typed into the login form; it is never printed."""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

base, user, pwfile, sid = sys.argv[1:5]
out = Path(sys.argv[5] if len(sys.argv) > 5 else "shots"); out.mkdir(exist_ok=True)
prefix = sys.argv[6] if len(sys.argv) > 6 else ""
pw = Path(pwfile).read_text().strip()

with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    for w, h, tag in ((1280, 900, "desktop"), (390, 844, "mobile")):
        ctx = b.new_context(viewport={"width": w, "height": h}, device_scale_factor=1, ignore_https_errors=True)
        pg = ctx.new_page()
        shot = lambda name, full=True: pg.screenshot(path=str(out / f"{prefix}{name}_{tag}.png"), full_page=full)
        pg.goto(base + "/"); pg.wait_for_selector("input[type=password]")
        shot("01_login")
        pg.fill("input[autocomplete=username]", user); pg.fill("input[type=password]", pw)
        pg.click("form button"); pg.wait_for_selector("text=Sources that will be searched", timeout=15000)
        shot("02_new_screening")
        pg.goto(f"{base}/screenings/{sid}"); pg.wait_for_selector("text=Source coverage", timeout=30000)
        pg.wait_for_timeout(500); shot("03_results", full=False); shot("04_results_full")
        cards = pg.locator("article button[aria-expanded]")
        if cards.count():
            cards.first.click(); pg.wait_for_timeout(300)
            pg.locator("article").first.screenshot(path=str(out / f"{prefix}05_finding_expanded_{tag}.png"))
        pg.goto(base + "/history"); pg.wait_for_selector("text=Screening history"); pg.wait_for_timeout(800); shot("06_history")
        pg.goto(base + "/audit"); pg.wait_for_selector("text=Verify hash chain"); pg.click("text=Verify hash chain")
        pg.wait_for_selector("text=Chain valid", timeout=10000); shot("07_audit", full=False)
        if pg.locator("a[href='/admin']").count() or True:
            pg.goto(base + "/admin"); pg.wait_for_timeout(1200); shot("08_admin", full=False)
        ctx.close()
    b.close()
print("screenshots written to", out)
