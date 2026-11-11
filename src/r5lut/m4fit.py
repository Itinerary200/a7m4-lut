"""A7M4 网格拟合:冻结 M4 响应模型,只优化 405 项 signed7 网格。

流程(与官方 AGENT_TRAINING 一致):
1. 载入冻结模型:bridge 网格多项式 + 标定 + 锚点网格 + Response 网络;
2. base = 原生前段输出(front)经 pixel_bridge 的零网格结果(0..255 codes);
3. target = 目标外观作用在 base 上(这里用 .cube 在 sRGB 上的观感);
4. Adam/STE 连续提案 → 量化 → 整数坐标抛光 → 校验;
5. 用种子 JSON 的原生参数 + 新网格封签写出 camera-look v2。

不改变原生参数,所以不需要 Sony Edit 参考文件。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .paths import ensure_path

ensure_path("vendor", "m4")
ensure_path("engine", "web")

GRID_SHAPE = (3, 5, 9, 9)
FRONT_SCALE = 1.0 / 16.0  # sony_input.front 是 8bit×16 的定点


class M4FitError(RuntimeError):
    """拟合前提或结果不满足合同。"""


def bundled_native16(tag: str = "anchor") -> Path | None:
    """内置的相机前段缓存(chart_native 输出)。

    tag 对应不同的原生参数:anchor 是中性起点,acros 是黑白胶片,
    ricoh-positive / ricoh-negative 是正片/负片风格。拟合难收敛时换一个起点更准。
    """
    import os

    from .paths import frozen, resource_dir

    if tag == "anchor":
        override = os.environ.get("R5_M4_NATIVE16", "")
        if override and Path(override).is_file():
            return Path(override)
    candidates = [
        resource_dir("assets", "native16", f"{tag}.npy"),
        resource_dir("r5lut", "assets", "native16", f"{tag}.npy"),
        Path(__file__).resolve().parent / "assets" / "native16" / f"{tag}.npy",
    ]
    if not frozen():
        candidates.append(Path(__file__).resolve().parents[2] / "build" / "anchor.npy")
        candidates.append(Path("out") / "m4-native" / "native16-cache" / f"{tag}.npy")
    for item in candidates:
        if item.is_file():
            return item
    return None


def _resolve_key(item: Path) -> Path:
    """取绝对路径用于去重,失败时退回原样(仅用于比较)。"""
    try:
        return item.resolve()
    except OSError:
        return item


def _has_models(item: Path) -> bool:
    """该目录是否是一套完整模型资产。"""
    try:
        return (item / "models" / "forward_model.json").is_file()
    except OSError:
        return False


def _asset_candidates(assets: Any, note: list[str]) -> list[Path]:
    """按优先级列出可能的资产目录(exe 同级、解包目录、工作目录都试一遍)。"""
    from .paths import resource_dir

    given = Path(str(assets))
    tries: list[Path] = [given, given / "M4-training-assets", Path.cwd() / "assets"]
    tries.append(resource_dir("assets"))
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        tries.extend([exe_dir / "assets", exe_dir / "_internal" / "assets"])
    unique: list[Path] = []
    seen: set[Path] = set()
    for item in tries:
        key = _resolve_key(item)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
        note.append(str(item))
    return unique


def resolve_assets(assets: Any) -> Path:
    """资产目录解析:给定路径缺 models/ 时,依次回落到内置 assets/。"""
    note: list[str] = []
    for item in _asset_candidates(assets, note):
        if _has_models(item):
            return item
    raise M4FitError(
        "找不到相机模型数据(models/forward_model.json)。\n"
        "可以在「显示更多设置 → 模型数据」里选 M4-training-assets 目录,\n"
        "或重新解压完整压缩包(assets 目录要和 exe 放在一起)。\n"
        "试过:" + "、".join(note[:4])
    )


@dataclass
class Model:
    """冻结的 M4 网格响应(与 CameraModel.forward 同一数学)。"""

    assets: Path
    device: str = "cuda"

    def __post_init__(self) -> None:
        from .m4guard import require

        require("torch")
        self.assets = resolve_assets(self.assets)
        require("numpy")
        import torch

        bridge_dir = self.assets / "models" / "bridge"
        bridge = json.loads((bridge_dir / "forward_model.json").read_text(encoding="utf-8"))
        sources = bridge["sources"]

        def _bridge(relative: str) -> dict[str, Any]:
            value = json.loads((bridge_dir / relative).read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise M4FitError(f"{relative} 顶层不是对象")
            return value

        self.grid_model = _bridge(sources["grid_response"]["path"])["model"]
        self.calibration = _bridge(sources["color_bridge"]["path"])
        anchor = _bridge(sources["anchor_native"]["path"])
        self.anchor_grid = np.asarray(anchor["parameters"]["grid"]["photo"], dtype=float)
        contract_path = self.assets / "models" / "forward_model.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        weights = Path(contract["sources"]["grid_weights"]["path"])
        if not weights.is_absolute():
            weights = contract_path.parent / weights
        checkpoint = torch.load(weights, map_location="cpu", weights_only=True)
        from response_network import Response

        response = Response(checkpoint["seed"], checkpoint["width"])
        response.load_state_dict(checkpoint["state"])
        self.device = self.device if torch.cuda.is_available() else "cpu"
        self.torch = torch
        self.response = response.to(self.device).eval()
        self.response.requires_grad_(False)
        import pixel_bridge

        self.pixel_bridge = pixel_bridge

    def _read(self, relative: str) -> dict[str, Any]:
        path = self.assets / relative
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise M4FitError(f"{path} 顶层不是对象")
        return value

    def native_base(self, native16: Any) -> Any:
        """相机前段输出(16bit)→ 0..255 坐标空间;这是网格的真正输入。"""
        return np.clip(np.asarray(native16, dtype=np.float64) / 257.0, 0.0, 255.0)

    def render_base(self, base: Any, grid: Any | None) -> Any:
        """给定 0..255 前段输入直接算输出(与相机查 129³ 表相差约 2.4 mae8)。"""
        torch = self.torch
        x = torch.as_tensor(
            np.asarray(base, dtype=np.float64), dtype=torch.float32, device=self.device
        )
        if grid is None:
            return np.asarray(x.detach().cpu().numpy())
        table = torch.as_tensor(np.asarray(grid, dtype=np.float32), device=self.device)
        out = self.response(x[None], table.reshape(1, *GRID_SHAPE))[0][0]
        return np.asarray(out.detach().cpu().numpy())

    def render(self, front: Any, grid: Any | None) -> Any:
        """front(0..8184) + 网格 → sRGB 0..255;grid=None 表示零网格(基础输出)。"""
        torch = self.torch
        rgb = torch.as_tensor(front * FRONT_SCALE, dtype=torch.float64, device=self.device)
        zero = torch.zeros(GRID_SHAPE, dtype=torch.float64, device=self.device)
        base = self.pixel_bridge.torch_transform(
            rgb, zero, self.grid_model, self.calibration, self.anchor_grid
        ).to(torch.float32)
        if grid is None:
            return np.asarray(base.detach().cpu().numpy())
        table = torch.as_tensor(np.asarray(grid, dtype=np.float32), device=self.device)
        out = self.response(base[None], table.reshape(1, *GRID_SHAPE))[0][0]
        return np.asarray(out.detach().cpu().numpy())


def load_front(assets: Path) -> tuple[Any, Any, Any]:
    """返回 (front, split, design_srgb);资产缺失时用 exe 内置副本。"""
    assets = resolve_assets(assets)
    with np.load(assets / "charts/sony_input.npz", allow_pickle=False) as archive:
        front = archive["front"].astype(np.float64)
        split = archive["split"].astype(str)
    with np.load(assets / "charts/design_pairs.npz", allow_pickle=False) as archive:
        design = archive["design_srgb"]
    return front, split, design


def cube_target(
    base: np.ndarray,
    cube: Any,
    transfer: str = "display",
    output: str = "display",
) -> np.ndarray:
    """把 .cube 作用在相机基础输出上(0..255 sRGB 观感)。

    transfer 是这份 LUT 的输入编码(索尼 S-Log3、富士 F-Log …),进门先换算成对应码值;
    output 是它吐出来的编码(有的官方 LUT 目标是 SLog2、PQ、HLG),出门再解码回显示域。
    两头都按 LUT 作者的本意处理,才谈得上「自动适配」。
    """
    from r5lut import preview
    from r5lut import transfer as transfer_mod

    flat = base.reshape(-1, 3) / 255.0
    out = np.empty_like(flat)
    use_in = transfer != transfer_mod.DISPLAY
    use_out = output != transfer_mod.DISPLAY
    for index, (red, green, blue) in enumerate(flat):
        if use_in:
            red = transfer_mod.display_to_code(float(red), transfer)
            green = transfer_mod.display_to_code(float(green), transfer)
            blue = transfer_mod.display_to_code(float(blue), transfer)
        sampled = preview.sample(cube, float(red), float(green), float(blue))
        if use_out:
            out[index] = (
                transfer_mod.code_to_display(float(sampled[0]), output),
                transfer_mod.code_to_display(float(sampled[1]), output),
                transfer_mod.code_to_display(float(sampled[2]), output),
            )
        else:
            out[index] = sampled
    return (np.clip(out, 0.0, 1.0) * 255.0).reshape(base.shape)


def table_stencil(coords: Any) -> tuple[Any, Any, Any]:
    """把 0..255 坐标映射到相机 129³ 表的 8 邻域(索引、权重、唯一节点坐标)。"""
    values = np.asarray(coords, dtype=np.float64).reshape(-1, 3)
    pos = values * (128.0 / 255.0)
    low = np.minimum(np.floor(pos).astype(np.int64), 127)
    fraction = pos - low
    indices = []
    weights = []
    for corner in np.ndindex(2, 2, 2):
        offset = np.asarray(corner)
        node = low + offset
        indices.append(node[:, 0] * 129 * 129 + node[:, 1] * 129 + node[:, 2])
        weights.append(np.prod(np.where(offset, fraction, 1.0 - fraction), axis=1))
    flat = np.stack(indices)
    unique, inverse = np.unique(flat, return_inverse=True)
    node_coords = np.column_stack((unique // (129 * 129), (unique // 129) % 129, unique % 129)) * (
        255.0 / 128.0
    )
    return node_coords, inverse.reshape(8, -1), np.stack(weights)


def table_render(model: Model, base: Any, grid: Any, stencil: Any) -> Any:
    """按相机实际路径(129³ 表三线性)重放输出,用于验收。"""
    torch = model.torch
    node_coords, inverse, weights = stencil
    nodes = torch.as_tensor(node_coords, dtype=torch.float64, device=model.device)
    # 表节点值 = forward(节点坐标) = response(pixel_bridge(节点坐标), grid)
    bridged = model.pixel_bridge.torch_transform(
        nodes,
        torch.zeros(GRID_SHAPE, dtype=torch.float64, device=model.device),
        model.grid_model,
        model.calibration,
        model.anchor_grid,
    ).to(torch.float32)
    table = torch.as_tensor(np.asarray(grid, dtype=np.float32), device=model.device)
    values = model.response(bridged[None], table.reshape(1, *GRID_SHAPE))[0][0]
    gathered = values[torch.as_tensor(inverse.reshape(-1), device=model.device)]
    weights_t = torch.as_tensor(weights.reshape(-1), dtype=torch.float32, device=model.device)
    out = (gathered.reshape(8, -1, 3) * weights_t.reshape(8, -1, 1)).sum(0)
    return np.asarray(out.detach().cpu().numpy())


def camera_render(model: Model, coords: Any, grid: Any) -> Any:
    """按相机实际做法(129³ 表 + 三线性)把 0..255 输入渲染成 0..255 输出。"""
    values = np.asarray(coords, dtype=np.float64)
    shape = values.shape
    flat = values.reshape(-1, 3)
    stencil = table_stencil(flat)
    out = table_render(model, flat, grid, stencil)
    return np.clip(np.asarray(out, dtype=np.float64), 0.0, 255.0).reshape(shape)


def stratified_ids(target: np.ndarray, count: int, seed: int = 20261110) -> np.ndarray:
    """按目标颜色的明度/色度分布分层取样,让训练覆盖整个色域而不是集中在肤色。"""
    values = np.clip(np.asarray(target, float), 0, 255).reshape(-1, 3) / 255.0
    lin = np.where(values <= 0.04045, values / 12.92, ((values + 0.055) / 1.055) ** 2.4)
    matrix = np.array(
        [
            [0.4124564, 0.3575761, 0.1804375],
            [0.2126729, 0.7151522, 0.0721750],
            [0.0193339, 0.1191920, 0.9503041],
        ]
    )
    xyz = lin @ matrix.T
    white = np.array([0.95047, 1.0, 1.08883])
    ratio = xyz / white
    delta = 6.0 / 29.0
    f = np.where(
        ratio > delta**3, np.cbrt(np.clip(ratio, 1e-9, None)), ratio / (3 * delta**2) + 4.0 / 29.0
    )
    lab = np.stack((116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])), 1)
    lightness = np.clip((lab[:, 0] - 0) / 100.0, 0, 0.999)
    chroma_a = np.clip((lab[:, 1] + 128) / 256.0, 0, 0.999)
    chroma_b = np.clip((lab[:, 2] + 128) / 256.0, 0, 0.999)
    bins = (
        (lightness * 12).astype(int) * 64
        + (chroma_a * 8).astype(int) * 8
        + (chroma_b * 8).astype(int)
    )
    rng = np.random.default_rng(seed)
    chosen: list[int] = []
    unique = np.unique(bins)
    quota = max(1, count // max(1, len(unique)))
    for value in unique:
        members = np.flatnonzero(bins == value)
        take = min(quota, len(members))
        chosen.extend(rng.choice(members, take, replace=False).tolist())
    remaining = count - len(chosen)
    if remaining > 0:
        pool = np.setdiff1d(np.arange(len(bins)), np.asarray(chosen, dtype=int))
        chosen.extend(rng.choice(pool, min(remaining, len(pool)), replace=False).tolist())
    return np.sort(np.asarray(chosen[:count], dtype=int))


def _de00_torch(pred: Any, target: Any) -> Any:
    """torch 版 ΔE00(冻结近似:用 Lab 欧氏距离代替,仅作训练项)。"""
    torch = __import__("torch")

    def lab(x: Any) -> Any:
        scaled = x / 255.0
        linear = torch.where(scaled <= 0.04045, scaled / 12.92, ((scaled + 0.055) / 1.055) ** 2.4)
        matrix = torch.tensor(
            [
                [0.4124564, 0.3575761, 0.1804375],
                [0.2126729, 0.7151522, 0.0721750],
                [0.0193339, 0.1191920, 0.9503041],
            ],
            dtype=x.dtype,
            device=x.device,
        )
        xyz = linear @ matrix.T
        white = torch.tensor([0.95047, 1.0, 1.08883], dtype=x.dtype, device=x.device)
        ratio = xyz / white
        delta = 6.0 / 29.0
        f = torch.where(
            ratio > delta**3,
            ratio.clamp_min(1e-9) ** (1.0 / 3.0),
            ratio / (3 * delta**2) + 4.0 / 29.0,
        )
        return torch.stack(
            (116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])), dim=1
        )

    a, b = lab(pred), lab(target)
    return torch.sqrt(((a - b) ** 2).sum(1) + 1e-9)


def _de00(pred: np.ndarray, target: np.ndarray) -> np.ndarray:
    from perceptual import de2000, to_lab

    return np.asarray(de2000(to_lab(np.clip(pred, 0, 255)), to_lab(np.clip(target, 0, 255))))


def fit(
    assets: Path | str,
    target: np.ndarray,
    front: np.ndarray,
    *,
    steps: int = 900,
    samples: int = 8192,
    learning_rate: float = 0.6,
    centre: np.ndarray | None = None,
    base: Any | None = None,
    perceptual: float = 0.0,
    stratified: bool = True,
    progress: Any = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Adam/STE 拟合 → 量化 → 整数抛光;返回 (3,5,9,9) int 网格与审计。"""
    torch_module = __import__("torch")
    model = Model(Path(assets), device="cuda")
    if base is None:
        base = model.render(front, None)
    base = np.asarray(base, dtype=np.float64)

    if stratified:
        ids = stratified_ids(target, min(samples, len(target)))
    else:
        rng = np.random.default_rng(20261110)
        ids = np.sort(rng.choice(len(target), min(samples, len(target)), replace=False))
    if centre is not None:
        seed_grid = np.asarray(centre, dtype=np.float32)
    else:
        seed_grid = np.zeros(GRID_SHAPE, np.float32)

    values = torch_module.tensor(
        seed_grid, device=model.device, dtype=torch_module.float32, requires_grad=True
    )
    optimizer = torch_module.optim.Adam([values], lr=learning_rate)
    want = torch_module.as_tensor(base[ids], device=model.device, dtype=torch_module.float32)
    goal = torch_module.as_tensor(target[ids], device=model.device, dtype=torch_module.float32)
    history = []
    for step in range(steps):
        optimizer.zero_grad(set_to_none=True)
        quantized = torch_module.round(values).clamp(-64, 63).detach() + (values - values.detach())
        out = model.response(want[None], quantized.reshape(1, *GRID_SHAPE))[0][0]
        rgb = ((out - goal) ** 2).mean()
        if perceptual > 0.0:
            de = _de00_torch(out, goal)
            rgb = rgb + perceptual * (2.55 * de**2).mean()
        smooth = (
            (quantized[:, 1:] - quantized[:, :-1]).abs().mean()
            + (quantized[:, :, 1:] - quantized[:, :, :-1]).abs().mean()
            + (quantized[:, :, :, 1:] - quantized[:, :, :, :-1]).abs().mean()
        )
        loss = rgb + 0.05 * smooth
        loss.backward()
        optimizer.step()
        if step % 100 == 0 or step == steps - 1:
            history.append(
                {
                    "step": step,
                    "loss": float(loss.detach().cpu()),
                    "rgb_mse": float(rgb.detach().cpu()),
                }
            )
            if progress:
                progress(history[-1])

    grid = np.clip(np.round(values.detach().cpu().numpy()), -64, 63).astype(np.int16)

    # 整数抛光:用梯度方向做量化步进(每次前向评估,代替 2430 次单点渲染)
    torch = torch_module
    polish_rows = ids[: min(len(ids), 4096)]
    x_polish = torch.as_tensor(base[polish_rows], device=model.device, dtype=torch.float32)
    y_polish = torch.as_tensor(target[polish_rows], device=model.device, dtype=torch.float32)

    def _loss(candidate: Any) -> float:
        tensor = torch.as_tensor(candidate, device=model.device, dtype=torch.float32)
        out = model.response(x_polish[None], tensor.reshape(1, *GRID_SHAPE))[0][0]
        return float(((out - y_polish) ** 2).mean().detach().cpu())

    current = np.clip(np.rint(grid), -64, 63).astype(np.int16)
    best_loss = _loss(current)

    for _ in range(4):
        values = torch.tensor(current, device=model.device, dtype=torch.float32, requires_grad=True)
        out = model.response(x_polish[None], values.reshape(1, *GRID_SHAPE))[0][0]
        loss = ((out - y_polish) ** 2).mean()
        gradient = torch.autograd.grad(loss, values)[0].detach().cpu().numpy()
        step_dir: Any = np.where(gradient > 0, -1, 1).astype(np.int16)
        trial = np.clip(current + step_dir, -64, 63).astype(np.int16)
        trial_loss = _loss(trial)
        if trial_loss >= best_loss - 1e-12:
            break
        current, best_loss = trial, trial_loss
    grid = current

    best = np.asarray(model.render(front, grid), dtype=np.float64)
    target_seen = np.asarray(target, dtype=np.float64)
    best_loss = float(np.mean((best - target_seen) ** 2))

    audit = {
        "steps": steps,
        "samples": int(len(ids)),
        "device": model.device,
        "rgb_mse": best_loss,
        "mae8": float(np.abs(best - target_seen).mean()),
        "de00": float(np.mean(_de00(best, target_seen))),
        "grid_nonzero": int(np.count_nonzero(grid)),
        "grid_min": int(grid.min()),
        "grid_max": int(grid.max()),
        "history": history[-6:],
    }
    return grid, audit


