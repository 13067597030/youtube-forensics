"""Check if revenue appears in batch get_creator_videos."""
import json
import re
from pathlib import Path

from yt_forensics.cookie.load import load_from_file
from yt_forensics.cookie.session import USER_AGENT, bootstrap_session, extract_ytcfg
from yt_forensics.export.evidence import load_video_list_csv, find_latest_video_list

CHANNEL = "UCIx-2w5LaY1rrFcVvecF6hQ"
cookies, _ = load_from_file(Path("data/cookies.txt"))
s = bootstrap_session(cookies)
O = "https://studio.youtube.com"
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
latest = find_latest_video_list(Path("Evidence"))
rows = load_video_list_csv(latest) if latest else []
ids = [r["video_id"] for r in rows[:10] if r.get("video_id")]
mask = {"videoId": True, "title": True, "metrics": {"all": True}, "publicMetrics": {"all": True}}
body = {"context": ctx, "failOnError": False, "videoIds": ids, "mask": mask, "criticalRead": False}
h = s.auth_headers(O)
h.update({"Content-Type": "application/json", "X-Youtube-Client-Name": "62", "X-Youtube-Client-Version": ver})
r = s.client.post(f"{O}/youtubei/v1/creator/get_creator_videos", params={"key": key}, json=body, headers=h)
text = r.text.lower()
print("status", r.status_code, "videos", len(r.json().get("videos") or []))
for kw in ("revenue", "rpm", "cpm", "estimated", "monetiz", "watchtime", "impression"):
    print(kw, kw in text)
# metric keys union
keys = set()
for v in r.json().get("videos") or []:
    keys.update((v.get("metrics") or {}).keys())
    keys.update((v.get("publicMetrics") or {}).keys())
print("metric keys", sorted(keys))
s.close()
