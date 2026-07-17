"""M4: YouTube Studio 统计分析采集。"""

from __future__ import annotations

import logging
import random
import time
from pathlib import Path
from typing import Any

from yt_forensics.analytics.parse import (
    YTA_CARD_METRICS,
    api_error_message,
    classify_row,
    extract_videos_list,
    merge_metrics,
    next_page_token,
    parse_creator_video,
    parse_get_cards,
)
from yt_forensics.analytics.resilience import (
    build_channel_analytics_rows,
    is_auth_error,
    load_prior_analytics,
    split_pending_video_ids,
)
from yt_forensics.analytics.studio_client import StudioClient, bootstrap_studio_client
from yt_forensics.config import Settings
from yt_forensics.cookie import CookieResult, acquire_cookies
from yt_forensics.export.evidence import format_iso8601, utc_now
from yt_forensics.export.schema import VIDEO_ANALYTICS_HEADERS
from yt_forensics.state.db import StateDB

logger = logging.getLogger(__name__)

MANAGE_PERMISSIONS = frozenset({"owner", "manager"})
BATCH_SIZE = 20
LIST_PAGE_SIZE = 50
LIST_MAX_PAGES = 120


def harvest_analytics(
    cookie: CookieResult,
    channels: list[dict[str, Any]],
    videos: list[dict[str, Any]],
    settings: Settings,
    *,
    cookie_file: Path | None = None,
    run_id: str = "",
    db: StateDB | None = None,
) -> list[dict[str, Any]]:
    """从 Studio 拉取视频级 Analytics，返回 Video_Analytics 行。"""
    if not videos:
        return []
    if cookie.session is None:
        raise RuntimeError("Cookie 会话不可用，无法采集 Analytics")

    scrape_time = format_iso8601(utc_now())
    videos_by_channel = _group_videos(videos)
    rows: list[dict[str, Any]] = []
    browser_jobs: list[dict[str, Any]] = []
    channel_metrics: dict[str, dict[str, dict[str, str]]] = {}

    prior: dict[tuple[str, str], dict[str, str]] = {}
    if settings.incremental:
        prior = load_prior_analytics(
            settings.evidence_dir,
            encoding=settings.csv_encoding,
            exclude_run_id=run_id,
            db=db,
        )
        if prior:
            logger.info("增量 Analytics：已加载 %s 条历史完成记录", len(prior))

    for ch in channels:
        channel_id = str(ch.get("channel_id") or "")
        if not channel_id:
            continue

        if db and run_id and db.is_channel_analytics_done(run_id, channel_id):
            logger.info("断点续采：频道 %s 本轮已完成，跳过", channel_id)
            channel_videos = videos_by_channel.get(channel_id, [])
            all_ids = [str(v["video_id"]) for v in channel_videos if v.get("video_id")]
            run_prior = db.load_run_analytics(run_id, channel_id)
            merged_prior = {**prior, **run_prior}
            rows.extend(
                build_channel_analytics_rows(
                    channel_id,
                    all_ids,
                    {},
                    merged_prior,
                    scrape_time,
                    blank_row_fn=_blank_row,
                    classify_fn=classify_row,
                )
            )
            continue

        permission = str(ch.get("permission_level") or "unknown").lower()
        channel_videos = videos_by_channel.get(channel_id, [])
        if not channel_videos:
            continue

        if permission not in MANAGE_PERMISSIONS:
            rows.extend(
                _unavailable_rows(
                    channel_id,
                    channel_videos,
                    scrape_time,
                    reason=f"permission_{permission}",
                )
            )
            continue

        all_video_ids = [str(v["video_id"]) for v in channel_videos if v.get("video_id")]
        pending_ids, reused_rows = split_pending_video_ids(
            channel_id,
            all_video_ids,
            prior,
            incremental=settings.incremental,
        )

        if not pending_ids:
            logger.info(
                "增量 Analytics 频道 %s 全部 %s 条已采，跳过网络请求",
                ch.get("channel_title") or channel_id,
                len(all_video_ids),
            )
            channel_rows = build_channel_analytics_rows(
                channel_id,
                all_video_ids,
                {},
                prior,
                scrape_time,
                blank_row_fn=_blank_row,
                classify_fn=classify_row,
            )
            rows.extend(channel_rows)
            _checkpoint_channel(db, run_id, channel_id, channel_rows)
            continue

        if reused_rows:
            logger.info(
                "增量 Analytics 频道 %s 跳过 %s 已采，待采 %s",
                ch.get("channel_title") or channel_id,
                len(reused_rows),
                len(pending_ids),
            )

        metrics_map: dict[str, dict[str, str]] = {vid: {} for vid in pending_ids}
        api_err = ""
        is_delegated = bool(ch.get("brand_account_id")) or permission == "manager"

        try:
            if is_delegated:
                api_err = "delegated_channel_browser_required"
            else:

                def _make_studio() -> StudioClient:
                    session = _refresh_session(cookie, settings, cookie_file=cookie_file)
                    return bootstrap_studio_client(
                        session,
                        channel_id,
                        permission_level=permission,
                        brand_account_id=str(ch.get("brand_account_id") or ""),
                    )

                studio_holder: dict[str, StudioClient] = {"client": _make_studio()}

                def _refresh_studio() -> StudioClient:
                    studio_holder["client"] = _make_studio()
                    return studio_holder["client"]

                api_err = _fetch_paginated_list_metrics(
                    studio_holder["client"],
                    pending_ids,
                    metrics_map,
                    settings,
                    refresh_studio=_refresh_studio,
                )
                if not api_err:
                    api_err = _fetch_batch_creator_metrics(
                        studio_holder["client"],
                        pending_ids,
                        metrics_map,
                        settings,
                        refresh_studio=_refresh_studio,
                    )
                _fetch_revenue_cards(
                    studio_holder["client"],
                    pending_ids,
                    metrics_map,
                    settings,
                    refresh_studio=_refresh_studio,
                )

            for v in channel_videos:
                vid = str(v.get("video_id") or "")
                views = str(v.get("view_count") or "")
                if vid in metrics_map and views and not metrics_map.get(vid, {}).get("views"):
                    metrics_map.setdefault(vid, {})["views"] = views

            channel_metrics[channel_id] = metrics_map

            if settings.enable_playwright_fallback and _needs_browser(ch, metrics_map):
                browser_jobs.append(
                    {
                        "channel_id": channel_id,
                        "channel_title": str(ch.get("channel_title") or channel_id),
                        "all_video_ids": all_video_ids,
                        "video_ids": pending_ids,
                        "brand_account_id": str(ch.get("brand_account_id") or ""),
                        "permission_level": permission,
                        "api_err": api_err,
                    }
                )
            else:
                channel_rows = build_channel_analytics_rows(
                    channel_id,
                    all_video_ids,
                    metrics_map,
                    prior,
                    scrape_time,
                    api_err=api_err,
                    blank_row_fn=_blank_row,
                    classify_fn=classify_row,
                )
                rows.extend(channel_rows)
                _checkpoint_channel(db, run_id, channel_id, channel_rows)
                _log_channel_summary(channel_id, channel_rows)

        except Exception as exc:  # noqa: BLE001
            logger.error("频道 %s Analytics HTTP 失败: %s", channel_id, exc)
            if db and run_id:
                db.update_channel_analytics_status(
                    run_id, channel_id, "failed", error=str(exc)
                )
            rows.extend(
                _unavailable_rows(
                    channel_id,
                    [v for v in channel_videos if str(v.get("video_id") or "") in pending_ids],
                    scrape_time,
                    reason=str(exc),
                )
            )

    if browser_jobs and settings.enable_playwright_fallback:
        try:
            from yt_forensics.analytics.browser_harvest import (
                ChannelBrowserJob,
                harvest_revenue_browser_batch,
            )

            session = _refresh_session(cookie, settings, cookie_file=cookie_file)
            jobs = [
                ChannelBrowserJob(
                    channel_id=str(j["channel_id"]),
                    video_ids=list(j["video_ids"]),
                    brand_account_id=str(j.get("brand_account_id") or ""),
                    permission_level=str(j.get("permission_level") or "owner"),
                    channel_title=str(j.get("channel_title") or j["channel_id"]),
                )
                for j in browser_jobs
            ]
            logger.info("启动批量浏览器收入采集 channels=%s", len(jobs))
            browser_out = harvest_revenue_browser_batch(
                jobs,
                cookies=dict(session.cookies),
                headless=True,
                settings=settings,
            )

            for job_meta in browser_jobs:
                cid = str(job_meta["channel_id"])
                metrics_map = channel_metrics.get(cid, {})
                extra_map = browser_out.get(cid, {})
                for vid, extra in extra_map.items():
                    if vid in metrics_map:
                        metrics_map[vid] = merge_metrics(metrics_map[vid], extra)

                rev_n = sum(
                    1
                    for v in job_meta["video_ids"]
                    if metrics_map.get(v, {}).get("estimated_revenue")
                )
                logger.info(
                    "浏览器收入补全 channel=%s matched=%s revenue=%s",
                    job_meta.get("channel_title") or cid,
                    sum(1 for v in job_meta["video_ids"] if extra_map.get(v)),
                    rev_n,
                )

                channel_rows = build_channel_analytics_rows(
                    cid,
                    list(job_meta["all_video_ids"]),
                    metrics_map,
                    prior,
                    scrape_time,
                    api_err=str(job_meta.get("api_err") or ""),
                    blank_row_fn=_blank_row,
                    classify_fn=classify_row,
                )
                rows.extend(channel_rows)
                _checkpoint_channel(db, run_id, cid, channel_rows)
                _log_channel_summary(cid, channel_rows)

        except Exception as exc:  # noqa: BLE001
            logger.warning("批量浏览器收入补全失败: %s", exc)
            for job_meta in browser_jobs:
                cid = str(job_meta["channel_id"])
                metrics_map = channel_metrics.get(cid, {})
                channel_rows = build_channel_analytics_rows(
                    cid,
                    list(job_meta["all_video_ids"]),
                    metrics_map,
                    prior,
                    scrape_time,
                    api_err=str(job_meta.get("api_err") or ""),
                    blank_row_fn=_blank_row,
                    classify_fn=classify_row,
                )
                rows.extend(channel_rows)
                _checkpoint_channel(db, run_id, cid, channel_rows)

    return rows