class TablePath:
    """相机 129³ 表路径的预计算器:pixel_bridge(节点) 与网格无关,只算一次。"""

    def __init__(self, model: Model, base: Any, ids: Any | None = None) -> None:
        torch = model.torch
        self.model = model
        values = np.asarray(base, dtype=np.float64).reshape(-1, 3)
        if ids is not None:
            values = values[np.asarray(ids)]
        node_coords, inverse, weights = table_stencil(values)
        nodes = torch.as_tensor(node_coords, dtype=torch.float64, device=model.device)
        with torch.no_grad():
            self.bridged = model.pixel_bridge.torch_transform(
                nodes,
                torch.zeros(GRID_SHAPE, dtype=torch.float64, device=model.device),
                model.grid_model,
                model.calibration,
                model.anchor_grid,
            ).to(torch.float32)
        self.inverse = torch.as_tensor(inverse.reshape(-1), device=model.device)
        self.weights = torch.as_tensor(
            weights.reshape(-1), dtype=torch.float32, device=model.device
        )

    def outputs(self, grid: Any) -> Any:
        torch = self.model.torch
        if not isinstance(grid, torch.Tensor):
            grid = torch.as_tensor(np.asarray(grid), dtype=torch.float32, device=self.model.device)
        values = self.model.response(self.bridged[None], grid.reshape(1, *GRID_SHAPE))[0][0]
        gathered = values[self.inverse]
        return (gathered.reshape(8, -1, 3) * self.weights.reshape(8, -1, 1)).sum(0)


