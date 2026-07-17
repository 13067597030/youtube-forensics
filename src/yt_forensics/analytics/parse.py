"""解析 Studio Analytics 响应。"""

from __future__ import annotations

from typing import Any

# CSV 字段 -> API 可能出现的 camelCase / snake 别名
METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "estimated_revenue": (
        "estimatedRevenue",
        "estimatedPartnerRevenue",
        "estimated_revenue",
        "revenue",
    ),
    "rpm": ("rpm", "RPM"),
    "playback_based_cpm": (
        "playbackBasedCpm",
        "playback_based_cpm",
        "cpm",
        "estimatedPlaybackBasedCpm",
    ),
    "views": ("views", "viewCount", "externalViews", "externalViewCount"),
    "watch_time": (
        "watchTime",
        "watch_time",
        "estimatedMinutesWatched",
        "watchTimeMinutes",
    ),
    "impressions": ("impressions", "impressionCount"),
    "ctr": ("ctr", "impressionsCtr", "impressions_ctr", "clickThroughRate"),
    "monetized_playbacks": (
        "monetizedPlaybacks",
        "monetized_playbacks",
        "estimatedMonetizedPlaybacks",
    ),
}

# yta_web/get_cards 使用的 metric 枚举（SUBSCRIBERS_NET_CHANGE 已验证可用）
YTA_CARD_METRICS: dict[str, str] = {
    "estimated_revenue": "ESTIMATED_PARTNER_REVENUE",
    "rpm": "RPM",
    "playback_based_cpm": "PLAYBACK_BASED_CPM",
    "views": "VIEWS",
    "watch_time": "WATCH_TIME",
    "impressions": "IMPRESSIONS",
    "ctr": "IMPRESSIONS_CLICK_THROUGH_RATE",
    "monetized_playbacks": "MONETIZED_PLAYBACKS",
}


def parse_lifetime_revenue(node: dict[str, Any]) -> str | None:
    """解析 revenueAnalytics.lifetimeRevenue（Studio list_creator_videos）。"""
    ra = node.get("revenueAnalytics")
    if not isinstance(ra, dict):
        return None
    lifetime = ra.get("lifetimeRevenue")
    if not isinstance(lifetime, dict):
        return None
    try:
        units = int(str(lifetime.get("units") or "0"))
        nanos = int(str(lifetime.get("nanos") or "0"))
    except ValueError:
        return None
    if units == 0 and nanos == 0:
        return None
    amount = units + nanos / 1_000_000_000
    text = f"{amount:.6f}".rstrip("0").rstrip(".")
    return text or None


def parse_creator_video(node: dict[str, Any]) -> dict[str, str]:
    """从 creator/list|get_creator_videos 单条 video 节点提取指标。"""
    out: dict[str, str] = {}
    metrics = node.get("metrics") or {}
    if isinstance(metrics, dict):
        for field, aliases in METRIC_ALIASES.items():
            val = _pick(metrics, aliases)
            if val is not None:
                out[field] = val

    # 部分字段在 monetization 或 publicMetrics 下
    for extra_key in ("monetization", "publicMetrics"):
        extra = node.get(extra_key)
        if not isinstance(extra, dict):
            continue
        for field, aliases in METRIC_ALIASES.items():
            if field in out:
                continue
            val = _pick(extra, aliases)
            if val is not None:
                out[field] = val

    rev = parse_lifetime_revenue(node)
    if rev is not None:
        out["estimated_revenue"] = rev

    return out


def parse_get_cards(data: dict[str, Any]) -> dict[str, str]:
    """从 yta_web/get_cards 响应提取 metric -> total。"""
    out: dict[str, str] = {}
    for api_metric, csv_field in _API_TO_CSV.items():
        total = _find_metric_total(data, api_metric)
        if total is not None:
            if api_metric == "WATCH_TIME":
                total = _watch_time_to_minutes(total)
            out[csv_field] = _stringify(total)
    return out


