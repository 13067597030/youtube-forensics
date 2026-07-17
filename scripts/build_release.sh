#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== YouTubeForensics macOS 绿色包构建 =="

PYTHON="${PYTHON:-python3}"
if [[ -x ".venv/bin/python" ]]; then
  PYTHON=".venv/bin/python"
fi

"$PYTHON" -m pip install -q -e ".[pack,browser]"

echo "PyInstaller 打包中..."
"$PYTHON" -m PyInstaller packaging/yt_forensics.spec --noconfirm --clean

DIST_DIR="dist/YouTubeForensics"
if [[ ! -d "$DIST_DIR" ]]; then
  echo "构建失败：未找到 $DIST_DIR" >&2
  exit 1
fi

mkdir -p "$DIST_DIR/config"
cp config/settings.yaml "$DIST_DIR/config/settings.yaml"
cp packaging/release_templates/README-macos.txt "$DIST_DIR/README.txt"
mkdir -p "$DIST_DIR/data" "$DIST_DIR/Evidence"

chmod +x "$DIST_DIR/yt-forensics"

VERSION=$("$PYTHON" -c "from yt_forensics import __version__; print(__version__)")
ARCH=$(uname -m)
ZIP="dist/YouTubeForensics-${VERSION}-macos-${ARCH}.zip"
"$PYTHON" packaging/zip_release.py "$DIST_DIR" "$ZIP"

echo "完成: $ZIP"
