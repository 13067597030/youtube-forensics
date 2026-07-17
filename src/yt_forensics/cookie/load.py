"""Cookie 来源：Chrome 自动读取 / 文件导入。"""

from __future__ import annotations

import json
import logging
from http.cookiejar import Cookie, CookieJar, MozillaCookieJar
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

INTERESTING_DOMAIN_SUFFIXES = (
    "youtube.com",
    "google.com",
    "googleapis.com",
    "youtu.be",
)


def load_from_chrome() -> tuple[dict[str, str], str]:
    """
    读取本机 Chrome Cookie。
    返回 (cookie_dict, detail) detail 含 profile 提示。
    """
    # 1) Windows 本地解密（复制 DB，通常无需管理员）
    if __import__("sys").platform == "win32":
        try:
            from yt_forensics.cookie.chromium_win import load_chromium_cookies

            return load_chromium_cookies("chrome")
        except Exception as exc:  # noqa: BLE001
            logger.debug("Windows 本地解密 Chrome 失败: %s", exc)
            win_err = str(exc)
    else:
        win_err = ""

    # 2) yt-dlp 浏览器 Cookie 提取
    errors: list[str] = [win_err] if win_err else []
    for browser in ("chrome", "edge", "brave"):
        try:
            cookies = _load_via_ytdlp(browser)
            if cookies:
                return cookies, f"ytdlp:{browser}"
        except Exception as exc:  # noqa: BLE001
            logger.debug("yt-dlp %s cookies 失败: %s", browser, exc)
            errors.append(f"ytdlp({browser}): {exc}")

    # 3) browser_cookie3 回退
    try:
        import browser_cookie3
    except ImportError:
        browser_cookie3 = None  # type: ignore[assignment]

    cookies: dict[str, str] = {}
    used_profile = "default"

    if browser_cookie3 is not None:
        for domain in (".youtube.com", ".google.com", None):
            try:
                jar = (
                    browser_cookie3.chrome(domain_name=domain)
                    if domain
                    else browser_cookie3.chrome()
                )
                part = filter_relevant_cookies(jar)
                if part:
                    cookies.update(part)
                    used_profile = f"chrome:domain={domain or '*'}"
            except Exception as exc:  # noqa: BLE001
                errors.append(f"chrome({domain}): {exc}")
                logger.debug("chrome domain=%s 失败: %s", domain, exc)

        if not cookies:
            for cookie_db, profile_name in _iter_chrome_cookie_dbs():
                try:
                    jar = browser_cookie3.chrome(cookie_file=str(cookie_db))
                    part = filter_relevant_cookies(jar)
                    if part:
                        cookies.update(part)
                        used_profile = f"chrome:{profile_name}"
                        break
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{profile_name}: {exc}")

    if not cookies:
        hint = (
            "读取 Chrome Cookie 失败。"
            "常见原因：Chrome v20 App-Bound 加密、浏览器正在运行、或未登录。"
            "处理建议：1) 完全退出 Chrome/Edge 后重试；2) 导出 Netscape/JSON Cookie 到 data/cookies.txt 或 --cookie-file。"
        )
        if errors:
            hint += " 技术细节: " + errors[-1]
        raise RuntimeError(hint)

    return cookies, used_profile


def _load_via_ytdlp(browser: str) -> dict[str, str]:
    from yt_dlp.cookies import extract_cookies_from_browser

    jar = extract_cookies_from_browser(browser)
    cookies = filter_relevant_cookies(jar)
    if not cookies:
        raise RuntimeError(f"yt-dlp 未从 {browser} 得到 YouTube/Google Cookie")
    return cookies


def load_from_edge() -> tuple[dict[str, str], str]:
    """读取 Edge Cookie（Windows 本地解密优先）。"""
    if __import__("sys").platform == "win32":
        from yt_forensics.cookie.chromium_win import load_chromium_cookies

        return load_chromium_cookies("edge")
    raise RuntimeError("Edge 自动读取当前仅支持 Windows；请使用 --cookie-file")


