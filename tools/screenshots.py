#!/usr/bin/env python3
"""Screenshot the status page in both themes at desktop and phone width.

    python3 tools/screenshots.py [URL] [OUT_DIR]

Needs Playwright (pip install playwright && playwright install chromium).
Screenshots go to out/shots unless OUT_DIR is given.
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8092/"
out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "out" / "shots"
out.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch()
    for scheme in ("light", "dark"):
        for name, width in (("desktop", 1280), ("phone", 400)):
            ctx = browser.new_context(viewport={"width": width, "height": 900}, color_scheme=scheme)
            page = ctx.new_page()
            page.goto(url, wait_until="load")
            page.wait_for_timeout(500)
            path = out / f"{scheme}-{name}.png"
            page.screenshot(path=str(path), full_page=True)
            print(path)
            ctx.close()
    browser.close()
