"""Analytics 增量采集、401 重试与断点辅助。"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable

from yt_forensics.analytics.parse import api_error_message
from yt_forensics.analytics.studio_client import StudioClient
from yt_forensics.config import Settings
from yt_forensics.export.evidence import (
    find_latest_video_analytics,
    load_video_analytics_csv,
)

logger = logging.getLogger(__name__)

AnalyticsKey = tuple[str, str]  # (channel_id, video_id)


def is_auth_error(message: str) -> bool:
    text = (message or "").lower()
    return text.startswith("http_401") or " 401" in text or text == "401"


def is_analytics_complete(row: dict[str, Any]) -> bool:
    """已采且可用于增量跳过的行。"""
    status = str(row.get("analytics_status") or "")
    if status not in {"ok", "partial"}:
        return False
    return bool(
        row.get("estimated_revenue")
        or row.get("views")
        or row.get("watch_time")
    )


def load_prior_analytics(
    evidence_dir: Path,
    *,
    encoding: str = "utf-8-sig",
    exclude_run_id: str = "",
    db: Any | None = None,
) -> dict[AnalyticsKey, dict[str, str]]:
    """合并历史 evidence CSV 与 state.db 中已完成的 Analytics 行。"""
    merged: dict[AnalyticsKey, dict[str, str]] = {}

    latest = find_latest_video_analytics(evidence_dir, exclude_run_id=exclude_run_id)
    if latest is not None:
        for row in load_video_analytics_csv(latest, encoding=encoding):
            cid = str(row.get("channel_id") or "")
            vid = str(row.get("video_id") or "")
            if not cid or not vid or not is_analytics_complete(row):
                continue
            merged[(cid, vid)] = {k: str(v or "") for k, v in row.items()}

    if db is not None:
        for key, row in db.load_completed_analytics(exclude_run_id=exclude_run_id).items():
            if is_analytics_complete(row):
                merged[key] = row

    if exclude_run_id and db is not None:
        for key, row in db.load_run_analytics(exclude_run_id).items():
            if is_analytics_complete(row):
                merged[key] = row

    return merged


def split_pending_video_ids(
    channel_id: str,
    video_ids: list[str],
    prior: dict[AnalyticsKey, dict[str, str]],
    *,
    incremental: bool,
) -> tuple[list[str], list[dict[str, str]]]:
    """返回 (待采 video_id, 可复用的 prior 行)。"""
    if not incremental:
        return list(video_ids), []

    pending: list[str] = []
    reused: list[dict[str, str]] = []
    for vid in video_ids:
        key = (channel_id, vid)
        row = prior.get(key)
        if row and is_analytics_complete(row):
            reused.append(dict(row))
        else:
            pending.append(vid)
    return pending, reused


def build_channel_analytics_rows(
    channel_id: str,
    all_video_ids: list[str],
    metrics_map: dict[str, dict[str, str]],
    prior: dict[AnalyticsKey, dict[str, str]],
    scrape_time: str,
    *,
    api_err: str = "",
    blank_row_fn: Callable[[str, str, str], dict[str, Any]],
    classify_fn: Callable[[dict[str, str]], tuple[str, str]],
) -> list[dict[str, Any]]:
    """按视频列表顺序合并新采 metrics 与 prior 行。"""
    rows: list[dict[str, Any]] = []
    for vid in all_video_ids:
        key = (channel_id, vid)
        metrics = metrics_map.get(vid, {})
        if metrics:
            status, reason = classify_fn(metrics)
            row = blank_row_fn(channel_id, vid, scrape_time)
            row.update(metrics)
            row["analytics_status"] = status
            row["unavailable_reason"] = reason if status != "ok" else ""
            rows.append(row)
            continue

        prior_row = prior.get(key)
        if prior_row and is_analytics_complete(prior_row):
            rows.append(dict(prior_row))
            continue

        row = blank_row_fn(channel_id, vid, scrape_time)
        row["analytics_status"] = "unavailable"
        row["unavailable_reason"] = api_err or "no_metrics"
        rows.append(row)
    return rows


def studio_call_with_auth_retry(
    settings: Settings,
    *,
    refresh_studio: Callable[[], StudioClient],
    call: Callable[[StudioClient], dict[str, Any]],
) -> dict[str, Any]:
    """HTTP Studio 调用；401 时刷新会话并重试。"""
    studio = refresh_studio()
    last: dict[str, Any] = {}
    for attempt in range(settings.max_retries + 1):
        last = call(studio)
        err = api_error_message(last)
        if not err or not is_auth_error(err):
            return last
        if attempt >= settings.max_retries:
            logger.warning("Studio HTTP 401 已达最大重试次数")
            return last
        delay = settings.backoff_base_sec * (2**attempt)
        logger.warning(
            "Studio HTTP 401，%.1fs 后刷新会话重试 (%s/%s)",
            delay,
            attempt + 1,
            settings.max_retries,
        )
        time.sleep(delay)
        studio = refresh_studio()
    return last
