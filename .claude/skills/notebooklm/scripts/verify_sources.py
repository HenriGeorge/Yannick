import atexit
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from browser_utils import BrowserFactory
from patchright.sync_api import sync_playwright

URL = sys.argv[1]

# Per-run 0700 dir (mkdtemp) — the full-page screenshot captures private notebook
# content, so never a fixed world-predictable /tmp path.
SHOTDIR = tempfile.mkdtemp(prefix="nblm_")
atexit.register(lambda: shutil.rmtree(SHOTDIR, ignore_errors=True))

with sync_playwright() as p:
    ctx = BrowserFactory.launch_persistent_context(p, headless=True)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.set_default_timeout(20000)
    page.goto(URL, wait_until="domcontentloaded")
    time.sleep(7)
    print("TITLE:", page.title())

    # ensure Sources/Bronnen tab
    for sel in ['[role="tab"]:has-text("Bronnen")', 'button:has-text("Bronnen")', '[role="tab"]:has-text("Sources")']:
        try:
            e = page.locator(sel).first
            if e.count() and e.is_visible():
                e.click()
                break
        except Exception:
            pass
    time.sleep(3)

    shot_path = os.path.join(SHOTDIR, "sources.png")
    page.screenshot(path=shot_path, full_page=True)
    print("SCREENSHOT:", shot_path)

    # grab visible text of anything that looks like a source filename
    body = page.inner_text("body")
    mds = sorted(set(re.findall(r"[A-Za-z0-9\-]+\.md", body)))
    print("SOURCE .md FILES VISIBLE:", len(mds))
    for m in mds:
        print("  ", m)
    ctx.close()
