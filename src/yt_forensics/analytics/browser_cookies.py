"""Netscape Cookie -> Playwright cookie list."""
from __future__ import annotations

from http.cookiejar import CookieJar, MozillaCookieJar
from pathlib import Path
from typing import Any

from yt_forensics.cookie.load import filter_relevant_cookies, load_from_file


def cookies_for_playwright(cookie_file: Path | None = None, cookie_dict: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """尽量保留 Netscape 元数据（httpOnly/secure/domain）供 Playwright 使用。"""
    rows: list[dict[str, Any]] = []
    if cookie_file and Path(cookie_file).is_file():
        rows.extend(_from_netscape_file(Path(cookie_file)))
    if not rows and cookie_dict:
        rows.extend(_from_dict(cookie_dict))
    return rows


def _from_netscape_file(path: Path) -> list[dict[str, Any]]:
    jar = MozillaCookieJar(str(path))
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except Exception:
        return _from_dict(dict(load_from_file(path)[0]))
    return _jar_to_playwright(jar)


def _from_dict(cookies: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, value in cookies.items():
        if not name or value is None:
            continue
        for domain in (".youtube.com",):
            rows.append(_make_cookie(name, str(value), domain))
    return rows


def _jar_to_playwright(jar: CookieJar) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for c in jar:
        domain = str(getattr(c, "domain", "") or "")
        if not domain:
            continue
        dom = domain.lstrip(".").lower()
        if not any(dom == s or dom.endswith("." + s) for s in ("youtube.com", "google.com")):
            continue
        name = str(getattr(c, "name", "") or "")
        value = getattr(c, "value", None)
        if not name or value is None:
            continue
        secure = bool(getattr(c, "secure", False))
        http_only = bool(getattr(c, "_rest", {}).get("HttpOnly") or getattr(c, "rest", {}).get("HttpOnly"))
        same_site = "None" if secure else "Lax"
        rows.append(
            {
                "name": name,
                "value": str(value),
                "domain": domain if domain.startswith(".") else domain,
                "path": str(getattr(c, "path", None) or "/"),
                "secure": secure,
                "httpOnly": http_only,
                "sameSite": same_site,
            }
        )
    return rows


def _make_cookie(name: str, value: str, domain: str) -> dict[str, Any]:
    secure = name.startswith("__Secure-") or name.startswith("__Host-")
    http_only = name in {
        "SID",
        "HSID",
        "SSID",
        "APISID",
        "SAPISID",
        "LOGIN_INFO",
        "__Secure-1PSID",
        "__Secure-3PSID",
        "__Secure-1PAPISID",
        "__Secure-3PAPISID",
    } or secure
    return {
        "name": name,
        "value": value,
        "domain": domain if domain.startswith(".") else f".{domain.lstrip('.')}",
        "path": "/",
        "secure": secure or True,
        "httpOnly": http_only,
        "sameSite": "None" if secure else "Lax",
    }
