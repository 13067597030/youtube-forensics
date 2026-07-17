"""Playwright 专用取证 Profile（勿使用系统 Chrome User Data）。"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def chromium_user_data_dir(browser: str = "chrome") -> Path:
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    if browser == "edge":
        return local / "Microsoft" / "Edge" / "User Data"
    return local / "Google" / "Chrome" / "User Data"


def dedicated_profile_dir(data_dir: Path, browser: str = "chrome") -> Path:
    """项目内独立 Profile，可安全用于 Playwright 持久化上下文。"""
    name = "browser_profile_edge" if browser == "edge" else "browser_profile"
    return Path(data_dir) / name


def first_usable_profile(browser: str = "chrome") -> Path | None:
    """检测系统 Profile 是否存在 Cookie DB（仅用于提示，不用于 Playwright 启动）。"""
    user_data = chromium_user_data_dir(browser)
    if not user_data.is_dir():
        return None
    for name in ("Default", *[p.name for p in sorted(user_data.glob("Profile *"))]):
        profile_dir = user_data / name
        for rel in ("Network/Cookies", "Cookies"):
            if (profile_dir / rel).is_file():
                return profile_dir
    return None


def is_chromium_running(browser: str = "chrome") -> bool:
    if sys.platform != "win32":
        return False
    import subprocess

    image = "chrome.exe" if browser == "chrome" else "msedge.exe"
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image}", "/NH"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        text = (out.stdout or "").lower()
        return image.lower() in text and "no tasks" not in text
    except Exception:
        return False


def profile_is_initialized(profile_dir: Path) -> bool:
    """Profile 目录已创建且存在 Local State。"""
    return profile_dir.is_dir() and (profile_dir / "Local State").is_file()


def storage_state_path(data_dir: Path) -> Path:
    """Playwright storage_state 快照（含完整 domain/path）。"""
    return Path(data_dir) / "browser_storage_state.json"


def resolve_chromium_executable(browser: str = "chrome") -> Path:
    """定位本机 Chrome / Edge 可执行文件。"""
    if sys.platform == "win32":
        candidates: list[Path] = []
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local = os.environ.get("LOCALAPPDATA", "")
        if browser == "edge":
            candidates = [
                Path(pf) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                Path(pf86) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            ]
        else:
            candidates = [
                Path(pf) / "Google" / "Chrome" / "Application" / "chrome.exe",
                Path(pf86) / "Google" / "Chrome" / "Application" / "chrome.exe",
                Path(local) / "Google" / "Chrome" / "Application" / "chrome.exe",
            ]
    elif sys.platform == "darwin":
        if browser == "edge":
            candidates = [Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")]
        else:
            candidates = [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")]
    else:
        candidates = [
            Path("/usr/bin/google-chrome"),
            Path("/usr/bin/chromium"),
            Path("/usr/bin/chromium-browser"),
        ]

    for path in candidates:
        if path.is_file():
            return path
    name = "msedge" if browser == "edge" else "chrome"
    raise FileNotFoundError(f"未找到 {name} 可执行文件，请安装 Chrome 或 Edge")


def launch_real_browser(profile_dir: Path, browser: str = "chrome", url: str = "https://studio.youtube.com/") -> subprocess.Popen:
    """
    用真实 Chrome/Edge 打开专用 Profile（非 Playwright），Google 登录不会被拦截。
    可与日常 Chrome 并存（user-data-dir 不同即可）。
    """
    profile_dir.mkdir(parents=True, exist_ok=True)
    exe = resolve_chromium_executable(browser)
    args = [
        str(exe),
        f"--user-data-dir={profile_dir.resolve()}",
        "--profile-directory=Default",
        "--new-window",
        "--no-first-run",
        "--no-default-browser-check",
        url,
    ]
    return subprocess.Popen(args)  # noqa: S603


def browser_process_alive(proc: subprocess.Popen, *, wait_sec: float = 2.5) -> bool:
    """启动后短暂等待，确认浏览器进程未立即退出。"""
    deadline = time.monotonic() + wait_sec
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        time.sleep(0.15)
    return proc.poll() is None


def reset_profile_dir(profile_dir: Path) -> Path:
    """将损坏的 Profile 目录移到备份位置，返回备份路径。"""
    profile_dir = Path(profile_dir)
    if not profile_dir.exists():
        profile_dir.mkdir(parents=True, exist_ok=True)
        return profile_dir
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = profile_dir.with_name(f"{profile_dir.name}.bak.{stamp}")
    try:
        shutil.move(str(profile_dir), str(backup))
    except PermissionError as exc:
        raise PermissionError(
            f"无法移动 Profile（文件被占用）: {profile_dir}\n"
            "请先完全关闭使用该专用 Profile 的 Chrome 窗口"
            "（任务管理器结束 chrome.exe 后重试），再运行 --reset。"
        ) from exc
    except OSError as exc:
        if getattr(exc, "winerror", None) == 32 or "WinError 32" in str(exc):
            raise PermissionError(
                f"无法移动 Profile（文件被占用）: {profile_dir}\n"
                "请先完全关闭使用该专用 Profile 的 Chrome 窗口后重试 --reset。"
            ) from exc
        raise
    profile_dir.mkdir(parents=True, exist_ok=True)
    return backup
