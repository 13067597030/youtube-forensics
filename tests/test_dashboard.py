"""Dashboard API 与数据读取测试。"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from yt_forensics.dashboard.app import create_app
from yt_forensics.dashboard.progress import get_progress
from yt_forensics.dashboard.services import build_summary, tail_log
from yt_forensics.export.schema import (
    ACCOUNT_MAPPING_HEADERS,
    VIDEO_ANALYTICS_HEADERS,
    VIDEO_LIST_HEADERS,
)


@pytest.fixture
def evidence_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "20260716T100000Z_test1234"
    run_dir.mkdir()
    with (run_dir / "run.log").open("w", encoding="utf-8") as fh:
        fh.write("2026-07-16T10:00:01 | INFO | test | hello\n")
        fh.write("2026-07-16T10:00:02 | WARNING | test | warn line\n")

    with (run_dir / "Account_Mapping.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(ACCOUNT_MAPPING_HEADERS), lineterminator="\n")
        w.writeheader()
        w.writerow({h: h for h in ACCOUNT_MAPPING_HEADERS})

    with (run_dir / "Video_List.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(VIDEO_LIST_HEADERS), lineterminator="\n")
        w.writeheader()
        w.writerow({"channel_id": "UC123", "video_id": "abc12345678", "title": "t1"})

    meta = {
        "run_id": "20260716T100000Z_test1234",
        "status": "completed",
        "started_at": "2026-07-16T10:00:00Z",
        "finished_at": "2026-07-16T10:05:00Z",
    }
    (run_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (run_dir / "hashes.sha256").write_text("deadbeef  Account_Mapping.csv\n", encoding="utf-8")
    return run_dir


def test_tail_log(evidence_dir: Path):
    first = tail_log(evidence_dir / "run.log", 0)
    assert len(first["lines"]) == 2
    second = tail_log(evidence_dir / "run.log", first["offset"])
    assert second["lines"] == []


def test_build_summary(evidence_dir: Path):
    summary = build_summary(evidence_dir)
    assert summary["files"]["account_mapping"] == 1
    assert summary["files"]["video_list"] == 1
    assert summary["meta_available"] is True


def test_dashboard_api(evidence_dir: Path):
    get_progress().reset(
        run_id="20260716T100000Z_test1234",
        evidence_dir=str(evidence_dir),
        requested_stage="all",
        started_at="2026-07-16T10:00:00Z",
    )
    get_progress().set_stage("videos", detail="testing")
    get_progress().update_counts(videos_total=10, videos_done=3)

    app = create_app(
        run_id="20260716T100000Z_test1234",
        evidence_dir=str(evidence_dir),
    )
    client = TestClient(app)

    status = client.get("/api/status").json()
    assert status["run_id"] == "20260716T100000Z_test1234"
    assert status["counts"]["videos_total"] == 10

    logs = client.get("/api/logs").json()
    assert any("hello" in line for line in logs["lines"])

    preview = client.get("/api/preview/video_list").json()
    assert preview["total_rows"] == 1
    assert preview["rows"][0]["video_id"] == "abc12345678"

    meta = client.get("/api/meta").json()
    assert meta["available"] is True
    assert meta["data"]["status"] == "completed"

    hashes = client.get("/api/hashes").json()
    assert hashes["available"] is True
    assert hashes["items"][0]["filename"] == "Account_Mapping.csv"


def test_dashboard_url():
    from yt_forensics.dashboard.app import dashboard_url

    assert dashboard_url("127.0.0.1", 8787) == "http://127.0.0.1:8787/"
    assert dashboard_url("0.0.0.0", 8787) == "http://127.0.0.1:8787/"


def test_progress_percent():
    progress = get_progress()
    progress.reset(
        run_id="r1",
        evidence_dir="/tmp/e",
        requested_stage="channels",
        started_at="t",
    )
    progress.set_stage("cookie")
    progress.complete_stage("cookie")
    progress.set_stage("channels")
    snap = progress.snapshot()
    assert snap["progress_percent"] >= 33
    assert any(s["id"] == "channels" and s["state"] == "active" for s in snap["stages"])
