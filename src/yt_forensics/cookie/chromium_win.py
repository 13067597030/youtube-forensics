"""Windows 浏览器 Cookie 本地解密（复制 DB + DPAPI，无需 browser_cookie3 管理员路径）。"""

from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

INTERESTING_SUFFIXES = (
    "youtube.com",
    "google.com",
    "googleapis.com",
    "youtu.be",
)


def load_chromium_cookies(browser: str = "chrome") -> tuple[dict[str, str], str]:
    if sys.platform != "win32":
        raise RuntimeError("本地解密仅实现 Windows；请使用 --cookie-file 导入")

    user_data = _user_data_dir(browser)
    if not user_data.is_dir():
        raise RuntimeError(f"未找到 {browser} 用户数据目录: {user_data}")

    errors: list[str] = []
    for profile, cookie_db in _iter_profiles(user_data):
        try:
            cookies = _read_cookie_db(user_data, cookie_db, profile)
            if cookies:
                return cookies, f"{browser}:{profile}:local_decrypt"
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{profile}: {exc}")
            logger.debug("profile %s 解密失败: %s", profile, exc)

    detail = errors[-1] if errors else "无可用 Profile"
    raise RuntimeError(
        f"本地解密 {browser} Cookie 失败（{detail}）。"
        "若 Cookie 为 Chrome v20 App-Bound 加密，请用扩展导出 Netscape/JSON 后 --cookie-file 导入。"
    )


def load_from_dedicated_profile(profile_user_data: Path) -> tuple[dict[str, str], str]:
    """
    从专用 user-data-dir（如 data/browser_profile）读取 Cookie。
    浏览器窗口仍打开时也可尝试（复制锁定 DB）。
    """
    if sys.platform != "win32":
        raise RuntimeError("专用 Profile 本地解密仅实现 Windows")

    profile_user_data = Path(profile_user_data)
    if not profile_user_data.is_dir():
        raise FileNotFoundError(f"Profile 目录不存在: {profile_user_data}")

    errors: list[str] = []
    for rel in ("Default/Network/Cookies", "Default/Cookies"):
        cookie_db = profile_user_data / rel.replace("/", os.sep)
        if not cookie_db.is_file():
            continue
        try:
            cookies = _read_cookie_db(profile_user_data, cookie_db, "Default")
            if cookies:
                return cookies, f"dedicated_profile_db:{profile_user_data.name}"
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))

    hint = errors[-1] if errors else "无 Cookie 数据库"
    raise RuntimeError(f"专用 Profile Cookie 读取失败: {hint}")


def _user_data_dir(browser: str) -> Path:
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    if browser == "edge":
        return local / "Microsoft" / "Edge" / "User Data"
    return local / "Google" / "Chrome" / "User Data"


def _iter_profiles(user_data: Path) -> Iterable[tuple[str, Path]]:
    names = ["Default", *[p.name for p in sorted(user_data.glob("Profile *"))]]
    for profile in names:
        for rel in ("Network/Cookies", "Cookies"):
            path = user_data / profile / rel
            if path.is_file():
                yield profile, path
                break


def _read_cookie_db(
    user_data: Path,
    cookie_db: Path,
    profile: str,
) -> dict[str, str]:
    local_state = user_data / "Local State"
    if not local_state.is_file():
        raise FileNotFoundError("Local State 不存在")

    key = _load_master_key(local_state)
    tmpdir = tempfile.mkdtemp(prefix="yt_forensics_cookies_")
    try:
        dest = Path(tmpdir) / "Cookies"
        _copy_cookie_db(cookie_db, dest)
        return _query_cookies(dest, key)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _copy_cookie_db(src: Path, dest: Path) -> None:
    """复制 Cookie DB；浏览器占用时尝试多种 Windows 复制方式。"""
    try:
        shutil.copy2(src, dest)
        if dest.stat().st_size > 0:
            return
    except OSError as exc:
        logger.debug("copy2 失败 %s: %s", src, exc)

    if sys.platform == "win32":
        for fn in (_copy_via_cmd, _copy_locked_file_windows):
            try:
                fn(src, dest)
                if dest.is_file() and dest.stat().st_size > 0:
                    return
            except OSError as exc:
                logger.debug("%s 失败: %s", fn.__name__, exc)

    src_uri = _sqlite_uri(src)
    try:
        src_conn = sqlite3.connect(src_uri, uri=True, timeout=10.0)
        dest_conn = sqlite3.connect(str(dest))
        try:
            for line in src_conn.iterdump():
                if line.startswith("CREATE") or line.startswith("INSERT"):
                    dest_conn.execute(line)
            dest_conn.commit()
        finally:
            src_conn.close()
            dest_conn.close()
        if dest.stat().st_size > 0:
            return
    except sqlite3.Error as exc:
        raise RuntimeError(
            f"无法读取 Cookie 数据库（可能被浏览器锁定）: {exc}"
        ) from exc
    raise RuntimeError("Cookie 数据库复制结果为空")


