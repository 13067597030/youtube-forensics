"""M2: 频道列表解析。"""

from __future__ import annotations

from yt_forensics.channels.discover import parse_accounts_list_response
from yt_forensics.cookie.session import sapisidhash
from yt_forensics.export.schema import ACCOUNT_MAPPING_HEADERS


def test_sapisidhash_format():
    h = sapisidhash("secret", "https://www.youtube.com")
    assert h.startswith("SAPISIDHASH ")
    parts = h.split(" ", 1)[1]
    ts, digest = parts.split("_", 1)
    assert ts.isdigit()
    assert len(digest) == 40


def test_parse_accounts_list_account_item():
    payload = {
        "actions": [
            {
                "updateAccountItemAction": {
                    "accountItem": {
                        "accountName": {"simpleText": "My Channel"},
                        "channelHandle": {"simpleText": "@mych"},
                        "accountByline": {"simpleText": "user@gmail.com"},
                        "hasChannel": True,
                        "serviceEndpoint": {
                            "selectActiveIdentityEndpoint": {
                                "supportedTokens": [
                                    {
                                        "offlineCacheKeyToken": {
                                            "clientId": "x"
                                        }
                                    }
                                ],
                                "nextNavigationEndpoint": {
                                    "browseEndpoint": {
                                        "browseId": "UCabcdefghijklmnopqrstuv"
                                    }
                                },
                            }
                        },
                    }
                }
            }
        ],
        "contents": {
            "accountItem": {
                "accountName": {"simpleText": "Brand One"},
                "channelHandle": {"simpleText": "@brand1"},
                "accountByline": {"simpleText": "Brand Account"},
                "hasChannel": True,
                "serviceEndpoint": {
                    "selectActiveIdentityEndpoint": {
                        "supportedTokens": [
                            {
                                "accountStateToken": {
                                    "obfuscatedGaiaId": "brand-gaia-001"
                                }
                            }
                        ],
                        "nextNavigationEndpoint": {
                            "browseEndpoint": {
                                "browseId": "UCbrandchannelid1234567"
                            }
                        },
                    }
                },
            }
        },
    }
    items = parse_accounts_list_response(payload)
    assert len(items) >= 1
    by_handle = {i.get("handle"): i for i in items}
    assert "@mych" in by_handle or "@brand1" in by_handle
    # channel id 应被挖出
    assert any(
        str(i.get("channel_id", "")).startswith("UC") for i in items
    )


def test_parse_accounts_list_brand_cache_channel_id():
    payload = {
        "contents": {
            "accountItem": {
                "accountName": {"simpleText": "LOVE ATTACK HUB"},
                "channelHandle": {"simpleText": "@loveattackhub"},
                "accountByline": {"simpleText": "301,000 subscribers"},
                "hasChannel": True,
                "serviceEndpoint": {
                    "selectActiveIdentityEndpoint": {
                        "supportedTokens": [
                            {"pageIdToken": {"pageId": "104103134451302421711"}},
                            {
                                "accountStateToken": {
                                    "hasChannel": True,
                                    "obfuscatedGaiaId": "104103134451302421711",
                                }
                            },
                            {
                                "offlineCacheKeyToken": {
                                    "clientCacheKey": "oyhCJAiwd42DU9GjZGdGcQ"
                                }
                            },
                        ]
                    }
                },
            }
        }
    }
    items = parse_accounts_list_response(payload)
    assert len(items) == 1
    item = items[0]
    assert item["channel_id"] == "UCoyhCJAiwd42DU9GjZGdGcQ"
    assert item["brand_account_id"] == "104103134451302421711"
    assert item["account_type"] == "brand"


def test_account_mapping_headers_still_cover_discover_keys():
    sample_keys = {
        "account_email",
        "cookie_source",
        "brand_account_id",
        "channel_id",
        "handle",
        "channel_title",
        "channel_url",
        "account_type",
        "permission_level",
        "forensic_time",
    }
    assert set(ACCOUNT_MAPPING_HEADERS) == sample_keys
