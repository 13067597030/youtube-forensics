"""Try Studio context variants; print only HTTP status."""
import json
import re
import time
from pathlib import Path

from yt_forensics.cookie.load import load_from_file
from yt_forensics.cookie.session import USER_AGENT, bootstrap_session, extract_ytcfg

CHANNEL = "UCIx-2w5LaY1rrFcVvecF6hQ"
VIDEO = "UrSvr8ADW7I"
ORIGIN = "https://studio.youtube.com"

cookies, _ = load_from_file(Path("data/cookies.txt"))
s = bootstrap_session(cookies)
resp = s.client.get(
    f"{ORIGIN}/channel/{CHANNEL}/videos",
    headers={"User-Agent": USER_AGENT, **s.auth_headers(ORIGIN)},
)
html = resp.text
cfg = extract_ytcfg(html)
api_key = str(cfg.get("INNERTUBE_API_KEY") or re.search(r'"INNERTUBE_API_KEY"\s*:\s*"([^"]+)"', html).group(1))
ver = str(cfg.get("INNERTUBE_CLIENT_VERSION") or re.search(r'"INNERTUBE_CLIENT_VERSION"\s*:\s*"([^"]+)"', html).group(1))
delegated = str(cfg.get("DELEGATED_SESSION_ID") or cfg.get("DATASYNC_ID") or s.datasync_id or "")
serialized = (re.search(r'"serializedDelegationContext"\s*:\s*"([^"]+)"', html) or [None, ""])[1]
session_token = (re.search(r'"sessionToken"\s*:\s*"([^"]+)"', html) or [None, ""])[1]

# Try parse embedded INNERTUBE_CONTEXT JSON
embedded_ctx = None
for pat in (
    r'"INNERTUBE_CONTEXT"\s*:\s*(\{.*?\})\s*,\s*"INNERTUBE_CONTEXT_CLIENT_NAME"',
    r'INNERTUBE_CONTEXT\s*=\s*(\{.*?\});',
):
    m = re.search(pat, html, re.DOTALL)
    if m:
        try:
            embedded_ctx = json.loads(m.group(1))
            break
        except json.JSONDecodeError:
            pass

def base_client(name=62):
    return {
        "clientName": name,
        "clientVersion": ver,
        "hl": "en",
        "gl": "US",
        "userAgent": USER_AGENT,
        **({"visitorData": s.visitor_data} if s.visitor_data else {}),
    }

def post(label, ctx, body_extra=None):
    body = {
        "context": ctx,
        "failOnError": False,
        "videoIds": [VIDEO],
        "mask": {"videoId": True, "metrics": {"all": True}},
        "criticalRead": False,
    }
    if body_extra:
        body.update(body_extra)
    headers = s.auth_headers(ORIGIN)
    headers.update({
        "Content-Type": "application/json",
        "X-Youtube-Client-Name": "62",
        "X-Youtube-Client-Version": ver,
        "X-Youtube-Bootstrap-Logged-In": "true",
    })
    r = s.client.post(
        f"{ORIGIN}/youtubei/v1/creator/get_creator_videos",
        params={"prettyPrint": "false", "key": api_key},
        json=body,
        headers=headers,
        timeout=60,
    )
    print(label, r.status_code, len(r.content))

deleg = {
    "externalChannelId": CHANNEL,
    "roleType": {"channelRoleType": "CREATOR_CHANNEL_ROLE_TYPE_OWNER"},
}

# V1: current impl
ctx1 = {
    "client": base_client(),
    "request": {"returnLogEntry": True, "internalExperimentFlags": []},
    "user": {
        "onBehalfOfUser": delegated,
        "delegationContext": deleg,
        **({"serializedDelegationContext": serialized} if serialized else {}),
    },
}
if session_token:
    ctx1["request"]["sessionInfo"] = {"token": session_token}
post("v1_onbehalf+deleg", ctx1)

# V2: no onBehalfOfUser
ctx2 = dict(ctx1)
ctx2["user"] = {"delegationContext": deleg}
if serialized:
    ctx2["user"]["serializedDelegationContext"] = serialized
post("v2_deleg_only", ctx2)

# V3: top-level delegationContext
post("v3_top_deleg", ctx2, {"delegationContext": deleg})

# V4: embedded page context
if embedded_ctx:
    post("v4_embedded_ctx", embedded_ctx)

# V5: serialized only
if serialized:
    post("v5_serialized_only", {"client": base_client(), "user": {"serializedDelegationContext": serialized}})

# V6: clientName WEB=1 with studio key
ctx6 = {
    "client": {
        "clientName": "WEB",
        "clientVersion": s.client_version,
        "hl": "en",
        "gl": "US",
        "userAgent": USER_AGENT,
    },
    "user": {"delegationContext": deleg},
}
post("v6_web_client", ctx6)

# V7: list_creator_videos minimal filter
body7 = {
    "context": ctx2,
    "filter": {"channelIdIs": {"value": CHANNEL}},
    "order": "VIDEO_ORDER_DISPLAY_TIME_DESC",
    "pageSize": 5,
    "mask": {"videoId": True, "metrics": {"all": True}},
}
headers = s.auth_headers(ORIGIN)
headers.update({"Content-Type": "application/json", "X-Youtube-Client-Name": "62", "X-Youtube-Client-Version": ver})
r7 = s.client.post(
    f"{ORIGIN}/youtubei/v1/creator/list_creator_videos",
    params={"prettyPrint": "false", "key": api_key},
    json=body7,
    headers=headers,
    timeout=60,
)
print("v7_list_simple", r7.status_code, len(r7.content))

s.close()
