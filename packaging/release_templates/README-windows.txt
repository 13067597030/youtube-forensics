# YouTubeForensics 绿色包（Windows）

解压后在本目录打开终端，或使用下方命令。

## 首次使用（必须）

本机需已安装 **Google Chrome**（Analytics 收入采集依赖 Studio + 专用 Profile）。

```powershell
.\yt-forensics.exe bootstrap-profile
```

按向导在弹出 Chrome 窗口登录 YouTube / Studio，关闭窗口后在终端按 Enter。

## 开始取证

```powershell
.\yt-forensics.exe --stage all --bootstrap-if-needed --dashboard
```

浏览器打开 Dashboard 可查看进度与 API 分页（第 X/Y 页）。

## 目录说明

| 路径 | 说明 |
|------|------|
| `config/settings.yaml` | 可修改配置（限流、增量采集等） |
| `data/` | Profile、Cookie 快照、state.db（自动生成） |
| `Evidence/` | 证据包输出目录 |
| `README.txt` | 本说明 |

## 常用命令

```powershell
.\yt-forensics.exe --stage channels
.\yt-forensics.exe --stage analytics --channel-id UCxxxxxxxx
.\yt-forensics.exe --resume-run-id 20260717T040002Z_xxxx --stage analytics
.\yt-forensics.exe bootstrap-profile --reset
```

## 系统要求

- Windows 10/11 x64
- 磁盘建议剩余 ≥ 500 MB
- 网络可访问 YouTube / Google
