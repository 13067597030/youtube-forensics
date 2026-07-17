"""Print Studio API error messages only (no cookie dump)."""
from pathlib import Path

from yt_forensics.analytics.studio_client import bootstrap_studio_client
from yt_forensics.cookie.load import load_from_file
from yt_forensics.cookie.session import bootstrap_session

CHANNEL = "UCIx-2w5LaY1rrFcVvecF6hQ"
VIDEO = "UrSvr8ADW7I"

cookies, _ = load_from_file(Path("data/cookies.txt"))
session = bootstrap_session(cookies)
studio = bootstrap_studio_client(session, CHANNEL)

for name, fn in (
    ("list", lambda: studio.list_creator_videos(page_size=5)),
    ("get", lambda: studio.get_creator_videos([VIDEO])),
    ("cards_views", lambda: studio.get_analytics_cards(VIDEO, ["VIEWS"])),
):
    data = fn()
    err = data.get("error") or {}
    raw = (data.get("_error_text") or "")[:800]
    print(name, "status", data.get("_http_status"), "msg", (err.get("message") or raw or "(empty)")[:800])

session.close()