def _copy_via_cmd(src: Path, dest: Path) -> None:
    import subprocess

    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    proc = subprocess.run(
        ["cmd", "/c", "copy", "/Y", str(src), str(dest)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0 or not dest.is_file() or dest.stat().st_size == 0:
        raise OSError(proc.stderr.strip() or proc.stdout.strip() or "cmd copy failed")


def _sqlite_uri(path: Path) -> str:
    resolved = path.resolve().as_posix()
    # file:///C:/...?mode=ro&nolock=1
    return f"file:///{resolved}?mode=ro&nolock=1"


def _copy_locked_file_windows(src: Path, dest: Path) -> None:
    """Windows：以共享读方式复制被 Chromium 占用的 Cookies 文件。"""
    import ctypes
    import ctypes.wintypes as wt

    GENERIC_READ = 0x80000000
    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    FILE_SHARE_DELETE = 0x00000004
    OPEN_EXISTING = 3
    INVALID = wt.HANDLE(-1).value

    CreateFileW = ctypes.windll.kernel32.CreateFileW
    ReadFile = ctypes.windll.kernel32.ReadFile
    CloseHandle = ctypes.windll.kernel32.CloseHandle

    handle = CreateFileW(
        str(src),
        GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None,
        OPEN_EXISTING,
        0,
        None,
    )
    if handle in (None, wt.HANDLE(-1).value, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF):
        raise OSError(f"CreateFileW 失败: {ctypes.get_last_error()}")

    chunks: list[bytes] = []
    try:
        buf = ctypes.create_string_buffer(1024 * 1024)
        read = wt.DWORD(0)
        while True:
            ok = ReadFile(handle, buf, len(buf), ctypes.byref(read), None)
            if not ok:
                err = ctypes.get_last_error()
                if err == 0 and read.value == 0:
                    break
                raise OSError(f"ReadFile 失败: {err}")
            if read.value == 0:
                break
            chunks.append(buf.raw[: read.value])
    finally:
        CloseHandle(handle)

    dest.write_bytes(b"".join(chunks))


def _query_cookies(dest: Path, key: bytes) -> dict[str, str]:
    conn = sqlite3.connect(str(dest))
    try:
        cur = conn.execute(
            "SELECT name, value, encrypted_value, host_key FROM cookies"
        )
        out: dict[str, str] = {}
        v20_count = 0
        for name, plain, encrypted, host in cur:
            dom = (host or "").lstrip(".").lower()
            if not _domain_ok(dom):
                continue
            if plain:
                out[str(name)] = str(plain)
                continue
            if not encrypted:
                continue
            blob = encrypted if isinstance(encrypted, bytes) else encrypted.encode(
                "latin-1"
            )
            if blob[:3] == b"v20":
                v20_count += 1
                continue
            try:
                out[str(name)] = _decrypt(blob, key)
            except Exception as exc:  # noqa: BLE001
                logger.debug("解密 %s@%s 失败: %s", name, host, exc)
        if not out and v20_count:
            raise RuntimeError(
                f"共 {v20_count} 条 Cookie 为 v20 App-Bound 加密，需管理员或导出文件"
            )
        return out
    finally:
        conn.close()


def _domain_ok(domain: str) -> bool:
    return any(domain == s or domain.endswith("." + s) for s in INTERESTING_SUFFIXES)


def _load_master_key(local_state: Path) -> bytes:
    data = json.loads(local_state.read_text(encoding="utf-8"))
    os_crypt = data.get("os_crypt") or {}
    enc_key_b64 = os_crypt.get("encrypted_key")
    if not enc_key_b64:
        raise RuntimeError("Local State 缺少 encrypted_key")
    enc_key = base64.b64decode(enc_key_b64)
    # "DPAPI" prefix
    if enc_key.startswith(b"DPAPI"):
        enc_key = enc_key[5:]
    return _dpapi_decrypt(enc_key)


def _decrypt(blob: bytes, key: bytes) -> str:
    if blob[:3] in (b"v10", b"v11"):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        nonce = blob[3:15]
        ciphertext = blob[15:]
        return AESGCM(key).decrypt(nonce, ciphertext, None).decode("utf-8")
    return _dpapi_decrypt(blob).decode("utf-8")


def _dpapi_decrypt(data: bytes) -> bytes:
    import ctypes
    import ctypes.wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", ctypes.wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_byte)),
        ]

    blob_in = DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_byte)))
    blob_out = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(blob_out),
    ):
        raise OSError("CryptUnprotectData 失败")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
