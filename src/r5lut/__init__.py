"""创意外观转换包:R5 固件 BIN + A7M4 camera-look v2 JSON。"""

from __future__ import annotations

from .core import (
    R5Error,
    TrainResult,
    compile_config,
    diagnostics,
    distill_grid,
    engine_root,
    finish,
    formal_budget,
    generate_pc,
    inspect_bin,
    prepare_chart_target,
    prepare_target,
    quick_budget,
    train,
    verify,
)

__version__ = "1.2.10"

__all__ = [
    "__version__",
    "R5Error",
    "TrainResult",
    "compile_config",
    "diagnostics",
    "distill_grid",
    "engine_root",
    "finish",
    "formal_budget",
    "generate_pc",
    "inspect_bin",
    "prepare_chart_target",
    "prepare_target",
    "quick_budget",
    "train",
    "verify",
]
