"""Preflight 与 Dashboard 分页进度测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from yt_forensics.config import Settings
from yt_forensics.dashboard.progress import get_progress, report_analytics_pagination
from yt_forensics.engine.preflight import run_preflight


def test_report_analytics_pagination():
    get_progress().reset(
        run_id="t",
        evidence_dir="/tmp",
        requested_stage="analytics",
    )
    report_analytics_pagination(
        channel="LOVE ATTACK HUB",
        page=3,
        page_total=22,
        source="Studio API",
    )
    snap = get_progress().snapshot()
    assert snap["analytics_progress"]["page"] == 3
    assert snap["analytics_progress"]["page_total"] == 22
    assert "LOVE ATTACK HUB" in snap["detail"]


def test_preflight_profile_missing(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        evidence_dir=tmp_path / "Evidence",
        enable_playwright_fallback=True,
        playwright_use_chrome_profile=True,
    )
    with patch("shutil.disk_usage", return_value=type("U", (), {"free": 10_000_000_000})()):
        result = run_preflight(settings, stage="analytics")
    assert not result.ok
    assert any("Profile" in e for e in result.errors)


def test_preflight_disk_low(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        evidence_dir=tmp_path / "Evidence",
        enable_playwright_fallback=False,
        extra={"preflight": {"min_disk_free_mb": 100, "warn_disk_free_mb": 500}},
    )
    (tmp_path / "data").mkdir(parents=True)
    with patch("shutil.disk_usage", return_value=type("U", (), {"free": 50 * 1024 * 1024})()):
        result = run_preflight(settings, stage="videos")
    assert not result.ok
    assert any("磁盘" in e for e in result.errors)
