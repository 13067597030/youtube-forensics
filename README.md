# YouTubeForensics

司法机关 **网络在线提取** 辅助工具：采集 YouTube 账号下频道、视频及可获取统计数据，导出标准 CSV，并生成 `meta.json` / `hashes.sha256`。

> 工具只负责提取、固定、校验与导出；笔录、双人签名等办案流程不在范围内。

## 导出格式（已定稿）

规范文档：[`specs/EXPORT_FORMAT.md`](specs/EXPORT_FORMAT.md)  
代码常量：`src/yt_forensics/export/schema.py`（`FORMAT_VERSION = 1.0.0`）

| 文件 | 说明 |
|------|------|
| `Account_Mapping.csv` | 频道映射 |
| `Video_List.csv` | 视频列表 |
| `Video_Analytics.csv` | 视频统计 |
| `meta.json` | 工具版本、时间校准、计数等 |
| `hashes.sha256` | GNU `sha256sum` 兼容校验文件 |
| `run.log` | 运行日志（脱敏） |

## 里程碑

| 阶段 | 状态 | 内容 |
|------|------|------|
| M1 | 已完成 | 配置、SQLite、Dashboard、导出/哈希、时间校准 |
| M2 | 已完成 | Cookie 自动/导入与校验、Personal+Brand 频道发现 |
| M3 | 已完成 | 视频列表（yt-dlp）、增量/限流 |
| M4 | 已完成 | Studio 统计分析（HTTP 分页 + 浏览器 `list_creator_videos` / `revenueAnalytics`） |
| M5 | 进行中 | Win/macOS 绿色包（PyInstaller，分平台构建） |

## 快速开始

```bash
cd youtube-forensics
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e ".[dev]"
pytest
python -m yt_forensics --dashboard
```

### M2 验证（Cookie + 频道）

```bash
# 自动读取本机 Chrome/Edge Cookie，只跑到频道映射
python -m yt_forensics --stage channels

# 或导入 Netscape / JSON Cookie 文件（推荐：Chrome v20 加密环境）
python -m yt_forensics --stage channels --cookie-file D:\path\cookies.txt

# 或将导出文件放到 data/cookies.txt（自动读取失败时自动回退）
```

**Cookie 导出（Chrome v20 / 浏览器占用时必做）**

1. 安装 Chrome 扩展 **Get cookies.txt LOCALLY**
2. 打开 `youtube.com` 与 `google.com`，导出 Netscape 格式
3. 保存为 `data/cookies.txt` 或通过 `--cookie-file` 指定

成功时 `Evidence/{run_id}/Account_Mapping.csv` 含全部频道，`meta.json` 中 `status=completed`。

**首次运行（Chrome v20 / 需 Studio 收入）**

```bash
# 内置向导（M5 打包后同样可用）
python -m yt_forensics bootstrap-profile

# 或旧脚本路径
python scripts/bootstrap_browser_profile.py

# Profile 未初始化时自动弹出向导
python -m yt_forensics --stage all --bootstrap-if-needed --dashboard
```

### M4 验证（Studio 统计分析）

```bash
# 首次或 Cookie 失效时初始化专用 Chrome Profile（只需一次）
python scripts/bootstrap_browser_profile.py

# 单频道（调试）
python -m yt_forensics --stage analytics --channel-id UCxxxxxxxx

# 全账号多频道
python -m yt_forensics --stage all
```

**说明**

- Manager / Brand 频道：HTTP 直调常 403，收入经 Playwright 内 `list_creator_videos` API 分页采集。
- Owner 频道：优先 HTTP 分页，缺字段时再走浏览器补全。
- `meta.json` 中 `analytics_done` = 成功采集条数（`ok` + `partial`）；`analytics_ok` = 全部指标齐全。

**增量与断点**

- 默认 `scrape.incremental: true`：跳过已有有效 Analytics 的视频（读历史 evidence + `state.db`）。
- 中断后继续同一 run：`--resume-run-id 20260717T040002Z_8949fe83 --stage analytics`
- 全量重采：`--no-incremental`

## M5 绿色包（Win + macOS）

双平台需**分别在对应系统上构建**（见 [`packaging/README.md`](packaging/README.md)）。

```powershell
# Windows 构建机
pip install -e ".[pack,browser]"
.\scripts\build_release.ps1
```

```bash
# macOS 构建机
pip install -e ".[pack,browser]"
./scripts/build_release.sh
```

现场 U 盘建议同时携带 `YouTubeForensics-*-win64.zip` 与 `YouTubeForensics-*-macos-*.zip`。

### M3 验证（视频列表）

```bash
python -m yt_forensics --stage videos --cookie-file data/cookies.txt
# 或全流程（到 M4 统计前）
python -m yt_forensics --stage all --cookie-file data/cookies.txt
```

## 配置

见 [`config/settings.yaml`](config/settings.yaml)。
