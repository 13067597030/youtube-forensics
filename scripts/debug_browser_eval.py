"""Debug Playwright evaluate return value."""
import json
from pathlib import Path

from yt_forensics.analytics.browser_harvest import create_studio_browser_context
from yt_forensics.analytics.browser_scripts import _RUN_FETCH_JS
from yt_forensics.cookie.load import load_from_file

CHANNEL = "UCIx-2w5LaY1rrFcVvecF6hQ"
cookies, _ = load_from_file(Path("data/cookies.txt"))

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    raise SystemExit("no playwright")

ids = ["UrSvr8ADW7I", "L6TSaHS4jYM"]

with sync_playwright() as p:
    browser, ctx = create_studio_browser_context(
        p, cookies, headless=True, cookie_file=Path("data/cookies.txt")
    )
    page = ctx.new_page()
    page.goto(
        f"https://studio.youtube.com/channel/{CHANNEL}/videos",
        wait_until="networkidle",
        timeout=120000,
    )
    try:
        page.wait_for_function("() => window.__yf_auth != null", timeout=30000)
    except Exception:
        pass
    page.wait_for_timeout(3000)
    out = page.evaluate(_RUN_FETCH_JS, {"videoIds": ids, "channelId": CHANNEL})
    browser.close()

safe = {k: v for k, v in out.items() if k not in ("results", "cardResults", "passiveBodies")}
safe["results_count"] = len(out.get("results") or [])
safe["cardResults_count"] = len(out.get("cardResults") or [])
safe["passive_count"] = len(out.get("passiveBodies") or [])
if out.get("results"):
    v0 = out["results"][0]
    safe["result0_keys"] = list(v0.keys())
    safe["result0_metrics"] = v0.get("metrics")
if out.get("cardResults"):
    safe["card0_keys"] = list(out["cardResults"][0].keys())[:15]
print(json.dumps(safe, ensure_ascii=False, indent=2))
