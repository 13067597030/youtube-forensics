"""Cookie / Studio 会话健康检查。"""

from __future__ import annotations

import logging

from yt_forensics.cookie.session import USER_AGENT, YTSession

logger = logging.getLogger(__name__)

STUDIO_ORIGIN = "https://studio.youtube.com"


def check_youtube_login(session: YTSession) -> tuple[bool, str]:
    if session.logged_in:
        return True, "logged_in"
    return False, "not_logged_in"


def check_studio_access(session: YTSession) -> tuple[bool, str]:
    """确认 httpx 会话能打开 Studio 而非跳转登录。"""
    try:
        resp = session.client.get(
            STUDIO_ORIGIN + "/",
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html",
                **session.auth_headers(STUDIO_ORIGIN),
            },
            follow_redirects=True,
            timeout=45.0,
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"studio_request_failed:{exc}"

    final_url = str(resp.url).lower()
    if "accounts.google.com" in final_url or "servicelogin" in final_url:
        return False, "studio_redirect_login"
    text = resp.text or ""
    if "INNERTUBE_API_KEY" not in text and "ytcp-app" not in text:
        if "unsupported" in text.lower()[:2000]:
            return False, "studio_unsupported_browser_page"
        return False, "studio_page_incomplete"
    return True, "ok"


def summarize_cookie_health(session: YTSession) -> dict[str, str]:
    yt_ok, yt_reason = check_youtube_login(session)
    studio_ok, studio_reason = check_studio_access(session)
    return {
        "youtube": yt_reason if yt_ok else f"fail:{yt_reason}",
        "studio": studio_reason if studio_ok else f"fail:{studio_reason}",
    }
