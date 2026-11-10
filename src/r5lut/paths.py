"""运行期资源定位:源码树与 PyInstaller 冻结包都能找到 vendor/ 与 engine/ 数据。"""

from __future__ import annotations

import sys
from pathlib import Path


def frozen() -> bool:
    """是否运行在 PyInstaller 打包后的可执行文件里。"""
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """资源根目录:冻结包是解包临时目录,源码树是项目根。"""
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(str(bundle))
    return Path(__file__).resolve().parents[2]


def resource_dir(*parts: str) -> Path:
    """取资源子目录,不存在时返回按源码树推导的路径(便于给出准确报错)。"""
    return resource_root().joinpath(*parts)


def ensure_path(*parts: str) -> Path:
    """把资源目录加入 sys.path 并返回它(重复调用安全)。"""
    target = resource_dir(*parts)
    text = str(target)
    if target.is_dir() and text not in sys.path:
        sys.path.insert(0, text)
    return target
