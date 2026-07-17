"""专用 Chrome Profile 初始化向导（可嵌入 CLI / M5 打包）。"""

from __future__ import annotations

import argparse
import sys

from yt_forensics.config import Settings, load_settings
from yt_forensics.cookie.browser_profile import (
    browser_process_alive,
    dedicated_profile_dir,
    launch_real_browser,
    profile_is_initialized,
    reset_profile_dir,
)
from yt_forensics.cookie.profile_sync import save_profile_storage_state

WIZARD_STEPS = (
    "在弹出窗口登录 Google / YouTube",
    "打开 YouTube Studio，确认目标频道可见「估算收入」",
    "关闭专用浏览器窗口",
    "回到终端按 Enter 完成初始化",
)


def build_bootstrap_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="初始化专用 Chrome/Edge Profile（Google 登录不被 Playwright 拦截）",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="备份并清空现有 Profile（损坏或闪退时使用）",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="配置文件路径",
    )
    return parser


def run_profile_bootstrap(
    settings: Settings | None = None,
    *,
    reset: bool = False,
    interactive: bool = True,
) -> int:
    """运行 Profile 向导；成功返回 0。"""
    cfg = settings or load_settings()
    browser = cfg.playwright_browser or cfg.cookie_browser or "chrome"
    profile_dir = dedicated_profile_dir(cfg.data_dir, browser)

    print(f"专用 Profile 目录: {profile_dir.resolve()}")
    print()
    print("将用【真实 Chrome】打开专用窗口（不是 Playwright），可与日常 Chrome 同时运行。")
    print()
    print("请完成：")
    for idx, step in enumerate(WIZARD_STEPS, start=1):
        print(f"  {idx}. {step}")
    print()

    if reset and profile_dir.exists():
        try:
            backup = reset_profile_dir(profile_dir)
        except PermissionError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"已备份旧 Profile 到: {backup.resolve()}")
        print()

    try:
        proc = launch_real_browser(profile_dir, browser=browser)
    except FileNotFoundError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"启动浏览器失败: {exc}", file=sys.stderr)
        return 1

    if not browser_process_alive(proc):
        code = proc.returncode
        print(f"Chrome 启动后立即退出（exit={code}），专用 Profile 可能已损坏。", file=sys.stderr)
        if not reset and profile_dir.exists():
            print("正在自动备份旧 Profile 并重试…", file=sys.stderr)
            try:
                backup = reset_profile_dir(profile_dir)
            except PermissionError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            print(f"旧 Profile 已备份到: {backup.resolve()}", file=sys.stderr)
            try:
                proc = launch_real_browser(profile_dir, browser=browser)
            except OSError as exc:
                print(f"重试启动失败: {exc}", file=sys.stderr)
                return 1
            if not browser_process_alive(proc):
                print("重试后仍未弹出窗口。请确认已安装 Chrome。", file=sys.stderr)
                return 1
            print("已用全新 Profile 重新打开 Chrome，请在弹出窗口中登录。")
        else:
            print("请执行: python -m yt_forensics bootstrap-profile --reset", file=sys.stderr)
            return 1
    else:
        print(f"Chrome 已启动 (pid={proc.pid})，请在弹出窗口中登录。")

    if interactive:
        input("\n登录完成并关闭专用浏览器窗口后，按 Enter…")
    if proc.poll() is None:
        proc.terminate()

    if not profile_is_initialized(profile_dir):
        print("警告: Profile 似乎未保存登录状态，请重试。", file=sys.stderr)
        return 1

    try:
        state_path = save_profile_storage_state(cfg)
        print(f"已保存 Cookie 快照: {state_path.resolve()}")
    except Exception as exc:  # noqa: BLE001
        print(f"警告: 无法导出 Cookie 快照（{exc}），采集时仍会尝试从 Profile 读取。", file=sys.stderr)

    print("Profile 已就绪。后续运行：")
    print("  python -m yt_forensics --stage all --dashboard")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_bootstrap_parser()
    args = parser.parse_args(argv)
    settings = load_settings(args.config) if args.config else load_settings()
    return run_profile_bootstrap(settings, reset=bool(args.reset))


if __name__ == "__main__":
    raise SystemExit(main())
