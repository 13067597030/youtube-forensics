"""导出格式定稿 — 与 specs/EXPORT_FORMAT.md 保持同步。"""

from __future__ import annotations

from typing import Final

FORMAT_VERSION: Final = "1.0.0"
TOOL_NAME: Final = "YouTubeForensics"
EXTRACTION_TYPE: Final = "network_online_extraction"

ACCOUNT_MAPPING_FILENAME: Final = "Account_Mapping.csv"
VIDEO_LIST_FILENAME: Final = "Video_List.csv"
VIDEO_ANALYTICS_FILENAME: Final = "Video_Analytics.csv"
META_FILENAME: Final = "meta.json"
LOG_FILENAME: Final = "run.log"
HASHES_FILENAME: Final = "hashes.sha256"

ACCOUNT_MAPPING_HEADERS: Final[tuple[str, ...]] = (
    "account_email",
    "cookie_source",
    "brand_account_id",
    "channel_id",
    "handle",
    "channel_title",
    "channel_url",
    "account_type",
    "permission_level",
    "forensic_time",
)

VIDEO_LIST_HEADERS: Final[tuple[str, ...]] = (
    "channel_id",
    "uploader_id",
    "video_id",
    "upload_date",
    "title",
    "description",
    "webpage_url",
    "availability",
    "duration",
    "live_status",
    "view_count",
    "scrape_time",
)

VIDEO_ANALYTICS_HEADERS: Final[tuple[str, ...]] = (
    "channel_id",
    "video_id",
    "estimated_revenue",
    "rpm",
    "playback_based_cpm",
    "views",
    "watch_time",
    "impressions",
    "ctr",
    "monetized_playbacks",
    "analytics_status",
    "unavailable_reason",
    "scrape_time",
)

# hashes.sha256 推荐行顺序（不含 hashes 自身）
HASH_TARGET_ORDER: Final[tuple[str, ...]] = (
    ACCOUNT_MAPPING_FILENAME,
    VIDEO_LIST_FILENAME,
    VIDEO_ANALYTICS_FILENAME,
    LOG_FILENAME,
    META_FILENAME,
)

COOKIE_SOURCES: Final[tuple[str, ...]] = (
    "chrome_auto",
    "import_file",
    "unknown",
)

ACCOUNT_TYPES: Final[tuple[str, ...]] = ("personal", "brand")

PERMISSION_LEVELS: Final[tuple[str, ...]] = (
    "none",
    "manager",
    "owner",
    "unknown",
)

ANALYTICS_STATUSES: Final[tuple[str, ...]] = (
    "ok",
    "unavailable",
    "partial",
    "skipped",
)

RUN_STATUSES: Final[tuple[str, ...]] = (
    "running",
    "completed",
    "failed",
    "partial",
)

TIME_SYNC_SOURCES: Final[tuple[str, ...]] = ("ntp", "http_date", "none")
