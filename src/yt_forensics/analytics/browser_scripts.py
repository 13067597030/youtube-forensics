_AUTH_HOOK_INIT_JS = """
(() => {
  if (window.__yf_hooked) return;
  window.__yf_hooked = true;
  window.__yf_auth = null;
  window.__yf_payloads = [];

  const capture = (url, headerSrc, bodyText) => {
    try {
      if (!url || !String(url).includes("youtubei") || !bodyText) return;
      let context = null;
      try { context = JSON.parse(bodyText).context; } catch (e) {}
      if (!context) return;
      const headers = {};
      if (headerSrc) {
        if (typeof headerSrc.forEach === "function") headerSrc.forEach((v, k) => { headers[k] = v; });
        else if (Array.isArray(headerSrc)) for (const p of headerSrc) headers[p[0]] = p[1];
        else for (const k of Object.keys(headerSrc)) headers[k] = headerSrc[k];
      }
      window.__yf_auth = { url: String(url), headers, context };
    } catch (e) {}
  };

  const origFetch = window.fetch;
  window.fetch = async function (...args) {
    let url = null, bodyText = null, headerSrc = null;
    try {
      const isReq = args[0] && typeof args[0] === "object" && "url" in args[0];
      url = isReq ? args[0].url : args[0];
      const opt = args[1] || {};
      headerSrc = opt.headers || (isReq ? args[0].headers : null);
      if (typeof opt.body === "string") bodyText = opt.body;
      capture(url, headerSrc, bodyText);
    } catch (e) {}
    const res = await origFetch.apply(this, args);
    try {
      if (url && String(url).includes("youtubei") && res.ok) {
        const clone = res.clone();
        clone.text().then(t => {
          try { window.__yf_payloads.push({ url: String(url), body: JSON.parse(t) }); } catch (e) {}
        }).catch(() => {});
      }
    } catch (e) {}
    return res;
  };

  const origOpen = XMLHttpRequest.prototype.open;
  const origSend = XMLHttpRequest.prototype.send;
  const origSetHeader = XMLHttpRequest.prototype.setRequestHeader;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.__yf_url = url;
    this.__yf_headers = {};
    return origOpen.call(this, method, url, ...rest);
  };
  XMLHttpRequest.prototype.setRequestHeader = function (name, value) {
    try {
      this.__yf_headers = this.__yf_headers || {};
      this.__yf_headers[name] = value;
    } catch (e) {}
    return origSetHeader.call(this, name, value);
  };
  XMLHttpRequest.prototype.send = function (body) {
    try {
      const bodyText = typeof body === "string" ? body : null;
      capture(this.__yf_url, this.__yf_headers, bodyText);
    } catch (e) {}
    this.addEventListener("load", function () {
      try {
        const url = this.__yf_url;
        if (!url || !String(url).includes("youtubei") || this.status < 200 || this.status >= 300) return;
        const t = this.responseText;
        window.__yf_payloads.push({ url: String(url), body: JSON.parse(t) });
      } catch (e) {}
    });
    return origSend.call(this, body);
  };
})();
"""

