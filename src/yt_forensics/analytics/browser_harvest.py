"""Playwright：在 Studio 页面上下文中拦截/复现 Analytics 收入请求。"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from contextlib import contextmanager
from typing import Any, Iterator

from yt_forensics.analytics.browser_cookies import cookies_for_playwright
from yt_forensics.analytics.browser_scripts import (
    _AUTH_HOOK_INIT_JS,
    _CLICK_NEXT_PAGE_JS,
    _LIST_CREATOR_VIDEOS_PAGE_JS,
    _SCrape_CONTENT_REVENUE_JS,
)
from yt_forensics.analytics.parse import parse_creator_video
from yt_forensics.analytics.studio_client import ROLE_BY_PERMISSION
from yt_forensics.config import Settings
from yt_forensics.cookie.browser_profile import dedicated_profile_dir, profile_is_initialized, storage_state_path

logger = logging.getLogger(__name__)

CHANNEL_VIDEOS_PATH = "/channel/{channel_id}/videos"
ROWS_PER_STUDIO_PAGE = 30
LIST_API_PAGE_SIZE = 50
MAX_CONTENT_PAGES = 120
PAGE_WAIT_MS = 800
STALL_PAGE_LIMIT = 3

_STEALTH_INIT_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = { runtime: {} };
"""

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# 从响应 JSON 中提取 video_id -> metrics
REVENUE_KEYS = frozenset(
    {
        "estimatedrevenue",
        "estimatedpartnerrevenue",
        "estimated_partner_revenue",
        "rpm",
        "playbackbasedcpm",
        "playback_based_cpm",
        "cpm",
        "watchtime",
        "watch_time",
        "estimatedminuteswatched",
        "impressions",
        "impressionsctr",
        "ctr",
        "monetizedplaybacks",
        "monetized_playbacks",
    }
)

FIELD_MAP = {
    "estimatedrevenue": "estimated_revenue",
    "estimatedpartnerrevenue": "estimated_revenue",
    "estimated_partner_revenue": "estimated_revenue",
    "rpm": "rpm",
    "playbackbasedcpm": "playback_based_cpm",
    "playback_based_cpm": "playback_based_cpm",
    "cpm": "playback_based_cpm",
    "watchtime": "watch_time",
    "watch_time": "watch_time",
    "estimatedminuteswatched": "watch_time",
    "impressions": "impressions",
    "impressionsctr": "ctr",
    "ctr": "ctr",
    "monetizedplaybacks": "monetized_playbacks",
    "monetized_playbacks": "monetized_playbacks",
    "viewcount": "views",
    "views": "views",
    "externalviewcount": "views",
}


@dataclass
class ChannelBrowserJob:
    channel_id: str
    video_ids: list[str]
    brand_account_id: str = ""
    permission_level: str = "owner"
    channel_title: str = ""


def max_content_pages(video_count: int) -> int:
    if video_count <= 0:
        return 1
    est = (video_count + LIST_API_PAGE_SIZE - 1) // LIST_API_PAGE_SIZE + 1
    return min(MAX_CONTENT_PAGES, max(1, est))


def harvest_revenue_browser(
    cookies: dict[str, str],
    channel_id: str,
    video_ids: list[str],
    *,
    headless: bool = True,
    timeout_ms: int = 120_000,
    cookie_file: Path | None = None,
    settings: Settings | None = None,
    brand_account_id: str = "",
    permission_level: str = "owner",
    channel_title: str = "",
) -> dict[str, dict[str, str]]:
    """单频道入口；内部复用多频道批量浏览器会话。"""
    job = ChannelBrowserJob(
        channel_id=channel_id,
        video_ids=video_ids,
        brand_account_id=brand_account_id,
        permission_level=permission_level,
        channel_title=channel_title or channel_id,
    )
    out = harvest_revenue_browser_batch(
        [job],
        cookies=cookies,
        headless=headless,
        timeout_ms=timeout_ms,
        cookie_file=cookie_file,
        settings=settings,
    )
    return out.get(channel_id, {})


