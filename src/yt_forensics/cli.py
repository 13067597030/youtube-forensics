"""命令行入口。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from yt_forensics import __tool_name__, __version__
from yt_forensics.config import load_settings
from yt_forensics.engine.runner import RunOptions, start_run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-forensics",
        description=f"{__tool_name__} v{__version__} — YouTube 账号网络在线提取",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="配置文件路径（默认使用内置 settings.yaml）",
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=None,
        help="证据输出根目录（覆盖配置）",
    )
    parser.add_argument(
        "--cookie-file",
        type=Path,
        default=None,
        help="导入 Cookie 文件（Netscape/JSON）；不指定则从本机 Chrome/Edge 实时读取",
    )
    parser.add_argument(
        "--prefer-browser-cookies",
        action="store_true",
        default=None,
        help="优先从本机浏览器读取 Cookie（覆盖配置文件）",
    )
    parser.add_argument(
        "--no-prefer-browser-cookies",
        action="store_true",
        help="禁用浏览器读取，仅使用 --cookie-file 或 data/cookies.txt",
    )
    parser.add_argument(
        "--channel-id",
        action="append",
        default=[],
        metavar="UC...",
        help="仅采集指定频道（可重复）；默认采集账号下全部可管理频道",
    )
    parser.add_argument(
        "--resume-run-id",
        default="",
        metavar="RUN_ID",
        help="断点续采：继续指定 run_id 的证据目录（配合 --stage analytics）",
    )
    parser.add_argument(
        "--no-incremental",
        action="store_true",
        help="禁用增量采集（视频列表与 Analytics 全量重采）",
    )
    parser.add_argument(
        "--bootstrap-if-needed",
        action="store_true",
        help="Profile 未初始化时自动启动 bootstrap-profile 向导",
    )
    parser.add_argument(
        "--stage",
        choices=["cookie", "channels", "videos", "analytics", "all"],
        default="all",
        help="执行到指定阶段后结束（默认 all；验证 M2 可用 channels）",
    )
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="启动本地 Web Dashboard",
    )
    parser.add_argument(
        "--no-open-browser",
        action="store_true",
        help="Dashboard 启动时不自动打开浏览器",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Dashboard 监听地址",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Dashboard 监听端口",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{__tool_name__} {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(argv if argv is not None else sys.argv[1:])
    if raw_argv and raw_argv[0] == "bootstrap-profile":
        from yt_forensics.bootstrap.profile_wizard import main as bootstrap_main

        return bootstrap_main(raw_argv[1:])

    parser = build_parser()
    args = parser.parse_args(raw_argv)
    settings = load_settings(args.config)

    if args.evidence_dir is not None:
        settings.evidence_dir = args.evidence_dir
    if args.host is not None:
        settings.dashboard_host = args.host
    if args.port is not None:
        settings.dashboard_port = args.port
    if args.prefer_browser_cookies:
        settings.cookie_prefer_browser = True
    if args.no_prefer_browser_cookies:
        settings.cookie_prefer_browser = False

    if args.no_open_browser:
        settings.dashboard_open_browser = False

    options = RunOptions(
        cookie_file=args.cookie_file,
        enable_dashboard=args.dashboard or settings.dashboard_enabled,
        stage=args.stage,
        channel_ids=tuple(args.channel_id or []),
        resume_run_id=str(args.resume_run_id or "").strip(),
        incremental=False if args.no_incremental else None,
        bootstrap_if_needed=bool(args.bootstrap_if_needed),
    )
    return start_run(settings, options)
