"""频道发现：Personal + Brand（Innertube accounts_list + 页面回退）。"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote

import httpx

from yt_forensics.cookie.session import USER_AGENT, YTSession
from yt_forensics.export.evidence import format_iso8601, utc_now

logger = logging.getLogger(__name__)

CHANNEL_ID_RE = re.compile(r"^UC[\w-]{20,}$")


def discover_all_channels(
    session: YTSession,
    *,
    account_email: str,
    cookie_source: str,
) -> list[dict[str, str]]:
    """返回 Account_Mapping 行字典列表（已按 channel_id 去重）。"""
    forensic_time = format_iso8601(utc_now())
    raw_items: list[dict[str, Any]] = []

    try:
        raw_items.extend(_from_accounts_list(session))
        logger.info("accounts_list 解析到候选 %s 条", len(raw_items))
    except Exception as exc:  # noqa: BLE001
        logger.warning("accounts_list 失败: %s", exc)

    # channel_switcher 常含当前 Personal 频道；即使 accounts_list 有结果也应合并
    try:
        switcher_items = _from_channel_switcher_page(session)
        logger.info("channel_switcher 解析到候选 %s 条", len(switcher_items))
        raw_items.extend(switcher_items)
    except Exception as exc:  # noqa: BLE001
        logger.warning("channel_switcher 失败: %s", exc)

    raw_items = _dedupe_raw(raw_items)

    if not raw_items:
        try:
            one = _from_studio_landing(session)
            if one:
                raw_items.append(one)
                logger.info("Studio 落地页得到当前频道 1 条")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Studio 落地页回退失败: %s", exc)

    if not raw_items:
        try:
            one = _from_homepage_active(session)
            if one:
                raw_items.append(one)
                logger.info("首页活动频道 1 条")
        except Exception as exc:  # noqa: BLE001
            logger.warning("首页活动频道解析失败: %s", exc)

    # 补全缺失 channel_id（clientCacheKey / handle）
    enriched: list[dict[str, Any]] = []
    for item in raw_items:
        if not item.get("channel_id"):
            cid = _resolve_channel_id(session, item)
            if cid:
                item["channel_id"] = cid
        if item.get("channel_id"):
            enriched.append(item)

    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in enriched:
        cid = str(item["channel_id"])
        if cid in seen:
            continue
        if not _channel_is_manageable(session, item):
            logger.debug("跳过非管理频道: %s", cid)
            continue
        seen.add(cid)
        handle = _norm_handle(str(item.get("handle") or ""))
        title = str(item.get("channel_title") or item.get("account_name") or "")
        if not title or not handle:
            meta = _fetch_channel_meta(session, cid)
            title = title or meta.get("title", "")
            handle = handle or meta.get("handle", "")
        url = str(item.get("channel_url") or "")
        if not url:
            url = (
                f"https://www.youtube.com/{handle}"
                if handle
                else f"https://www.youtube.com/channel/{cid}"
            )
        account_type = str(item.get("account_type") or _guess_account_type(item))
        brand_id = str(item.get("brand_account_id") or "")
        permission = probe_permission(session, cid, brand_account_id=brand_id)
        if permission in {"unknown", "none"} and brand_id:
            permission = "manager"
        elif permission == "unknown" and account_type == "brand":
            permission = "manager"
        rows.append(
            {
                "account_email": account_email or "",
                "cookie_source": cookie_source,
                "brand_account_id": str(item.get("brand_account_id") or ""),
                "channel_id": cid,
                "handle": handle,
                "channel_title": title,
                "channel_url": url,
                "account_type": account_type,
                "permission_level": permission,
                "forensic_time": forensic_time,
            }
        )

    return rows


def _from_accounts_list(session: YTSession) -> list[dict[str, Any]]:
    data = session.innertube_post(
        "account/accounts_list",
        {
            "requestType": "ACCOUNTS_LIST_REQUEST_TYPE_CHANNEL_SWITCHER",
            "callCircumstance": "SWITCHING_USERS_FULL",
        },
    )
    items: list[dict[str, Any]] = []
    for action in data.get("actions") or []:
        if not isinstance(action, dict):
            continue
        page = (
            action.get("updateChannelSwitcherPageAction") or {}
        ).get("page") or {}
        csr = page.get("channelSwitcherPageRenderer") or {}
        for content in csr.get("contents") or []:
            if not isinstance(content, dict):
                continue
            block = content.get("accountItemRenderer")
            if isinstance(block, dict):
                parsed = _parse_account_item(block)
                if parsed:
                    items.append(parsed)
    items.extend(parse_accounts_list_response(data))
    return _dedupe_raw(items)


def parse_accounts_list_response(data: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for node in _walk(data):
        if not isinstance(node, dict):
            continue
        # accountItem / accountItemRenderer
        block = None
        if "accountName" in node and (
            "channelHandle" in node or "serviceEndpoint" in node or "hasChannel" in node
        ):
            block = node
        elif "accountItemRenderer" in node and isinstance(
            node["accountItemRenderer"], dict
        ):
            block = node["accountItemRenderer"]
        if block is None:
            continue
        parsed = _parse_account_item(block)
        if parsed:
            items.append(parsed)
    return _dedupe_raw(items)


def _parse_account_item(block: dict[str, Any]) -> dict[str, Any] | None:
    name = _text(block.get("accountName"))
    handle = _norm_handle(_text(block.get("channelHandle")))
    byline = _text(block.get("accountByline"))
    has_channel = bool(block.get("hasChannel", True))

    channel_id = ""
    brand_id = ""
    endpoint = block.get("serviceEndpoint") or block.get("endpoint") or {}
    if isinstance(endpoint, dict):
        channel_id = _find_channel_id(endpoint) or _find_cache_channel_id(endpoint) or ""
        brand_id = _find_brand_id(endpoint) or ""

    if not has_channel and not channel_id and not handle:
        return None
    if not channel_id and not handle and not name:
        return None

    account_type = "brand"
    # 经验：byline 含 "Google Account" / 邮箱 时常为 personal；Brand 常带成员数等
    lower_byline = byline.lower()
    if "google account" in lower_byline or (byline and "@" in byline):
        account_type = "personal"
    if brand_id:
        account_type = "brand"

    return {
        "account_name": name,
        "channel_title": name,
        "handle": handle,
        "channel_id": channel_id,
        "brand_account_id": brand_id,
        "account_type": account_type,
        "byline": byline,
        "has_channel": has_channel,
        "from_accounts_list": True,
    }


def _from_channel_switcher_page(session: YTSession) -> list[dict[str, Any]]:
    resp = session.client.get(
        "https://www.youtube.com/channel_switcher",
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html",
            **session.auth_headers(),
        },
    )
    resp.raise_for_status()
    html = resp.text
    # ytInitialData
    m = re.search(
        r"var ytInitialData\s*=\s*(\{.+?\});\s*</script>",
        html,
        re.DOTALL,
    )
    if not m:
        m = re.search(r"ytInitialData\s*=\s*(\{.+?\});", html, re.DOTALL)
    if not m:
        return []
    import json

    data = json.loads(m.group(1))
    items = _items_from_switcher_data(data)
    if items:
        return items
    return []


def _items_from_switcher_data(data: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for action in data.get("actions") or []:
        if not isinstance(action, dict):
            continue
        page = (action.get("updateChannelSwitcherPageAction") or {}).get("page") or {}
        csr = page.get("channelSwitcherPageRenderer") or {}
        for content in csr.get("contents") or []:
            if isinstance(content, dict) and "accountItemRenderer" in content:
                parsed = _parse_account_item(content["accountItemRenderer"])
                if parsed:
                    items.append(parsed)
    items.extend(parse_accounts_list_response(data))
    # 结构化 navigationEndpoint：仅 /channel/UC... 路径
    for node in _walk(data):
        if not isinstance(node, dict):
            continue
        nav = node.get("navigationEndpoint") or node.get("command") or {}
        if not isinstance(nav, dict):
            continue
        url = (
            (nav.get("commandMetadata") or {})
            .get("webCommandMetadata", {})
            .get("url", "")
        )
        browse = nav.get("browseEndpoint") or {}
        cid = browse.get("browseId") if isinstance(browse, dict) else ""
        if isinstance(url, str) and "/channel/UC" in url:
            m = re.search(r"/channel/(UC[\w-]{22})", url)
            if m:
                cid = m.group(1)
        if isinstance(cid, str) and CHANNEL_ID_RE.match(cid):
            items.append(
                {
                    "channel_id": cid,
                    "channel_title": _text(node.get("title")) or "",
                    "handle": "",
                    "brand_account_id": "",
                    "account_type": "brand",
                }
            )
    return _dedupe_raw(items)


def _from_homepage_active(session: YTSession) -> dict[str, Any] | None:
    resp = session.client.get(
        "https://www.youtube.com/",
        headers={"User-Agent": USER_AGENT, "Accept": "text/html", **session.auth_headers()},
    )
    m = re.search(r'"channelId"\s*:\s*"(UC[\w-]{22})"', resp.text)
    if not m:
        return None
    return {
        "channel_id": m.group(1),
        "channel_title": "",
        "handle": "",
        "brand_account_id": "",
        "account_type": "personal",
    }


def _resolve_channel_id(session: YTSession, item: dict[str, Any]) -> str:
    cid = str(item.get("channel_id") or "")
    if cid:
        return cid
    handle = str(item.get("handle") or "")
    if handle:
        resolved = resolve_channel_id_by_handle(session, handle)
        if resolved:
            return resolved
    return ""


def _channel_is_manageable(session: YTSession, item: dict[str, Any]) -> bool:
    """accounts_list 中的 Brand/频道切换项视为可管理；否则回退 Studio 页面探测。"""
    cid = str(item.get("channel_id") or "")
    if not cid:
        return False
    if item.get("from_accounts_list") and item.get("has_channel", True):
        return True
    perm = probe_permission(
        session,
        cid,
        brand_account_id=str(item.get("brand_account_id") or ""),
    )
    return perm in {"owner", "manager"}


def _fetch_channel_meta(session: YTSession, channel_id: str) -> dict[str, str]:
    try:
        data = session.innertube_post(
            "browse",
            {"browseId": channel_id},
        )
        title = ""
        handle = ""
        for node in _walk(data):
            if not isinstance(node, dict):
                continue
            if not title and "title" in node:
                t = _text(node.get("title"))
                if t and len(t) < 200:
                    title = t
            if not handle and "canonicalChannelUrl" in str(node):
                url = str(node.get("canonicalChannelUrl") or node.get("navigationEndpoint", {}))
                hm = re.search(r"@[\w.-]+", url)
                if hm:
                    handle = hm.group(0)
        return {"title": title, "handle": _norm_handle(handle)}
    except Exception as exc:  # noqa: BLE001
        logger.debug("频道元数据 %s 失败: %s", channel_id, exc)
        return {}


def _from_studio_landing(session: YTSession) -> dict[str, Any] | None:
    resp = session.client.get(
        "https://studio.youtube.com/",
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html",
            **session.auth_headers("https://studio.youtube.com"),
        },
    )
    final = str(resp.url)
    m = re.search(r"/channel/(UC[\w-]{20,})", final)
    if not m:
        m = re.search(r"/channel/(UC[\w-]{20,})", resp.text)
    if not m:
        return None
    cid = m.group(1)
    return {
        "channel_id": cid,
        "channel_title": "",
        "handle": "",
        "brand_account_id": "",
        "account_type": "personal",
    }


def resolve_channel_id_by_handle(session: YTSession, handle: str) -> str:
    handle = _norm_handle(handle)
    if not handle:
        return ""
    url = f"https://www.youtube.com/{quote(handle)}"
    try:
        resp = session.client.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
        )
        m = re.search(
            r'"channelId"\s*:\s*"(UC[\w-]{20,})"',
            resp.text,
        )
        if m:
            return m.group(1)
        m = re.search(r"/channel/(UC[\w-]{20,})", str(resp.url))
        if m:
            return m.group(1)
    except httpx.HTTPError as exc:
        logger.debug("解析 handle %s 失败: %s", handle, exc)
    return ""


def probe_permission(
    session: YTSession,
    channel_id: str,
    *,
    brand_account_id: str = "",
) -> str:
    """轻量探测 Studio 权限：能打开频道工作室视为 owner/manager，否则 none。"""
    page_url = f"https://studio.youtube.com/channel/{channel_id}/videos"
    if brand_account_id:
        page_url += f"?pageId={brand_account_id}"
    try:
        resp = session.client.get(
            page_url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html",
                **session.auth_headers("https://studio.youtube.com"),
            },
            follow_redirects=True,
        )
        text = resp.text
        lower = text.lower()
        url = str(resp.url).lower()
        if resp.status_code == 200 and channel_id.lower() in url:
            if "无权" in text or "permission" in lower and "denied" in lower:
                return "none"
            if brand_account_id or "CREATOR_CHANNEL_ROLE_TYPE_MANAGER" in text:
                return "manager"
            return "owner"
        if resp.status_code in {401, 403}:
            return "none"
    except httpx.HTTPError as exc:
        logger.debug("权限探测失败 %s: %s", channel_id, exc)
    return "unknown"


def _find_cache_channel_id(obj: Any) -> str | None:
    """Brand 频道：offlineCacheKeyToken.clientCacheKey -> UC...（Studio 后台 ID）。"""
    for node in _walk(obj):
        if not isinstance(node, dict):
            continue
        token = node.get("offlineCacheKeyToken")
        if not isinstance(token, dict):
            continue
        key = token.get("clientCacheKey")
        if isinstance(key, str) and key and not key.startswith("UC"):
            return "UC" + key
        if isinstance(key, str) and CHANNEL_ID_RE.match(key):
            return key
    return None


def _guess_account_type(item: dict[str, Any]) -> str:
    if item.get("brand_account_id"):
        return "brand"
    if str(item.get("account_type")) in {"personal", "brand"}:
        return str(item["account_type"])
    return "personal"


def _find_channel_id(obj: Any) -> str | None:
    for node in _walk(obj):
        if isinstance(node, dict):
            for key in ("browseId", "channelId", "externalChannelId"):
                val = node.get(key)
                if isinstance(val, str) and CHANNEL_ID_RE.match(val):
                    return val
        if isinstance(node, str) and CHANNEL_ID_RE.match(node):
            return node
    return None


def _find_brand_id(obj: Any) -> str | None:
    for node in _walk(obj):
        if not isinstance(node, dict):
            continue
        for key in (
            "obfuscatedGaiaId",
            "obfuscatedGaiaID",
            "delegatedSessionId",
            "datasyncId",
        ):
            val = node.get(key)
            if isinstance(val, str) and val and not CHANNEL_ID_RE.match(val):
                return val
        token = node.get("accountStateToken")
        if isinstance(token, dict):
            val = token.get("obfuscatedGaiaId")
            if isinstance(val, str) and val:
                return val
    return None


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        if "simpleText" in value:
            return str(value["simpleText"]).strip()
        runs = value.get("runs")
        if isinstance(runs, list):
            return "".join(str(r.get("text", "")) for r in runs if isinstance(r, dict))
    return str(value).strip()


def _norm_handle(handle: str) -> str:
    handle = (handle or "").strip()
    if not handle:
        return ""
    if handle.startswith("http"):
        m = re.search(r"youtube\.com/(@[\w.-]+)", handle)
        if m:
            return m.group(1)
    if not handle.startswith("@") and re.fullmatch(r"[\w.-]+", handle):
        return "@" + handle
    return handle


def _walk(obj: Any):
    stack = [obj]
    while stack:
        cur = stack.pop()
        yield cur
        if isinstance(cur, dict):
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)


def _dedupe_raw(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for it in items:
        key = str(it.get("channel_id") or it.get("handle") or it.get("account_name") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out