def _checkpoint_channel(
    db: StateDB | None,
    run_id: str,
    channel_id: str,
    channel_rows: list[dict[str, Any]],
) -> None:
    if not db or not run_id or not channel_rows:
        return
    db.save_analytics_rows(run_id, channel_rows)
    db.update_channel_analytics_status(run_id, channel_id, "done")


def _log_channel_summary(channel_id: str, rows: list[dict[str, Any]]) -> None:
    ok = sum(1 for r in rows if r.get("analytics_status") == "ok")
    partial = sum(1 for r in rows if r.get("analytics_status") == "partial")
    logger.info(
        "频道 %s Analytics 完成 total=%s ok=%s partial=%s unavailable=%s",
        channel_id,
        len(rows),
        ok,
        partial,
        len(rows) - ok - partial,
    )


def _needs_browser(ch: dict[str, Any], metrics_map: dict[str, dict[str, str]]) -> bool:
    return _needs_revenue(metrics_map)


def _refresh_session(
    cookie: CookieResult,
    settings: Settings,
    *,
    cookie_file: Path | None,
) -> Any:
    """从 Profile/storage_state 刷新 httpx 会话（轻量，约数秒）。"""
    if cookie.session is not None:
        try:
            cookie.session.close()
        except Exception:  # noqa: BLE001
            pass
        cookie.session = None

    fresh = acquire_cookies(cookie_file, settings=settings)
    if not fresh.ok or fresh.session is None:
        raise RuntimeError(fresh.error or "Cookie 刷新失败")
    cookie.session = fresh.session
    cookie.source = fresh.source
    return fresh.session