def _iter_chrome_cookie_dbs() -> list[tuple[Path, str]]:
    """返回 (Cookies路径, profile名) 列表。"""
    import os
    import sys

    candidates: list[tuple[Path, str]] = []
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
    else:
        base = Path.home() / ".config" / "google-chrome"

    if not base.is_dir():
        return candidates

    for profile in ("Default", *[p.name for p in base.glob("Profile *")]):
        for rel in ("Network/Cookies", "Cookies"):
            path = base / profile / rel
            if path.is_file():
                candidates.append((path, profile))
                break
    return candidates


def load_from_file(path: Path) -> tuple[dict[str, str], str]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Cookie 文件不存在: {path}")

    text = path.read_text(encoding="utf-8-sig", errors="replace").strip()
    if not text:
        raise RuntimeError("Cookie 文件为空")

    if text[0] in "{[":
        cookies = _load_json_cookies(text)
        return cookies, f"import_file:json:{path.name}"

    cookies = _load_netscape_cookies(path)
    return cookies, f"import_file:netscape:{path.name}"


def filter_relevant_cookies(jar: CookieJar | list[Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    items = list(jar) if not isinstance(jar, list) else jar
    for c in items:
        domain = str(getattr(c, "domain", "") or "")
        name = str(getattr(c, "name", "") or "")
        value = getattr(c, "value", None)
        if not name or value is None:
            continue
        dom = domain.lstrip(".").lower()
        if any(dom == s or dom.endswith("." + s) for s in INTERESTING_DOMAIN_SUFFIXES):
            out[name] = str(value)
    return out


def _load_netscape_cookies(path: Path) -> dict[str, str]:
    jar = MozillaCookieJar(str(path))
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except Exception:
        # 部分导出缺头两行，手工解析
        return _parse_netscape_manual(path)
    cookies = filter_relevant_cookies(jar)
    if not cookies:
        cookies = _parse_netscape_manual(path)
    if not cookies:
        raise RuntimeError("Netscape Cookie 文件中无 YouTube/Google 相关项")
    return cookies


def _parse_netscape_manual(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain, _flag, _path, _secure, _expiry, name, value = parts[:7]
        dom = domain.lstrip(".").lower()
        if any(dom == s or dom.endswith("." + s) for s in INTERESTING_DOMAIN_SUFFIXES):
            out[name] = value
    return out


def _load_json_cookies(text: str) -> dict[str, str]:
    data = json.loads(text)
    out: dict[str, str] = {}

    if isinstance(data, dict) and "cookies" in data:
        data = data["cookies"]

    if isinstance(data, dict) and all(isinstance(v, str) for v in data.values()):
        # {name: value}
        return {str(k): str(v) for k, v in data.items()}

    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("Name")
            value = item.get("value") or item.get("Value")
            domain = str(item.get("domain") or item.get("Domain") or "")
            if not name or value is None:
                continue
            dom = domain.lstrip(".").lower()
            if domain and not any(
                dom == s or dom.endswith("." + s) for s in INTERESTING_DOMAIN_SUFFIXES
            ):
                continue
            out[str(name)] = str(value)
        if out:
            return out

    raise RuntimeError("无法识别的 JSON Cookie 格式")


def cookiejar_from_dict(cookies: dict[str, str]) -> CookieJar:
    jar = CookieJar()
    for name, value in cookies.items():
        c = Cookie(
            version=0,
            name=name,
            value=value,
            port=None,
            port_specified=False,
            domain=".youtube.com",
            domain_specified=True,
            domain_initial_dot=True,
            path="/",
            path_specified=True,
            secure=True,
            expires=None,
            discard=True,
            comment=None,
            comment_url=None,
            rest={"HttpOnly": None},
            rfc2109=False,
        )
        jar.set_cookie(c)
    return jar
