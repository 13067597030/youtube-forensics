"""首次初始化专用浏览器 Profile（委托 yt_forensics.bootstrap）。"""
from __future__ import annotations

import sys

from yt_forensics.bootstrap.profile_wizard import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
