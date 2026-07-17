"""M3: 视频列表采集。"""

from __future__ import annotations

from typing import Any

from yt_forensics.config import Settings
from yt_forensics.cookie import CookieResult
from yt_forensics.videos.harvest import harvest_videos

__all__ = ["harvest_videos"]
