"""长跑前环境检查（Profile、磁盘空间）。"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from yt_forensics.config import Settings
from yt_forensics.cookie.browser_profile import dedicated_profile_dir, profile_is_initialized

logger = logging.getLogger(__name__)

STAGES_NEED_PROFILE = frozenset({"all", "analytics"})


@dataclass
class PreflightResult:
    ok: bool = True
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)
        logger.warning("Preflight: %s", msg)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.ok = False
        logger.error("Preflight: %s", msg)


def run_preflight(settings: Settings, *, stage: str) -> PreflightResult:
    """采集开始前检查磁盘与 Profile。"""
    result = PreflightResult()
    _check_disk_space(settings, result)
    if _needs_playwright_profile(settings, stage):
        _check_browser_profile(settings, result)
    return result


def _needs_playwright_profile(settings: Settings, stage: str) -> bool:
    if stage not in STAGES_NEED_PROFILE:
        return False
    if not settings.enable_playwright_fallback:
        return False
    return bool(settings.playwright_use_chrome_profile)


def _check_disk_space(settings: Settings, result: PreflightResult) -> None:
    min_free = int(settings.extra.get("preflight", {}).get("min_disk_free_mb", 100))
    warn_free = int(settings.extra.get("preflight", {}).get("warn_disk_free_mb", 500))

    for label, path in (
        ("证据目录", settings.evidence_dir),
        ("数据目录", settings.data_dir),
    ):
        try:
            path.mkdir(parents=True, exist_ok=True)
            usage = shutil.disk_usage(path)
        except OSError as exc:
            result.add_warning(f"无法检测 {label} 磁盘空间 ({path}): {exc}")
            continue

        free_mb = usage.free / (1024 * 1024)
        if free_mb < min_free:
            result.add_error(
                f"{label} 所在磁盘剩余 {free_mb:.0f} MB，低于最低要求 {min_free} MB（{path}）"
            )
        elif free_mb < warn_free:
            result.add_warning(
                f"{label} 所在磁盘剩余 {free_mb:.0f} MB，建议至少保留 {warn_free} MB"
            )
        else:
            logger.info("Preflight 磁盘 %s 剩余 %.0f MB", label, free_mb)


def _check_browser_profile(settings: Settings, result: PreflightResult) -> None:
    browser = settings.playwright_browser or settings.cookie_browser or "chrome"
    profile_dir = dedicated_profile_dir(settings.data_dir, browser)
    if profile_is_initialized(profile_dir):
        logger.info("Preflight Profile 已初始化: %s", profile_dir)
        return
    result.add_error(
        "专用浏览器 Profile 未初始化，Analytics 收入采集将无法进行。\n"
        f"  目录: {profile_dir}\n"
        "  请先运行: python -m yt_forensics bootstrap-profile"
    )


def format_preflight_errors(result: PreflightResult) -> str:
    return "; ".join(result.errors)
