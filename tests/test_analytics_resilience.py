"""Analytics 增量、401 与 state.db 断点测试。"""

from __future__ import annotations

from pathlib import Path

from yt_forensics.analytics.resilience import (
    is_analytics_complete,
    is_auth_error,
    load_prior_analytics,
    split_pending_video_ids,
)
from yt_forensics.export.schema import VIDEO_ANALYTICS_HEADERS
from yt_forensics.state.db import StateDB


def test_is_auth_error():
    assert is_auth_error("http_401:Unauthorized")
    assert is_auth_error("http_401")
    assert not is_auth_error("http_403")


def test_is_analytics_complete():
    assert is_analytics_complete({"analytics_status": "partial", "views": "1"})
    assert not is_analytics_complete({"analytics_status": "partial"})
    assert not is_analytics_complete({"analytics_status": "unavailable", "views": "1"})


def test_split_pending_video_ids():
    prior = {
        ("UCa", "v1"): {"analytics_status": "partial", "views": "10", "video_id": "v1"},
    }
    pending, reused = split_pending_video_ids(
        "UCa", ["v1", "v2"], prior, incremental=True
    )
    assert pending == ["v2"]
    assert len(reused) == 1


def test_load_prior_analytics_from_db(tmp_path: Path):
    db = StateDB(tmp_path / "state.db")
    row = {h: "" for h in VIDEO_ANALYTICS_HEADERS}
    row.update(
        {
            "channel_id": "UCx",
            "video_id": "abc12345678",
            "views": "99",
            "analytics_status": "partial",
        }
    )
    db.save_analytics_rows("run_a", [row])
    prior = load_prior_analytics(tmp_path, exclude_run_id="run_b", db=db)
    assert ("UCx", "abc12345678") in prior


def test_state_db_channel_checkpoint(tmp_path: Path):
    db = StateDB(tmp_path / "state.db")
    db.create_run("run1", "2026-07-17T12:00:00+08:00", str(tmp_path / "ev"))
    db._conn.execute(
        """
        INSERT INTO channels (
          run_id, channel_id, brand_account_id, handle, title, url,
          account_type, permission_level, video_list_status, analytics_status, last_error
        ) VALUES (?, ?, '', '', '', '', 'brand', 'manager', 'done', 'pending', '')
        """,
        ("run1", "UCx"),
    )
    db._conn.commit()
    assert not db.is_channel_analytics_done("run1", "UCx")
    db.update_channel_analytics_status("run1", "UCx", "done")
    assert db.is_channel_analytics_done("run1", "UCx")