_RUN_FETCH_JS = """
async ({ videoIds, channelId, roleType }) => {
  const out = { results: [], cardResults: [], workingMetrics: [], yta_error: "" };
  const channelRole = roleType || "CREATOR_CHANNEL_ROLE_TYPE_OWNER";

  let lastAuth = window.__yf_auth;
  if (!lastAuth) {
    // 回退：从 ytcfg 组装 context
    try {
      const d = (window.ytcfg && window.ytcfg.data_) || {};
      const innertube = d.INNERTUBE_CONTEXT || {};
      const client = innertube.client || {
        clientName: 62,
        clientVersion: d.INNERTUBE_CLIENT_VERSION || "1.0",
        hl: "en", gl: "US",
      };
      const user = Object.assign({}, innertube.user || {});
      user.delegationContext = {
        externalChannelId: channelId,
        roleType: { channelRoleType: channelRole },
      };
      out.yta_error = "ytcfg_fallback";
      lastAuth = {
        url: location.origin + "/youtubei/v1/creator/list_creator_videos?key=" + (d.INNERTUBE_API_KEY || ""),
        headers: {
          "content-type": "application/json",
          "X-Youtube-Client-Name": String(client.clientName || 62),
          "X-Youtube-Client-Version": client.clientVersion || d.INNERTUBE_CLIENT_VERSION || "",
          "X-Youtube-Bootstrap-Logged-In": "true",
        },
        context: { client, user },
      };
    } catch (e) {
      out.yta_error = "no_auth";
      return out;
    }
  } else if (lastAuth.context && lastAuth.context.user) {
    lastAuth.context.user.delegationContext = {
      externalChannelId: channelId,
      roleType: { channelRoleType: channelRole },
    };
  }

  const origFetch = window.fetch;
  const studioHeaders = () => {
    const headers = Object.assign({}, lastAuth.headers || {});
    delete headers["content-length"]; delete headers["Content-Length"];
    headers["content-type"] = "application/json";
    const d = (window.ytcfg && window.ytcfg.data_) || {};
    const client = ((d.INNERTUBE_CONTEXT || {}).client) || {};
    if (!headers["X-Youtube-Client-Name"]) headers["X-Youtube-Client-Name"] = String(client.clientName || 62);
    if (!headers["X-Youtube-Client-Version"]) {
      headers["X-Youtube-Client-Version"] = client.clientVersion || d.INNERTUBE_CLIENT_VERSION || "";
    }
    if (!headers["X-Youtube-Bootstrap-Logged-In"]) headers["X-Youtube-Bootstrap-Logged-In"] = "true";
    return headers;
  };
  const buildUrl = (endpoint) => {
    const d = (window.ytcfg && window.ytcfg.data_) || {};
    const key = d.INNERTUBE_API_KEY || "";
    let search = "";
    try { search = new URL(lastAuth.url, location.origin).search; } catch (e) {}
    if (!search && key) search = "?key=" + encodeURIComponent(key) + "&prettyPrint=false";
    else if (search && !search.includes("prettyPrint")) search += (search.includes("?") ? "&" : "?") + "prettyPrint=false";
    return location.origin + "/youtubei/v1/" + endpoint + search;
  };

  const chunks = [];
  for (let i = 0; i < videoIds.length; i += 20) chunks.push(videoIds.slice(i, i + 20));

  for (const batch of chunks) {
    try {
      const headers = studioHeaders();
      const body = JSON.stringify({
        context: lastAuth.context,
        failOnError: false,
        videoIds: batch,
        mask: { videoId: true, title: true, metrics: { all: true }, publicMetrics: { all: true } },
        criticalRead: false,
      });
      const res = await origFetch(buildUrl("creator/get_creator_videos"), {
        method: "POST", credentials: "include", headers, body,
      });
      const text = await res.text();
      if (!res.ok) {
        out.yta_error = "creator:" + res.status + ":" + text.slice(0, 180);
        continue;
      }
      const json = JSON.parse(text);
      if (json && json.videos) out.results.push(...json.videos);
    } catch (e) {
      out.yta_error = "creator:" + String(e);
    }
  }

  const metricCandidates = [
    "ESTIMATED_PARTNER_REVENUE", "ESTIMATED_REVENUE", "VIDEO_ESTIMATED_REVENUE", "RPM", "PLAYBACK_BASED_CPM",
    "MONETIZED_PLAYBACKS", "IMPRESSIONS", "IMPRESSIONS_CLICK_THROUGH_RATE", "WATCH_TIME", "VIEWS",
  ];
  const tz = -new Date().getTimezoneOffset() * 60;
  const probeId = videoIds[0];
  const working = [];
  if (probeId) {
    for (const metric of metricCandidates) {
      try {
        const headers = studioHeaders();
        const body = JSON.stringify({
          context: lastAuth.context,
          screenConfig: {
            entity: { videoId: probeId },
            timePeriod: {
              referencePoint: "TIME_PERIOD_REFERENCE_POINT_SINCE_PUBLISH",
              timePeriodType: "ANALYTICS_TIME_PERIOD_TYPE_SINCE_PUBLISH",
              entity: { videoId: probeId },
            },
            currency: "USD",
            timeZoneOffsetSecs: tz,
          },
          cardConfigs: [{
            autoUpdateInterval: "ANALYTICS_AUTO_UPDATE_INTERVAL_NEVER",
            keyMetricCardConfig: { metricTabConfigs: [{ metric }] },
            failureMode: "ANALYTICS_CARD_FAILURE_MODE_FAIL_PAGE",
          }],
        });
        const res = await origFetch(buildUrl("yta_web/get_cards"), {
          method: "POST", credentials: "include", headers, body,
        });
        if (res.status === 200) working.push(metric);
      } catch (e) {}
    }
  }
  out.workingMetrics = working;

  for (const metric of working) {
    for (const videoId of videoIds) {
      try {
        const headers = studioHeaders();
        const body = JSON.stringify({
          context: lastAuth.context,
          screenConfig: {
            entity: { videoId },
            timePeriod: {
              referencePoint: "TIME_PERIOD_REFERENCE_POINT_SINCE_PUBLISH",
              timePeriodType: "ANALYTICS_TIME_PERIOD_TYPE_SINCE_PUBLISH",
              entity: { videoId },
            },
            currency: "USD",
            timeZoneOffsetSecs: tz,
          },
          cardConfigs: [{
            autoUpdateInterval: "ANALYTICS_AUTO_UPDATE_INTERVAL_NEVER",
            keyMetricCardConfig: { metricTabConfigs: [{ metric }] },
            failureMode: "ANALYTICS_CARD_FAILURE_MODE_FAIL_PAGE",
          }],
        });
        const res = await origFetch(buildUrl("yta_web/get_cards"), {
          method: "POST", credentials: "include", headers, body,
        });
        if (res.status === 200) {
          const json = await res.json();
          json.__videoId = videoId;
          json.__metric = metric;
          out.cardResults.push(json);
        }
      } catch (e) {}
    }
  }

  out.passiveBodies = (window.__yf_payloads || []).map(p => p.body);
  return out;
}
"""