def merge_metrics(*parts: dict[str, str]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for part in parts:
        for k, v in part.items():
            if v not in (None, "") and k not in merged:
                merged[k] = v
    return merged


def classify_row(metrics: dict[str, str]) -> tuple[str, str]:
    """返回 (analytics_status, unavailable_reason)。"""
    if not metrics:
        return "unavailable", "no_metrics"
    core = ("estimated_revenue", "views", "watch_time")
    if any(metrics.get(k) for k in core):
        optional = ("rpm", "playback_based_cpm", "impressions", "ctr", "monetized_playbacks")
        if all(metrics.get(k) for k in optional):
            return "ok", ""
        return "partial", ""
    if metrics.get("views"):
        return "partial", "revenue_unavailable"
    return "unavailable", "no_metrics"


def summarize_analytics_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    """汇总 Video_Analytics 行状态，供 meta.json / Dashboard 使用。"""
    ok = partial = unavailable = skipped = 0
    for row in rows:
        status = str(row.get("analytics_status") or "")
        if status == "ok":
            ok += 1
        elif status == "partial":
            partial += 1
        elif status == "unavailable":
            unavailable += 1
        elif status == "skipped":
            skipped += 1
    total = len(rows)
    return {
        "analytics_total": total,
        "analytics_done": ok + partial,
        "analytics_ok": ok,
        "analytics_partial": partial,
        "analytics_unavailable": unavailable + skipped,
    }


def extract_videos_list(data: dict[str, Any]) -> list[dict[str, Any]]:
    videos = data.get("videos")
    if isinstance(videos, list):
        return [v for v in videos if isinstance(v, dict)]
    return []


def next_page_token(data: dict[str, Any]) -> str:
    for key in ("nextPageToken", "continuationToken"):
        val = data.get(key)
        if isinstance(val, str) and val:
            return val
    return ""


def api_error_message(data: dict[str, Any]) -> str:
    if not data:
        return "empty_response"
    status = data.get("_http_status")
    if status:
        err = data.get("error") or {}
        if isinstance(err, dict):
            msg = err.get("message") or err.get("status")
            if msg:
                return f"http_{status}:{msg}"
        return f"http_{status}"
    err = data.get("error")
    if isinstance(err, dict):
        return str(err.get("message") or err.get("status") or "api_error")
    return ""


# 反向映射：API metric 名 -> CSV 字段
_API_TO_CSV = {v: k for k, v in YTA_CARD_METRICS.items()}


def _watch_time_to_minutes(value: Any) -> Any:
    """Studio get_cards 的 WATCH_TIME total 通常为毫秒。"""
    try:
        n = float(str(value))
    except ValueError:
        return value
    if n > 100_000:
        return round(n / 60_000, 2)
    return n


def _pick(obj: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        if key not in obj:
            continue
        val = _stringify(obj[key])
        if val not in ("", "None"):
            return val
    return None


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        # 金额：{amountMicros, currency} 或 {simpleText}
        if "simpleText" in value:
            return str(value["simpleText"]).strip()
        if "amountMicros" in value:
            micros = value.get("amountMicros")
            if micros is not None:
                try:
                    amount = int(str(micros)) / 1_000_000
                    return str(amount)
                except ValueError:
                    return str(micros)
        if "amount" in value:
            return _stringify(value["amount"])
        if "value" in value:
            return _stringify(value["value"])
    if isinstance(value, list) and value:
        return _stringify(value[0])
    return str(value)


def _find_metric_total(node: Any, metric: str, depth: int = 0) -> Any:
    if depth > 24 or node is None:
        return None
    if isinstance(node, list):
        for item in node:
            found = _find_metric_total(item, metric, depth + 1)
            if found is not None:
                return found
        return None
    if not isinstance(node, dict):
        return None
    if node.get("metric") == metric:
        if "total" in node:
            return node["total"]
        if "value" in node:
            return node["value"]
    for child in node.values():
        found = _find_metric_total(child, metric, depth + 1)
        if found is not None:
            return found
    return None
