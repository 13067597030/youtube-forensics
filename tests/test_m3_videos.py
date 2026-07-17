"""M3: 视频行映射测试。"""

from yt_forensics.videos.harvest import _channel_videos_url, _entry_to_row


def test_channel_videos_url_prefers_uploads_playlist():
    url = _channel_videos_url({}, "UCoyhCJAiwd42DU9GjZGdGcQ")
    assert url == "https://www.youtube.com/playlist?list=UUoyhCJAiwd42DU9GjZGdGcQ"


def test_entry_to_row_basic():
    row = _entry_to_row(
        {
            "id": "dQw4w9WgXcQ",
            "title": "Test Video",
            "description": "desc",
            "upload_date": "20240101",
            "duration": 212,
            "view_count": 1000,
            "channel_id": "UCxxxxxxxxxxx",
            "uploader_id": "UCxxxxxxxxxxx",
            "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "live_status": "not_live",
            "availability": "public",
        },
        "UCxxxxxxxxxxx",
        "2026-07-16T06:00:00Z",
    )
    assert row["video_id"] == "dQw4w9WgXcQ"
    assert row["title"] == "Test Video"
    assert row["duration"] == "212"
    assert row["view_count"] == "1000"
    assert row["scrape_time"] == "2026-07-16T06:00:00Z"
