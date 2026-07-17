"""M2: Cookie 获取与校验。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from yt_forensics.config import Settings
from yt_forensics.cookie.browser_profile import dedicated_profile_dir, profile_is_initialized
from yt_forensics.cookie.health import check_studio_access, check_youtube_login, summarize_cookie_health
from yt_forensics.cookie.load import load_from_chrome, load_from_edge, load_from_file
from yt_forensics.cookie.profile_sync import export_cookies_from_profile
from yt_forensics.cookie.session import YTSession, bootstrap_session

logger = logging.getLogger(__name__)


@dataclass
class CookieResult:
    ok: bool
    source: str  # chrome_auto | playwright_profile | import_file | unknown
    account_email: str = ""
    error: str = ""
    detail: str = ""
    session: YTSession | None = None
    health: dict[str, str] | None = None

    def close(self) -> None:
        if self.session is not None:
            self.session.close()
            self.session = None


def acquire_cookies(
    cookie_file: Path | None = None,
    *,
    settings: Settings | None = None,
) -> CookieResult:
    """
    Cookie 获取策略：
    1. 命令行显式 --cookie-file → 仅使用文件
    2. prefer_browser → 读本机 Chrome/Edge 数据库
    3. 专用 Playwright Profile 导出（Chrome v20 推荐）
    4. file_fallback → data/cookies.txt / data/cookies.json
    """
    cfg = settings or Settings()
    data_dir = cfg.data_dir
    profile_dir = dedicated_profile_dir(data_dir, cfg.cookie_browser)
    profile_ready = profile_is_initialized(profile_dir)

    if cookie_file is not None:
        result = _from_file(Path(cookie_file))
        if result.ok and cfg.cookie_health_check:
            _attach_health(result)
        return result

    if cfg.cookie_prefer_browser:
        result = _from_browser_auto(cfg.cookie_browser)
        if result.ok:
            if cfg.cookie_health_check:
                _attach_health(result)
            return result
        logger.warning("浏览器实时读取 Cookie 失败: %s", result.error)

        result = _from_playwright_profile(cfg)
        if result.ok:
            if cfg.cookie_health_check:
                _attach_health(result)
            return result
        logger.warning("专用 Profile 导出 Cookie 失败: %s", result.error)

        if profile_ready and cfg.playwright_use_chrome_profile:
            return CookieResult(
                ok=False,
                source="playwright_profile",
                error=(
                    "专用 Profile 已存在但当前无法读取。"
                    "请【关闭】 bootstrap 打开的专用 Chrome 窗口（不是日常 Chrome），然后重试。"
                    f" 详情: {result.error}"
                ),
            )

    if cfg.cookie_file_fallback and not profile_ready:
        for fallback in (data_dir / "cookies.txt", data_dir / "cookies.json"):
            if fallback.is_file():
                logger.info("回退 Cookie 文件: %s", fallback)
                fb = _from_file(fallback)
                if fb.ok:
                    if cfg.cookie_health_check:
                        _attach_health(fb)
                    return fb

    return CookieResult(
        ok=False,
        source="unknown",
        error=(
            "未找到可用 Cookie。"
            "Chrome v20 请运行: python scripts/bootstrap_browser_profile.py；"
            "或导出 cookies.txt 并使用 --cookie-file"
        ),
    )


def _from_browser_auto(browser: str) -> CookieResult:
    loaders = []
    if browser == "edge":
        loaders.append((load_from_edge, "edge_auto"))
    else:
        loaders.append((load_from_chrome, "chrome_auto"))
    if browser != "edge":
        loaders.append((load_from_edge, "edge_auto"))

    last_err = ""
    for loader, src in loaders:
        try:
            cookies, detail = loader()
            session = bootstrap_session(cookies)
            return CookieResult(
                ok=True,
                source=src,
                account_email=session.account_email,
                detail=detail,
                session=session,
            )
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
            logger.warning("%s 失败: %s", loader.__name__, exc)

    hint = (
        f"{last_err}。"
        "请完全退出 Chrome/Edge 后重试；Chrome v20 请使用专用 Profile bootstrap。"
    )
    return CookieResult(ok=False, source="chrome_auto", error=hint)


def _from_playwright_profile(cfg: Settings) -> CookieResult:
    if not cfg.playwright_use_chrome_profile:
        return CookieResult(ok=False, source="playwright_profile", error="disabled")
    try:
        cookies, detail = export_cookies_from_profile(cfg)
        session = bootstrap_session(cookie_rows=cookies)
        result = CookieResult(
            ok=True,
            source="playwright_profile",
            account_email=session.account_email,
            detail=detail,
            session=session,
        )
        if cfg.cookie_health_check:
            _attach_health(result)
            studio_ok, studio_reason = check_studio_access(session)
            if not studio_ok:
                session.close()
                result.session = None
                return CookieResult(
                    ok=False,
                    source="playwright_profile",
                    error=(
                        f"Studio 会话无效 ({studio_reason})。"
                        "请运行: python scripts/bootstrap_browser_profile.py 重新登录，"
                        "并关闭专用 Chrome 后重试。"
                    ),
                )
        return result
    except Exception as exc:  # noqa: BLE001
        return CookieResult(ok=False, source="playwright_profile", error=str(exc))


def _from_file(path: Path) -> CookieResult:
    source = "import_file"
    try:
        cookies, detail = load_from_file(path)
        session = bootstrap_session(cookies)
        return CookieResult(
            ok=True,
            source=source,
            account_email=session.account_email,
            detail=detail,
            session=session,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("导入 Cookie 失败: %s", exc)
        return CookieResult(ok=False, source=source, error=str(exc))


def _attach_health(result: CookieResult) -> None:
    if result.session is None:
        return
    health = summarize_cookie_health(result.session)
    result.health = health
    yt_ok, _ = check_youtube_login(result.session)
    studio_ok, studio_reason = check_studio_access(result.session)
    logger.info(
        "Cookie 健康检查 youtube=%s studio=%s",
        health.get("youtube"),
        health.get("studio"),
    )
    if not yt_ok:
        logger.warning("YouTube 未登录或会话无效")
    if not studio_ok:
        logger.warning(
            "Studio 不可访问 (%s)；Analytics/收入字段可能失败，请确认已登录 studio.youtube.com",
            studio_reason,
        )
