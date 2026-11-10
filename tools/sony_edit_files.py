"""从 Sony Imaging Edge Edit 提取 M4 训练所需的两个外部文件,并校验指纹。

M4 冻结模型(`models/forward_model.json`)要求:
  edit_constants : Edit 可执行文件(7,279,952 字节)
  srsettings     : srsettings0000.tbl(89,048 字节)

两种来源都支持:
  1) `.dmg`(Windows 上用 7-Zip 直接展开);
  2) 已装好的 macOS 应用目录(例如整个 `Imaging Edge Edit.app` 拷贝过来)。

用法:
    py -3 tools/sony_edit_files.py --source "D:\\dl\\ImagingEdgeDesktop.dmg" ^
        --dest "D:\\ai逆向\\a7r5-ref\\a7m4\\sony-edit"
    py -3 tools/sony_edit_files.py --source "D:\\dl\\Imaging Edge Edit.app" --dest ...
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

EXPECTED = {
    "edit_constants": (
        7_279_952,
        "43ae5e1cb4bc18a52183b430e02b16a4506b89a907a6fd0feed359fa85a82ce9",
    ),
    "srsettings": (
        89_048,
        "ef1dd637b6656dc895246265bd311fbc63b0e95f7b50005ceb61c19d472d9aba",
    ),
}
SEVEN_ZIP_CANDIDATES = (
    r"C:\Program Files\7-Zip\7z.exe",
    r"C:\Program Files (x86)\7-Zip\7z.exe",
    "7z",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _seven_zip() -> str:
    for candidate in SEVEN_ZIP_CANDIDATES:
        if candidate == "7z" or Path(candidate).is_file():
            return candidate
    raise SystemExit("找不到 7-Zip:请安装后重试,或手工展开 dmg 再传 --source 目录")


def expand_dmg(dmg: Path, target: Path) -> None:
    completed = subprocess.run(
        [_seven_zip(), "x", "-y", f"-o{target}", str(dmg)],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise SystemExit(f"7-Zip 展开失败:\n{completed.stdout[-1500:]}\n{completed.stderr[-800:]}")


def walk(root: Path) -> list[Path]:
    """遍历文件;macOS 应用包里的符号链接在 Windows 上是坏的,跳过即可。"""
    found: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(root, onerror=lambda _e: None):
        for name in filenames:
            path = Path(dirpath) / name
            try:
                if path.is_file():
                    found.append(path)
            except OSError:
                continue
    return found


def match(files: list[Path]) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for path in files:
        size = path.stat().st_size
        if size == EXPECTED["srsettings"][0] and path.name.lower().endswith(".tbl"):
            found.setdefault("srsettings", path)
        elif size == EXPECTED["edit_constants"][0]:
            found.setdefault("edit_constants", path)
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="提取 Imaging Edge Edit 的两个外部文件")
    parser.add_argument("--source", required=True, type=Path, help=".dmg 文件或已展开的应用目录")
    parser.add_argument("--dest", required=True, type=Path, help="输出目录")
    args = parser.parse_args(argv)

    source: Path = args.source
    if not source.exists():
        raise SystemExit(f"路径不存在:{source}")

    with tempfile.TemporaryDirectory(prefix="iedit-") as scratch:
        root = source
        if source.suffix.lower() == ".dmg":
            expanded = Path(scratch) / "dmg"
            expanded.mkdir()
            expand_dmg(source, expanded)
            root = expanded
        files = walk(root)
        found = match(files)
        missing = [key for key in EXPECTED if key not in found]
        if missing:
            raise SystemExit(
                "未找到:"
                + ", ".join(missing)
                + "\n提示:确认来源是 Imaging Edge Desktop 的 macOS 包,且含 Edit 应用;"
                "\n也可手工指定已装应用目录(Imaging Edge Edit.app)。"
            )
        args.dest.mkdir(parents=True, exist_ok=True)
        ok = True
        for key, path in found.items():
            size, digest = EXPECTED[key]
            actual = sha256(path)
            passed = actual == digest
            ok = ok and passed
            if not passed:
                pass
            target = args.dest / (path.name if key == "srsettings" else "Edit")
            shutil.copyfile(path, target)
        return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
