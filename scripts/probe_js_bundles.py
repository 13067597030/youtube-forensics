"""Search all Studio JS bundles for analytics endpoints/metrics."""
import re
from pathlib import Path

from yt_forensics.cookie.load import load_from_file
from yt_forensics.cookie.session import USER_AGENT, bootstrap_session

CHANNEL = "UCIx-2w5LaY1rrFcVvecF6hQ"
O = "https://studio.youtube.com"
cookies, _ = load_from_file(Path("data/cookies.txt"))
s = bootstrap_session(cookies)
html = s.client.get(f"{O}/channel/{CHANNEL}/analytics/tab-revenue/period-default", headers={"User-Agent": USER_AGENT, **s.auth_headers(O)}).text
scripts = re.findall(r'src="(https://studio\.youtube\.com/s/[^"]+\.js)"', html)
all_metrics: set[str] = set()
all_endpoints: set[str] = set()
all_cols: set[str] = set()
for url in scripts:
    js = s.client.get(url, headers={"User-Agent": USER_AGENT}, timeout=60).text
    all_metrics.update(re.findall(r"ANALYTICS_METRIC_[A-Z0-9_]+", js))
    all_endpoints.update(re.findall(r"yta_web/[a-z_]+", js))
    all_cols.update(re.findall(r"VIDEO_REPORTING_COLUMN_[A-Z0-9_]+", js))
    all_cols.update(re.findall(r'"([A-Z][A-Z0-9_]{3,30})"\s*:\s*\d+\s*,\s*//\s*.*revenue', js, re.I))
    for pat in (r"ESTIMATED_[A-Z_]+", r"RPM", r"MONETIZED_[A-Z_]+", r"PLAYBACK_BASED_CPM", r"IMPRESSIONS_[A-Z_]+"):
        all_metrics.update(re.findall(pat, js))

print("bundles", len(scripts), "bytes", sum(len(s.client.get(u).text) for u in scripts[:1]))
print("endpoints", sorted(all_endpoints))
rev = sorted(x for x in all_metrics | all_cols if any(k in x for k in ("REVENUE", "RPM", "CPM", "MONETIZED", "IMPRESSION", "WATCH")))
print("revenue-related", rev[:40])
print("metric count", len(all_metrics), "col count", len(all_cols))
s.close()
