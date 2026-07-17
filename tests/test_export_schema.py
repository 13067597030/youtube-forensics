"""锁定导出格式：表头与 hashes/meta 约定不可漂移。"""

from __future__ import annotations

import json
from pathlib import Path

from yt_forensics.export.evidence import (
    EvidenceWriter,
    MetaDocument,
    format_iso8601,
    sha256_file,
    utc_now,
)
from datetime import datetime
from yt_forensics.export.schema import (
    ACCOUNT_MAPPING_HEADERS,
    FORMAT_VERSION,
    HASH_TARGET_ORDER,
    VIDEO_ANALYTICS_HEADERS,
    VIDEO_LIST_HEADERS,
)


def test_format_iso8601_beijing():
    from datetime import timezone

    utc = datetime(2026, 7, 16, 9, 30, 0, tzinfo=timezone.utc)
    assert format_iso8601(utc) == "2026-07-16T17:30:00+08:00"


def test_headers_locked():
    assert ACCOUNT_MAPPING_HEADERS == (
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
    assert VIDEO_LIST_HEADERS[0] == "channel_id"
    assert VIDEO_LIST_HEADERS[-1] == "scrape_time"
    assert len(VIDEO_LIST_HEADERS) == 12
    assert VIDEO_ANALYTICS_HEADERS[2] == "estimated_revenue"
    assert VIDEO_ANALYTICS_HEADERS[10] == "analytics_status"
    assert len(VIDEO_ANALYTICS_HEADERS) == 13


def test_evidence_writer_meta_and_hashes(tmp_path: Path):
    writer = EvidenceWriter(tmp_path, run_id="20260716T053000Z_testhash")
    writer.append_account_mapping(
        [
            {
                "account_email": "a@example.com",
                "cookie_source": "import_file",
                "brand_account_id": "",
                "channel_id": "UCtest",
                "handle": "@test",
                "channel_title": "Test",
                "channel_url": "https://www.youtube.com/@test",
                "account_type": "personal",
                "permission_level": "unknown",
                "forensic_time": format_iso8601(utc_now()),
            }
        ]
    )
    writer.log_path.write_text("hello\n", encoding="utf-8")

    meta = MetaDocument(
        run_id=writer.run_id,
        started_at=format_iso8601(utc_now()),
        finished_at=format_iso8601(utc_now()),
        status="partial",
        platform="windows",
        account_email="a@example.com",
        cookie_source="import_file",
        time_sync={
            "system_time": "2026-07-16T05:30:00Z",
            "reference_time": "2026-07-16T05:30:00Z",
            "offset_seconds": 0.0,
            "source": "none",
        },
        counts={
            "channels_total": 1,
            "channels_done": 1,
            "videos_total": 0,
            "videos_done": 0,
            "analytics_total": 0,
            "analytics_done": 0,
            "analytics_unavailable": 0,
        },
        notes="unit test",
    )
    writer.finalize(meta)

    meta_path = writer.dir / "meta.json"
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    assert data["format_version"] == FORMAT_VERSION
    assert data["tool_name"] == "YouTubeForensics"
    assert data["extraction_type"] == "network_online_extraction"
    assert "hashes.sha256" in data["evidence_files"]

    hashes_text = (writer.dir / "hashes.sha256").read_text(encoding="utf-8")
    lines = [ln for ln in hashes_text.splitlines() if ln.strip()]
    assert lines, "hashes.sha256 不应为空"

    by_name = {}
    for line in lines:
        digest, name = line.split("  ", 1)
        assert len(digest) == 64
        assert digest == digest.lower()
        by_name[name] = digest

    for name in HASH_TARGET_ORDER:
        path = writer.dir / name
        if path.is_file():
            assert name in by_name
            assert by_name[name] == sha256_file(path)

    assert "hashes.sha256" not in by_name
