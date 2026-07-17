"""M4: Analytics 解析与行映射测试。"""

from yt_forensics.analytics.harvest import _blank_row
from yt_forensics.analytics.parse import (
    classify_row,
    merge_metrics,
    parse_creator_video,
    parse_get_cards,
)


def test_parse_creator_video_metrics():
    parsed = parse_creator_video(
        {
            "videoId": "abc123",
            "metrics": {
                "viewCount": "1893",
                "likeCount": "7",
            },
            "publicMetrics": {
                "externalViewCount": "1893",
            },
        }
    )
    assert parsed["views"] == "1893"


def test_parse_get_cards_metric_total():
    data = {
        "cards": [
            {
                "keyMetricCardData": {
                    "metricTabs": [
                        {
                            "metric": "VIEWS",
                            "total": 12345,
                        }
                    ]
                }
            }
        ]
    }
    parsed = parse_get_cards(data)
    assert parsed.get("views") == "12345"


def test_classify_row_ok_and_partial():
    assert classify_row({"estimated_revenue": "1.0", "views": "10"})[0] == "partial"
    full = {
        "estimated_revenue": "1",
        "views": "1",
        "watch_time": "1",
        "rpm": "1",
        "playback_based_cpm": "1",
        "impressions": "1",
        "ctr": "1",
        "monetized_playbacks": "1",
    }
    status, reason = classify_row(full)
    assert status == "ok"
    assert reason == ""


def test_parse_lifetime_revenue():
    from yt_forensics.analytics.parse import parse_lifetime_revenue, parse_creator_video

    assert parse_lifetime_revenue({"revenueAnalytics": {"lifetimeRevenue": {"units": "1", "nanos": 500000000}}}) == "1.5"
    assert parse_lifetime_revenue({"revenueAnalytics": {"lifetimeRevenue": {"units": "0", "nanos": 48000000}}}) == "0.048"
    parsed = parse_creator_video(
        {
            "videoId": "abc123",
            "metrics": {"viewCount": "100"},
            "revenueAnalytics": {"lifetimeRevenue": {"units": "0", "nanos": 760000000, "currencyCode": "USD"}},
        }
    )
    assert parsed["views"] == "100"
    assert parsed["estimated_revenue"] == "0.76"


def test_max_content_pages_capped():
    from yt_forensics.analytics.browser_harvest import max_content_pages

    assert max_content_pages(1026) <= 120
    assert max_content_pages(50) == 2
    assert max_content_pages(0) == 1


def test_summarize_analytics_counts():
    from yt_forensics.analytics.parse import summarize_analytics_counts

    rows = [
        {"analytics_status": "ok"},
        {"analytics_status": "partial"},
        {"analytics_status": "partial"},
        {"analytics_status": "unavailable"},
    ]
    summary = summarize_analytics_counts(rows)
    assert summary == {
        "analytics_total": 4,
        "analytics_done": 3,
        "analytics_ok": 1,
        "analytics_partial": 2,
        "analytics_unavailable": 1,
    }


def test_merge_metrics_and_blank_row():
    merged = merge_metrics({"views": "1"}, {"rpm": "2", "views": "9"})
    assert merged == {"views": "1", "rpm": "2"}
    row = _blank_row("UCx", "vid1", "2026-07-16T06:00:00Z")
    assert row["channel_id"] == "UCx"
    assert row["video_id"] == "vid1"


def test_browser_walk_revenue_payload():
    from yt_forensics.analytics.browser_harvest import _walk_videos

    payload = {
        "videos": [
            {
                "videoId": "abc12345678",
                "metrics": {
                    "viewCount": "100",
                    "estimatedRevenue": {"amountMicros": "2500000"},
                    "rpm": "1.23",
                },
            }
        ]
    }
    found = _walk_videos(payload)
    assert "abc12345678" in found
    assert found["abc12345678"]["views"] == "100"
    assert found["abc12345678"]["estimated_revenue"] == "2.5"
    assert found["abc12345678"]["rpm"] == "1.23"