class TableFit:
    """直接对「相机 129³ 表 + 三线性插值」这条真实路径做优化。"""

    def __init__(
        self,
        model: Model,
        base: Any,
        target: Any,
        samples: int = 8192,
        seed: int = 20261110,
    ) -> None:
        torch = model.torch
        self.model = model
        wanted = np.asarray(target, dtype=np.float64).reshape(-1, 3)
        rng = np.random.default_rng(seed)
        self.ids = np.sort(rng.choice(len(wanted), min(samples, len(wanted)), replace=False))
        self.path = TablePath(model, base, self.ids)
        self.want = torch.as_tensor(wanted[self.ids], dtype=torch.float32, device=model.device)

    def _outputs(self, grid: Any) -> Any:
        return self.path.outputs(grid)

    def refine(self, grid: Any, steps: int = 120, learning_rate: float = 0.4) -> tuple[Any, float]:
        torch = self.model.torch
        values = torch.tensor(
            np.asarray(grid, dtype=np.float32), device=self.model.device, requires_grad=True
        )
        optimizer = torch.optim.Adam([values], lr=learning_rate)
        best = np.clip(np.rint(np.asarray(grid)), -64, 63).astype(np.int16)
        best_loss = self.loss(best)
        for _ in range(steps):
            optimizer.zero_grad(set_to_none=True)
            quantized = torch.round(values).clamp(-64, 63).detach() + (values - values.detach())
            out = self._outputs(quantized)
            loss = ((out - self.want) ** 2).mean()
            loss.backward()
            optimizer.step()
        candidate = np.clip(np.rint(values.detach().cpu().numpy()), -64, 63).astype(np.int16)
        candidate_loss = self.loss(candidate)
        if candidate_loss < best_loss:
            best, best_loss = candidate, candidate_loss
        # 量化步进抛光(真实表路径)
        for _ in range(3):
            tensor = torch.tensor(
                best, device=self.model.device, dtype=torch.float32, requires_grad=True
            )
            out = self._outputs(tensor)
            gradient = torch.autograd.grad(((out - self.want) ** 2).mean(), tensor)[0]
            direction = np.where(gradient.detach().cpu().numpy() > 0, -1, 1).astype(np.int16)
            trial = np.clip(best + direction, -64, 63).astype(np.int16)
            trial_loss = self.loss(trial)
            if trial_loss >= best_loss - 1e-12:
                break
            best, best_loss = trial, trial_loss
        return best, best_loss

    def loss(self, grid: Any) -> float:
        torch = self.model.torch
        with torch.no_grad():
            out = self._outputs(
                torch.as_tensor(np.asarray(grid), dtype=torch.float32, device=self.model.device)
            )
            return float(((out - self.want) ** 2).mean().detach().cpu())


def evaluate(
    assets: Path | str, grid: np.ndarray, target: np.ndarray, front: np.ndarray, split: np.ndarray
) -> dict[str, Any]:
    model = Model(Path(assets))
    out = model.render(front, grid)
    report: dict[str, Any] = {}
    for name in ("train", "valid", "test"):
        mask = split == name
        if not mask.any():
            continue
        diff = out[mask] - target[mask]
        report[name] = {
            "samples": int(mask.sum()),
            "mae8": float(np.abs(diff).mean()),
            "rmse8": float(np.sqrt(np.mean(diff**2))),
            "de00": float(np.mean(_de00(out[mask], target[mask]))),
        }
    return report
