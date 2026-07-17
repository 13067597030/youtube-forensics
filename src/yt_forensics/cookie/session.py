"""已登录 YouTube / Google 会话（基于 httpx）。"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

DEFAULT_CLIENT = {
    "clientName": "WEB",
    "clientVersion": "2.20240715.00.00",
    "hl": "en",
    "gl": "US",
    "userAgent": USER_AGENT,
}


@dataclass
class YTSession:
    client: httpx.Client
    cookies: dict[str, str] = field(default_factory=dict)
    api_key: str = ""
    client_version: str = DEFAULT_CLIENT["clientVersion"]
    visitor_data: str = ""
    datasync_id: str = ""
    account_email: str = ""
    logged_in: bool = False

    def close(self) -> None:
        self.client.close()

    def auth_headers(self, origin: str = "https://www.youtube.com") -> dict[str, str]:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": origin,
            "Referer": f"{origin}/",
            "X-Youtube-Client-Name": "1",
            "X-Youtube-Client-Version": self.client_version,
        }
        sapisid = (
            self.cookies.get("SAPISID")
            or self.cookies.get("__Secure-1PAPISID")
            or self.cookies.get("__Secure-3PAPISID")
        )
        if sapisid:
            headers["Authorization"] = sapisidhash(sapisid, origin)
            headers["X-Origin"] = origin
        if self.visitor_data:
            headers["X-Goog-Visitor-Id"] = self.visitor_data
        return headers

    def innertube_context(self) -> dict[str, Any]:
        client = dict(DEFAULT_CLIENT)
        client["clientVersion"] = self.client_version or client["clientVersion"]
        if self.visitor_data:
            client["visitorData"] = self.visitor_data
        ctx: dict[str, Any] = {"client": client}
        if self.datasync_id:
            ctx["user"] = {"onBehalfOfUser": self.datasync_id}
        return ctx

    def innertube_post(
        self,
        endpoint: str,
        payload: dict[str, Any] | None = None,
        *,
        origin: str = "https://www.youtube.com",
    ) -> dict[str, Any]:
        body = dict(payload or {})
        body.setdefault("context", self.innertube_context())
        # 使用 onBehalfOfUser 时仅放在特定请求；accounts_list 通常不要带
        if endpoint.endswith("accounts_list"):
            body["context"].get("user", {}).pop("onBehalfOfUser", None)
            if not body["context"].get("user"):
                body["context"].pop("user", None)

        base = origin.rstrip("/")
        url = f"{base}/youtubei/v1/{endpoint.lstrip('/')}"
        params = {"prettyPrint": "false"}
        if self.api_key:
            params["key"] = self.api_key

        resp = self.client.post(
            url,
            params=params,
            json=body,
            headers=self.auth_headers(origin),
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()


def sapisidhash(sapisid: str, origin: str = "https://www.youtube.com") -> str:
    ts = int(time.time())
    digest = hashlib.sha1(f"{ts} {sapisid} {origin}".encode("utf-8")).hexdigest()
    return f"SAPISIDHASH {ts}_{digest}"


def cookies_to_dict(jar: CookieJar | list[Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    if isinstance(jar, CookieJar):
        iterable = list(jar)
    else:
        iterable = jar
    for c in iterable:
        name = getattr(c, "name", None)
        value = getattr(c, "value", None)
        if name and value is not None:
            # 同名时后写覆盖；优先保留 youtube/google 域在 load 阶段已过滤
            out[str(name)] = str(value)
    return out


def build_client(cookie_dict: dict[str, str]) -> httpx.Client:
    client = httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        follow_redirects=True,
        timeout=30.0,
    )
    for name, value in cookie_dict.items():
        # 写入常见 Google/YouTube 域，确保请求带上会话
        for domain in (".youtube.com", ".google.com"):
            client.cookies.set(name, value, domain=domain, path="/")
    return client


def build_client_from_rows(rows: list[dict[str, Any]]) -> httpx.Client:
    """按 Playwright / storage_state 元数据写入 Cookie（保留 domain/path）。"""
    client = httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        follow_redirects=True,
        timeout=30.0,
    )
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "")
        value = row.get("value")
        if not name or value is None:
            continue
        domain = str(row.get("domain") or "")
        path = str(row.get("path") or "/")
        if not domain:
            continue
        client.cookies.set(name, str(value), domain=domain, path=path)
    return client


def rows_to_lookup_dict(rows: list[dict[str, Any]]) -> dict[str, str]:
    """同名 Cookie 按域优先级合并为查找表（供 SAPISID 等鉴权字段）。"""
    priority = {
        ".youtube.com": 0,
        "youtube.com": 0,
        "studio.youtube.com": 0,
        ".google.com": 1,
        "google.com": 1,
        "accounts.google.com": 2,
        "myaccount.google.com": 3,
    }

    def _rank(domain: str) -> int:
        d = (domain or "").lower()
        if d in priority:
            return priority[d]
        if d.endswith(".youtube.com"):
            return 0
        if d.endswith(".google.com"):
            return 1
        return 99

    ordered = sorted(rows, key=lambda r: _rank(str(r.get("domain") or "")))
    out: dict[str, str] = {}
    for row in ordered:
        name = str(row.get("name") or "")
        value = row.get("value")
        if name and value is not None:
            out[name] = str(value)
    return out


def filter_relevant_cookie_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """保留 YouTube / Google 相关 Cookie 行。"""
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        domain = str(row.get("domain") or "").lstrip(".").lower()
        if not domain:
            continue
        if not any(
            domain == suffix or domain.endswith("." + suffix)
            for suffix in ("youtube.com", "google.com", "youtu.be")
        ):
            continue
        name = str(row.get("name") or "")
        value = row.get("value")
        if not name or value is None:
            continue
        out.append(row)
    return out


def load_storage_state_rows(path: Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cookies = data.get("cookies") if isinstance(data, dict) else None
    if not isinstance(cookies, list):
        raise ValueError("storage_state 缺少 cookies 数组")
    rows = filter_relevant_cookie_rows([c for c in cookies if isinstance(c, dict)])
    if not rows:
        raise ValueError("storage_state 无有效 YouTube/Google Cookie")
    return rows


def bootstrap_session(
    cookie_dict: dict[str, str] | None = None,
    *,
    cookie_rows: list[dict[str, Any]] | None = None,
) -> YTSession:
    """用 Cookie 访问 YouTube，解析 ytcfg，校验登录态。"""
    if cookie_rows:
        rows = filter_relevant_cookie_rows(cookie_rows)
        lookup = rows_to_lookup_dict(rows)
        client = build_client_from_rows(rows)
    elif cookie_dict:
        lookup = dict(cookie_dict)
        client = build_client(cookie_dict)
    else:
        raise ValueError("需要 cookie_dict 或 cookie_rows")

    session = YTSession(client=client, cookies=lookup)

    html = ""
    try:
        resp = client.get(
            "https://www.youtube.com/",
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        html = resp.text
    except httpx.HTTPError as exc:
        session.close()
        raise RuntimeError(f"访问 YouTube 失败: {exc}") from exc

    cfg = extract_ytcfg(html)
    session.api_key = (
        str(cfg.get("INNERTUBE_API_KEY") or cfg.get("innertubeApiKey") or "")
    )
    session.client_version = str(
        cfg.get("INNERTUBE_CLIENT_VERSION")
        or cfg.get("innertubeClientVersion")
        or DEFAULT_CLIENT["clientVersion"]
    )
    session.visitor_data = str(
        cfg.get("VISITOR_DATA") or cfg.get("visitorData") or ""
    )
    session.datasync_id = str(
        cfg.get("DATASYNC_ID") or cfg.get("delegatedSessionId") or ""
    )

    logged = cfg.get("LOGGED_IN")
    if logged is None:
        logged = '"LOGGED_IN":true' in html or '"LOGGED_IN": true' in html
    session.logged_in = bool(logged) or _has_session_cookies(lookup)

    email = (
        str(cfg.get("EMAIL") or "")
        or _extract_email_from_html(html)
        or fetch_google_email(client, lookup)
    )
    session.account_email = email

    if not session.logged_in and not _has_session_cookies(lookup):
        session.close()
        raise RuntimeError("Cookie 无效或未登录（未检测到 YouTube 登录态）")

    # 二次确认：带鉴权请求 accounts_list 轻量探测由频道模块负责
    logger.info(
        "会话就绪 logged_in=%s api_key=%s email=%s",
        session.logged_in,
        bool(session.api_key),
        _mask(email),
    )
    return session


def extract_ytcfg(html: str) -> dict[str, Any]:
    patterns = (
        r"ytcfg\.set\((\{.*?\})\);",
        r"ytcfg\.set\((\{.*?\})\)\s*;",
    )
    for pat in patterns:
        m = re.search(pat, html, re.DOTALL)
        if not m:
            continue
        raw = m.group(1)
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                # 有时是 {"INNERTUBE_API_KEY":...} 直接；有时嵌套
                if "INNERTUBE_API_KEY" in data or "LOGGED_IN" in data:
                    return data
                inner = data.get("INNERTUBE_CONTEXT") or data
                if isinstance(inner, dict):
                    merged = dict(data)
                    client = (data.get("INNERTUBE_CONTEXT") or {}).get("client") or {}
                    if client.get("clientVersion"):
                        merged.setdefault(
                            "INNERTUBE_CLIENT_VERSION", client["clientVersion"]
                        )
                    if client.get("visitorData"):
                        merged.setdefault("VISITOR_DATA", client["visitorData"])
                    return merged
        except json.JSONDecodeError:
            continue

    # 回退：逐项正则
    out: dict[str, Any] = {}
    for key in (
        "INNERTUBE_API_KEY",
        "INNERTUBE_CLIENT_VERSION",
        "VISITOR_DATA",
        "DATASYNC_ID",
        "EMAIL",
    ):
        m = re.search(rf'"{key}"\s*:\s*"([^"]+)"', html)
        if m:
            out[key] = m.group(1)
    m = re.search(r'"LOGGED_IN"\s*:\s*(true|false)', html)
    if m:
        out["LOGGED_IN"] = m.group(1) == "true"
    return out


def fetch_google_email(client: httpx.Client, cookie_dict: dict[str, str]) -> str:
    """尝试从 Google 账户页读取邮箱（失败则空）。"""
    _ = cookie_dict
    try:
        resp = client.get(
            "https://myaccount.google.com/",
            headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
        )
        email = _extract_email_from_html(resp.text)
        if email:
            return email
    except httpx.HTTPError as exc:
        logger.debug("读取 Google 账户页失败: %s", exc)
    return ""


def _extract_email_from_html(html: str) -> str:
    patterns = (
        r'"email"\s*:\s*"([^"]+@[^"]+)"',
        r'([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})',
    )
    for pat in patterns:
        for m in re.finditer(pat, html):
            email = m.group(1)
            # 过滤明显非账号邮箱的资源
            if any(x in email.lower() for x in ("example.com", "youtube.com", "google.com", "w3.org")):
                if not email.lower().endswith("@gmail.com") and "googlemail" not in email.lower():
                    continue
            if email.lower().endswith(("@gmail.com", "@googlemail.com")) or "@" in email:
                # 跳过静态资源误匹配
                if " " in email or len(email) > 128:
                    continue
                if email.count("@") == 1:
                    return email
    return ""


def _has_session_cookies(cookie_dict: dict[str, str]) -> bool:
    keys = {k.lower() for k in cookie_dict}
    markers = (
        "sid",
        "hsid",
        "ssid",
        "sapisid",
        "__secure-1psid",
        "__secure-3psid",
        "login_info",
    )
    return any(m in keys or any(m in k for k in keys) for m in markers)


def _mask(email: str) -> str:
    if not email or "@" not in email:
        return email or ""
    name, domain = email.split("@", 1)
    if len(name) <= 2:
        return "*" * len(name) + "@" + domain
    return name[0] + "*" * (len(name) - 2) + name[-1] + "@" + domain


def domain_matches(cookie_domain: str, wanted: str) -> bool:
    d = (cookie_domain or "").lstrip(".").lower()
    w = wanted.lstrip(".").lower()
    return d == w or d.endswith("." + w) or w.endswith("." + d)
