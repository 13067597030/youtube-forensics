"""Probe monetization fields."""
import json
import re
from pathlib import Path

from yt_forensics.cookie.load import load_from_file
from yt_forensics.cookie.session import USER_AGENT, bootstrap_session, extract_ytcfg

CHANNEL = "UCIx-2w5LaY1rrFcVvecF6hQ"
VIDEO = "UrSvr8ADW7I"
cookies, _ = load_from_file(Path("data/cookies.txt"))
s = bootstrap_session(cookies)
O = "https://studio.youtube.com"
html = s.client.get(f"{O}/channel/{CHANNEL}/videos", headers={"User-Agent": USER_AGENT, **s.auth_headers(O)}).text
cfg = extract_ytcfg(html)
key = str(cfg["INNERTUBE_API_KEY"])
ver = str(cfg["INNERTUBE_CLIENT_VERSION"])
ser = (re.search(r'"serializedDelegationContext"\s*:\s*"([^"]+)"', html) or [None, ""])[1]
ctx = {
    "client": {"clientName": 62, "clientVersion": ver, "hl": "en", "gl": "US", "userAgent": USER_AGENT},
    "user": {"delegationContext": {"externalChannelId": CHANNEL, "roleType": {"channelRoleType": "CREATOR_CHANNEL_ROLE_TYPE_OWNER"}}},
}
if ser:
    ctx["user"]["serializedDelegationContext"] = ser
mask = {"videoId": True, "title": True, "metrics": {"all": True}, "publicMetrics": {"all": True}, "monetization": {"all": True}}
body = {"context": ctx, "failOnError": False, "videoIds": [VIDEO], "mask": mask, "criticalRead": False}
h = s.auth_headers(O)
h.update({"Content-Type": "application/json", "X-Youtube-Client-Name": "62", "X-Youtube-Client-Version": ver})
r = s.client.post(f"{O}/youtubei/v1/creator/get_creator_videos", params={"key": key}, json=body, headers=h)
v = (r.json().get("videos") or [{}])[0]
print("status", r.status_code)
print("metrics", json.dumps(v.get("metrics"), ensure_ascii=False)[:500])
print("monetization", json.dumps(v.get("monetization"), ensure_ascii=False)[:500])
s.close()
