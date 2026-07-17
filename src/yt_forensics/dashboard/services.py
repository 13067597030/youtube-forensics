"""Dashboard 数据读取辅助。"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from yt_forensics.export.schema import (
    ACCOUNT_MAPPING_FILENAME,
    HASHES_FILENAME,
    META_FILENAME,
    VIDEO_ANALYTICS_FILENAME,
    VIDEO_LIST_FILENAME,
)


def tail_log(path: Path, offset: int = 0, *, max_lines: int = 200) -> dict[str, Any]:
    if not path.is_file():
        return {"lines": [], "offset": 0, "eof": True}

    size = path.stat().st_size
    if offset > size:
        offset = 0

    with path.open("rb") as fh:
        fh.seek(offset)
        chunk = fh.read()
        new_offset = fh.tell()

    text = chunk.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    return {"lines": lines, "offset": new_offset, "eof": new_offset >= size}


def read_csv_preview(
    path: Path,
    *,
    limit: int = 25,
    encoding: str = "utf-8-sig",
) -> dict[str, Any]:
    if not path.is_file():
        return {"headers": [], "rows": [], "total_rows": 0}

    headers: list[str] = []
    rows: list[dict[str, str]] = []
    total = 0
    with path.open("r", encoding=encoding, newline="") as fh:
        reader = csv.DictReader(fh)
        headers = list(reader.fieldnames or [])
        for row in reader:
            total += 1
            if len(rows) < limit:
                rows.append({k: str(v or "") for k, v in row.items()})
    return {"headers": headers, "rows": rows, "total_rows": total}


def read_meta(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def read_hashes(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    items: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        digest, name = parts
        items.append({"filename": name.strip(), "sha256": digest.strip()})
    return items


def build_summary(evidence_dir: Path, *, encoding: str = "utf-8-sig") -> dict[str, Any]:
    account = read_csv_preview(evidence_dir / ACCOUNT_MAPPING_FILENAME, limit=0, encoding=encoding)
    videos = read_csv_preview(evidence_dir / VIDEO_LIST_FILENAME, limit=0, encoding=encoding)
    analytics = read_csv_preview(evidence_dir / VIDEO_ANALYTICS_FILENAME, limit=0, encoding=encoding)

    status_counts: dict[str, int] = {}
    if analytics["total_rows"]:
        with (evidence_dir / VIDEO_ANALYTICS_FILENAME).open(
            "r", encoding=encoding, newline=""
        ) as fh:
            reader = csv.DictReader(fh)
            counter: Counter[str] = Counter()
            for row in reader:
                counter[str(row.get("analytics_status") or "unknown")] += 1
            status_counts = dict(counter)

    meta = read_meta(evidence_dir / META_FILENAME)
    hashes = read_hashes(evidence_dir / HASHES_FILENAME)

    return {
        "files": {
            "account_mapping": account["total_rows"],
            "video_list": videos["total_rows"],
            "video_analytics": analytics["total_rows"],
        },
        "analytics_status": status_counts,
        "meta_available": meta is not None,
        "hashes_count": len(hashes),
        "meta_status": (meta or {}).get("status", ""),
    }
