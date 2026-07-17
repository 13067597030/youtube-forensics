"""Test yta_web with full embedded INNERTUBE_CONTEXT from page."""
import json
import re
import time
from pathlib import Path

from yt_forensics.cookie.load import load_from_file
from yt_forensics.cookie.session import USER_AGENT, bootstrap_session

CHANNEL = "UCIx-2w5LaY1rrFcVvecF6hQ"
VIDEO = "UrSvr8ADW7I"
O = "https://studio.youtube.com"
cookies, _ = load_from_file(Path("data/cookies.txt"))
s = bootstrap_session(cookies)
for page in (
    f"{O}/channel/{CHANNEL}/videos",
    f"{O}/channel/{CHANNEL}/analytics/tab-revenue/period-default",
):
    html = s.client.get(page, headers={"User-Agent": USER_AGENT, **s.auth_headers(O)}).text
    if '"INNERTUBE_API_KEY"' in html:
        break
key_m = re.search(r'"INNERTUBE_API_KEY"\s*:\s*"([^"]+)"', html)
if not key_m:
    print("no api key in page")
    s.close()
    raise SystemExit(1)
key = key_m.group(1)
ver = re.search(r'"INNERTUBE_CLIENT_VERSION"\s*:\s*"([^"]+)"', html).group(1)
m = re.search(r'"INNERTUBE_CONTEXT"\s*:\s*(\{.*?\})\s*,\s*"INNERTUBE_CONTEXT_CLIENT_NAME"', html, re.DOTALL)
embedded = json.loads(m.group(1)) if m else {}

ctx = json.loads(json.dumps(embedded))
user = ctx.setdefault("user", {})
user["delegationContext"] = {
    "externalChannelId": CHANNEL,
    "roleType": {"channelRoleType": "CREATOR_CHANNEL_ROLE_TYPE_OWNER"},
}
ser_m = re.search(r'"serializedDelegationContext"\s*:\s*"([^"]+)"', html)
if ser_m:
    user["serializedDelegationContext"] = ser_m.group(1)

h = s.auth_headers(O)
h.update({
    "Content-Type": "application/json",
    "X-Youtube-Client-Name": str((embedded.get("client") or {}).get("clientName", 62)),
    "X-Youtube-Client-Version": ver,
    "Referer": f"{O}/channel/{CHANNEL}/analytics/tab-revenue/period-default",
})
if embedded.get("client", {}).get("visitorData"):
    h["X-Goog-Visitor-Id"] = embedded["client"]["visitorData"]

tz = -time.timezone
body = {
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
        "autoUpdateInterval": "ANALYTICS_AUTO_UPDATE_INTERVAL_NEVER",
        "keyMetricCardConfig": {"metricTabConfigs": [{"metric": "VIEWS"}]},
        "failureMode": "ANALYTICS_CARD_FAILURE_MODE_FAIL_PAGE",
    }],
}
r = s.client.post(f"{O}/youtubei/v1/yta_web/get_cards", params={"key": key}, json=body, headers=h)
print("get_cards", r.status_code, len(r.content))
if r.status_code == 200:
    low = r.text.lower()
    print("has total", "total" in low, "has views", "views" in low)
else:
    print((r.json().get("error") or {}).get("message", "")[:200])

# Also try creator/get with monetization subfields only
ctx2 = {
    "client": {"clientName": 62, "clientVersion": ver, "hl": "en", "gl": "US", "userAgent": USER_AGENT},
    "user": user,
}
masks = [
    ("rev_field", {"videoId": True, "estimatedPartnerRevenue": True}),
    ("rev_metrics", {"videoId": True, "metrics": {"estimatedPartnerRevenue": True, "viewCount": True}}),
    ("contentRev", {"videoId": True, "contentTabEstimatedRevenue": True}),
]
for name, mask in masks:
    b = {"context": ctx2, "failOnError": False, "videoIds": [VIDEO], "mask": mask, "criticalRead": False}
    r2 = s.client.post(f"{O}/youtubei/v1/creator/get_creator_videos", params={"key": key}, json=b, headers=h)
    v = (r2.json().get("videos") or [{}])[0] if r2.status_code == 200 else {}
    print("get", name, r2.status_code, sorted(v.keys()), "revenue" in r2.text.lower())

s.close()
