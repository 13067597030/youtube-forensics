"""Check HTML for auth token patterns (presence only, no values)."""
import re
from pathlib import Path

from yt_forensics.cookie.load import load_from_file
from yt_forensics.cookie.session import USER_AGENT, bootstrap_session

CHANNEL = "UCIx-2w5LaY1rrFcVvecF6hQ"
O = "https://studio.youtube.com"
cookies, _ = load_from_file(Path("data/cookies.txt"))
s = bootstrap_session(cookies)
for path in (
    f"/channel/{CHANNEL}/videos",
    f"/channel/{CHANNEL}/analytics/tab-revenue/period-default",
):
    html = s.client.get(f"{O}{path}", headers={"User-Agent": USER_AGENT, **s.auth_headers(O)}).text
    print("page", path, "len", len(html))
    for pat in (
        "access_token",
        "oauthToken",
        "ya29.",
        "SAPISIDHASH",
        "serializedDelegationContext",
        "sessionToken",
        "INNERTUBE_CONTEXT",
        "yta_web",
        "get_cards",
        "get_table",
        "ESTIMATED_REVENUE",
        "estimatedRevenue",
        "VideoReporting",
        "analyticsMetrics",
        "estimatedRevenueColumn",
    ):
        print(" ", pat, bool(re.search(pat, html, re.I)))
s.close()
