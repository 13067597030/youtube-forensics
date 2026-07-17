# YouTubeForensics 绿色包（macOS）

解压后在终端进入本目录：

```bash
chmod +x yt-forensics
xattr -dr com.apple.quarantine .   # 若 Gatekeeper 拦截，按需执行
```

## 首次使用（必须）

本机需已安装 **Google Chrome**。

```bash
./yt-forensics bootstrap-profile
```

## 开始取证

```bash
./yt-forensics --stage all --bootstrap-if-needed --dashboard
```

断点续采（记下 run_id）：

```bash
./yt-forensics --resume-run-id 20260717T040002Z_xxxx --stage analytics
```

## 目录说明

| 路径 | 说明 |
|------|------|
| `config/settings.yaml` | 配置文件 |
| `data/` | Profile 与状态库 |
| `Evidence/` | 证据输出 |

## 系统要求

- macOS 12+（Apple Silicon 或 Intel 需对应架构包）
- 磁盘建议剩余 ≥ 500 MB
