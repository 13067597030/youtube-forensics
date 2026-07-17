# 导出格式定稿（V1.0）

> 本文件为格式唯一规范源。代码实现须与 `src/yt_forensics/export/schema.py` 保持一致；变更须同步改两处并升版 `FORMAT_VERSION`。

## 通用约定

| 项 | 约定 |
|----|------|
| 编码 | UTF-8 with BOM（`utf-8-sig`） |
| 分隔符 | 英文逗号 `,` |
| 换行 | `\n`（LF） |
| 空值 | 空字符串（不写 `null` / `N/A`） |
| 时间 | ISO8601，**北京时间（UTC+8，后缀 `+08:00`）**；`run_id` 仍用 UTC 戳便于排序 |
| 布尔 | 不使用；状态用小写枚举字符串 |
| `FORMAT_VERSION` | `1.0.0` |

证据目录结构：

```text
Evidence/{run_id}/
├── Account_Mapping.csv
├── Video_List.csv
├── Video_Analytics.csv
├── meta.json
├── run.log
└── hashes.sha256
```

`run_id` 格式：`{YYYYMMDDTHHMMSSZ}_{8位hex}`，例：`20260716T053000Z_a1b2c3d4`。

---

## 1. Account_Mapping.csv

文件名（固定）：`Account_Mapping.csv`

| # | 列名 | 类型 | 说明 |
|---|------|------|------|
| 1 | account_email | string | Google 账号邮箱 |
| 2 | cookie_source | string | `chrome_auto` \| `import_file` |
| 3 | brand_account_id | string | Brand Account ID；Personal 可空 |
| 4 | channel_id | string | 频道 ID（UC…） |
| 5 | handle | string | @handle，无则空 |
| 6 | channel_title | string | 频道名称 |
| 7 | channel_url | string | 频道规范 URL |
| 8 | account_type | string | `personal` \| `brand` |
| 9 | permission_level | string | `none` \| `manager` \| `owner` \| `unknown` |
| 10 | forensic_time | string | 该行写入时的 ISO8601 时间 |

列顺序固定，禁止增删改名（扩展列须升 `FORMAT_VERSION`）。

---

## 2. Video_List.csv

文件名（固定）：`Video_List.csv`

| # | 列名 | 类型 | 说明 |
|---|------|------|------|
| 1 | channel_id | string | 所属频道 ID |
| 2 | uploader_id | string | 上传者 ID |
| 3 | video_id | string | 视频 ID |
| 4 | upload_date | string | 上传日期，优先 `YYYYMMDD`；未知则空 |
| 5 | title | string | 标题 |
| 6 | description | string | 描述（可含换行，CSV 按 RFC4180 引号转义） |
| 7 | webpage_url | string | 视频页 URL |
| 8 | availability | string | 可见性/可得性（平台原值或规范化小写） |
| 9 | duration | string | 时长（秒，整数字符串）；未知则空 |
| 10 | live_status | string | 直播状态；非直播可空 |
| 11 | view_count | string | 播放量（整数字符串）；未知则空 |
| 12 | scrape_time | string | 采集该条时的 ISO8601 时间 |

---

## 3. Video_Analytics.csv

文件名（固定）：`Video_Analytics.csv`

| # | 列名 | 类型 | 说明 |
|---|------|------|------|
| 1 | channel_id | string | 频道 ID |
| 2 | video_id | string | 视频 ID |
| 3 | estimated_revenue | string | Estimated Revenue |
| 4 | rpm | string | RPM |
| 5 | playback_based_cpm | string | Playback-based CPM |
| 6 | views | string | Views（统计口径） |
| 7 | watch_time | string | Watch Time |
| 8 | impressions | string | Impressions |
| 9 | ctr | string | CTR |
| 10 | monetized_playbacks | string | Monetized Playbacks |
| 11 | analytics_status | string | `ok` \| `unavailable` \| `partial` \| `skipped` |
| 12 | unavailable_reason | string | 失败/跳过原因；`ok` 时为空 |
| 13 | scrape_time | string | 采集该条时的 ISO8601 时间 |

数值类字段以字符串写出，保留接口原始精度文本，不做本地四舍五入。

---

## 4. meta.json

文件名（固定）：`meta.json`  
编码：UTF-8（无 BOM）  
格式：JSON，缩进 2 空格，键顺序按下表（实现按 `schema.py` 序列化）。

```json
{
  "format_version": "1.0.0",
  "tool_name": "YouTubeForensics",
  "tool_version": "0.1.0",
  "extraction_type": "network_online_extraction",
  "run_id": "20260716T053000Z_a1b2c3d4",
  "started_at": "2026-07-16T13:30:00+08:00",
  "finished_at": "2026-07-16T14:10:00+08:00",
  "status": "completed",
  "platform": "windows",
  "account_email": "user@example.com",
  "cookie_source": "chrome_auto",
  "time_sync": {
    "system_time": "2026-07-16T13:29:58+08:00",
    "reference_time": "2026-07-16T13:30:00+08:00",
    "offset_seconds": -2.0,
    "source": "ntp"
  },
  "counts": {
    "channels_total": 0,
    "channels_done": 0,
    "videos_total": 0,
    "videos_done": 0,
    "analytics_total": 0,
    "analytics_done": 0,
    "analytics_ok": 0,
    "analytics_partial": 0,
    "analytics_unavailable": 0
  },
  "evidence_files": [
    "Account_Mapping.csv",
    "Video_List.csv",
    "Video_Analytics.csv",
    "run.log",
    "hashes.sha256"
  ],
  "notes": ""
}
```

### 字段约束

| 字段 | 约束 |
|------|------|
| `format_version` | 固定与本文档一致 |
| `tool_name` | 固定 `YouTubeForensics` |
| `extraction_type` | 固定 `network_online_extraction` |
| `status` | `running` \| `completed` \| `failed` \| `partial` |
| `platform` | `windows` \| `darwin` \| `linux` |
| `cookie_source` | `chrome_auto` \| `import_file` \| `playwright_profile` \| `unknown` |
| `time_sync.source` | `ntp` \| `http_date` \| `none` |
| `time_sync.offset_seconds` | `system_time - reference_time`（秒，浮点） |
| `counts.analytics_done` | 成功采集条数（`analytics_status` 为 `ok` 或 `partial`） |
| `counts.analytics_ok` | 全部 Studio 指标齐全（`analytics_status=ok`） |
| `counts.analytics_partial` | 部分指标缺失但已有核心数据（多为缺 rpm/impressions 等） |
| `counts.analytics_unavailable` | 不可用或跳过（`unavailable` + `skipped`） |
| `evidence_files` | 相对本目录的文件名列表；`meta.json` 自身不列入 |

---

## 5. hashes.sha256

文件名（固定）：`hashes.sha256`  
编码：UTF-8（无 BOM）  
每行格式（与 GNU `sha256sum` 兼容）：

```text
<64位小写十六进制sha256><两个空格><文件名>
```

规则：

1. 计算对象：`Account_Mapping.csv`、`Video_List.csv`、`Video_Analytics.csv`、`meta.json`、`run.log`（若存在）  
2. **不包含** `hashes.sha256` 自身  
3. 文件名仅为 basename，不含路径  
4. 行顺序与 `meta.json` → `evidence_files` 中可哈希文件顺序一致，最后补上 `meta.json`（若未在 evidence_files 中）  
5. 推荐固定顺序：

```text
Account_Mapping.csv
Video_List.csv
Video_Analytics.csv
run.log
meta.json
```

示例：

```text
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  Account_Mapping.csv
```
