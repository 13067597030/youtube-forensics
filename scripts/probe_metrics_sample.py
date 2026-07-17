"""Probe get_creator_videos mask + get_cards auth."""
import json
import re
from pathlib import Path

from yt_forensics.analytics.parse import extract_videos_list, parse_creator_video
from yt_forensics.cookie.load import load_from_file
from yt_forensics.cookie.session import USER_AGENT, bootstrap_session, extract_ytcfg

CHANNEL = "UCIx-2w5LaY1rrFcVvecF6hQ"
VIDEO = "UrSvr8ADW7I"
cookies, _ = load_from_file(Path("data/cookies.txt"))
s = bootstrap_session(cookies)
O = "https://studio.youtube.com"
html = s.client.get(f"{O}/channel/{CHANNEL}/analytics/tab-overview/period-default", headers={"User-Agent": USER_AGENT, **s.auth_headers(O)}).text
cfg = extract_ytcfg(html)
key = str(cfg.get("INNERTUBE_API_KEY") or re.search(r'"INNERTUBE_API_KEY"\s*:\s*"([^"]+)"', html).group(1))
ver = str(cfg.get("INNERTUBE_CLIENT_VERSION") or re.search(r'"INNERTUBE_CLIENT_VERSION"\s*:\s*"([^"]+)"', html).group(1))
serialized = (re.search(r'"serializedDelegationContext"\s*:\s*"([^"]+)"', html) or [None, ""])[1]

ctx = {
    "client": {"clientName": 62, "clientVersion": ver, "hl": "en", "gl": "US", "userAgent": USER_AGENT},
    "user": {
        "delegationContext": {"externalChannelId": CHANNEL, "roleType": {"channelRoleType": "CREATOR_CHANNEL_ROLE_TYPE_OWNER"}},
    },
}
if serialized:
    ctx["user"]["serializedDelegationContext"] = serialized

h = s.auth_headers(O)
h.update({"Content-Type": "application/json", "X-Youtube-Client-Name": "62", "X-Youtube-Client-Version": ver})

mask = {"videoId": True, "title": True, "metrics": {"all": True}, "publicMetrics": {"all": True}}
body = {"context": ctx, "failOnError": False, "videoIds": [VIDEO], "mask": mask, "criticalRead": False}
r = s.client.post(f"{O}/youtubei/v1/creator/get_creator_videos", params={"key": key}, json=body, headers=h)
print("get inject mask", r.status_code)
vids = extract_videos_list(r.json())
if vids:
    v0 = vids[0]
    print("keys", sorted(v0.keys()))
    print("responseStatus", v0.get("responseStatus"))
    print("metrics", list((v0.get("metrics") or {}).keys())[:20])
    print("publicMetrics", v0.get("publicMetrics"))
    print("parsed", parse_creator_video(v0))

import time
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
        "timeZoneOffsetSecs": -time.timezone,
    },
    "cardConfigs": [{
        "autoUpdateInterval": "ANALYTICS_AUTO_UPDATE_INTERVAL_NEVER",
        "keyMetricCardConfig": {"metricTabConfigs": [{"metric": "VIEWS"}]},
        "failureMode": "ANALYTICS_CARD_FAILURE_MODE_FAIL_PAGE",
    }],
}
r2 = s.client.post(f"{O}/youtubei/v1/yta_web/get_cards", params={"key": key}, json=cards, headers=h)
print("cards VIEWS", r2.status_code, (r2.json().get("error") or {}).get("message", "ok")[:120])

s.close()