def _needs_revenue(metrics_map: dict[str, dict[str, str]]) -> bool:
    if not metrics_map:
        return True
    for metrics in metrics_map.values():
        if not metrics.get("estimated_revenue"):
            return True
    return False


def _fetch_paginated_list_metrics(
    studio: StudioClient,
    video_ids: list[str],
    metrics_map: dict[str, dict[str, str]],
    settings: Settings,
    *,
    refresh_studio: Any | None = None,
) -> str:
    """HTTP list_creator_videos 分页（Owner 频道可一次拿 views + revenue）。"""
    wanted = set(video_ids)
    seen: set[str] = set()
    token = ""
    last_err = ""
    max_pages = min(LIST_MAX_PAGES, (len(video_ids) + LIST_PAGE_SIZE - 1) // LIST_PAGE_SIZE + 2)
    client = studio

    for page_idx in range(1, max_pages + 1):
        for attempt in range(settings.max_retries + 1):
            if refresh_studio and attempt > 0:
                client = refresh_studio()

            data = client.list_creator_videos(page_token=token, page_size=LIST_PAGE_SIZE)
            err = api_error_message(data)
            if err and is_auth_error(err) and refresh_studio and attempt < settings.max_retries:
                delay = settings.backoff_base_sec * (2**attempt)
                logger.warning(
                    "list_creator_videos 401，%.1fs 后重试 页=%s (%s/%s)",
                    delay,
                    page_idx,
                    attempt + 1,
                    settings.max_retries,
                )
                time.sleep(delay)
                continue
            break

        if err:
            last_err = err
            logger.warning(
                "list_creator_videos 第 %s 页失败 channel=%s: %s",
                page_idx,
                client.channel_id,
                err,
            )
            return last_err if page_idx == 1 else ""

        batch = extract_videos_list(data)
        for video in batch:
            vid = str(video.get("videoId") or "")
            if not vid or vid not in wanted:
                continue
            seen.add(vid)
            metrics_map[vid] = merge_metrics(metrics_map.get(vid, {}), parse_creator_video(video))

        token = next_page_token(data)
        logger.info(
            "HTTP list_creator_videos channel=%s 第 %s 页 batch=%s 累计=%s/%s",
            client.channel_id,
            page_idx,
            len(batch),
            len(seen),
            len(wanted),
        )
        try:
            from yt_forensics.dashboard.progress import report_analytics_pagination

            report_analytics_pagination(
                channel=client.channel_id,
                page=page_idx,
                page_total=max_pages,
                source="HTTP list",
            )
        except ImportError:
            pass
        if len(seen) >= len(wanted) or not token:
            break
        _rate_sleep(settings, scale=0.35)

    return last_err


def _fetch_revenue_cards(
    studio: StudioClient,
    video_ids: list[str],
    metrics_map: dict[str, dict[str, str]],
    settings: Settings,
    *,
    refresh_studio: Any | None = None,
) -> None:
    """HTTP yta_web/get_cards 补 revenue 等指标（Owner 频道可用）。"""
    if studio.permission_level.lower() == "manager":
        return

    revenue_metrics = [
        YTA_CARD_METRICS["estimated_revenue"],
        YTA_CARD_METRICS["rpm"],
        YTA_CARD_METRICS["views"],
        YTA_CARD_METRICS["watch_time"],
    ]
    client = studio

    for vid in video_ids:
        if metrics_map.get(vid, {}).get("estimated_revenue"):
            continue

        for attempt in range(settings.max_retries + 1):
            if refresh_studio and attempt > 0:
                client = refresh_studio()
            data = client.get_analytics_cards(vid, revenue_metrics)
            err = api_error_message(data)
            if err and is_auth_error(err) and refresh_studio and attempt < settings.max_retries:
                delay = settings.backoff_base_sec * (2**attempt)
                logger.warning(
                    "get_cards 401 video=%s，%.1fs 后重试 (%s/%s)",
                    vid,
                    delay,
                    attempt + 1,
                    settings.max_retries,
                )
                time.sleep(delay)
                continue
            break

        if err:
            continue
        parsed = parse_get_cards(data)
        if parsed:
            metrics_map[vid] = merge_metrics(metrics_map.get(vid, {}), parsed)
        _rate_sleep(settings, scale=0.5)


def _fetch_batch_creator_metrics(
    studio: StudioClient,
    video_ids: list[str],
    metrics_map: dict[str, dict[str, str]],
    settings: Settings,
    *,
    refresh_studio: Any | None = None,
) -> str:
    last_err = ""
    client = studio

    for i in range(0, len(video_ids), BATCH_SIZE):
        batch = video_ids[i : i + BATCH_SIZE]
        data: dict[str, Any] = {}

        for attempt in range(settings.max_retries + 1):
            if refresh_studio and attempt > 0:
                client = refresh_studio()
            data = client.get_creator_videos(batch)
            err = api_error_message(data)
            if err and is_auth_error(err) and refresh_studio and attempt < settings.max_retries:
                delay = settings.backoff_base_sec * (2**attempt)
                logger.warning(
                    "get_creator_videos 401，%.1fs 后重试 batch=%s (%s/%s)",
                    delay,
                    i // BATCH_SIZE + 1,
                    attempt + 1,
                    settings.max_retries,
                )
                time.sleep(delay)
                continue
            break

        err = api_error_message(data)
        if err:
            last_err = err
            logger.warning("get_creator_videos 批次失败: %s", err)
            continue

        for video in extract_videos_list(data):
            vid = str(video.get("videoId") or "")
            if not vid or vid not in metrics_map:
                continue
            parsed = parse_creator_video(video)
            metrics_map[vid] = merge_metrics(metrics_map[vid], parsed)
        _rate_sleep(settings)

    return last_err


def _group_videos(videos: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for v in videos:
        cid = str(v.get("channel_id") or "")
        if cid:
            out.setdefault(cid, []).append(v)
    return out


def _blank_row(channel_id: str, video_id: str, scrape_time: str) -> dict[str, str]:
    row = {h: "" for h in VIDEO_ANALYTICS_HEADERS}
    row["channel_id"] = channel_id
    row["video_id"] = video_id
    row["scrape_time"] = scrape_time
    row["analytics_status"] = "skipped"
    row["unavailable_reason"] = ""
    return row


def _unavailable_rows(
    channel_id: str,
    channel_videos: list[dict[str, Any]],
    scrape_time: str,
    *,
    reason: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for v in channel_videos:
        vid = str(v.get("video_id") or "")
        if not vid:
            continue
        row = _blank_row(channel_id, vid, scrape_time)
        row["analytics_status"] = "unavailable"
        row["unavailable_reason"] = reason
        rows.append(row)
    return rows


def _rate_sleep(settings: Settings, *, scale: float = 1.0) -> None:
    lo = settings.rate_min_interval_sec * scale
    hi = settings.rate_max_interval_sec * scale
    if hi <= 0:
        return
    time.sleep(random.uniform(lo, hi))
