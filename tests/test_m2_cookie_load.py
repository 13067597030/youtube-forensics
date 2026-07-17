"""M2: Cookie 文件解析（不依赖本机 Chrome）。"""

from __future__ import annotations

from pathlib import Path

from yt_forensics.cookie.load import load_from_file


def test_load_netscape(tmp_path: Path):
    p = tmp_path / "cookies.txt"
    p.write_text(
        "# Netscape HTTP Cookie File\n"
        ".youtube.com\tTRUE\t/\tTRUE\t0\tSAPISID\tabc123\n"
        ".google.com\tTRUE\t/\tTRUE\t0\tSID\txyz\n",
        encoding="utf-8",
    )
    cookies, detail = load_from_file(p)
    assert cookies["SAPISID"] == "abc123"
    assert cookies["SID"] == "xyz"
    assert "netscape" in detail


def test_load_json_list(tmp_path: Path):
    p = tmp_path / "cookies.json"
    p.write_text(
        """
        [
          {"name": "SAPISID", "value": "v1", "domain": ".youtube.com"},
          {"name": "SID", "value": "v2", "domain": ".google.com"}
        ]
        """,
        encoding="utf-8",
    )
    cookies, detail = load_from_file(p)
    assert cookies["SAPISID"] == "v1"
    assert "json" in detail


def test_load_json_map(tmp_path: Path):
    p = tmp_path / "map.json"
    p.write_text('{"SAPISID": "x", "SID": "y"}', encoding="utf-8")
    cookies, _ = load_from_file(p)
    assert cookies["SAPISID"] == "x"
