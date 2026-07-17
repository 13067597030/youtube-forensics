"""Debug browser revenue harvest (no cookie values printed)."""
from pathlib import Path

from yt_forensics.analytics.browser_harvest import harvest_revenue_browser
from yt_forensics.cookie.load import load_from_file
from yt_forensics.export.evidence import find_latest_video_list, load_video_list_csv

cookies, _ = load_from_file(Path("data/cookies.txt"))
latest = find_latest_video_list(Path("Evidence"))
rows = load_video_list_csv(latest) if latest else []
ids = [r["video_id"] for r in rows[:5] if r.get("video_id")]
print("probe videos", len(ids))

result = harvest_revenue_browser(cookies, "UCIx-2w5LaY1rrFcVvecF6hQ", ids, headless=True)
for vid in ids:
    m = result.get(vid, {})
    print(vid, m or "(empty)")
