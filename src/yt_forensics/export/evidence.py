"""Evidence 目录写入：CSV / meta.json / hashes.sha256。"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from yt_forensics import __tool_name__, __version__
from yt_forensics.export.schema import (
    ACCOUNT_MAPPING_FILENAME,
    ACCOUNT_MAPPING_HEADERS,
    EXTRACTION_TYPE,
    FORMAT_VERSION,
    HASH_TARGET_ORDER,
    HASHES_FILENAME,
    LOG_FILENAME,
    META_FILENAME,
    VIDEO_ANALYTICS_FILENAME,
    VIDEO_ANALYTICS_HEADERS,
    VIDEO_LIST_FILENAME,
    VIDEO_LIST_HEADERS,
)

logger = logging.getLogger(__name__)

# 导出时间统一为北京时间（UTC+8）
BEIJING_TZ = timezone(timedelta(hours=8))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def beijing_now() -> datetime:
    return datetime.now(BEIJING_TZ)


def format_iso8601(dt: datetime) -> str:
    """导出用 ISO8601，固定北京时间 +08:00。"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(BEIJING_TZ)
    return local.strftime("%Y-%m-%dT%H:%M:%S") + "+08:00"


def make_run_id(when: datetime | None = None) -> str:
    dt = when or utc_now()
    stamp = dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = hashlib.sha256(f"{stamp}-{dt.timestamp()}".encode()).hexdigest()[:8]
    return f"{stamp}_{suffix}"


@dataclass
class TimeSyncInfo:
    system_time: str
    reference_time: str
    offset_seconds: float
    source: str  # ntp | http_date | none


@dataclass
class RunCounts:
    channels_total: int = 0
    channels_done: int = 0
    videos_total: int = 0
    videos_done: int = 0
    analytics_total: int = 0
    analytics_done: int = 0
    analytics_ok: int = 0
    analytics_partial: int = 0
    analytics_unavailable: int = 0

    def analytics_counts_dict(self) -> dict[str, int]:
        return {
            "analytics_total": self.analytics_total,
            "analytics_done": self.analytics_done,
            "analytics_ok": self.analytics_ok,
            "analytics_partial": self.analytics_partial,
            "analytics_unavailable": self.analytics_unavailable,
        }


