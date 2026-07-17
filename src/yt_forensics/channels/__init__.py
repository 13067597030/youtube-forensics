"""M2: 频道发现（Personal + Brand）。"""

from __future__ import annotations

import logging
from typing import Any

from yt_forensics.channels.discover import discover_all_channels
from yt_forensics.cookie import CookieResult

logger = logging.getLogger(__name__)


def discover_channels(cookie: CookieResult) -> list[dict[str, Any]]:
    """发现全部频道，返回 Account_Mapping 行。"""
    if cookie.session is None:
        raise RuntimeError("Cookie 会话不可用，无法发现频道")

    rows = discover_all_channels(
        cookie.session,
        account_email=cookie.account_email,
        cookie_source=cookie.source,
    )
    logger.info("频道去重后共 %s 个", len(rows))
    return rows
