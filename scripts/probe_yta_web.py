"""Probe yta_web endpoints from analytics page."""
import json
import re
import time
from pathlib import Path

from yt_forensics.cookie.load import load_from_file
from yt_forensics.cookie.session import USER_AGENT, bootstrap_session, extract_ytcfg

CHANNEL = "UCIx-2w5LaY1rrFcVvecF6hQ"
VIDEO = "UrSvr8ADW7I"
cookies, _ = load_from_file(Path("data/cookies.txt"))
s = bootstrap_session(cookies)
O = "https://studio.youtube.com"
html = s.client.get(
    f"{O}/channel/{CHANNEL}/analytics/tab-revenue/period-default",
    headers={"User-Agent": USER_AGENT, **s.auth_headers(O)},
).text
cfg = extract_ytcfg(html)
key = str(cfg.get("INNERTUBE_API_KEY") or re.search(r'"INNERTUBE_API_KEY"\s*:\s*"([^"]+)"', html).group(1))
ver = str(cfg.get("INNERTUBE_CLIENT_VERSION") or re.search(r'"INNERTUBE_CLIENT_VERSION"\s*:\s*"([^"]+)"', html).group(1))
ser = (re.search(r'"serializedDelegationContext"\s*:\s*"([^"]+)"', html) or [None, ""])[1]
session_token = (re.search(r'"sessionToken"\s*:\s*"([^"]+)"', html) or [None, ""])[1]

ctx = {
    "client": {"clientName": 62, "clientVersion": ver, "hl": "en", "gl": "US", "userAgent": USER_AGENT},
    "user": {
        "delegationContext": {
            "externalChannelId": CHANNEL,
            "roleType": {"channelRoleType": "CREATOR_CHANNEL_ROLE_TYPE_OWNER"},
        }
    },
}
if ser:
    ctx["user"]["serializedDelegationContext"] = ser
if session_token:
    ctx["request"] = {"sessionInfo": {"token": session_token}}

h = s.auth_headers(O)
h.update({"Content-Type": "application/json", "X-Youtube-Client-Name": "62", "X-Youtube-Client-Version": ver, "Referer": f"{O}/channel/{CHANNEL}/analytics/tab-revenue/period-default"})

tz = -time.timezone
cards = {
    "context": ctx,
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
        "keyMetricCardConfig": {"metricTabConfigs": [{"metric": "VIEWS"}]},
        "failureMode": "ANALYTICS_CARD_FAILURE_MODE_FAIL_PAGE",
    }],
}

paths = [
    ("yta_web/get_cards", cards),
    ("yta_web/get_screen", {"context": ctx, "screenConfig": {"entity": {"channelId": CHANNEL}}, "desktopState": {"tabId": "ANALYTICS_TAB_ID_REVENUE"}}),
    ("yta_web/get_table", {"context": ctx, "query": {"dimensions": ["VIDEO"], "metrics": ["VIEWS"], "timeRange": {"dateIdRange": {"dateIdRangeType": "DATE_ID_RANGE_TYPE_LIFETIME"}}, "limit": 5}}),
]
for path, body in paths:
    r = s.client.post(f"{O}/youtubei/v1/{path}", params={"key": key}, json=body, headers=h, timeout=60)
    msg = ""
    if r.status_code != 200:
        try:
            msg = (r.json().get("error") or {}).get("message", "")[:150]
        except Exception:
            msg = r.text[:100]
    else:
        msg = f"len={len(r.content)}"
    print(path, r.status_code, msg)

s.close()