def harvest_revenue_browser_batch(
    jobs: list[ChannelBrowserJob],
    *,
    cookies: dict[str, str],
    headless: bool = True,
    timeout_ms: int = 120_000,
    cookie_file: Path | None = None,
    settings: Settings | None = None,
) -> dict[str, dict[str, dict[str, str]]]:
    """一次 Playwright 会话顺序处理多个频道（避免重复启动 Chrome）。"""
    if not jobs:
        return {}
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("未安装 playwright，请执行: pip install playwright") from exc

    cfg = settings or Settings()
    results: dict[str, dict[str, dict[str, str]]] = {
        job.channel_id: {vid: {} for vid in job.video_ids} for job in jobs
    }

    with sync_playwright() as p:
        with _studio_context(
            p,
            cookies=cookies,
            cookie_file=cookie_file,
            headless=headless,
            settings=cfg,
        ) as context:
            page = context.new_page()
            response_state: dict[str, Any] = {"wanted": set(), "collected": {}}

            def on_response(resp) -> None:
                wanted_now = response_state.get("wanted") or set()
                collected_now = response_state.get("collected") or {}
                if not wanted_now:
                    return
                url = resp.url
                if "youtubei/v1/" not in url or resp.status != 200:
                    return
                try:
                    body = resp.json()
                except Exception:
                    return
                for vid, metrics in _walk_videos(body).items():
                    if vid not in wanted_now:
                        continue
                    collected_now[vid] = _merge_metrics(collected_now.get(vid, {}), metrics)

            page.on("response", on_response)

            for idx, job in enumerate(jobs, start=1):
                title = job.channel_title or job.channel_id
                logger.info(
                    "浏览器收入 [%s/%s] 频道 %s videos=%s",
                    idx,
                    len(jobs),
                    title,
                    len(job.video_ids),
                )
                response_state["wanted"] = set(job.video_ids)
                response_state["collected"] = results[job.channel_id]
                channel_metrics = _harvest_channel_in_page(
                    page,
                    job,
                    timeout_ms=timeout_ms,
                    collected=results[job.channel_id],
                    settings=cfg,
                )
                results[job.channel_id] = channel_metrics

    return results


def _harvest_channel_in_page(
    page,
    job: ChannelBrowserJob,
    *,
    timeout_ms: int,
    collected: dict[str, dict[str, str]],
    settings: Settings | None = None,
) -> dict[str, dict[str, str]]:
    wanted = set(job.video_ids)

    base = "https://studio.youtube.com"
    videos_url = base + CHANNEL_VIDEOS_PATH.format(channel_id=job.channel_id)
    if job.brand_account_id:
        videos_url += f"?pageId={job.brand_account_id}"

    logger.info("Playwright 打开 Studio Content: %s", videos_url)
    page.goto(videos_url, wait_until="domcontentloaded", timeout=timeout_ms)
    try:
        page.wait_for_selector("ytcp-app", timeout=30_000)
    except Exception:
        logger.debug("等待 ytcp-app 超时")
    try:
        page.wait_for_function("() => window.__yf_auth != null", timeout=45_000)
    except Exception:
        logger.debug("等待 __yf_auth 超时，将使用 ytcfg 回退")
    page.wait_for_timeout(1000)

    all_videos_seen = _paginate_list_creator_revenue(
        page,
        job,
        collected,
        wanted,
        channel_label=job.channel_title or job.channel_id,
        settings=settings,
        reload_url=videos_url,
    )

    rev_count = sum(1 for vid in wanted if collected.get(vid, {}).get("estimated_revenue"))
    if not all_videos_seen:
        _paginate_scrape_revenue(
            page,
            collected,
            wanted,
            channel_label=job.channel_title or job.channel_id,
        )
        rev_count = sum(1 for vid in wanted if collected.get(vid, {}).get("estimated_revenue"))
    elif rev_count < len(wanted):
        logger.info(
            "频道 %s API 已遍历 %s 条视频，其中 %s 条无 lifetimeRevenue（可能未创收/零收入）",
            job.channel_title or job.channel_id,
            len(wanted),
            len(wanted) - rev_count,
        )
    logger.info(
        "频道 %s 浏览器收入完成 revenue=%s/%s",
        job.channel_title or job.channel_id,
        rev_count,
        len(wanted),
    )
    return collected


