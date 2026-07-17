"""Inspect list_creator_videos response structure for revenue fields."""
import json
import re
from pathlib import Path

from yt_forensics.cookie.load import load_from_file
from yt_forensics.cookie.session import USER_AGENT, bootstrap_session, extract_ytcfg

CHANNEL = "UCIx-2w5LaY1rrFcVvecF6hQ"
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
    "content_tab": {
        "videoId": True,
        "title": True,
        "metrics": {"all": True},
        "publicMetrics": {"all": True},
        "contentDetails": {"all": True},
        "analyticsMetrics": {"all": True},
        "estimatedRevenue": True,
        "estimatedPartnerRevenue": True,
        "revenueMetrics": {"all": True},
        "monetizationDetails": {"all": True},
    },
    "list_ytstudio": {
        "channelId": True,
        "videoId": True,
        "title": True,
        "metrics": {"all": True},
        "monetization": {"all": True},
    },
}

for name, mask in masks.items():
    body = {
        "context": ctx,
        "order": "VIDEO_ORDER_DISPLAY_TIME_DESC",
        "pageSize": 2,
        "mask": mask,
        "criticalRead": False,
    }
    r = s.client.post(f"{O}/youtubei/v1/creator/list_creator_videos", params={"key": key}, json=body, headers=h)
    data = r.json() if r.status_code == 200 else {}
    vids = data.get("videos") or []
    print("mask", name, "status", r.status_code, "count", len(vids))
    if vids:
        v0 = vids[0]
        print("  top keys", sorted(v0.keys()))
        for k in v0:
            if k in ("videoId", "title", "responseStatus"):
                continue
            val = v0[k]
            if isinstance(val, dict):
                print(f"  {k} keys", sorted(val.keys())[:25])
            else:
                print(f"  {k}", str(val)[:80])
    low = r.text.lower()
    for kw in ("revenue", "rpm", "cpm", "estimated"):
        if kw in low:
            print("  contains", kw)

# Search minified JS in page for endpoint names
for m in re.finditer(r"/youtubei/v1/[a-z_/]+", html):
    p = m.group(0)
    if "revenue" in p or "yta" in p or "analytic" in p:
        print("page endpoint", p)

s.close()
