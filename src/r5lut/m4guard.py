"""M4 拟合的运行前置检查:缺少依赖时给出可执行的指引,而不是抛裸异常。"""

from __future__ import annotations

import sys
from pathlib import Path

MESSAGE = """M4 拟合需要 PyTorch(冻结模型推理与梯度优化)。

本机当前环境缺少: {missing}

两种做法(任选):
1) 用随包源码环境跑(推荐,已随压缩包提供):
       cd <解压目录>
       启动M4.bat --cube X.cube --assets <M4-training-assets> --name 名称 -o out\\look
   该脚本会用系统 Python 安装依赖并调用 r5lut m4。

2) 手动安装后再用同一命令:
       py -3 -m pip install torch numpy scipy rawpy
       set PYTHONPATH=<解压目录>\\src
       py -3 -m r5lut m4 --cube X.cube --assets <资产目录> --name 名称 -o out\\look

说明:打包的 R5LUT.exe 只带 R5 训练与格式校验(不含 PyTorch,否则体积会到 2 GB 以上);
A7M4 的 cube→JSON 转换走上面的源码环境,产物与 exe 完全一致(camera-look v2 + provenance)。
"""


def require(module: str) -> None:
    """确认模块可用;缺失时抛出带指引的 RuntimeError。"""
    try:
        __import__(module)
    except ModuleNotFoundError as exc:
        raise RuntimeError(MESSAGE.format(missing=exc.name or module)) from exc


def python_hint() -> str:
    """给用户看的解释器路径提示。"""
    return f"{Path(sys.executable)}"
