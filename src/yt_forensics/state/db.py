"""SQLite 任务状态库（断点续采）。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  status TEXT NOT NULL,
  account_email TEXT,
  cookie_source TEXT,
  evidence_dir TEXT
);

CREATE TABLE IF NOT EXISTS channels (
  run_id TEXT NOT NULL,
  channel_id TEXT NOT NULL,
  brand_account_id TEXT,
  handle TEXT,
  title TEXT,
  url TEXT,
  account_type TEXT,
  permission_level TEXT,
  video_list_status TEXT,
  analytics_status TEXT,
  last_error TEXT,
  PRIMARY KEY (run_id, channel_id)
);

CREATE TABLE IF NOT EXISTS videos (
  run_id TEXT NOT NULL,
  channel_id TEXT NOT NULL,
  video_id TEXT NOT NULL,
  payload_json TEXT,
  list_status TEXT,
  analytics_json TEXT,
  analytics_status TEXT,
  updated_at TEXT,
  PRIMARY KEY (run_id, channel_id, video_id)
);

CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  job_type TEXT NOT NULL,
  target_id TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  next_run_at TEXT,
  status TEXT NOT NULL,
  last_error TEXT
);
"""


class StateDB:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def create_run(
        self,
        run_id: str,
        created_at: str,
        evidence_dir: str,
        status: str = "running",
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO runs (run_id, created_at, status, evidence_dir)
            VALUES (?, ?, ?, ?)
            """,
            (run_id, created_at, status, evidence_dir),
        )
        self._conn.commit()

    def ensure_run(
        self,
        run_id: str,
        created_at: str,
        evidence_dir: str,
        status: str = "running",
    ) -> None:
        """断点续采：run 不存在则创建，存在则更新状态为 running。"""
        cur = self._conn.execute(
            "SELECT run_id FROM runs WHERE run_id = ?",
            (run_id,),
        )
        if cur.fetchone():
            self.update_run_status(run_id, status)
            return
        self.create_run(run_id, created_at, evidence_dir, status=status)

    def update_run_status(self, run_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE runs SET status = ? WHERE run_id = ?",
            (status, run_id),
        )
        self._conn.commit()

    def known_video_ids(self, run_id: str | None = None) -> set[str]:
        """增量采集：返回已记录 video_id 集合。"""
        if run_id:
            cur = self._conn.execute(
                "SELECT video_id FROM videos WHERE run_id = ?",
                (run_id,),
            )
        else:
            cur = self._conn.execute("SELECT DISTINCT video_id FROM videos")
        return {str(r[0]) for r in cur if r[0]}

    def upsert_videos(self, run_id: str, rows: list[dict]) -> None:
        import json
        from yt_forensics.export.evidence import format_iso8601, utc_now

        now = format_iso8601(utc_now())
        for row in rows:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO videos (
                  run_id, channel_id, video_id, payload_json,
                  list_status, updated_at
                ) VALUES (?, ?, ?, ?, 'done', ?)
                """,
                (
                    run_id,
                    row.get("channel_id", ""),
                    row.get("video_id", ""),
                    json.dumps(row, ensure_ascii=False),
                    now,
                ),
            )
        self._conn.commit()

    def save_analytics_rows(self, run_id: str, rows: list[dict]) -> None:
        """断点：按频道批次写入 Analytics 行。"""
        import json
        from yt_forensics.export.evidence import format_iso8601, utc_now

        now = format_iso8601(utc_now())
        for row in rows:
            cid = str(row.get("channel_id") or "")
            vid = str(row.get("video_id") or "")
            if not cid or not vid:
                continue
            self._conn.execute(
                """
                INSERT OR REPLACE INTO videos (
                  run_id, channel_id, video_id, analytics_json,
                  analytics_status, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    cid,
                    vid,
                    json.dumps(row, ensure_ascii=False),
                    str(row.get("analytics_status") or ""),
                    now,
                ),
            )
        self._conn.commit()

    def load_completed_analytics(
        self, *, exclude_run_id: str = ""
    ) -> dict[tuple[str, str], dict[str, str]]:
        """读取历史已完成 Analytics（按 updated_at 取最新）。"""
        import json

        sql = """
            SELECT channel_id, video_id, analytics_json, analytics_status, updated_at
            FROM videos
            WHERE analytics_json IS NOT NULL AND analytics_json != ''
              AND analytics_status IN ('ok', 'partial')
        """
        params: list[str] = []
        if exclude_run_id:
            sql += " AND run_id != ?"
            params.append(exclude_run_id)
        sql += " ORDER BY updated_at DESC"
        cur = self._conn.execute(sql, params)
        out: dict[tuple[str, str], dict[str, str]] = {}
        for r in cur:
            cid = str(r["channel_id"] or "")
            vid = str(r["video_id"] or "")
            key = (cid, vid)
            if not cid or not vid or key in out:
                continue
            try:
                row = json.loads(r["analytics_json"])
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                out[key] = {k: str(v or "") for k, v in row.items()}
        return out

    def update_channel_analytics_status(
        self,
        run_id: str,
        channel_id: str,
        status: str,
        *,
        error: str = "",
    ) -> None:
        self._conn.execute(
            """
            UPDATE channels
            SET analytics_status = ?, last_error = ?
            WHERE run_id = ? AND channel_id = ?
            """,
            (status, error, run_id, channel_id),
        )
        self._conn.commit()

    def is_channel_analytics_done(self, run_id: str, channel_id: str) -> bool:
        cur = self._conn.execute(
            """
            SELECT analytics_status FROM channels
            WHERE run_id = ? AND channel_id = ?
            """,
            (run_id, channel_id),
        )
        row = cur.fetchone()
        return bool(row and str(row[0]) == "done")

    def load_run_analytics(
        self, run_id: str, channel_id: str = ""
    ) -> dict[tuple[str, str], dict[str, str]]:
        """读取本轮 run 已 checkpoint 的 Analytics 行。"""
        import json

        sql = """
            SELECT channel_id, video_id, analytics_json
            FROM videos
            WHERE run_id = ? AND analytics_json IS NOT NULL AND analytics_json != ''
        """
        params: list[str] = [run_id]
        if channel_id:
            sql += " AND channel_id = ?"
            params.append(channel_id)
        cur = self._conn.execute(sql, params)
        out: dict[tuple[str, str], dict[str, str]] = {}
        for r in cur:
            cid = str(r["channel_id"] or "")
            vid = str(r["video_id"] or "")
            try:
                row = json.loads(r["analytics_json"])
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and cid and vid:
                out[(cid, vid)] = {k: str(v or "") for k, v in row.items()}
        return out
