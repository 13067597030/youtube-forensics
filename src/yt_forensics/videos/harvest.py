"""M3: 视频列表采集（yt-dlp + 限流 + 增量）。"""

from __future__ import annotations

import logging
import random
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable

from yt_forensics.config import Settings
from yt_forensics.cookie import CookieResult
from yt_forensics.export.evidence import format_iso8601, utc_now

logger = logging.getLogger(__name__)


def harvest_videos(
    cookie: CookieResult,
    channels: list[dict[str, Any]],
    settings: Settings,
    *,
    existing_video_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """采集全部频道视频列表，返回 Video_List 行。"""
    if not channels:
        return []

    existing = existing_video_ids or set()
    rows: list[dict[str, Any]] = []
    cookie_path = _write_temp_cookies(cookie)

    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError("未安装 yt-dlp，无法采集视频列表") from exc

    ydl_base = _base_ydl_opts(settings, cookie_path)

    for idx, ch in enumerate(channels, start=1):
        channel_id = str(ch.get("channel_id") or "")
        if not channel_id:
            continue
        url = _channel_videos_url(ch, channel_id)
        logger.info("采集频道视频 [%s/%s] %s", idx, len(channels), channel_id)

        try:
            channel_rows = _harvest_channel(yt_dlp, ydl_base, url, channel_id, existing)
            rows.extend(channel_rows)
            logger.info("频道 %s 新增 %s 条视频", channel_id, len(channel_rows))
        except Exception as exc:  # noqa: BLE001
            logger.error("频道 %s 视频采集失败: %s", channel_id, exc)

        _rate_sleep(settings)

    return rows


def _channel_videos_url(ch: dict[str, Any], channel_id: str) -> str:
    """优先 uploads 播放列表（可超过 /videos 标签约 500 条上限）。"""
    if channel_id.startswith("UC") and len(channel_id) > 2:
        return f"https://www.youtube.com/playlist?list=UU{channel_id[2:]}"
    raw = str(ch.get("channel_url") or "").strip()
    if raw:
        base = raw.rstrip("/")
        if base.endswith("/videos") or base.endswith("/shorts") or base.endswith("/streams"):
            return base if base.endswith("/videos") else f"{base.split('/shorts')[0].split('/streams')[0]}/videos"
        if "/@" in base or base.endswith(f"/{channel_id}"):
            return f"{base}/videos"
    return f"https://www.youtube.com/channel/{channel_id}/videos"


def _harvest_channel(
    yt_dlp: Any,
    base_opts: dict[str, Any],
    channel_videos_url: str,
    channel_id: str,
    existing: set[str],
) -> list[dict[str, Any]]:
    scrape_time = format_iso8601(utc_now())
    rows: list[dict[str, Any]] = []

    # 1) 扁平列出 uploads
    flat_opts = {**base_opts, "extract_flat": "in_playlist", "skip_download": True}
    entries: list[dict[str, Any]] = []
    with yt_dlp.YoutubeDL(flat_opts) as ydl:
        info = ydl.extract_info(channel_videos_url, download=False)
        if not info:
            return rows
        entries = _collect_entries(info)

    for entry in entries:
        vid = str(entry.get("id") or entry.get("url") or "")
        if not vid or vid in existing:
            continue
        if vid.startswith("http"):
            vid = vid.rstrip("/").split("/")[-1]
        if len(vid) != 11 and entry.get("url"):
            vid = str(entry["url"]).split("=")[-1].split("&")[0][:11]
        if len(vid) != 11:
            continue

        row = _entry_to_row(entry, channel_id, scrape_time)
        if row and row.get("video_id"):
            rows.append(row)
            existing.add(row["video_id"])

    # flat 模式通常已含 title；仅缺关键字段时再补详情
    need_detail = [
        r
        for r in rows
        if not r.get("title") or (not r.get("view_count") and not r.get("duration"))
    ]
    if need_detail:
        _fill_details(yt_dlp, base_opts, need_detail, scrape_time)

    return rows


def _fill_details(
    yt_dlp: Any,
    base_opts: dict[str, Any],
    rows: list[dict[str, Any]],
    scrape_time: str,
) -> None:
    detail_opts = {
        **base_opts,
        "skip_download": True,
        "ignoreerrors": True,
        "ignore_no_formats_error": True,
        "format": "worst",
    }
    with yt_dlp.YoutubeDL(detail_opts) as ydl:
        for row in rows:
            url = row.get("webpage_url") or f"https://www.youtube.com/watch?v={row['video_id']}"
            try:
                info = ydl.extract_info(url, download=False)
                if not info:
                    continue
                filled = _entry_to_row(info, row["channel_id"], scrape_time)
                row.update({k: v for k, v in filled.items() if v})
            except Exception as exc:  # noqa: BLE001
                logger.debug("详情补充失败 %s: %s", row.get("video_id"), exc)


def _collect_entries(info: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if info.get("_type") == "playlist" and info.get("entries"):
        for e in info["entries"]:
            if e:
                entries.append(e)
    elif info.get("entries"):
        entries.extend(e for e in info["entries"] if e)
    else:
        entries.append(info)
    return entries


def _entry_to_row(
    entry: dict[str, Any],
    channel_id: str,
    scrape_time: str,
) -> dict[str, str]:
    video_id = str(entry.get("id") or "")
    if not video_id and entry.get("url"):
        url = str(entry["url"])
        if "v=" in url:
            video_id = url.split("v=")[-1].split("&")[0]
        elif "/shorts/" in url:
            video_id = url.split("/shorts/")[-1].split("?")[0]
    if not video_id:
        return {}

    upload_date = str(entry.get("upload_date") or "")
    duration = entry.get("duration")
    view_count = entry.get("view_count")

    availability = str(entry.get("availability") or "")
    if not availability:
        availability = "public" if not entry.get("is_private") else "private"

    live_status = str(entry.get("live_status") or "")
    if entry.get("is_live"):
        live_status = live_status or "is_live"

    webpage = str(
        entry.get("webpage_url")
        or entry.get("original_url")
        or f"https://www.youtube.com/watch?v={video_id}"
    )

    return {
        "channel_id": str(entry.get("channel_id") or channel_id),
        "uploader_id": str(
            entry.get("uploader_id") or entry.get("channel_id") or channel_id
        ),
        "video_id": video_id,
        "upload_date": upload_date,
        "title": str(entry.get("title") or ""),
        "description": str(entry.get("description") or ""),
        "webpage_url": webpage,
        "availability": availability,
        "duration": str(int(duration)) if duration is not None else "",
        "live_status": live_status,
        "view_count": str(int(view_count)) if view_count is not None else "",
        "scrape_time": scrape_time,
    }


def _base_ydl_opts(settings: Settings, cookie_path: Path | None) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "skip_download": True,
        "ignore_no_formats_error": True,
        "extractor_args": {"youtubetab": {"approximate_date": [""]}},
    }
    if cookie_path and cookie_path.is_file():
        opts["cookiefile"] = str(cookie_path)
    return opts


def _write_temp_cookies(cookie: CookieResult) -> Path | None:
    if cookie.session is None or not cookie.session.cookies:
        return None
    tmp = Path(tempfile.mkdtemp(prefix="yt_forensics_ytdlp_"))
    path = tmp / "cookies.txt"
    lines = ["# Netscape HTTP Cookie File\n"]
    for name, value in cookie.session.cookies.items():
        lines.append(
            f".youtube.com\tTRUE\t/\tTRUE\t0\t{name}\t{value}\n"
        )
        lines.append(f".google.com\tTRUE\t/\tTRUE\t0\t{name}\t{value}\n")
    path.write_text("".join(lines), encoding="utf-8")
    return path


def _rate_sleep(settings: Settings) -> None:
    lo = settings.rate_min_interval_sec
    hi = settings.rate_max_interval_sec
    if hi > 0:
        time.sleep(random.uniform(lo, hi))
