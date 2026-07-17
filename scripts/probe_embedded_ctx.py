"""Extract INNERTUBE_CONTEXT from page and test yta_web."""
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
html = s.client.get(
    f"{O}/channel/{CHANNEL}/analytics/tab-revenue/period-default",
    headers={"User-Agent": USER_AGENT, **s.auth_headers(O)},
).text
key = re.search(r'"INNERTUBE_API_KEY"\s*:\s*"([^"]+)"', html).group(1)
ver = re.search(r'"INNERTUBE_CLIENT_VERSION"\s*:\s*"([^"]+)"', html).group(1)

embedded = None
m = re.search(r'"INNERTUBE_CONTEXT"\s*:\s*(\{.*?\})\s*,\s*"INNERTUBE_CONTEXT_CLIENT_NAME"', html, re.DOTALL)
if m:
    try:
        embedded = json.loads(m.group(1))
    except json.JSONDecodeError:
        pass
print("embedded_ctx", bool(embedded))
if embedded:
    print("ctx keys", list(embedded.keys()))
    print("client keys", list((embedded.get("client") or {}).keys())[:12])
    print("user keys", list((embedded.get("user") or {}).keys()))

h = s.auth_headers(O)
h.update({
    "Content-Type": "application/json",
    "X-Youtube-Client-Name": "62",
    "X-Youtube-Client-Version": ver,
    "Referer": f"{O}/channel/{CHANNEL}/analytics/tab-revenue/period-default",
})

# discover js bundles
scripts = re.findall(r'src="(https://studio\.youtube\.com/s/[^"]+\.js)"', html)
print("js bundles", len(scripts))

tz = -time.timezone
for label, ctx in [
    ("embedded", embedded),
    ("embedded+deleg", None),
]:
    if label == "embedded+deleg" and embedded:
        ctx = json.loads(json.dumps(embedded))
        ctx.setdefault("user", {})["delegationContext"] = {
            "externalChannelId": CHANNEL,
            "roleType": {"channelRoleType": "CREATOR_CHANNEL_ROLE_TYPE_OWNER"},
        }
    if not ctx:
        continue
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
            "keyMetricCardConfig": {"metricTabConfigs": [{"metric": "VIEWS"}]},
            "failureMode": "ANALYTICS_CARD_FAILURE_MODE_FAIL_PAGE",
        }],
    }
    r = s.client.post(f"{O}/youtubei/v1/yta_web/get_cards", params={"key": key}, json=body, headers=h)
    print("get_cards", label, r.status_code)

# Fetch first js bundle and search metric strings
if scripts:
    js = s.client.get(scripts[0], headers={"User-Agent": USER_AGENT}).text[:500000]
    metrics = sorted(set(re.findall(r"ANALYTICS_METRIC_[A-Z0-9_]+", js)))
    cols = sorted(set(re.findall(r"VIDEO_REPORTING_COLUMN_[A-Z0-9_]+", js)))
    endpoints = sorted(set(re.findall(r"yta_web/[a-z_]+", js)))
    print("metrics sample", metrics[:20])
    print("columns sample", cols[:20])
    print("endpoints", endpoints[:20])
    for kw in ("ESTIMATED", "REVENUE", "RPM", "MONETIZED"):
        found = [x for x in metrics + cols if kw in x]
        if found:
            print(kw, found[:15])

s.close()
