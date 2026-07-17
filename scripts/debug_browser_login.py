"""Check Playwright login state and auth capture."""
import json
from pathlib import Path

from yt_forensics.analytics.browser_harvest import create_studio_browser_context
from yt_forensics.cookie.load import load_from_file

CHANNEL = "UCIx-2w5LaY1rrFcVvecF6hQ"
cookies, _ = load_from_file(Path("data/cookies.txt"))

from playwright.sync_api import sync_playwright

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
    page.wait_for_timeout(5000)
    info = page.evaluate(
        """
    () => ({
      url: location.href,
      title: document.title,
      webdriver: navigator.webdriver,
      hasAuth: !!window.__yf_auth,
      payloadCount: (window.__yf_payloads || []).length,
      hasYtcfg: !!(window.ytcfg && window.ytcfg.data_),
      apiKey: !!(window.ytcfg && window.ytcfg.data_ && window.ytcfg.data_.INNERTUBE_API_KEY),
      hasStudioApp: !!document.querySelector('ytcp-app'),
      bodyLen: document.body ? document.body.innerText.length : 0,
      unsupported: (document.body && document.body.innerText || '').includes('unsupported'),
      signIn: (document.body && document.body.innerText || '').toLowerCase().includes('sign in'),
    })
    """
    )
    print(json.dumps(info, ensure_ascii=False, indent=2))
    if info.get("payloadCount"):
        urls = page.evaluate("() => (window.__yf_payloads || []).map(p => p.url).slice(0,10)")
        print("payload urls", urls)
    browser.close()