def _paginate_list_creator_revenue(
    page,
    job: ChannelBrowserJob,
    collected: dict[str, dict[str, str]],
    wanted: set[str],
    *,
    channel_label: str,
    settings: Settings | None = None,
    reload_url: str = "",
) -> bool:
    """浏览器内 list_creator_videos 分页拉取 metrics + revenueAnalytics（Manager/Brand 可用）。

    返回是否已遍历全部目标 video_id。
    """
    role_type = ROLE_BY_PERMISSION.get(
        job.permission_level.lower(), "CREATOR_CHANNEL_ROLE_TYPE_OWNER"
    )
    max_pages = max_content_pages(len(wanted))
    page_token = ""
    seen_ids: set[str] = set()
    stall = 0
    cfg = settings or Settings()
    max_auth_retries = cfg.max_retries

    for page_idx in range(1, max_pages + 1):
        auth_attempt = 0
        result: dict[str, Any] = {}
        while True:
            result = page.evaluate(
                _LIST_CREATOR_VIDEOS_PAGE_JS,
                {
                    "channelId": job.channel_id,
                    "roleType": role_type,
                    "pageToken": page_token,
                    "pageSize": LIST_API_PAGE_SIZE,
                },
            )
            if not isinstance(result, dict):
                logger.warning("Studio API list [%s] 第 %s 页响应无效", channel_label, page_idx)
                return len(seen_ids) >= len(wanted)

            status = int(result.get("status") or 0)
            if status == 401 and auth_attempt < max_auth_retries and reload_url:
                auth_attempt += 1
                delay = cfg.backoff_base_sec * (2 ** (auth_attempt - 1))
                logger.warning(
                    "Studio API list [%s] 401 页=%s，%.1fs 后重载 Studio (%s/%s)",
                    channel_label,
                    page_idx,
                    delay,
                    auth_attempt,
                    max_auth_retries,
                )
                time.sleep(delay)
                page.goto(reload_url, wait_until="domcontentloaded", timeout=120_000)
                try:
                    page.wait_for_function("() => window.__yf_auth != null", timeout=45_000)
                except Exception:
                    pass
                page.wait_for_timeout(1000)
                continue
            break

        if status != 200:
            logger.warning(
                "Studio API list [%s] 第 %s 页 HTTP %s: %s",
                channel_label,
                page_idx,
                status,
                str(result.get("error") or "")[:120],
            )
            break

        videos = result.get("videos") or []
        new_rev = 0
        new_ids = 0
        for video in videos:
            if not isinstance(video, dict):
                continue
            vid = str(video.get("videoId") or "")
            if not vid or vid not in wanted:
                continue
            if vid not in seen_ids:
                seen_ids.add(vid)
                new_ids += 1
            parsed = parse_creator_video(video)
            if parsed.get("estimated_revenue") and not collected.get(vid, {}).get(
                "estimated_revenue"
            ):
                new_rev += 1
            if parsed:
                collected[vid] = _merge_metrics(collected.get(vid, {}), parsed)

        rev_total = sum(1 for vid in wanted if collected.get(vid, {}).get("estimated_revenue"))
        try:
            from yt_forensics.dashboard.progress import report_analytics_pagination

            report_analytics_pagination(
                channel=channel_label,
                page=page_idx,
                page_total=max_pages,
                source="Studio API",
            )
        except ImportError:
            pass
        logger.info(
            "Studio API list [%s] 第 %s/%s 页 videos=%s 本页新增收入=%s 累计收入=%s/%s 已见视频=%s/%s",
            channel_label,
            page_idx,
            max_pages,
            len(videos),
            new_rev,
            rev_total,
            len(wanted),
            len(seen_ids),
            len(wanted),
        )

        if len(seen_ids) >= len(wanted):
            logger.info("Studio API list [%s] 已遍历全部目标视频，提前结束", channel_label)
            return True

        page_token = str(result.get("nextPageToken") or "")
        if not page_token:
            logger.info("Studio API list [%s] 无下一页 token，结束分页", channel_label)
            return len(seen_ids) >= len(wanted)

        if new_ids == 0:
            stall += 1
            if stall >= STALL_PAGE_LIMIT:
                logger.info(
                    "Studio API list [%s] 连续 %s 页无新视频，停止分页",
                    channel_label,
                    STALL_PAGE_LIMIT,
                )
                return len(seen_ids) >= len(wanted)
        else:
            stall = 0

        page.wait_for_timeout(PAGE_WAIT_MS)

    return len(seen_ids) >= len(wanted)


