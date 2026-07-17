"""从 Playwright 专用 Profile 导出 Cookie 供 httpx 使用。"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from yt_forensics.config import Settings
from yt_forensics.cookie.browser_profile import (
    dedicated_profile_dir,
    profile_is_initialized,
    storage_state_path,
)
from yt_forensics.cookie.session import (
    bootstrap_session,
    filter_relevant_cookie_rows,
    load_storage_state_rows,
    rows_to_lookup_dict,
)

logger = logging.getLogger(__name__)

_STEALTH_INIT_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = { runtime: {} };
"""


def export_cookies_from_profile(settings: Settings) -> tuple[list[dict], str]:
    """
    从专用 Profile 读取 Cookie 行（含 domain/path）。
    优先 storage_state 快照；否则 Playwright 打开 Profile 导出并更新快照。
    """
    browser = settings.playwright_browser or settings.cookie_browser or "chrome"
    profile_dir = dedicated_profile_dir(settings.data_dir, browser)
    if not profile_is_initialized(profile_dir):
        raise RuntimeError(
            f"专用浏览器 Profile 未初始化: {profile_dir}。"
            "请先运行: python scripts/bootstrap_browser_profile.py"
        )

    state_path = storage_state_path(settings.data_dir)
    if state_path.is_file():
        try:
            rows = load_storage_state_rows(state_path)
            if _rows_have_valid_studio_session(rows):
                logger.info("从 storage_state 读取 Cookie rows=%s", len(rows))
                return rows, f"storage_state:{state_path.name}"
            logger.warning("storage_state 会话已失效（Studio 不可用），从 Profile 重新导出…")
        except Exception as exc:  # noqa: BLE001
            logger.debug("storage_state 无效，重新导出: %s", exc)

    if sys.platform == "win32":
        try:
            from yt_forensics.cookie.chromium_win import load_from_dedicated_profile

            cookies, detail = load_from_dedicated_profile(profile_dir)
            if cookies:
                rows = _dict_to_rows(cookies)
                _save_storage_state(settings.data_dir, rows)
                logger.info("从专用 Profile DB 读取 Cookie rows=%s", len(rows))
                return rows, detail
        except Exception as exc:  # noqa: BLE001
            logger.debug("专用 Profile DB 读取失败，尝试 Playwright: %s", exc)

    return _export_via_playwright(profile_dir, browser, settings.data_dir)


def save_profile_storage_state(settings: Settings) -> Path:
    """bootstrap 后调用：从 Profile 导出 storage_state 快照。"""
    browser = settings.playwright_browser or settings.cookie_browser or "chrome"
    profile_dir = dedicated_profile_dir(settings.data_dir, browser)
    _export_via_playwright(profile_dir, browser, settings.data_dir)
    return storage_state_path(settings.data_dir)


def _rows_have_valid_studio_session(rows: list[dict]) -> bool:
    """storage_state 快照是否仍能访问 Studio（过期则返回 False）。"""
    from yt_forensics.cookie.health import check_studio_access, check_youtube_login

    session = bootstrap_session(cookie_rows=rows)
    try:
        yt_ok, _ = check_youtube_login(session)
        studio_ok, reason = check_studio_access(session)
        if not yt_ok:
            logger.debug("storage_state YouTube 未登录")
            return False
        if not studio_ok:
            logger.debug("storage_state Studio 不可用: %s", reason)
            return False
        return True
    finally:
        session.close()


def _dict_to_rows(cookies: dict[str, str]) -> list[dict]:
    """本地 DB 解密结果缺少 domain 时，写入常见域（回退）。"""
    rows: list[dict] = []
    for name, value in cookies.items():
        for domain in (".youtube.com", ".google.com"):
            rows.append(
                {
                    "name": name,
                    "value": value,
                    "domain": domain,
                    "path": "/",
                    "secure": True,
                    "httpOnly": False,
                    "sameSite": "Lax",
                }
            )
    return rows


def _save_storage_state(data_dir: Path, rows: list[dict]) -> None:
    path = storage_state_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"cookies": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("已写入 storage_state: %s rows=%s", path, len(rows))


def _export_via_playwright(
    profile_dir: Path,
    browser: str,
    data_dir: Path,
) -> tuple[list[dict], str]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("未安装 playwright") from exc

    channel = browser if browser in ("chrome", "msedge") else "chrome"
    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                str(profile_dir),
                channel=channel,
                headless=True,
                ignore_default_args=["--enable-automation"],
                args=["--disable-blink-features=AutomationControlled"],
            )
            context.add_init_script(_STEALTH_INIT_JS)
            page = context.new_page()
            page.goto("https://www.youtube.com/", wait_until="domcontentloaded", timeout=90_000)
            page.wait_for_timeout(1000)
            page.goto("https://studio.youtube.com/", wait_until="domcontentloaded", timeout=90_000)
            page.wait_for_timeout(2000)
            if "accounts.google.com" in page.url:
                context.close()
                raise RuntimeError("专用 Profile 未登录 Studio，请重新运行 bootstrap 登录")
            rows = filter_relevant_cookie_rows(context.cookies())
            context.close()
    except RuntimeError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"Playwright 无法打开专用 Profile（可能专用 Chrome 仍开着）: {exc}。"
            "请关闭 data/browser_profile 对应的 Chrome 窗口后重试。"
        ) from exc

    if not rows:
        raise RuntimeError("专用 Profile 中无 YouTube/Google Cookie，请重新 bootstrap 登录")

    _save_storage_state(data_dir, rows)
    detail = f"playwright_profile:{profile_dir.name}"
    logger.info(
        "从专用 Profile 导出 Cookie rows=%s lookup=%s",
        len(rows),
        len(rows_to_lookup_dict(rows)),
    )
    return rows, detail
