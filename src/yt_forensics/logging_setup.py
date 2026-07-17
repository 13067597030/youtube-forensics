"""日志：同时写控制台与 Evidence/run.log；禁止输出 Cookie 等敏感值。"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from yt_forensics.export.evidence import BEIJING_TZ

_SENSITIVE = re.compile(
    r"(cookie|authorization|sapisid|psid|sessionid)\s*[:=]\s*\S+",
    re.IGNORECASE,
)


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if _SENSITIVE.search(msg):
            record.msg = _SENSITIVE.sub(r"\1=[REDACTED]", msg)
            record.args = ()
        return True


class BeijingFormatter(logging.Formatter):
    """日志时间戳使用北京时间，与导出 CSV/meta 一致。"""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        dt = datetime.fromtimestamp(record.created, tz=BEIJING_TZ)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime("%Y-%m-%dT%H:%M:%S")


def setup_logging(log_file: Path | None = None, level: int = logging.INFO) -> None:
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    fmt = BeijingFormatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    redact = RedactFilter()

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console.addFilter(redact)
    root.addHandler(console)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(fmt)
        file_handler.addFilter(redact)
        root.addHandler(file_handler)
