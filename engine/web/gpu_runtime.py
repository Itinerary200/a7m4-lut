"""GPU 设备策略:Apple Metal(MPS)→ NVIDIA CUDA → CPU,显式按进程选择。

环境变量 R5_GPU_TRAINING: '1'/'true' 启用 GPU;'0'/'false'/'cpu'/'off' 强制 CPU。
默认 '0'(CPU),与上游行为一致——显式开启才走 GPU 路径。
"""
import os
from functools import lru_cache


@lru_cache(maxsize=1)
def device():
    if os.environ.get('R5_GPU_TRAINING', '0').lower() in ('0', 'false', 'cpu', 'off'):
        return 'cpu'
    try:
        import torch
    except ImportError:
        return 'cpu'
    try:
        if hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
            return 'mps'
    except Exception:
        pass
    try:
        if torch.cuda.is_available():
            return 'cuda'
    except Exception:
        pass
    return 'cpu'


def available():
    return device() != 'cpu'


def policy():
    dev = device()
    label = {'mps': 'Apple Metal/MPS', 'cuda': 'NVIDIA CUDA', 'cpu': 'CPU'}[dev]
    return dict(requested=os.environ.get('R5_GPU_TRAINING', '0'),
                available=available(), backend=label, device=dev)
