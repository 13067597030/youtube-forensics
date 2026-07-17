# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — Win / macOS 共用。在项目根目录执行 build 脚本。"""

import sys
from pathlib import Path

block_cipher = None
ROOT = Path(SPEC).resolve().parent.parent
SRC = ROOT / "src"

a = Analysis(
    [str(SRC / "yt_forensics" / "__main__.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=[
        (str(ROOT / "config" / "settings.yaml"), "config"),
        (str(SRC / "yt_forensics" / "dashboard" / "static"), "yt_forensics/dashboard/static"),
    ],
    hiddenimports=[
        "yt_forensics",
        "yt_forensics.cli",
        "yt_forensics.bootstrap.profile_wizard",
        "yt_forensics.engine.runner",
        "yt_forensics.engine.preflight",
        "yt_forensics.dashboard.app",
        "yt_forensics.dashboard.progress",
        "yt_forensics.dashboard.services",
        "yt_forensics.analytics.harvest",
        "yt_forensics.analytics.browser_harvest",
        "yt_forensics.analytics.resilience",
        "uvicorn",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "fastapi",
        "starlette",
        "yaml",
        "httpx",
        "httpx._transports",
        "httpx._transports.default",
        "browser_cookie3",
        "yt_dlp",
        "playwright",
        "playwright.sync_api",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="yt-forensics",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="YouTubeForensics",
)
