"""Investigate yta_web / revenue API auth and endpoints."""
import json
import re
import time
from pathlib import Path

from yt_forensics.cookie.load import load_from_file
from yt_forensics.cookie.session import USER_AGENT, bootstrap_session, extract_ytcfg

CHANNEL = "UCIx-2w5LaY1rrFcVvecF6hQ"
VIDEO = "UrSvr8ADW7I"
ORIGIN = "https://studio.youtube.com"

cookies, _ = load_from_file(Path("data/cookies.txt"))
s = bootstrap_session(cookies)

pages = [
    f"{ORIGIN}/channel/{CHANNEL}/videos",
    f"{ORIGIN}/channel/{CHANNEL}/analytics/tab-revenue/period-default",
    f"{ORIGIN}/channel/{CHANNEL}/analytics/tab-overview/period-default",
]
html = ""
for url in pages:
    r = s.client.get(url, headers={"User-Agent": USER_AGENT, **s.auth_headers(ORIGIN)})
    html = r.text if len(r.text) > len(html) else html

cfg = extract_ytcfg(html)
key = str(cfg.get("INNERTUBE_API_KEY") or re.search(r'"INNERTUBE_API_KEY"\s*:\s*"([^"]+)"', html).group(1))
ver = str(cfg.get("INNERTUBE_CLIENT_VERSION") or re.search(r'"INNERTUBE_CLIENT_VERSION"\s*:\s*"([^"]+)"', html).group(1))
ser = (re.search(r'"serializedDelegationContext"\s*:\s*"([^"]+)"', html) or [None, ""])[1]
session_token = (re.search(r'"sessionToken"\s*:\s*"([^"]+)"', html) or [None, ""])[1]

# Search page for revenue-related API hints
for pat in (
    r"yta_web/[a-z_]+",
    r"estimatedRevenue",
    r"ESTIMATED_REVENUE",
    r"estimated_revenue",
    r"get_table",
    r"VideoReporting",
):
    hits = set(re.findall(pat, html))
    if hits:
        print("hint", pat, sorted(hits)[:15])

deleg = {
    "externalChannelId": CHANNEL,
    "roleType": {"channelRoleType": "CREATOR_CHANNEL_ROLE_TYPE_OWNER"},
}

def ctx(*, with_ser=True, with_token=True, with_visitor=True):
    client = {"clientName": 62, "clientVersion": ver, "hl": "en", "gl": "US", "userAgent": USER_AGENT}
    if with_visitor and s.visitor_data:
        client["visitorData"] = s.visitor_data
    c = {
        "client": client,
        "user": {"delegationContext": deleg},
    }
    if with_ser and ser:
        c["user"]["serializedDelegationContext"] = ser
    if with_token and session_token:
        c["request"] = {"sessionInfo": {"token": session_token}}
    return c

def post(path, body, label, referer=None):
    h = s.auth_headers(ORIGIN)
    h.update({
        "Content-Type": "application/json",
        "X-Youtube-Client-Name": "62",
        "X-Youtube-Client-Version": ver,
        "X-Youtube-Bootstrap-Logged-In": "true",
        "Referer": referer or f"{ORIGIN}/channel/{CHANNEL}/analytics/tab-revenue/period-default",
    })
    r = s.client.post(
        f"{ORIGIN}/youtubei/v1/{path}",
        params={"prettyPrint": "false", "key": key},
        json=body,
        headers=h,
        timeout=60,
    )
    msg = ""
    if r.status_code == 200:
        low = r.text.lower()
        msg = f"len={len(r.content)} revenue={'revenue' in low or 'estimated' in low}"
    else:
        try:
            msg = (r.json().get("error") or {}).get("message", "")[:200]
        except Exception:
            msg = r.text[:100]
    print(label, r.status_code, msg)

tz = -time.timezone
cards_base = {
    "screenConfig": {
        "entity": {"videoId": VIDEO},
        "timePeriod": {
            "referencePoint": "TIME_PERIOD_REFERENCE_POINT_SINCE_PUBLISH",
            "timePeriodType": "ANALYTICS_TIME_PERIOD_TYPE_SINCE_PUBLISH",
            "entity": {"videoId": VIDEO},
        },
        "currency": "USD",
        "timeZoneOffsetSecs": tz,
    },
    "cardConfigs": [{
        "autoUpdateInterval": "ANALYTICS_AUTO_UPDATE_INTERVAL_NEVER",
        "keyMetricCardConfig": {"metricTabConfigs": [{"metric": "VIEWS"}]},
        "failureMode": "ANALYTICS_CARD_FAILURE_MODE_FAIL_PAGE",
    }],
}

for label, c in [
    ("ctx_full", ctx()),
    ("ctx_no_ser", ctx(with_ser=False)),
    ("ctx_no_token", ctx(with_token=False)),
    ("ctx_minimal", ctx(with_ser=False, with_token=False, with_visitor=False)),
]:
    post("yta_web/get_cards", {"context": c, **cards_base}, f"cards_{label}")

# Try channel-level revenue screen
screen_body = {
    "context": ctx(),
    "screenConfig": {
        "entity": {"channelId": CHANNEL},
        "timePeriod": {
            "timePeriodType": "ANALYTICS_TIME_PERIOD_TYPE_LIFETIME",
        },
        "currency": "USD",
        "timeZoneOffsetSecs": tz,
    },
    "desktopState": {"tabId": "ANALYTICS_TAB_ID_REVENUE"},
}
post("yta_web/get_screen", screen_body, "screen_revenue")

# Try table endpoints with different paths
table_q = {
    "dimensions": ["VIDEO"],
    "metrics": ["VIEWS", "ESTIMATED_REVENUE"],
    "timeRange": {"dateIdRange": {"dateIdRangeType": "DATE_ID_RANGE_TYPE_LIFETIME"}},
    "limit": 5,
}
for path in (
    "yta_web/get_table",
    "yta_web/get_report_table",
    "yta_web/get_top_entities_table",
    "analytics/get_table",
    "analytics_data/get_table",
):
    post(path, {"context": ctx(), "query": table_q}, path)

# Creator list with revenue column mask variants
list_mask = {
    "videoId": True,
    "title": True,
    "metrics": {"all": True},
    "estimatedRevenue": True,
    "revenue": True,
}
post(
    "creator/list_creator_videos",
    {
        "context": ctx(),
        "order": "VIDEO_ORDER_DISPLAY_TIME_DESC",
        "pageSize": 3,
        "mask": list_mask,
    },
    "list_no_filter",
)

s.close()