def _paginate_scrape_revenue(
    page,
    collected: dict[str, dict[str, str]],
    wanted: set[str],
    *,
    channel_label: str,
) -> None:
    """Python 侧翻页 + 日志；连续无新增则早停。"""
    max_pages = max_content_pages(len(wanted))
    seen_ids: set[str] = set()
    stall = 0

    for page_idx in range(1, max_pages + 1):
        scraped = page.evaluate(_SCrape_CONTENT_REVENUE_JS)
        rows = scraped if isinstance(scraped, list) else []
        new_rev = 0
        new_ids = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            vid = str(row.get("videoId") or "")
            if not vid or vid not in wanted:
                continue
            if vid not in seen_ids:
                seen_ids.add(vid)
                new_ids += 1
            rev = str(row.get("revenueGuess") or "").strip()
            if rev and not collected.get(vid, {}).get("estimated_revenue"):
                collected[vid] = _merge_metrics(
                    collected.get(vid, {}),
                    {"estimated_revenue": rev.lstrip("$¥€").strip()},
                )
                new_rev += 1

        rev_total = sum(1 for vid in wanted if collected.get(vid, {}).get("estimated_revenue"))
        logger.info(
            "Studio 内容表 [%s] 第 %s/%s 页 rows=%s 本页新增收入=%s 累计收入=%s/%s",
            channel_label,
            page_idx,
            max_pages,
            len(rows),
            new_rev,
            rev_total,
            len(wanted),
        )

        if rev_total >= len(wanted):
            logger.info("Studio 内容表 [%s] 收入已全覆盖，提前结束翻页", channel_label)
            break

        if new_rev == 0 and new_ids == 0:
            stall += 1
            if stall >= STALL_PAGE_LIMIT:
                logger.info(
                    "Studio 内容表 [%s] 连续 %s 页无新增，停止翻页",
                    channel_label,
                    STALL_PAGE_LIMIT,
                )
                break
        else:
            stall = 0

        if page_idx >= max_pages:
            break
        clicked = page.evaluate(_CLICK_NEXT_PAGE_JS)
        if not clicked:
            logger.info("Studio 内容表 [%s] 已到最后一页", channel_label)
            break
        page.wait_for_timeout(PAGE_WAIT_MS)
        # 等待表格行变化，避免重复抓取同一页
        try:
            first_id = rows[0].get("videoId") if rows else ""
            if first_id:
                page.wait_for_function(
                    "(prev) => {"
                    "  const a = document.querySelector('a[href*=\"/video/\"]');"
                    "  if (!a) return false;"
                    "  const m = (a.getAttribute('href')||'').match(/\\/video\\/([^/?#]+)/);"
                    "  return m && m[1] !== prev;"
                    "}",
                    arg=first_id,
                    timeout=8000,
                )
        except Exception:
            pass