_CLICK_NEXT_PAGE_JS = """
() => {
  const btn = document.querySelector('ytcp-icon-button#navigate-after:not([disabled])')
    || document.querySelector('#navigate-after:not([disabled])')
    || document.querySelector('ytcp-icon-button#next-page:not([disabled])')
    || document.querySelector('tp-yt-paper-icon-button#next-page:not([disabled])')
    || Array.from(document.querySelectorAll('ytcp-icon-button, tp-yt-paper-icon-button, button')).find(el => {
      const label = (el.getAttribute('aria-label') || el.innerText || '').toLowerCase();
      return label.includes('next') || label.includes('下一') || label.includes('下一页');
    });
  if (btn && btn.getAttribute('disabled') == null && !btn.disabled) {
    btn.click();
    return true;
  }
  return false;
}
"""

_LIST_CREATOR_VIDEOS_PAGE_JS = """
async ({ channelId, roleType, pageToken, pageSize }) => {
  const out = { status: 0, videos: [], nextPageToken: "", error: "" };
  let lastAuth = window.__yf_auth;
  if (!lastAuth) {
    out.error = "no_auth";
    return out;
  }
  if (lastAuth.context && lastAuth.context.user) {
    lastAuth.context.user.delegationContext = {
      externalChannelId: channelId,
      roleType: { channelRoleType: roleType || "CREATOR_CHANNEL_ROLE_TYPE_OWNER" },
    };
  }
  const d = (window.ytcfg && window.ytcfg.data_) || {};
  const key = d.INNERTUBE_API_KEY || "";
  const client = ((d.INNERTUBE_CONTEXT || {}).client) || {};
  const headers = Object.assign({}, lastAuth.headers || {});
  delete headers["content-length"]; delete headers["Content-Length"];
  headers["content-type"] = "application/json";
  headers["X-Youtube-Client-Name"] = String(client.clientName || 62);
  headers["X-Youtube-Client-Version"] = client.clientVersion || d.INNERTUBE_CLIENT_VERSION || "";
  headers["X-Youtube-Bootstrap-Logged-In"] = "true";
  const body = {
    context: lastAuth.context,
    filter: {
      and: {
        operands: [
          { channelIdIs: { value: channelId } },
          { videoOriginIs: { value: "VIDEO_ORIGIN_UPLOAD" } },
        ],
      },
    },
    order: "VIDEO_ORDER_DISPLAY_TIME_DESC",
    pageSize: pageSize || 50,
    mask: {
      videoId: true,
      title: true,
      metrics: { all: true },
      publicMetrics: { all: true },
      revenueAnalytics: { all: true },
    },
    criticalRead: false,
  };
  if (pageToken) body.pageToken = pageToken;
  let search = "";
  try { search = new URL(lastAuth.url, location.origin).search; } catch (e) {}
  if (!search && key) search = "?key=" + encodeURIComponent(key) + "&prettyPrint=false";
  else if (search && !search.includes("prettyPrint")) {
    search += (search.includes("?") ? "&" : "?") + "prettyPrint=false";
  }
  const url = location.origin + "/youtubei/v1/creator/list_creator_videos" + search;
  try {
    const res = await fetch(url, {
      method: "POST",
      credentials: "include",
      headers,
      body: JSON.stringify(body),
    });
    out.status = res.status;
    const text = await res.text();
    if (!res.ok) {
      out.error = text.slice(0, 240);
      return out;
    }
    const json = JSON.parse(text);
    out.videos = json.videos || [];
    out.nextPageToken = json.nextPageToken || json.continuationToken || "";
  } catch (e) {
    out.error = String(e);
  }
  return out;
}
"""

_SCrape_CONTENT_REVENUE_JS = """
() => {
  const rows = [];
  const byId = new Map();
  document.querySelectorAll('a[href*="/video/"]').forEach(a => {
    const m = (a.getAttribute('href') || '').match(/\\/video\\/([^/?#]+)/);
    if (!m) return;
    const id = m[1];
    let row = a.closest('ytcp-video-row') || a.closest('[role="row"]');
    if (!row) return;
    const text = (row.innerText || '').replace(/\\s+/g, ' ').trim();
    if (!byId.has(id)) byId.set(id, text);
  });
  for (const [id, text] of byId.entries()) {
    const money = text.match(/(?:\\$|USD|¥|€)\\s*[\\d,]+(?:\\.\\d+)?|[\\d,]+(?:\\.\\d+)?\\s*(?:USD)/);
    rows.push({ videoId: id, rowText: text.slice(0, 300), revenueGuess: money ? money[0] : "" });
  }
  return rows;
}
"""
