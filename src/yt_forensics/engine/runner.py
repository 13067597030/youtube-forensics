"""主流程编排。"""

from __future__ import annotations

import logging
import platform
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from yt_forensics.config import Settings
from yt_forensics.export.evidence import (
    EvidenceWriter,
    MetaDocument,
    RunCounts,
    format_iso8601,
    utc_now,
)
from yt_forensics.logging_setup import setup_logging
from yt_forensics.state import StateDB
from yt_forensics.util.time_sync import sync_time

try:
    from yt_forensics.dashboard.progress import get_progress
except ImportError:  # pragma: no cover
    get_progress = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

STAGES = ("cookie", "channels", "videos", "analytics", "all")


@dataclass
class RunOptions:
    cookie_file: Path | None = None
    enable_dashboard: bool = False
    stage: str = "all"  # cookie | channels | videos | analytics | all
    channel_ids: tuple[str, ...] = ()
    resume_run_id: str = ""
    incremental: bool | None = None  # None = 使用配置文件
    bootstrap_if_needed: bool = False


def start_run(settings: Settings, options: RunOptions) -> int:
    stage = options.stage if options.stage in STAGES else "all"
    if options.incremental is not None:
        settings.incremental = options.incremental
    settings.evidence_dir.mkdir(parents=True, exist_ok=True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    writer = EvidenceWriter(
        settings.evidence_dir,
        run_id=options.resume_run_id or None,
        csv_encoding=settings.csv_encoding,
    )
    resuming = bool(options.resume_run_id)
    setup_logging(writer.log_path)
    started = utc_now()
    _progress_reset(writer.run_id, writer.dir, stage, format_iso8601(started))
    logger.info(
        "启动提取 run_id=%s evidence=%s stage=%s",
        writer.run_id,
        writer.dir,
        stage,
    )

    from yt_forensics.engine.preflight import format_preflight_errors, run_preflight

    preflight = run_preflight(settings, stage=stage)
    for warn in preflight.warnings:
        logger.warning("Preflight: %s", warn)
    if not preflight.ok:
        if options.bootstrap_if_needed and _needs_profile_bootstrap(settings, stage):
            logger.info("Profile 未就绪，启动 bootstrap-profile 向导…")
            from yt_forensics.bootstrap.profile_wizard import run_profile_bootstrap

            code = run_profile_bootstrap(settings)
            if code != 0:
                raise RuntimeError("Profile 初始化失败")
            preflight = run_preflight(settings, stage=stage)
            for warn in preflight.warnings:
                logger.warning("Preflight: %s", warn)
        if not preflight.ok:
            raise RuntimeError(format_preflight_errors(preflight))

    time_sync = sync_time(settings.time_sync_source)
    plat = _platform_name()

    db_path = settings.data_dir / "state.db"
    db = StateDB(db_path)
    if resuming:
        db.ensure_run(
            run_id=writer.run_id,
            created_at=format_iso8601(started),
            evidence_dir=str(writer.dir),
            status="running",
        )
        logger.info("断点续采：继续 run_id=%s", writer.run_id)
    else:
        db.create_run(
            run_id=writer.run_id,
            created_at=format_iso8601(started),
            evidence_dir=str(writer.dir),
            status="running",
        )

    dashboard_thread: threading.Thread | None = None
    if options.enable_dashboard:
        dashboard_thread = _start_dashboard(settings, writer.run_id, writer.dir)
        if settings.dashboard_open_browser:
            from yt_forensics.dashboard.app import open_dashboard_browser, wait_for_dashboard

            if wait_for_dashboard(settings.dashboard_host, settings.dashboard_port):
                open_dashboard_browser(settings.dashboard_host, settings.dashboard_port)
            else:
                logger.warning(
                    "Dashboard 尚未就绪，请稍后手动打开: http://%s:%s",
                    settings.dashboard_host,
                    settings.dashboard_port,
                )

    cookie_source = "import_file" if options.cookie_file else "unknown"
    account_email = ""
    counts = RunCounts()
    status = "partial"
    notes = ""
    cookie_result = None

    try:
        _progress_stage("cookie", detail="读取登录态")
        from yt_forensics.cookie import acquire_cookies

        cookie_result = acquire_cookies(options.cookie_file, settings=settings)
        cookie_source = cookie_result.source
        account_email = cookie_result.account_email
        _progress_account(email=account_email, cookie_source=cookie_source)
        logger.info(
            "Cookie 阶段完成 source=%s detail=%s email=%s ok=%s",
            cookie_source,
            cookie_result.detail,
            _mask_email(account_email),
            cookie_result.ok,
        )

        if not cookie_result.ok:
            status = "failed"
            notes = cookie_result.error or "cookie acquisition failed"
            raise RuntimeError(notes)

        _progress_complete("cookie")

        if stage == "cookie":
            status = "completed"
            notes = "stage=cookie"
            raise _StageDone()

        _progress_stage("channels", detail="发现 Personal / Brand 频道")
        from yt_forensics.channels import discover_channels

        channels = discover_channels(cookie_result)
        if options.channel_ids:
            wanted = {c.strip() for c in options.channel_ids if c.strip()}
            channels = [ch for ch in channels if str(ch.get("channel_id") or "") in wanted]
            logger.info("频道过滤 --channel-id %s -> %s 条", wanted, len(channels))
        counts.channels_total = len(channels)
        if channels:
            writer.append_account_mapping(channels)
            counts.channels_done = len(channels)
            # 同步写入状态库（便于后续断点）
            _persist_channels(db, writer.run_id, channels)
        _progress_counts(counts)
        logger.info("频道发现完成 count=%s", counts.channels_total)
        _progress_complete("channels")

        if counts.channels_total == 0:
            status = "failed"
            notes = "未发现任何频道（请确认 Cookie 对应账号已开通 YouTube 频道）"
            raise RuntimeError(notes)

        if stage == "channels":
            status = "completed"
            notes = "stage=channels"
            raise _StageDone()

        _progress_stage("videos", detail="采集视频列表")
        from yt_forensics.export.evidence import find_latest_video_list, load_video_list_csv
        from yt_forensics.videos import harvest_videos

        videos: list[dict] = []
        if stage == "analytics":
            latest = find_latest_video_list(
                settings.evidence_dir, exclude_run_id=writer.run_id
            )
            if latest is not None:
                videos = load_video_list_csv(latest, encoding=settings.csv_encoding)
                logger.info(
                    "Analytics 阶段复用视频列表 path=%s count=%s",
                    latest,
                    len(videos),
                )
        if not videos:
            existing_ids = (
                db.known_video_ids(writer.run_id) if settings.incremental else set()
            )
            videos = harvest_videos(
                cookie_result, channels, settings, existing_video_ids=existing_ids
            )
        counts.videos_total = len(videos)
        if videos:
            writer.append_video_list(videos)
            counts.videos_done = len(videos)
            db.upsert_videos(writer.run_id, videos)
        _progress_counts(counts)
        logger.info("视频列表完成 count=%s", counts.videos_total)
        _progress_complete("videos")

        if stage == "videos":
            status = "completed" if counts.videos_total else "partial"
            notes = "stage=videos" + (
                "" if counts.videos_total else " (no videos collected)"
            )
            raise _StageDone()

        _progress_stage("analytics", detail="拉取 Studio 统计数据")
        from yt_forensics.analytics import harvest_analytics

        analytics_rows = harvest_analytics(
            cookie_result,
            channels,
            videos,
            settings,
            cookie_file=options.cookie_file,
            run_id=writer.run_id,
            db=db,
        )
        counts.analytics_total = len(analytics_rows)
        if analytics_rows:
            if resuming and stage in {"analytics", "all"}:
                writer.write_video_analytics(analytics_rows)
            else:
                writer.append_video_analytics(analytics_rows)
            from yt_forensics.analytics.parse import summarize_analytics_counts

            summary = summarize_analytics_counts(analytics_rows)
            counts.analytics_total = summary["analytics_total"]
            counts.analytics_done = summary["analytics_done"]
            counts.analytics_ok = summary["analytics_ok"]
            counts.analytics_partial = summary["analytics_partial"]
            counts.analytics_unavailable = summary["analytics_unavailable"]
        _progress_counts(counts)
        logger.info("统计分析完成 count=%s", counts.analytics_total)
        _progress_complete("analytics")

        if stage == "analytics":
            status = "completed" if counts.analytics_total else "partial"
            notes = "stage=analytics"
            raise _StageDone()

        if counts.videos_total == 0 and counts.analytics_total == 0:
            status = "partial"
            notes = "channels done; videos/analytics empty or skipped"
        elif counts.videos_total > 0:
            status = "completed"
            notes = ""
        else:
            status = "partial"
            notes = ""

    except _StageDone:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.exception("提取失败: %s", exc)
        status = "failed"
        notes = str(exc)
    finally:
        if cookie_result is not None:
            cookie_result.close()
        _progress_stage("finalize", detail="写入 meta.json 与 hashes.sha256")
        finished = utc_now()
        meta = MetaDocument(
            run_id=writer.run_id,
            started_at=format_iso8601(started),
            finished_at=format_iso8601(finished),
            status=status,
            platform=plat,
            account_email=account_email,
            cookie_source=cookie_source,
            time_sync={
                "system_time": time_sync.system_time,
                "reference_time": time_sync.reference_time,
                "offset_seconds": time_sync.offset_seconds,
                "source": time_sync.source,
            },
            counts={
                "channels_total": counts.channels_total,
                "channels_done": counts.channels_done,
                "videos_total": counts.videos_total,
                "videos_done": counts.videos_done,
                **counts.analytics_counts_dict(),
            },
            notes=notes,
        )
        writer.finalize(meta)
        db.update_run_status(writer.run_id, status)
        db.close()
        _progress_finish(status=status, notes=notes, finished_at=format_iso8601(finished))
        logger.info(
            "导出完成 status=%s hashes=%s",
            status,
            writer.dir / "hashes.sha256",
        )

    if dashboard_thread is not None:
        url = f"http://{settings.dashboard_host}:{settings.dashboard_port}/"
        logger.info(
            "Dashboard 运行中: %s （按 Ctrl+C 结束）",
            url.rstrip("/"),
        )
        try:
            while dashboard_thread.is_alive():
                dashboard_thread.join(timeout=0.5)
        except KeyboardInterrupt:
            logger.info("收到 Ctrl+C，正在关闭 Dashboard…")
            from yt_forensics.dashboard.app import stop_dashboard

            stop_dashboard()
            dashboard_thread.join(timeout=8)
            logger.info("Dashboard 已关闭")

    return 0 if status in {"completed", "partial"} else 1


class _StageDone(Exception):
    """内部：阶段提前结束。"""


def _persist_channels(db: StateDB, run_id: str, channels: list[dict]) -> None:
    conn = db._conn  # noqa: SLF001 — 同包状态写入
    for ch in channels:
        conn.execute(
            """
            INSERT OR REPLACE INTO channels (
              run_id, channel_id, brand_account_id, handle, title, url,
              account_type, permission_level, video_list_status, analytics_status,
              last_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 'pending', '')
            """,
            (
                run_id,
                ch.get("channel_id", ""),
                ch.get("brand_account_id", ""),
                ch.get("handle", ""),
                ch.get("channel_title", ""),
                ch.get("channel_url", ""),
                ch.get("account_type", ""),
                ch.get("permission_level", ""),
            ),
        )
    conn.execute(
        "UPDATE runs SET account_email = ?, cookie_source = ? WHERE run_id = ?",
        (
            channels[0].get("account_email", "") if channels else "",
            channels[0].get("cookie_source", "") if channels else "",
            run_id,
        ),
    )
    conn.commit()


def _start_dashboard(settings: Settings, run_id: str, evidence_dir: Path) -> threading.Thread:
    from yt_forensics.dashboard.app import serve_dashboard

    thread = threading.Thread(
        target=serve_dashboard,
        kwargs={
            "host": settings.dashboard_host,
            "port": settings.dashboard_port,
            "run_id": run_id,
            "evidence_dir": str(evidence_dir),
            "evidence_root": str(settings.evidence_dir),
            "csv_encoding": settings.csv_encoding,
        },
        name="dashboard",
        daemon=False,
    )
    thread.start()
    return thread


def _progress_reset(run_id: str, evidence_dir: Path, stage: str, started_at: str) -> None:
    if get_progress is None:
        return
    get_progress().reset(
        run_id=run_id,
        evidence_dir=str(evidence_dir),
        requested_stage=stage,
        started_at=started_at,
    )


def _progress_stage(name: str, *, detail: str = "") -> None:
    if get_progress is None:
        return
    get_progress().set_stage(name, detail=detail)


def _progress_complete(name: str) -> None:
    if get_progress is None:
        return
    get_progress().complete_stage(name)


def _progress_counts(counts: RunCounts) -> None:
    if get_progress is None:
        return
    get_progress().update_counts(
        channels_total=counts.channels_total,
        channels_done=counts.channels_done,
        videos_total=counts.videos_total,
        videos_done=counts.videos_done,
        **counts.analytics_counts_dict(),
    )


def _progress_account(*, email: str, cookie_source: str) -> None:
    if get_progress is None:
        return
    get_progress().set_account(email=email, cookie_source=cookie_source)


def _progress_finish(*, status: str, notes: str, finished_at: str) -> None:
    if get_progress is None:
        return
    get_progress().finish(status=status, notes=notes, finished_at=finished_at)


def _platform_name() -> str:
    system = platform.system().lower()
    if system.startswith("windows"):
        return "windows"
    if system == "darwin":
        return "darwin"
    return "linux"


def _needs_profile_bootstrap(settings: Settings, stage: str) -> bool:
    from yt_forensics.engine.preflight import STAGES_NEED_PROFILE

    if stage not in STAGES_NEED_PROFILE:
        return False
    if not settings.enable_playwright_fallback or not settings.playwright_use_chrome_profile:
        return False
    from yt_forensics.cookie.browser_profile import dedicated_profile_dir, profile_is_initialized

    browser = settings.playwright_browser or settings.cookie_browser or "chrome"
    return not profile_is_initialized(dedicated_profile_dir(settings.data_dir, browser))


def _mask_email(email: str) -> str:
    if not email or "@" not in email:
        return email
    name, domain = email.split("@", 1)
    if len(name) <= 2:
        masked = "*" * len(name)
    else:
        masked = name[0] + "*" * (len(name) - 2) + name[-1]
    return f"{masked}@{domain}"


def ensure_src_on_path() -> None:
    """开发模式下保证 src 可导入。"""
    root = Path(__file__).resolve().parents[3]
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
