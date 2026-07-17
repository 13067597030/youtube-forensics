"""Cookie 获取策略单元测试（不依赖本机 Chrome）。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from yt_forensics.config import Settings
from yt_forensics.cookie import acquire_cookies


def test_acquire_prefers_browser_when_no_file(tmp_path: Path):
    settings = Settings(data_dir=tmp_path, cookie_prefer_browser=True, cookie_file_fallback=False)
    fake_session = object()
    with patch("yt_forensics.cookie._from_browser_auto") as auto:
        auto.return_value = type(
            "R",
            (),
            {
                "ok": True,
                "source": "chrome_auto",
                "detail": "test",
                "session": fake_session,
                "error": "",
                "account_email": "",
                "health": None,
            },
        )()
        with patch("yt_forensics.cookie._attach_health"):
            result = acquire_cookies(None, settings=settings)
    assert result.ok
    assert result.source == "chrome_auto"
    auto.assert_called_once()


def test_acquire_explicit_file_skips_browser(tmp_path: Path):
    settings = Settings(data_dir=tmp_path, cookie_prefer_browser=True)
    cookie_path = tmp_path / "c.txt"
    cookie_path.write_text(
        ".youtube.com\tTRUE\t/\tTRUE\t0\tSAPISID\tx\n",
        encoding="utf-8",
    )
    with patch("yt_forensics.cookie._from_browser_auto") as auto:
        result = acquire_cookies(cookie_path, settings=settings)
    auto.assert_not_called()
    assert result.ok
    assert result.source == "import_file"
