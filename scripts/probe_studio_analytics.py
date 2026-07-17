"""Probe Studio analytics endpoints (dev)."""
import json
import re
import time
from pathlib import Path

from yt_forensics.cookie.load import load_from_file
from yt_forensics.cookie.session import USER_AGENT, bootstrap_session

CHANNEL = "UCIx-2w5LaY1rrFcVvecF6hQ"
VIDEO = "UrSvr8ADW7I"

cookies, _ = load_from_file(Path("data/cookies.txt"))
s = bootstrap_session(cookies)

# Load studio channel page for keys
resp = s.client.get(
    f"https://studio.youtube.com/channel/{CHANNEL}/analytics/tab-overview/period-default",
    headers={"User-Agent": USER_AGENT, **s.auth_headers("https://studio.youtube.com")},
)
html = resp.text
key_m = re.search(r'"INNERTUBE_API_KEY"\s*:\s*"([^"]+)"', html)
ver_m = re.search(r'"INNERTUBE_CLIENT_VERSION"\s*:\s*"([^"]+)"', html)
api_key = key_m.group(1) if key_m else s.api_key
client_ver = ver_m.group(1) if ver_m else "1.20260714.02.00"
print("api_key", bool(api_key), "ver", client_ver[:24] if client_ver else "")

studio_ctx = {
    "client": {
        "clientName": "62",
        "clientVersion": client_ver,
        "hl": "en",
        "gl": "US",
        "userAgent": USER_AGENT,
    },
    "user": {
        "delegationContext": {
            "externalChannelId": CHANNEL,
            "roleType": {"channelRoleType": "CREATOR_CHANNEL_ROLE_TYPE_OWNER"},
        },
    },
}


def studio_post(path: str, body: dict) -> dict:
    body = {**body, "context": studio_ctx}
    url = f"https://studio.youtube.com/youtubei/v1/{path}"
    params = {"prettyPrint": "false", "key": api_key}
    headers = s.auth_headers("https://studio.youtube.com")
    headers["Content-Type"] = "application/json"
    headers["X-Youtube-Client-Name"] = "62"
    headers["X-Youtube-Client-Version"] = client_ver
    r = s.client.post(url, params=params, json=body, headers=headers, timeout=60)
    print(path, r.status_code, len(r.content))
    if r.status_code != 200:
        print(r.text[:400])
        return {}
    return r.json()


tz = -time.timezone if time.daylight == 0 else -time.altzone

payloads = [
    (
        "creator/get_creator_videos",
        {
            "failOnError": False,
            "videoIds": [VIDEO],
            "mask": {
                "videoId": True,
                "title": True,
                "metrics": {"all": True},
                "publicMetrics": {"all": True},
            },
            "criticalRead": False,
        },
    ),
    (
        "yta_web/get_cards",
        {
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
            "cardConfigs": [
                {
                    "keyMetricCardConfig": {
                        "metricTabConfigs": [
                            {"metric": "ESTIMATED_REVENUE"},
                            {"metric": "RPM"},
                            {"metric": "PLAYBACK_BASED_CPM"},
                            {"metric": "VIEWS"},
                            {"metric": "WATCH_TIME"},
                            {"metric": "IMPRESSIONS"},
                            {"metric": "IMPRESSIONS_CTR"},
                            {"metric": "MONETIZED_PLAYBACKS"},
                        ],
                    },
                }
            ],
        },
    ),
    (
        "yta_web/get_table",
        {
            "query": {
                "dimensions": ["VIDEO"],
                "metrics": [
                    "ESTIMATED_REVENUE",
                    "RPM",
                    "PLAYBACK_BASED_CPM",
                    "VIEWS",
                    "WATCH_TIME",
                    "IMPRESSIONS",
                    "IMPRESSIONS_CTR",
                    "MONETIZED_PLAYBACKS",
                ],
                "sort": {"metric": "ESTIMATED_REVENUE", "order": "ANALYTICS_ORDER_DESC"},
                "filters": [
                    {
                        "dimension": {"type": "VIDEO"},
                        "type": "IN",
                        "operator": "IN",
                        "values": [VIDEO],
                    }
                ],
                "timeRange": {
                    "dateIdRange": {"dateIdRangeType": "DATE_ID_RANGE_TYPE_LIFETIME"}
                },
            },
        },
    ),
    (
        "yta_web/get_table",
        {
            "query": {
                "dimensions": ["VIDEO"],
                "metrics": [
                    "ESTIMATED_REVENUE",
                    "RPM",
                    "PLAYBACK_BASED_CPM",
                    "VIEWS",
                    "WATCH_TIME",
                    "IMPRESSIONS",
                    "IMPRESSIONS_CTR",
                    "MONETIZED_PLAYBACKS",
                ],
                "sort": {"metric": "ESTIMATED_REVENUE", "order": "ANALYTICS_ORDER_DESC"},
                "filters": [
                    {
                        "dimension": {"type": "CHANNEL"},
                        "type": "IN",
                        "operator": "IN",
                        "values": [CHANNEL],
                    }
                ],
                "timeRange": {
                    "dateIdRange": {"dateIdRangeType": "DATE_ID_RANGE_TYPE_LIFETIME"}
                },
                "limit": 50,
            },
        },
    ),
]

for path, body in payloads:
    try:
        data = studio_post(path, body)
        if data:
            print(json.dumps(data, ensure_ascii=False)[:2000])
    except Exception as e:
        print("ERR", path, e)

s.close()
