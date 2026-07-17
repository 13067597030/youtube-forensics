"""本地 Web Dashboard。"""

from __future__ import annotations

import logging
import socket
import threading
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from yt_forensics.dashboard.progress import get_progress
from yt_forensics.dashboard.services import (
    build_summary,
    read_csv_preview,
    read_hashes,
    read_meta,
    tail_log,
)
from yt_forensics.export.schema import (
    ACCOUNT_MAPPING_FILENAME,
    HASHES_FILENAME,
    LOG_FILENAME,
    META_FILENAME,
    VIDEO_ANALYTICS_FILENAME,
    VIDEO_LIST_FILENAME,
)

if TYPE_CHECKING:
    import uvicorn

from yt_forensics.runtime_paths import dashboard_static_dir

logger = logging.getLogger(__name__)

STATIC_DIR = dashboard_static_dir()

PREVIEW_FILES = {
    "account_mapping": ACCOUNT_MAPPING_FILENAME,
    "video_list": VIDEO_LIST_FILENAME,
    "video_analytics": VIDEO_ANALYTICS_FILENAME,
}

_server: uvicorn.Server | None = None
_server_lock = threading.Lock()


def create_app(
    run_id: str = "",
    evidence_dir: str = "",
    evidence_root: str = "Evidence",
    csv_encoding: str = "utf-8-sig",
) -> FastAPI:
    app = FastAPI(title="YouTubeForensics Dashboard", version="0.2.0")
    resolved_evidence = Path(evidence_dir) if evidence_dir else Path(evidence_root) / run_id

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        index_path = STATIC_DIR / "index.html"
        if index_path.is_file():
            return index_path.read_text(encoding="utf-8")
        return "<h1>YouTubeForensics</h1><p>Dashboard static missing.</p>"

    @app.get("/api/status")
    def status() -> dict:
        data = get_progress().snapshot()
        if not data.get("run_id"):
            data.update(
                {
                    "run_id": run_id,
                    "evidence_dir": str(resolved_evidence),
                    "status": "starting",
                    "phase": "starting",
                    "current_label": "启动中",
                    "message": "等待采集引擎…",
                }
            )
        else:
            data["message"] = data.get("detail") or data.get("notes") or data.get("current_label", "")
        data["evidence_root"] = evidence_root
        return data

    @app.get("/api/logs")
    def logs(offset: int = Query(0, ge=0)) -> dict:
        log_path = resolved_evidence / LOG_FILENAME
        return tail_log(log_path, offset)

    @app.get("/api/preview/summary")
    def preview_summary() -> dict:
        return build_summary(resolved_evidence, encoding=csv_encoding)

    @app.get("/api/preview/{name}")
    def preview_table(name: str, limit: int = Query(25, ge=1, le=200)) -> dict:
        filename = PREVIEW_FILES.get(name)
        if not filename:
            raise HTTPException(status_code=404, detail="unknown preview")
        return read_csv_preview(resolved_evidence / filename, limit=limit, encoding=csv_encoding)

    @app.get("/api/meta")
    def meta() -> dict:
        data = read_meta(resolved_evidence / META_FILENAME)
        if data is None:
            return {"available": False}
        return {"available": True, "data": data}

    @app.get("/api/hashes")
    def hashes() -> dict:
        items = read_hashes(resolved_evidence / HASHES_FILENAME)
        return {"available": bool(items), "items": items}

    return app


def dashboard_url(host: str, port: int) -> str:
    display_host = host if host not in ("0.0.0.0", "::") else "127.0.0.1"
    return f"http://{display_host}:{port}/"


def wait_for_dashboard(host: str, port: int, *, timeout_sec: float = 20.0) -> bool:
    """轮询直到 Dashboard 可连接。"""
    import time

    probe_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            with socket.create_connection((probe_host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.15)
    return False


def open_dashboard_browser(host: str, port: int) -> None:
    url = dashboard_url(host, port)
    try:
        opened = webbrowser.open(url, new=2)
        if opened:
            logger.info("已自动打开浏览器: %s", url)
        else:
            logger.warning("未能自动打开浏览器，请手动访问: %s", url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("打开浏览器失败 (%s)，请手动访问: %s", exc, url)


def stop_dashboard() -> None:
    with _server_lock:
        server = _server
    if server is not None:
        server.should_exit = True


def serve_dashboard(
    host: str = "127.0.0.1",
    port: int = 8787,
    run_id: str = "",
    evidence_dir: str = "",
    evidence_root: str = "Evidence",
    csv_encoding: str = "utf-8-sig",
) -> None:
    import uvicorn

    global _server
    app = create_app(
        run_id=run_id,
        evidence_dir=evidence_dir,
        evidence_root=evidence_root,
        csv_encoding=csv_encoding,
    )
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    with _server_lock:
        _server = server
    logger.info("Dashboard listening on http://%s:%s", host, port)
    try:
        server.run()
    finally:
        with _server_lock:
            if _server is server:
                _server = None
