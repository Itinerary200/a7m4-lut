"""每次改动前留一份可回滚备份(源码 + 打包配置 + 产物指纹)。"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

root = Path().resolve()
stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
tag = sys.argv[1] if len(sys.argv) > 1 else "manual"
dest = root / "backups" / f"{stamp}_{tag}"
dest.mkdir(parents=True, exist_ok=True)

items = [
    "src",
    "build/A7M4.spec",
    "build/m4app.py",
    "pyproject.toml",
    "README.md",
    "requirements-m4.txt",
]
for item in items:
    src = root / item
    if not src.exists():
        continue
    target = dest / Path(item)
    target.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    else:
        shutil.copy2(src, target)

artifacts = {}
for name in ("dist/A7M4LUT.exe", "dist/A7M4LUT-1.0.1.zip", "dist/A7M4-LUT-1.0.1.zip"):
    path = root / name
    if path.exists():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        artifacts[name] = {
            "bytes": path.stat().st_size,
            "sha256": digest,
            "mtime": path.stat().st_mtime,
        }

note = {
    "stamp": stamp,
    "tag": tag,
    "artifacts_at_backup": artifacts,
    "restore": "把备份里的 src 覆盖回项目 src,按需重打包",
}
(dest / "backup.json").write_text(json.dumps(note, ensure_ascii=False, indent=2), encoding="utf-8")

archive = dest.with_suffix("")
with zipfile.ZipFile(f"{archive}.zip", "w", zipfile.ZIP_DEFLATED) as bundle:
    for path in sorted(dest.rglob("*")):
        if path.is_file():
            bundle.write(path, path.relative_to(dest))
if not any((dest / name).exists() for name in ("src",)):
    shutil.rmtree(dest)
print("备份:", dest.with_suffix(".zip"))
print(json.dumps(artifacts, ensure_ascii=False, indent=2))
