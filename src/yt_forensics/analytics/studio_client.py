"""YouTube Studio Innertube 客户端（M4）。"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from yt_forensics.cookie.session import USER_AGENT, YTSession, extract_ytcfg

logger = logging.getLogger(__name__)

STUDIO_ORIGIN = "https://studio.youtube.com"
DEFAULT_STUDIO_CLIENT_VERSION = "1.20260714.02.00"

ROLE_BY_PERMISSION = {
    "owner": "CREATOR_CHANNEL_ROLE_TYPE_OWNER",
    "manager": "CREATOR_CHANNEL_ROLE_TYPE_MANAGER",
}


@dataclass
class StudioClient:
    """针对单个频道的 Studio API 会话。"""

    session: YTSession
    channel_id: str
    api_key: str
    client_version: str
    permission_level: str = "owner"
    delegated_session_id: str = ""
    serialized_delegation_context: str = ""
    session_token: str = ""
    embedded_context: dict[str, Any] = field(default_factory=dict, repr=False)
    _context: dict[str, Any] = field(default_factory=dict, repr=False)

    def close(self) -> None:
        pass

    @property
    def context(self) -> dict[str, Any]:
        if not self._context:
            self._context = self._build_context()
        return self._context

    def post(
        self,
        endpoint: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        body = dict(payload or {})
        body.setdefault("context", self.context)
        url = f"{STUDIO_ORIGIN}/youtubei/v1/{endpoint.lstrip('/')}"
        params = {"prettyPrint": "false"}
        if self.api_key:
            params["key"] = self.api_key

        headers = self.session.auth_headers(STUDIO_ORIGIN)
        headers["Content-Type"] = "application/json"
        headers["X-Youtube-Client-Name"] = "62"
        headers["X-Youtube-Client-Version"] = self.client_version
        headers["X-Youtube-Bootstrap-Logged-In"] = "true"
        headers["Referer"] = f"{STUDIO_ORIGIN}/channel/{self.channel_id}/videos"

        resp = self.session.client.post(
            url,
            params=params,
            json=body,
            headers=headers,
            timeout=timeout,
        )
        if resp.status_code >= 400:
            detail = resp.text[:500]
            logger.debug("Studio %s -> %s %s", endpoint, resp.status_code, detail)
            return {
                "_http_status": resp.status_code,
                "_error_text": detail,
                "error": _safe_json(resp),
            }
        try:
            return resp.json()
        except json.JSONDecodeError:
            return {"_http_status": resp.status_code, "_error_text": resp.text[:500]}

    def list_creator_videos(
        self,
        *,
        page_token: str = "",
        page_size: int = 50,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "filter": {
                "and": {
                    "operands": [
                        {"channelIdIs": {"value": self.channel_id}},
                        {"videoOriginIs": {"value": "VIDEO_ORIGIN_UPLOAD"}},
                    ]
                }
            },
            "order": "VIDEO_ORDER_DISPLAY_TIME_DESC",
            "pageSize": page_size,
            "mask": _video_metrics_mask(),
            "criticalRead": False,
        }
        if page_token:
            body["pageToken"] = page_token
        return self.post("creator/list_creator_videos", body)

    def get_creator_videos(self, video_ids: list[str]) -> dict[str, Any]:
        if not video_ids:
            return {}
        return self.post(
            "creator/get_creator_videos",
            {
                "failOnError": False,
                "videoIds": video_ids,
                "mask": _video_metrics_mask(),
                "criticalRead": False,
            },
        )

    def get_analytics_cards(
        self,
        video_id: str,
        metrics: list[str],
        *,
        lifetime: bool = True,
    ) -> dict[str, Any]:
        tz = -time.timezone if time.daylight == 0 else -time.altzone
        if lifetime:
            time_period = {
                "referencePoint": "TIME_PERIOD_REFERENCE_POINT_SINCE_PUBLISH",
                "timePeriodType": "ANALYTICS_TIME_PERIOD_TYPE_SINCE_PUBLISH",
                "entity": {"videoId": video_id},
            }
        else:
            time_period = {
                "referencePoint": "TIME_PERIOD_REFERENCE_POINT_LAST_28_DAYS",
                "timePeriodType": "ANALYTICS_TIME_PERIOD_TYPE_LAST_28_DAYS",
            }
        return self.post(
            "yta_web/get_cards",
            {
                "screenConfig": {
                    "entity": {"videoId": video_id},
                    "timePeriod": time_period,
                    "currency": "USD",
                    "timeZoneOffsetSecs": tz,
                },
                "cardConfigs": [
                    {
                        "autoUpdateInterval": "ANALYTICS_AUTO_UPDATE_INTERVAL_NEVER",
                        "keyMetricCardConfig": {
                            "metricTabConfigs": [{"metric": m} for m in metrics],
                        },
                        "failureMode": "ANALYTICS_CARD_FAILURE_MODE_FAIL_PAGE",
                    }
                ],
            },
        )

    def _build_context(self) -> dict[str, Any]:
        if self.embedded_context:
            ctx = json.loads(json.dumps(self.embedded_context))
            user = ctx.setdefault("user", {})
            role = ROLE_BY_PERMISSION.get(
                self.permission_level.lower(), "CREATOR_CHANNEL_ROLE_TYPE_OWNER"
            )
            user["delegationContext"] = {
                "externalChannelId": self.channel_id,
                "roleType": {"channelRoleType": role},
            }
            if self.serialized_delegation_context:
                user["serializedDelegationContext"] = self.serialized_delegation_context
            if self.session_token:
                ctx.setdefault("request", {})["sessionInfo"] = {"token": self.session_token}
            return ctx

        role = ROLE_BY_PERMISSION.get(
            self.permission_level.lower(), "CREATOR_CHANNEL_ROLE_TYPE_OWNER"
        )
        client: dict[str, Any] = {
            "clientName": 62,
            "clientVersion": self.client_version,
            "hl": "en",
            "gl": "US",
            "userAgent": USER_AGENT,
        }
        if self.session.visitor_data:
            client["visitorData"] = self.session.visitor_data

        ctx: dict[str, Any] = {
            "client": client,
            "request": {
                "returnLogEntry": True,
                "internalExperimentFlags": [],
            },
            "user": {
                "delegationContext": {
                    "externalChannelId": self.channel_id,
                    "roleType": {"channelRoleType": role},
                },
            },
        }
        if self.delegated_session_id:
            # onBehalfOfUser 与 delegationContext 同用会触发 INVALID_ARGUMENT (400)
            pass
        if self.serialized_delegation_context:
            ctx["user"]["serializedDelegationContext"] = self.serialized_delegation_context
        if self.session_token:
            ctx["request"]["sessionInfo"] = {"token": self.session_token}
        return ctx


def bootstrap_studio_client(
    session: YTSession,
    channel_id: str,
    *,
    permission_level: str = "owner",
    brand_account_id: str = "",
) -> StudioClient:
    """加载 Studio 页面并解析 Innertube 配置。"""
    # 先访问 Studio 根域，确保会话在 studio 域生效
    try:
        session.client.get(
            STUDIO_ORIGIN + "/",
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html",
                **session.auth_headers(STUDIO_ORIGIN),
            },
        )
    except httpx.HTTPError as exc:
        logger.debug("Studio 根页访问失败: %s", exc)

    page_url = f"{STUDIO_ORIGIN}/channel/{channel_id}/videos"
    if brand_account_id:
        page_url += f"?pageId={brand_account_id}"
    resp = session.client.get(
        page_url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html",
            **session.auth_headers(STUDIO_ORIGIN),
        },
        follow_redirects=True,
    )
    html = resp.text
    cfg = extract_ytcfg(html)
    embedded_ctx = _extract_innertube_context(html)
    api_key = str(
        cfg.get("INNERTUBE_API_KEY")
        or _regex(html, r'"INNERTUBE_API_KEY"\s*:\s*"([^"]+)"')
        or session.api_key
    )
    client_version = str(
        cfg.get("INNERTUBE_CLIENT_VERSION")
        or _regex(html, r'"INNERTUBE_CLIENT_VERSION"\s*:\s*"([^"]+)"')
        or DEFAULT_STUDIO_CLIENT_VERSION
    )
    delegated = str(
        cfg.get("DELEGATED_SESSION_ID")
        or cfg.get("DATASYNC_ID")
        or session.datasync_id
        or ""
    )
    serialized = _regex(html, r'"serializedDelegationContext"\s*:\s*"([^"]+)"') or ""
    session_token = (
        _regex(html, r'"sessionToken"\s*:\s*"([^"]+)"')
        or session.cookies.get("SESSION_TOKEN", "")
    )

    client = StudioClient(
        session=session,
        channel_id=channel_id,
        api_key=api_key,
        client_version=client_version,
        permission_level=permission_level,
        delegated_session_id=delegated,
        serialized_delegation_context=serialized,
        session_token=session_token,
        embedded_context=embedded_ctx or {},
    )
    logger.info(
        "Studio 客户端就绪 channel=%s api_key=%s ver=%s delegated=%s",
        channel_id,
        bool(api_key),
        client_version[:20],
        bool(delegated),
    )
    return client


def _video_metrics_mask() -> dict[str, Any]:
    # 与 Studio 前端 inject.js 一致；含 monetization.all 会导致 metrics 为空
    return {
        "videoId": True,
        "title": True,
        "metrics": {"all": True},
        "publicMetrics": {"all": True},
        "revenueAnalytics": {"all": True},
    }


def _extract_innertube_context(html: str) -> dict[str, Any]:
    m = re.search(
        r'"INNERTUBE_CONTEXT"\s*:\s*(\{.*?\})\s*,\s*"INNERTUBE_CONTEXT_CLIENT_NAME"',
        html,
        re.DOTALL,
    )
    if not m:
        return {}
    try:
        data = json.loads(m.group(1))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _regex(text: str, pattern: str) -> str | None:
    m = re.search(pattern, text)
    return m.group(1) if m else None


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except json.JSONDecodeError:
        return {"message": resp.text[:300]}
