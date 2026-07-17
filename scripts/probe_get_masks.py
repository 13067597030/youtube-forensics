"""Probe get_creator_videos masks for revenue fields."""
import json
import re
from pathlib import Path

from yt_forensics.cookie.load import load_from_file
from yt_forensics.cookie.session import USER_AGENT, bootstrap_session, extract_ytcfg

CHANNEL = "UCIx-2w5LaY1rrFcVvecF6hQ"
VIDEO = "UrSvr8ADW7I"
O = "https://studio.youtube.com"
cookies, _ = load_from_file(Path("data/cookies.txt"))
s = bootstrap_session(cookies)
html = s.client.get(f"{O}/channel/{CHANNEL}/videos", headers={"User-Agent": USER_AGENT, **s.auth_headers(O)}).text
cfg = extract_ytcfg(html)
key = str(cfg.get("INNERTUBE_API_KEY") or re.search(r'"INNERTUBE_API_KEY"\s*:\s*"([^"]+)"', html).group(1))
ver = str(cfg.get("INNERTUBE_CLIENT_VERSION") or re.search(r'"INNERTUBE_CLIENT_VERSION"\s*:\s*"([^"]+)"', html).group(1))
ser = (re.search(r'"serializedDelegationContext"\s*:\s*"([^"]+)"', html) or [None, ""])[1]
ctx = {
    "client": {"clientName": 62, "clientVersion": ver, "hl": "en", "gl": "US", "userAgent": USER_AGENT},
    "user": {"delegationContext": {"externalChannelId": CHANNEL, "roleType": {"channelRoleType": "CREATOR_CHANNEL_ROLE_TYPE_OWNER"}}},
}
if ser:
    ctx["user"]["serializedDelegationContext"] = ser
h = s.auth_headers(O)
h.update({"Content-Type": "application/json", "X-Youtube-Client-Name": "62", "X-Youtube-Client-Version": ver})

masks = {
    "inject": {"videoId": True, "title": True, "metrics": {"all": True}, "publicMetrics": {"all": True}},
    "analyticsMetrics": {"videoId": True, "analyticsMetrics": {"all": True}},
    "contentDetails": {"videoId": True, "contentDetails": {"all": True}, "metrics": {"all": True}},
    "revenueColumn": {"videoId": True, "estimatedRevenueColumn": True, "estimatedRevenue": True},
    "all_top": {"videoId": True, "metrics": {"all": True}, "analyticsMetrics": {"all": True}, "estimatedRevenue": True, "estimatedPartnerRevenue": True},
}

for name, mask in masks.items():
    body = {"context": ctx, "failOnError": False, "videoIds": [VIDEO], "mask": mask, "criticalRead": False}
    r = s.client.post(f"{O}/youtubei/v1/creator/get_creator_videos", params={"key": key}, json=body, headers=h)
    low = r.text.lower()
    print("mask", name, r.status_code, "revenue" in low, "rpm" in low)
    if r.status_code == 200:
        v = (r.json().get("videos") or [{}])[0]
        print("  keys", sorted(v.keys()))
        for k, val in v.items():
            if k in ("videoId", "title", "loggingDirectives", "responseStatus"):
                continue
            if isinstance(val, dict):
                print(f"  {k}:", json.dumps(val, ensure_ascii=False)[:300])
            else:
                print(f"  {k}:", val)

# Brute search creator endpoints from common patterns
candidates = [
    "creator/get_video_estimated_revenue",
    "creator/get_estimated_revenue",
    "creator/get_content_tab_data",
    "creator/get_videos_revenue",
    "creator/batch_get_video_analytics",
    "creator/get_creator_video_analytics",
]
for path in candidates:
    body = {"context": ctx, "videoIds": [VIDEO], "channelId": CHANNEL}
    r = s.client.post(f"{O}/youtubei/v1/{path}", params={"key": key}, json=body, headers=h)
    if r.status_code != 404:
        print("endpoint", path, r.status_code, len(r.content))

s.close()
