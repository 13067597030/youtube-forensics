# M5 双平台绿色包构建说明



PyInstaller **无法交叉编译**：Windows 包必须在 Windows 上构建，macOS 包必须在 Mac 上构建（或 GitHub Actions `release-build.yml`）。



## 环境准备



```bash

pip install -e ".[dev,pack,browser]"

playwright install chromium   # 可选；生产使用系统 Chrome + bootstrap-profile

```



## Windows



```powershell

.\scripts\build_release.ps1

```



产出：`dist/YouTubeForensics-<version>-win64.zip`



## macOS



```bash

chmod +x scripts/build_release.sh

./scripts/build_release.sh

```



产出：`dist/YouTubeForensics-<version>-macos-<arch>.zip`（`arm64` 或 `x86_64`）



## 发布前检查（两平台相同）



1. `yt-forensics bootstrap-profile` 能弹出 Chrome 并完成登录

2. `yt-forensics --stage channels` 能发现频道

3. `yt-forensics --stage all --dashboard` Dashboard 显示 API 分页进度

4. `Evidence/` 下生成完整 CSV + meta.json + hashes.sha256



## 取证现场 U 盘清单（Win + macOS 有备无患）



现场可能同时出现 Windows 与 macOS 电脑，建议 U 盘**同时携带两份包**（版本号一致）：



| 文件 | 适用 |

|------|------|

| `YouTubeForensics-0.1.0-win64.zip` | Windows 10/11 x64 |

| `YouTubeForensics-0.1.0-macos-arm64.zip` | Apple Silicon Mac |

| `YouTubeForensics-0.1.0-macos-x86_64.zip` | Intel Mac（如有） |



附加建议：



- 打印或 PDF 一份「现场速查」（bootstrap → all → 校验 hashes）

- 确认目标机已装 **Google Chrome**（不捆绑 Chromium，减小体积）

- 预留磁盘 ≥ 500 MB；大频道 Analytics 可能需数 GB 临时空间

- 断点续采：记下 Dashboard / 终端中的 `run_id`，换机或中断后用 `--resume-run-id`



### 现场流程（两平台逻辑相同）



1. 解压对应 zip 到本地磁盘（勿直接在 U 盘跑，避免 I/O 慢）

2. 首次：`bootstrap-profile`（或 `--bootstrap-if-needed`）

3. 全量：`--stage all --dashboard`

4. 交付：整个 `Evidence/<run_id>/` 目录 + `hashes.sha256`



### 平台差异速查



| 项目 | Windows | macOS |

|------|---------|-------|

| 可执行文件 | `yt-forensics.exe` | `./yt-forensics` |

| Gatekeeper | 一般无 | 可能被拦：右键打开，或 `xattr -dr com.apple.quarantine .` |

| 终端 | PowerShell / cmd | Terminal |

| 架构 | win64 | arm64 / x86_64 须匹配 |



## CI 构建



推送 tag `v*` 或手动触发 workflow，Artifacts 中下载 Win + macOS 两个 zip。



## macOS 签名（可选）



未签名包首次运行可能被 Gatekeeper 拦截，现场可右键打开或使用 `xattr -dr com.apple.quarantine`。正式交付建议 Apple Developer 签名 + 公证。

