"""Verify list + metrics after context fix."""
import re
from pathlib import Path

from yt_forensics.analytics.parse import extract_videos_list, parse_creator_video
from yt_forensics.cookie.load import load_from_file
from yt_forensics.cookie.session import USER_AGENT, bootstrap_session, extract_ytcfg

CHANNEL = "UCIx-2w5LaY1rrFcVvecF6hQ"
cookies, _ = load_from_file(Path("data/cookies.txt"))
s = bootstrap_session(cookies)
O = "https://studio.youtube.com"
html = s.client.get(
    f"{O}/channel/{CHANNEL}/videos",
    headers={"User-Agent": USER_AGENT, **s.auth_headers(O)},
).text
cfg = extract_ytcfg(html)
key = str(cfg.get("INNERTUBE_API_KEY") or re.search(r'"INNERTUBE_API_KEY"\s*:\s*"([^"]+)"', html).group(1))
ver = str(cfg.get("INNERTUBE_CLIENT_VERSION") or re.search(r'"INNERTUBE_CLIENT_VERSION"\s*:\s*"([^"]+)"', html).group(1))
ctx = {
    "client": {"clientName": 62, "clientVersion": ver, "hl": "en", "gl": "US", "userAgent": USER_AGENT},
    "user": {
        "delegationContext": {
            "externalChannelId": CHANNEL,
            "roleType": {"channelRoleType": "CREATOR_CHANNEL_ROLE_TYPE_OWNER"},
        }
    },
}
body = {
    "context": ctx,
    "filter": {
        "and": {
            "operands": [
                {"channelIdIs": {"value": CHANNEL}},
                {"videoOriginIs": {"value": "VIDEO_ORIGIN_UPLOAD"}},
            ]
        }
    },
    "order": "VIDEO_ORDER_DISPLAY_TIME_DESC",
    "pageSize": 3,
    "mask": {"videoId": True, "metrics": {"all": True}},
}
h = s.auth_headers(O)
h.update({"Content-Type": "application/json", "X-Youtube-Client-Name": "62", "X-Youtube-Client-Version": ver})
r = s.client.post(
    f"{O}/youtubei/v1/creator/list_creator_videos",
    params={"key": key},
    json=body,
    headers=h,
)
print("list", r.status_code)
data = r.json()
vids = extract_videos_list(data)
print("videos", len(vids))
if vids:
    m = parse_creator_video(vids[0])
    print("sample", vids[0].get("videoId"), m)
s.close()