@dataclass
class MetaDocument:
    format_version: str = FORMAT_VERSION
    tool_name: str = __tool_name__
    tool_version: str = __version__
    extraction_type: str = EXTRACTION_TYPE
    run_id: str = ""
    started_at: str = ""
    finished_at: str = ""
    status: str = "running"
    platform: str = ""
    account_email: str = ""
    cookie_source: str = "unknown"
    time_sync: dict[str, Any] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    evidence_files: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EvidenceWriter:
    """管理单次提取的 Evidence/{run_id}/ 输出。"""

    def __init__(
        self,
        root: Path,
        run_id: str | None = None,
        csv_encoding: str = "utf-8-sig",
    ) -> None:
        self.run_id = run_id or make_run_id()
        self.dir = Path(root) / self.run_id
        self.csv_encoding = csv_encoding
        self.dir.mkdir(parents=True, exist_ok=True)
        self._account_path = self.dir / ACCOUNT_MAPPING_FILENAME
        self._video_path = self.dir / VIDEO_LIST_FILENAME
        self._analytics_path = self.dir / VIDEO_ANALYTICS_FILENAME
        self._meta_path = self.dir / META_FILENAME
        self._log_path = self.dir / LOG_FILENAME
        self._hashes_path = self.dir / HASHES_FILENAME
        self._init_csv(self._account_path, ACCOUNT_MAPPING_HEADERS)
        self._init_csv(self._video_path, VIDEO_LIST_HEADERS)
        self._init_csv(self._analytics_path, VIDEO_ANALYTICS_HEADERS)

    def _init_csv(self, path: Path, headers: Sequence[str]) -> None:
        if path.exists():
            return
        with path.open("w", encoding=self.csv_encoding, newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(headers), lineterminator="\n")
            writer.writeheader()

    def append_rows(
        self,
        path: Path,
        headers: Sequence[str],
        rows: Iterable[Mapping[str, Any]],
    ) -> int:
        count = 0
        with path.open("a", encoding=self.csv_encoding, newline="") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=list(headers),
                lineterminator="\n",
                extrasaction="ignore",
            )
            for row in rows:
                normalized = {h: _cell(row.get(h, "")) for h in headers}
                writer.writerow(normalized)
                count += 1
        return count

    def append_account_mapping(self, rows: Iterable[Mapping[str, Any]]) -> int:
        return self.append_rows(self._account_path, ACCOUNT_MAPPING_HEADERS, rows)

    def append_video_list(self, rows: Iterable[Mapping[str, Any]]) -> int:
        return self.append_rows(self._video_path, VIDEO_LIST_HEADERS, rows)

    def append_video_analytics(self, rows: Iterable[Mapping[str, Any]]) -> int:
        return self.append_rows(self._analytics_path, VIDEO_ANALYTICS_HEADERS, rows)

    def write_video_analytics(self, rows: Iterable[Mapping[str, Any]]) -> int:
        """覆盖写入 Video_Analytics.csv（断点续采完成后使用）。"""
        with self._analytics_path.open("w", encoding=self.csv_encoding, newline="") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=list(VIDEO_ANALYTICS_HEADERS),
                lineterminator="\n",
                extrasaction="ignore",
            )
            writer.writeheader()
            count = 0
            for row in rows:
                writer.writerow({h: _cell(row.get(h, "")) for h in VIDEO_ANALYTICS_HEADERS})
                count += 1
        return count

    def write_meta(self, meta: MetaDocument) -> Path:
        meta.evidence_files = [
            ACCOUNT_MAPPING_FILENAME,
            VIDEO_LIST_FILENAME,
            VIDEO_ANALYTICS_FILENAME,
            LOG_FILENAME,
            HASHES_FILENAME,
        ]
        payload = meta.to_dict()
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        self._meta_path.write_text(text, encoding="utf-8")
        return self._meta_path

    def write_hashes(self) -> Path:
        lines: list[str] = []
        for name in HASH_TARGET_ORDER:
            path = self.dir / name
            if not path.is_file():
                logger.warning("哈希跳过缺失文件: %s", name)
                continue
            digest = sha256_file(path)
            lines.append(f"{digest}  {name}")
        content = "\n".join(lines) + ("\n" if lines else "")
        self._hashes_path.write_text(content, encoding="utf-8")
        return self._hashes_path

    @property
    def log_path(self) -> Path:
        return self._log_path

    def finalize(self, meta: MetaDocument) -> Path:
        """写入 meta 后计算 hashes（hashes 覆盖 meta 的最终内容）。"""
        self.write_meta(meta)
        return self.write_hashes()


def _cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_video_list_csv(path: Path, *, encoding: str = "utf-8-sig") -> list[dict[str, str]]:
    """读取 Video_List.csv 为行字典列表。"""
    if not path.is_file():
        return []
    rows: list[dict[str, str]] = []
    with path.open("r", encoding=encoding, newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows.append({k: str(v or "") for k, v in row.items()})
    return rows


def find_latest_video_list(evidence_root: Path, *, exclude_run_id: str = "") -> Path | None:
    """返回最新证据包中的 Video_List.csv 路径（按目录名排序）。"""
    root = Path(evidence_root)
    if not root.is_dir():
        return None
    candidates: list[Path] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        if exclude_run_id and child.name == exclude_run_id:
            continue
        video_list = child / VIDEO_LIST_FILENAME
        if not video_list.is_file():
            continue
        rows = load_video_list_csv(video_list)
        if rows:
            candidates.append(video_list)
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.parent.name, reverse=True)
    return candidates[0]


def load_video_analytics_csv(path: Path, *, encoding: str = "utf-8-sig") -> list[dict[str, str]]:
    """读取 Video_Analytics.csv 为行字典列表。"""
    if not path.is_file():
        return []
    rows: list[dict[str, str]] = []
    with path.open("r", encoding=encoding, newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows.append({k: str(v or "") for k, v in row.items()})
    return rows


def find_latest_video_analytics(
    evidence_root: Path, *, exclude_run_id: str = ""
) -> Path | None:
    """返回最新证据包中的 Video_Analytics.csv（含有效行）。"""
    root = Path(evidence_root)
    if not root.is_dir():
        return None
    candidates: list[Path] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        if exclude_run_id and child.name == exclude_run_id:
            continue
        analytics_path = child / VIDEO_ANALYTICS_FILENAME
        if not analytics_path.is_file():
            continue
        rows = load_video_analytics_csv(analytics_path)
        if rows:
            candidates.append(analytics_path)
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.parent.name, reverse=True)
    return candidates[0]
