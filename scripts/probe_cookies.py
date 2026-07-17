import os
import sqlite3
import tempfile
from pathlib import Path

from yt_forensics.cookie.chromium_win import _copy_cookie_db, _sqlite_uri

local = Path(os.environ["LOCALAPPDATA"])
for name, base in [
    ("edge", local / "Microsoft" / "Edge" / "User Data"),
    ("chrome", local / "Google" / "Chrome" / "User Data"),
]:
    db = base / "Default" / "Network" / "Cookies"
    if not db.is_file():
        print(name, "no db")
        continue
    print(name, "size", db.stat().st_size)
    td = tempfile.mkdtemp()
    dest = Path(td) / "Cookies"
    try:
        _copy_cookie_db(db, dest)
        print(" copy ok", dest.stat().st_size)
        conn = sqlite3.connect(str(dest))
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        ]
        print(" tables", tables)
        conn.close()
    except Exception as e:
        print(" err", e)
    try:
        conn = sqlite3.connect(_sqlite_uri(db), uri=True, timeout=5)
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        ]
        print(" uri tables", tables)
        conn.close()
    except Exception as e:
        print(" uri err", e)
