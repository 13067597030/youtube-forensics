"""临时：列出 accounts_list 频道与 Studio 权限。"""
from __future__ import annotations

import sys

from yt_forensics.config import load_settings
from yt_forensics.cookie import acquire_cookies
from yt_forensics.channels.discover import (
    _from_accounts_list,
    resolve_channel_id_by_handle,
    probe_permission,
)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    settings = load_settings()
    cr = acquire_cookies(settings=settings)
    if not cr.ok or cr.session is None:
        print("cookie fail", cr.error)
        return 1
    items = _from_accounts_list(cr.session)
    print(f"accounts_list: {len(items)}")
    for it in items:
        cid = str(it.get("channel_id") or "")
        handle = str(it.get("handle") or "")
        brand = str(it.get("brand_account_id") or "")
        if not cid and handle:
            cid = resolve_channel_id_by_handle(cr.session, handle)
        perm = probe_permission(cr.session, cid, brand_account_id=brand) if cid else "none"
        print(
            f"  {it.get('account_name')} | {cid} | {handle} | "
            f"{it.get('account_type')} | brand={brand} | perm={perm}"
        )
    cr.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
