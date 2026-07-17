"""Find enum strings in Studio HTML/JS."""
import re
from pathlib import Path

from yt_forensics.cookie.load import load_from_file
from yt_forensics.cookie.session import USER_AGENT, bootstrap_session

CHANNEL = "UCIx-2w5LaY1rrFcVvecF6hQ"
O = "https://studio.youtube.com"
cookies, _ = load_from_file(Path("data/cookies.txt"))
s = bootstrap_session(cookies)
html = s.client.get(f"{O}/channel/{CHANNEL}/videos", headers={"User-Agent": USER_AGENT, **s.auth_headers(O)}).text
if '"INNERTUBE_API_KEY"' not in html:
    print("cookie invalid - no ytcfg")
    s.close()
    raise SystemExit(1)
scripts = re.findall(r'src="(https://studio\.youtube\.com/s/[^"]+\.js)"', html)
blob = html
for u in scripts:
    blob += s.client.get(u, timeout=60).text
for needle in (
    "SUBSCRIBERS_NET_CHANGE",
    "ESTIMATED",
    "REVENUE",
    "MONETIZED",
    "PLAYBACK",
    "IMPRESSIONS",
    "get_cards",
    "get_table",
    "list_creator_videos",
    "estimatedRevenue",
):
    print(needle, needle in blob)
# find strings near REVENUE
for m in re.finditer(r'.{0,30}REVENUE.{0,30}', blob):
    s0 = m.group(0)
    if "function" not in s0 and len(s0) < 80:
        print("ctx", repr(s0))
s.close()
