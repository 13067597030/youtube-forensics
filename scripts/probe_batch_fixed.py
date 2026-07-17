"""Quick batch analytics test using fixed studio client."""
from pathlib import Path

from yt_forensics.analytics.harvest import _fetch_batch_creator_metrics
from yt_forensics.analytics.parse import classify_row
from yt_forensics.analytics.studio_client import bootstrap_studio_client
from yt_forensics.config import load_settings
from yt_forensics.cookie.load import load_from_file
from yt_forensics.cookie.session import bootstrap_session
from yt_forensics.export.evidence import find_latest_video_list, load_video_list_csv

CHANNEL = "UCIx-2w5LaY1rrFcVvecF6hQ"
settings = load_settings()
latest = find_latest_video_list(Path("Evidence"))
rows = load_video_list_csv(latest) if latest else []
ids = [r["video_id"] for r in rows if r.get("video_id")][:36]
print("videos", len(ids), "from", latest)

cookies, _ = load_from_file(Path("data/cookies.txt"))
session = bootstrap_session(cookies)
studio = bootstrap_studio_client(session, CHANNEL)
metrics_map = {vid: {} for vid in ids}
err = _fetch_batch_creator_metrics(studio, ids, metrics_map, settings)
ok = partial = 0
for vid in ids:
    st, _ = classify_row(metrics_map.get(vid, {}))
    if st == "ok":
        ok += 1
    elif st == "partial":
        partial += 1
print("api_err", err or "none")
print("ok", ok, "partial", partial, "empty", len(ids) - ok - partial)
if metrics_map.get(ids[0] if ids else ""):
    print("sample", ids[0], metrics_map[ids[0]])
session.close()
