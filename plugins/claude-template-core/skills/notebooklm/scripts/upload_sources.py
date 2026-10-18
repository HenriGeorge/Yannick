import atexit
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from browser_utils import BrowserFactory
from patchright.sync_api import sync_playwright

NOTEBOOK_URL = sys.argv[1]
FILES = sys.argv[2:]

# Per-run 0700 dir (mkdtemp) — screenshots capture private notebook + logged-in
# Google UI, so never fixed world-predictable /tmp paths (info-disclosure + symlink-clobber).
SHOTDIR = tempfile.mkdtemp(prefix="nblm_")
atexit.register(lambda: shutil.rmtree(SHOTDIR, ignore_errors=True))


def log(*a):
    print(*a, flush=True)


def shot(page, n):
    try:
        page.screenshot(path=os.path.join(SHOTDIR, f"{n}.png"))
    except Exception:
        pass


with sync_playwright() as p:
    ctx = BrowserFactory.launch_persistent_context(p, headless=False)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.set_default_timeout(20000)
    page.goto(NOTEBOOK_URL, wait_until="domcontentloaded")
    time.sleep(6)
    log("title:", page.title())

    for sel in ['[role="tab"]:has-text("Bronnen")', 'button:has-text("Bronnen")']:
        try:
            e = page.locator(sel).first
            if e.count() and e.is_visible():
                e.click()
                break
        except Exception:
            pass
    time.sleep(2)

    for sel in ['button:has-text("Toevoegen")', 'button:has-text("Bron toevoegen")', 'button[aria-label*="toevoeg" i]']:
        try:
            e = page.locator(sel).first
            if e.count() and e.is_visible():
                e.click()
                log("opened dialog via", sel)
                break
        except Exception:
            pass
    time.sleep(3)

    # click "Bestanden uploaden" and catch the file chooser
    try:
        with page.expect_file_chooser(timeout=15000) as fc_info:
            page.locator('button:has-text("Bestanden uploaden")').first.click()
        fc = fc_info.value
        fc.set_files(FILES)
        log("file_chooser.set_files OK ->", len(FILES))
    except Exception as e:
        log("file_chooser FAIL:", type(e).__name__, str(e)[:200])
        # fallback: maybe a hidden input appeared
        try:
            page.locator('input[type="file"]').first.set_input_files(FILES)
            log("fallback input OK")
        except Exception as e2:
            log("fallback FAIL:", type(e2).__name__)
            shot(page, "6fail")
            ctx.close()
            sys.exit(2)

    time.sleep(18)
    shot(page, "7done")
    log(f"done -> {os.path.join(SHOTDIR, '7done.png')}")
    ctx.close()
