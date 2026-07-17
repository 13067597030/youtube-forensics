"""提取前时间校准，结果写入 meta.time_sync。"""

from __future__ import annotations

import logging
import socket
import struct
from datetime import datetime, timezone

from yt_forensics.export.evidence import TimeSyncInfo, format_iso8601, utc_now

logger = logging.getLogger(__name__)

NTP_SERVERS = (
    "ntp.aliyun.com",
    "time.windows.com",
    "pool.ntp.org",
)


def sync_time(source: str = "ntp") -> TimeSyncInfo:
    system = utc_now()
    if source == "none":
        iso = format_iso8601(system)
        return TimeSyncInfo(
            system_time=iso,
            reference_time=iso,
            offset_seconds=0.0,
            source="none",
        )

    if source == "http_date":
        ref = _http_date_reference()
    else:
        ref = _ntp_reference()

    if ref is None:
        iso = format_iso8601(system)
        logger.warning("时间校准失败，source=none")
        return TimeSyncInfo(
            system_time=iso,
            reference_time=iso,
            offset_seconds=0.0,
            source="none",
        )

    offset = (system - ref).total_seconds()
    return TimeSyncInfo(
        system_time=format_iso8601(system),
        reference_time=format_iso8601(ref),
        offset_seconds=round(offset, 3),
        source="ntp" if source != "http_date" else "http_date",
    )


def _ntp_reference() -> datetime | None:
    for server in NTP_SERVERS:
        try:
            return _query_ntp(server)
        except OSError as exc:
            logger.debug("NTP %s 失败: %s", server, exc)
    return None


def _query_ntp(server: str, timeout: float = 2.0) -> datetime:
    # NTP packet: first byte LI=0 VN=3 Mode=3 (client) => 0x1B
    packet = bytearray(48)
    packet[0] = 0x1B
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.sendto(packet, (server, 123))
        data, _ = sock.recvfrom(48)
    if len(data) < 48:
        raise OSError("NTP 响应过短")
    seconds = struct.unpack("!I", data[40:44])[0]
    # NTP epoch -> Unix epoch
    unix = seconds - 2208988800
    return datetime.fromtimestamp(unix, tz=timezone.utc)


def _http_date_reference() -> datetime | None:
    try:
        import urllib.request

        with urllib.request.urlopen(
            "https://www.google.com",
            timeout=3,
        ) as resp:
            date_hdr = resp.headers.get("Date")
        if not date_hdr:
            return None
        # e.g. Wed, 16 Jul 2026 05:30:00 GMT
        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(date_hdr)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception as exc:  # noqa: BLE001 — 校准失败可降级
        logger.debug("HTTP Date 校准失败: %s", exc)
        return None
