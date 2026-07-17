"""打包后运行时路径（PyInstaller 绿色包）。"""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    """可执行文件所在目录（绿色包根目录，含 config/、data/、Evidence/）。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def bundle_dir() -> Path:
    """PyInstaller 解压资源目录（_internal / _MEIPASS）。"""
    if is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return app_root()
    return Path(__file__).resolve().parents[2]


def default_config_path() -> Path:
    """优先绿色包根目录 config/，其次内置默认配置。"""
    external = app_root() / "config" / "settings.yaml"
    if external.is_file():
        return external
    bundled = bundle_dir() / "config" / "settings.yaml"
    if bundled.is_file():
        return bundled
    return Path(__file__).resolve().parents[2] / "config" / "settings.yaml"


def dashboard_static_dir() -> Path:
    """Dashboard 静态资源目录。"""
    if is_frozen():
        for candidate in (
            bundle_dir() / "yt_forensics" / "dashboard" / "static",
            bundle_dir() / "dashboard" / "static",
            app_root() / "dashboard" / "static",
        ):
            if candidate.is_dir():
                return candidate
    return Path(__file__).resolve().parent / "dashboard" / "static"
