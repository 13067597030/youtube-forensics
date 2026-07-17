"""Test Playwright persistent Chrome profile (no cookie values printed)."""
import json

from yt_forensics.config import load_settings
from yt_forensics.cookie.browser_profile import (
    chromium_user_data_dir,
    first_usable_profile,
    is_chromium_running,
)
from playwright.sync_api import sync_playwright

STEALTH = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = { runtime: {} };
"""

settings = load_settings()
browser = settings.playwright_browser
print("chrome_running", is_chromium_running(browser))
profile = first_usable_profile(browser)
print("profile", profile)
user_data = chromium_user_data_dir(browser)
profile_name = profile.name if profile else "Default"
print("user_data", user_data, "profile_name", profile_name)
if not user_data.is_dir():
    raise SystemExit("no user data")

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        str(user_data),
        channel="chrome",
        headless=True,
        ignore_default_args=["--enable-automation"],
        args=[
            "--disable-blink-features=AutomationControlled",
            f"--profile-directory={profile_name}",
        ],
    )
    ctx.add_init_script(STEALTH)
    page = ctx.new_page()
    page.goto("https://studio.youtube.com/", wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_timeout(5000)
    info = page.evaluate(
        """() => ({
      url: location.href.slice(0, 120),
      hasYtcfg: !!(window.ytcfg && window.ytcfg.data_),
      hasStudioApp: !!document.querySelector('ytcp-app'),
      signIn: (document.body && document.body.innerText || '').toLowerCase().includes('sign in'),
    })"""
    )
    print(json.dumps(info, ensure_ascii=True))
    ctx.close()