def _launch_browser(p, *, headless: bool, channel: str | None = None):
    launch_kwargs: dict[str, Any] = {
        "headless": headless,
        "ignore_default_args": ["--enable-automation"],
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    channels = [channel] if channel else ["chrome", "msedge", None]
    for ch in channels:
        try:
            if ch:
                return p.chromium.launch(channel=ch, **launch_kwargs)
            return p.chromium.launch(**launch_kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.debug("launch channel=%s 失败: %s", ch, exc)
    raise RuntimeError("无法启动 Chromium/Chrome，请安装 Chrome 或运行 playwright install chromium")


@contextmanager
def _studio_context(
    p,
    *,
    cookies: dict[str, str],
    cookie_file: Path | None,
    headless: bool,
    settings: Settings,
) -> Iterator[Any]:
    """优先 Chrome Profile 持久化上下文；失败则 Cookie 注入。"""
    browser = None
    context = None
    browser_name = settings.playwright_browser or settings.cookie_browser or "chrome"

    if settings.playwright_use_chrome_profile:
        profile_dir = dedicated_profile_dir(settings.data_dir, browser_name)
        if not profile_is_initialized(profile_dir):
            logger.warning(
                "专用 Profile 未初始化 (%s)，请先运行 scripts/bootstrap_browser_profile.py",
                profile_dir,
            )
        else:
            try:
                channel = browser_name if browser_name in ("chrome", "msedge") else "chrome"
                context = p.chromium.launch_persistent_context(
                    str(profile_dir),
                    channel=channel,
                    headless=headless,
                    ignore_default_args=["--enable-automation"],
                    args=["--disable-blink-features=AutomationControlled"],
                    user_agent=_DEFAULT_USER_AGENT,
                    viewport={"width": 1920, "height": 1080},
                    locale="en-US",
                )
                context.add_init_script(_STEALTH_INIT_JS)
                context.add_init_script(_AUTH_HOOK_INIT_JS)
                logger.info("Playwright 使用专用 Profile: %s", profile_dir)
                yield context
                context.close()
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning("专用 Profile 启动失败，回退 Cookie 注入: %s", exc)

    browser = _launch_browser(p, headless=headless, channel=browser_name if browser_name in ("chrome", "msedge") else "chrome")
    context = _new_fallback_context(
        browser,
        cookies=cookies,
        cookie_file=cookie_file,
        settings=settings,
    )
    context.add_init_script(_AUTH_HOOK_INIT_JS)
    try:
        yield context
    finally:
        context.close()
        browser.close()


def _new_fallback_context(
    browser,
    *,
    cookies: dict[str, str],
    cookie_file: Path | None,
    settings: Settings,
):
    state_path = storage_state_path(settings.data_dir)
    if state_path.is_file():
        try:
            context = browser.new_context(
                user_agent=_DEFAULT_USER_AGENT,
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
                storage_state=str(state_path),
            )
            context.add_init_script(_STEALTH_INIT_JS)
            logger.info("Playwright 使用 storage_state: %s", state_path)
            return context
        except Exception as exc:  # noqa: BLE001
            logger.debug("storage_state 加载失败: %s", exc)
    context = browser.new_context(
        user_agent=_DEFAULT_USER_AGENT,
        viewport={"width": 1920, "height": 1080},
        locale="en-US",
    )
    context.add_init_script(_STEALTH_INIT_JS)
    try:
        _inject_cookies(context, cookies, cookie_file=cookie_file)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cookie 注入失败: %s", exc)
    return context


def create_studio_browser_context(
    p,
    cookies: dict[str, str],
    *,
    headless: bool = True,
    cookie_file: Path | None = None,
    settings: Settings | None = None,
):
    """供调试脚本复用（非 context manager，调用方负责 close）。"""
    cfg = settings or Settings()
    browser_name = cfg.playwright_browser or "chrome"
    profile_dir = dedicated_profile_dir(cfg.data_dir, browser_name)
    if cfg.playwright_use_chrome_profile and profile_is_initialized(profile_dir):
        try:
            context = p.chromium.launch_persistent_context(
                str(profile_dir),
                channel=browser_name if browser_name in ("chrome", "msedge") else "chrome",
                headless=headless,
                ignore_default_args=["--enable-automation"],
                args=["--disable-blink-features=AutomationControlled"],
                user_agent=_DEFAULT_USER_AGENT,
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
            )
            context.add_init_script(_STEALTH_INIT_JS)
            context.add_init_script(_AUTH_HOOK_INIT_JS)
            return context, context
        except Exception:
            pass
    browser = _launch_browser(p, headless=headless, channel=browser_name if browser_name in ("chrome", "msedge") else "chrome")
    context = browser.new_context(
        user_agent=_DEFAULT_USER_AGENT,
        viewport={"width": 1920, "height": 1080},
        locale="en-US",
    )
    context.add_init_script(_STEALTH_INIT_JS)
    _inject_cookies(context, cookies, cookie_file=cookie_file)
    context.add_init_script(_AUTH_HOOK_INIT_JS)
    return browser, context


def _inject_cookies(context, cookies: dict[str, str], *, cookie_file: Path | None = None) -> None:
    rows = cookies_for_playwright(cookie_file=cookie_file, cookie_dict=cookies)
    if rows:
        context.add_cookies(rows)
        return
    fallback: list[dict[str, Any]] = []
    for name, value in cookies.items():
        if not name or value is None:
            continue
        for domain in (".youtube.com", ".google.com"):
            fallback.append(
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
    if fallback:
        context.add_cookies(fallback)


def _merge_metrics(a: dict[str, str], b: dict[str, str]) -> dict[str, str]:
    out = dict(a)
    for k, v in b.items():
        if v not in (None, "") and k not in out:
            out[k] = v
    return out


def _walk_videos(node: Any, depth: int = 0) -> dict[str, dict[str, str]]:
    """深度遍历 JSON，关联 videoId 与指标。"""
    if depth > 28:
        return {}
    found: dict[str, dict[str, str]] = {}

    if isinstance(node, list):
        for item in node:
            found = _merge_metrics_map(found, _walk_videos(item, depth + 1))
        return found

    if not isinstance(node, dict):
        return found

    vid = _extract_video_id(node)
    if not vid and isinstance(node.get("__videoId"), str):
        vid = node["__videoId"]
    metrics = _extract_metrics_from_node(node)
    if vid and metrics:
        found[vid] = metrics

    for val in node.values():
        found = _merge_metrics_map(found, _walk_videos(val, depth + 1))
    return found


def _merge_metrics_map(
    a: dict[str, dict[str, str]], b: dict[str, dict[str, str]]
) -> dict[str, dict[str, str]]:
    out = {k: dict(v) for k, v in a.items()}
    for vid, metrics in b.items():
        out[vid] = _merge_metrics(out.get(vid, {}), metrics)
    return out


def _extract_video_id(node: dict[str, Any]) -> str:
    for key in ("videoId", "externalVideoId", "encryptedVideoId"):
        val = node.get(key)
        if isinstance(val, str) and len(val) == 11:
            return val
    return ""


def _extract_metrics_from_node(node: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for section_key in ("metrics", "publicMetrics", "analyticsMetrics", "monetization", "revenue"):
        section = node.get(section_key)
        if isinstance(section, dict):
            out = _merge_metrics(out, _flatten_metrics(section))
    # 顶层字段
    out = _merge_metrics(out, _flatten_metrics(node))
    return out


def _flatten_metrics(obj: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, val in obj.items():
        norm = re.sub(r"[^a-z0-9_]", "", key.lower())
        if norm not in REVENUE_KEYS and norm not in ("viewcount", "views", "externalviewcount"):
            continue
        csv_key = FIELD_MAP.get(norm)
        if not csv_key:
            continue
        text = _stringify(val)
        if text:
            out[csv_key] = text
    return out


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        if "simpleText" in value:
            return str(value["simpleText"]).strip()
        if "amountMicros" in value:
            try:
                return str(int(str(value["amountMicros"])) / 1_000_000)
            except ValueError:
                return str(value["amountMicros"])
        if "value" in value:
            return _stringify(value["value"])
    return str(value).strip()
