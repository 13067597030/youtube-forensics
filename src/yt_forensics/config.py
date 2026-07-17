"""配置加载。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from yt_forensics.runtime_paths import default_config_path

DEFAULT_CONFIG_PATH = default_config_path()


@dataclass
class Settings:
    evidence_dir: Path = Path("Evidence")
    data_dir: Path = Path("data")
    dashboard_enabled: bool = True
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8787
    dashboard_open_browser: bool = True
    rate_min_interval_sec: float = 0.8
    rate_max_interval_sec: float = 2.5
    max_retries: int = 5
    backoff_base_sec: float = 2.0
    incremental: bool = True
    analytics_lifetime: bool = True
    enable_playwright_fallback: bool = False
    time_sync_source: str = "ntp"
    csv_encoding: str = "utf-8-sig"
    # Cookie：默认优先读本机 Chrome/Edge，避免静态 cookies.txt 频繁失效
    cookie_prefer_browser: bool = True
    cookie_browser: str = "chrome"
    cookie_file_fallback: bool = True
    cookie_health_check: bool = True
    playwright_use_chrome_profile: bool = True
    playwright_browser: str = "chrome"
    extra: dict[str, Any] = field(default_factory=dict)


def load_settings(path: Path | None = None) -> Settings:
    config_path = path or DEFAULT_CONFIG_PATH
    raw: dict[str, Any] = {}
    if config_path.is_file():
        with config_path.open("r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh) or {}
            if not isinstance(loaded, dict):
                raise ValueError(f"配置文件格式错误: {config_path}")
            raw = loaded

    dashboard = raw.get("dashboard") or {}
    rate = raw.get("rate_limit") or {}
    scrape = raw.get("scrape") or {}
    export = raw.get("export") or {}
    cookie = raw.get("cookie") or {}

    return Settings(
        evidence_dir=Path(export.get("evidence_dir", "Evidence")),
        data_dir=Path(raw.get("data_dir", "data")),
        dashboard_enabled=bool(dashboard.get("enabled", True)),
        dashboard_host=str(dashboard.get("host", "127.0.0.1")),
        dashboard_port=int(dashboard.get("port", 8787)),
        dashboard_open_browser=bool(dashboard.get("open_browser", True)),
        rate_min_interval_sec=float(rate.get("min_interval_sec", 0.8)),
        rate_max_interval_sec=float(rate.get("max_interval_sec", 2.5)),
        max_retries=int(rate.get("max_retries", 5)),
        backoff_base_sec=float(rate.get("backoff_base_sec", 2.0)),
        incremental=bool(scrape.get("incremental", True)),
        analytics_lifetime=bool(scrape.get("analytics_lifetime", True)),
        enable_playwright_fallback=bool(
            scrape.get("enable_playwright_fallback", False)
        ),
        time_sync_source=str(raw.get("time_sync_source", "ntp")),
        csv_encoding=str(export.get("csv_encoding", "utf-8-sig")),
        cookie_prefer_browser=bool(cookie.get("prefer_browser", True)),
        cookie_browser=str(cookie.get("browser", "chrome")),
        cookie_file_fallback=bool(cookie.get("file_fallback", True)),
        cookie_health_check=bool(cookie.get("health_check", True)),
        playwright_use_chrome_profile=bool(
            cookie.get("playwright_use_chrome_profile", True)
        ),
        playwright_browser=str(cookie.get("playwright_browser", "chrome")),
        extra=raw,
    )
