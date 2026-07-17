"""采集进度追踪（Dashboard 与 runner 共享）。"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

STAGE_PIPELINES: dict[str, tuple[str, ...]] = {
    "all": ("cookie", "channels", "videos", "analytics", "finalize"),
    "cookie": ("cookie", "finalize"),
    "channels": ("cookie", "channels", "finalize"),
    "videos": ("cookie", "channels", "videos", "finalize"),
    "analytics": ("cookie", "channels", "videos", "analytics", "finalize"),
}

STAGE_LABELS: dict[str, str] = {
    "cookie": "Cookie 获取",
    "channels": "频道发现",
    "videos": "视频列表",
    "analytics": "统计分析",
    "finalize": "导出校验",
}


@dataclass
class RunProgressState:
    run_id: str = ""
    evidence_dir: str = ""
    requested_stage: str = "all"
    status: str = "running"
    current_stage: str = ""
    current_label: str = ""
    detail: str = ""
    notes: str = ""
    started_at: str = ""
    finished_at: str = ""
    account_email: str = ""
    cookie_source: str = ""
    channels_total: int = 0
    channels_done: int = 0
    videos_total: int = 0
    videos_done: int = 0
    analytics_total: int = 0
    analytics_done: int = 0
    analytics_ok: int = 0
    analytics_partial: int = 0
    analytics_unavailable: int = 0
    analytics_channel: str = ""
    analytics_page: int = 0
    analytics_page_total: int = 0
    analytics_page_source: str = ""
    completed_stages: list[str] = field(default_factory=list)

    def snapshot(self) -> dict[str, Any]:
        pipeline = STAGE_PIPELINES.get(self.requested_stage, STAGE_PIPELINES["all"])
        stage_index = pipeline.index(self.current_stage) if self.current_stage in pipeline else 0
        done_count = len([s for s in self.completed_stages if s in pipeline])
        if self.status in {"completed", "partial", "failed"} and "finalize" in pipeline:
            done_count = len(pipeline)
        elif self.current_stage and self.current_stage not in self.completed_stages:
            done_count = max(done_count, stage_index)

        total = max(len(pipeline), 1)
        percent = min(100, int(done_count / total * 100))
        if self.status == "running" and self.current_stage and percent >= 100:
            percent = 99

        stages = []
        for name in pipeline:
            if name in self.completed_stages:
                state = "done"
            elif name == self.current_stage:
                state = "active"
            else:
                state = "pending"
            stages.append(
                {
                    "id": name,
                    "label": STAGE_LABELS.get(name, name),
                    "state": state,
                }
            )

        return {
            "run_id": self.run_id,
            "evidence_dir": self.evidence_dir,
            "requested_stage": self.requested_stage,
            "status": self.status,
            "phase": self.current_stage or "starting",
            "current_label": self.current_label or STAGE_LABELS.get(self.current_stage, ""),
            "detail": self.detail,
            "notes": self.notes,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "account_email": self.account_email,
            "cookie_source": self.cookie_source,
            "progress_percent": percent,
            "stages": stages,
            "analytics_progress": {
                "channel": self.analytics_channel,
                "page": self.analytics_page,
                "page_total": self.analytics_page_total,
                "source": self.analytics_page_source,
            },
            "counts": {
                "channels_total": self.channels_total,
                "channels_done": self.channels_done,
                "videos_total": self.videos_total,
                "videos_done": self.videos_done,
                "analytics_total": self.analytics_total,
                "analytics_done": self.analytics_done,
                "analytics_ok": self.analytics_ok,
                "analytics_partial": self.analytics_partial,
                "analytics_unavailable": self.analytics_unavailable,
            },
        }


class RunProgress:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = RunProgressState()

    def reset(
        self,
        *,
        run_id: str,
        evidence_dir: str,
        requested_stage: str,
        started_at: str = "",
    ) -> None:
        with self._lock:
            self._state = RunProgressState(
                run_id=run_id,
                evidence_dir=evidence_dir,
                requested_stage=requested_stage,
                started_at=started_at,
            )

    def set_stage(self, stage: str, *, label: str = "", detail: str = "") -> None:
        with self._lock:
            prev = self._state.current_stage
            if prev and prev != stage and prev not in self._state.completed_stages:
                self._state.completed_stages.append(prev)
            self._state.current_stage = stage
            if label:
                self._state.current_label = label
            else:
                self._state.current_label = STAGE_LABELS.get(stage, stage)
            if detail:
                self._state.detail = detail

    def complete_stage(self, stage: str) -> None:
        with self._lock:
            if stage not in self._state.completed_stages:
                self._state.completed_stages.append(stage)

    def update_counts(self, **kwargs: int) -> None:
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self._state, key):
                    setattr(self._state, key, int(value))

    def set_account(self, *, email: str = "", cookie_source: str = "") -> None:
        with self._lock:
            if email:
                self._state.account_email = email
            if cookie_source:
                self._state.cookie_source = cookie_source

    def set_analytics_pagination(
        self,
        *,
        channel: str = "",
        page: int = 0,
        page_total: int = 0,
        source: str = "",
    ) -> None:
        with self._lock:
            self._state.analytics_channel = channel
            self._state.analytics_page = int(page)
            self._state.analytics_page_total = int(page_total)
            self._state.analytics_page_source = source
            if channel and page_total > 0:
                src = source or "API"
                self._state.detail = f"{channel} · {src} 第 {page}/{page_total} 页"

    def finish(self, *, status: str, notes: str = "", finished_at: str = "") -> None:
        with self._lock:
            self._state.status = status
            self._state.notes = notes
            if finished_at:
                self._state.finished_at = finished_at
            if self._state.current_stage and self._state.current_stage not in self._state.completed_stages:
                self._state.completed_stages.append(self._state.current_stage)
            if "finalize" not in self._state.completed_stages:
                self._state.completed_stages.append("finalize")
            self._state.current_stage = "finalize"
            self._state.current_label = STAGE_LABELS["finalize"]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._state.snapshot()


_progress = RunProgress()


def get_progress() -> RunProgress:
    return _progress


def report_analytics_pagination(
    *,
    channel: str,
    page: int,
    page_total: int,
    source: str = "Studio API",
) -> None:
    """供 harvest / browser_harvest 上报分页进度（Dashboard 展示）。"""
    try:
        get_progress().set_analytics_pagination(
            channel=channel,
            page=page,
            page_total=page_total,
            source=source,
        )
    except Exception:  # noqa: BLE001
        pass
