"""将 dist/YouTubeForensics 目录打成 zip（Win/macOS 构建脚本共用）。"""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path


def zip_directory(src_dir: Path, zip_path: Path) -> int:
    src_dir = src_dir.resolve()
    zip_path = zip_path.resolve()
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.is_file():
        zip_path.unlink()

    count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(src_dir.rglob("*")):
            if path.is_file():
                arcname = path.relative_to(src_dir.parent).as_posix()
                zf.write(path, arcname)
                count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Zip YouTubeForensics release folder")
    parser.add_argument("src_dir", type=Path, help="dist/YouTubeForensics")
    parser.add_argument("zip_path", type=Path, help="output zip path")
    args = parser.parse_args()
    entries = zip_directory(args.src_dir, args.zip_path)
    print(f"zip entries: {entries}")


if __name__ == "__main__":
    main()
