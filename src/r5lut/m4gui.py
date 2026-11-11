"""A7M4 滤镜转换器界面:照搬 CubeLUT Studio 的布局与观感。

左上是输入(可多选文件/文件夹/zip)、转换设置与操作按钮,左下是结果表格;
右侧是「颜色预览」——原图、套用 LUT 后、色块对照,点图可读取出色号。
界面文字只讲人话,不出现术语;所有耗时工作都在后台线程,界面不卡。
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import queue
import sys
import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, cast

from . import looktheme, preview

ACCURACY: dict[str, int] = {
    "快速(约 10 秒)": 600,
    "标准(约 20 秒)": 1000,
    "精细(约 35 秒)": 1600,
}
ACCURACY_DEFAULT = "标准(约 20 秒)"

ACCURACY_NOTE = {
    "快速(约 10 秒)": "最快,颜色靠近但不追细节",
    "标准(约 20 秒)": "日常够用,推荐",
    "精细(约 35 秒)": "最费时间,渐变过渡最顺",
}
SAMPLES_DEFAULT = 8192
TABLE_STEPS_DEFAULT = 150
MAX_NAME_BYTES = 63
PREVIEW_WIDTH = 384
MIN_PANEL = 260
MIN_LEFT = 560
CHART_WIDTH = 320
CHART_HEIGHT = 180
SWATCH_HEIGHT = 34

# 预览里「相机查表」这步只在缩略尺寸上算:整张照片(几千万像素)直接查 129³ 表
# 会瞬间吃掉几个 GB,以前就是这么把预览弄挂的。取等效 800x375 左右,放大由画布做。
CAMERA_MAX_PIXELS = 300_000
CAMERA_CHUNK = 65_536
# 用户自己载入的图先缩到这个宽度再进预览,原图另存不参与渲染。
IMAGE_MAX_WIDTH = 1600
# 两张预览图各自的高度上限:竖图/长图不能把下面的开关和按钮挤出卡片。
PREVIEW_CANVAS_MAX = 220


def convert_one(
    cube: Path,
    assets: Path,
    out: Path,
    name: str,
    native: str | None,
    steps: int,
    table_steps: int,
    log: Any,
    samples: int = 8192,
    state: dict[str, Any] | None = None,
    input_transfer: str = "auto",
) -> dict[str, Any]:
    """单张转换(界面与命令行共用)。state 用来把模型与网格交回界面做预览。"""
    import hashlib

    import numpy as np

    from . import m4fit, m4json

    out.mkdir(parents=True, exist_ok=True)
    # 文件名尾部的空格/点在 Windows 上会被吃掉,导致建目录失败 —— 统一清掉
    name = name.strip(" .") or cube.stem.strip(" .") or "look"
    assets = m4fit.resolve_assets(assets)
    log(f"读取 LUT:{cube.name}")
    baked = preview.load_cube(cube)
    from . import transfer as transfer_mod

    if input_transfer == "auto":
        input_transfer = transfer_mod.detect(baked, cube.name)
    output_kind = transfer_mod.detect_output(baked, cube.name)
    # 优先用 LUT 自身反解出来的曲线:各家的固件版本会微调,关键词查表有时不准。
    calibrated, residual = transfer_mod.solve(baked, output_kind)
    curve: str | Any = input_transfer
    if calibrated is not None:
        log(f"另外反解出 LUT 自己的输入曲线(残差 {residual:.4f}),关键词曲线不准时改用它")
    elif input_transfer != transfer_mod.DISPLAY:
        log(f"这个 LUT 的输入是 {transfer_mod.label(input_transfer)},先把画面换算成 log 域再查表")
    front, split, _design = m4fit.load_front(assets)
    model = m4fit.Model(assets)
    native_path = native or (str(m4fit.bundled_native16()) if m4fit.bundled_native16() else "")
    from perceptual import de2000, to_lab

    mask = split == "test"
    # 评分只看抽样的测试点:整张图逐点算 129³ 查表要几十秒,抽样 2 万点结论一样。
    points = np.flatnonzero(mask)
    stride = max(1, points.size // 20000)
    eval_ids = points[::stride]

    # 曲线候选:先按名字/关键词查到的曲线;如果这一版调不出精度,再试「从 LUT 自己反解出来的曲线」。
    # 注意反解曲线会把 LUT 的对比度一起吃进去,所以只在关键词曲线不够准的时候才用。
    curve_cell: list[Any] = [curve]
    candidates: list[tuple[str, Any]] = [(str(input_transfer), curve)]
    if calibrated is not None and calibrated is not curve:
        candidates.append((transfer_mod.curve_label(calibrated), calibrated))

    if native_path:
        log("使用相机原始色彩数据(精度准确口径)")
    else:
        log("没有相机数据,改用估算口径(结果会偏乐观)")

    def attempt(tag: str, path: str | None) -> tuple[Any, Any, Any, Any, float, float] | None:
        """用某个起点拟合一次,返回 (base, grid, audit, target, de00, mae8)。"""
        base = model.native_base(np.load(path)) if path else model.render(front, None)
        target = m4fit.cube_target(base, baked, curve_cell[0], output_kind)
        grid, audit = m4fit.fit(
            assets,
            target,
            front,
            steps=steps,
            samples=samples,
            base=base,
            stratified=False,
        )
        sub_base = np.array(base, copy=True)[eval_ids]
        candidate = np.asarray(
            m4fit.TablePath(model, sub_base).outputs(grid).detach().cpu().numpy()
        )
        left = np.clip(candidate, 0, 255)
        right = np.clip(np.asarray(target)[eval_ids], 0, 255)
        score = float(de2000(to_lab(left), to_lab(right)).mean())
        return base, grid, audit, target, score, float(np.abs(left - right).mean())

    grid: Any = None
    audit: Any = None
    de00 = float("inf")
    mae8 = 0.0
    seed_tag = "anchor"
    used_curve = str(input_transfer)

    for curve_name, curve_value in candidates:
        curve_cell[0] = curve_value
        log(
            "正在计算颜色对应关系…"
            if curve_value is curve
            else f"换成自校准曲线再算一遍({curve_name})…"
        )

        order: list[tuple[str, str | None]] = []
        if native:
            order.append(("指定起点", native))
        else:
            # 先量一下这份 LUT 有多"没颜色":黑白 LUT 用中性起点根本拟合不出来
            # (残差就是整块去色),直接用黑白胶片起点,一次就能到位。
            probe_base = (
                model.native_base(np.load(native_path))
                if native_path
                else model.render(front, None)
            )
            probe_target = m4fit.cube_target(probe_base, baked, curve_value, output_kind)
            chroma = float(np.abs(probe_target.max(axis=1) - probe_target.min(axis=1)).mean())
            if chroma < 8.0:
                order.append(("acros", str(m4fit.bundled_native16("acros") or "")))
            order.append(("anchor", native_path))
            for tag in ("ricoh-positive", "ricoh-negative", "acros"):
                found = m4fit.bundled_native16(tag)
                if found is not None:
                    order.append((tag, str(found)))

        trial_base: Any = None
        trial_grid: Any = None
        trial_audit: Any = None
        trial_target: Any = None
        trial_de00 = float("inf")
        trial_mae8 = 0.0
        trial_seed = "anchor"

        for tag, candidate_path in order:
            if trial_base is not None:
                log(f"换个相机起点再试一次({tag})…")
            current = attempt(tag, candidate_path or None)
            if current is None:
                continue
            if current[4] + 0.15 < trial_de00:
                trial_base, trial_grid, trial_audit, trial_target, trial_de00, trial_mae8 = current
                trial_seed = tag
            if trial_de00 < 2.5:
                break

        if trial_base is None:
            continue

        if table_steps:
            log("按相机实际处理方式再校正一次…")
            refiner = m4fit.TableFit(model, trial_base, trial_target, samples=samples)
            trial_grid, _ = refiner.refine(trial_grid, steps=table_steps)

        sub_base = np.array(trial_base, copy=True)[eval_ids]
        pred = np.asarray(
            m4fit.TablePath(model, sub_base).outputs(trial_grid).detach().cpu().numpy()
        )
        a = np.clip(pred, 0, 255)
        b = np.clip(np.asarray(trial_target)[eval_ids], 0, 255)
        scored = float(de2000(to_lab(a), to_lab(b)).mean())
        if scored < de00:
            grid, audit = trial_grid, trial_audit
            de00, mae8, seed_tag, used_curve = (
                scored,
                float(np.abs(a - b).mean()),
                trial_seed,
                curve_name,
            )
        if de00 < 2.5:
            break

    curve_cell[0] = used_curve
    if state is not None:
        state["model"] = model
        state["grid"] = np.array(grid, copy=True)
        state["cube"] = cube
        state["transfer"] = used_curve

    seed = m4json.load_seed(assets / "models" / "bridge" / "anchor.json")
    table = [
        [[[int(grid[c, y, u, v]) for v in range(9)] for u in range(9)] for y in range(5)]
        for c in range(3)
    ]
    provenance = {
        "generator": "A7M4 滤镜转换器",
        "conversion": "cube -> camera-look v2,405 网格在冻结 M4 模型上拟合",
        "source": {
            "cube": cube.name,
            "cube_sha256": hashlib.sha256(cube.read_bytes()).hexdigest(),
            "cube_size": getattr(baked, "size", None),
            "target_semantics": "cube 作用在中性原生输出上",
            "input_transfer": input_transfer,
            "input_curve": str(curve)
            if isinstance(curve, str)
            else transfer_mod.curve_label(curve),
            "curve_residual": round(residual, 5),
        },
        "fit": {
            "grid_nonzero": audit["grid_nonzero"],
            "native_seed": seed_tag,
            "table_mae8": round(mae8, 3),
            "table_de00": round(de00, 3),
            "steps": steps,
            "table_steps": table_steps,
        },
        "limits": {
            "physical_camera_verified": False,
            "live_branch": "沿用照片网格(与官方 15 个参考 look 相同做法)",
            "accuracy_claim": "冻结模型实测值,不构成实机颜色保证",
        },
    }
    value = m4json.build(
        seed,
        name=name,
        author="A7M4 滤镜转换器",
        description=f"{cube.stem} → A7M4 camera-look v2",
        grid=table,
        live_grid=table,
        provenance=provenance,
    )
    info = m4json.write(out / "PRIVATE" / "M4ROOT" / "GENERAL" / "LUT" / f"{name}.json", value)
    info["fit"] = {"de00": de00, "mae8": mae8, "grid_nonzero": audit["grid_nonzero"]}
    info["sd_path"] = m4json.sd_path(f"{name}.json")
    return info


SETTINGS_PATH = Path.home() / ".a7m4lut.json"


def _load_settings() -> dict[str, Any]:
    """记一点界面偏好:预览栏宽度、配色主题。"""
    if not SETTINGS_PATH.is_file():
        return {}
    with contextlib.suppress(Exception):
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(key): value for key, value in data.items()}
    return {}


def _asset_bytes(name: str) -> bytes | None:
    """读内置图片资源(打包后也要能找到)。"""
    from .paths import resource_dir

    folders = (
        resource_dir("assets"),
        resource_dir("r5lut", "assets"),
        Path(__file__).resolve().parent / "assets",
    )
    for folder in folders:
        path = Path(folder) / name
        if path.is_file():
            with contextlib.suppress(OSError):
                return path.read_bytes()
    return None


def _load_logo(size: int) -> tk.PhotoImage | None:
    """界面左上角的立方体图标(来自 CubeLUT Studio 的 logo)。"""
    raw = _asset_bytes("logo-32.png")
    if raw is None:
        return None
    try:
        base = tk.PhotoImage(data=base64.b64encode(raw).decode("ascii"))
    except tk.TclError:
        return None
    factor = max(1, round(size / max(1, base.width())))
    return base if factor == 1 else base.subsample(factor)


def _set_window_icon(root: tk.Misc) -> None:
    """任务栏与标题栏图标。"""
    raw = _asset_bytes("logo.png")
    if raw is None:
        return
    with contextlib.suppress(tk.TclError):
        icon = tk.PhotoImage(data=base64.b64encode(raw).decode("ascii"))
        factor = max(1, round(icon.width() / 64))
        if factor > 1:
            icon = icon.subsample(factor)
        root.iconphoto(True, icon)  # type: ignore[attr-defined]
        root._window_icon = icon  # type: ignore[attr-defined]


def _logical_screen(widget: tk.Misc) -> tuple[int, int, float]:
    """屏幕可用区域(逻辑像素)与实际缩放比。"""
    scale = widget.winfo_fpixels("1i") / 96.0 or 1.0
    return (
        int(widget.winfo_screenwidth() / scale),
        int(widget.winfo_screenheight() / scale),
        scale,
    )


def _enable_dpi_awareness() -> None:
    """必须在创建窗口之前声明,否则 Windows 会把界面整体放大导致内容被裁。"""
    with contextlib.suppress(Exception):
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwarenessContext(-4)  # per-monitor v2
        except Exception:  # noqa: BLE001 - 老系统退回旧接口
            ctypes.windll.shcore.SetProcessDpiAwareness(2)


def _safe_name(text: str, fallback: str = "Look") -> str:
    """相机只认 63 字节以内的名字,非法字符一律换掉。"""
    cleaned = "".join("-" if ch in '\\/:*?"<>|' else ch for ch in text).strip()
    cleaned = " ".join(cleaned.split()) or fallback
    while len(cleaned.encode("utf-8")) > MAX_NAME_BYTES:
        cleaned = cleaned[:-1]
    return cleaned.rstrip() or fallback


def _decode_image(data: bytes) -> preview.Raster:
    """优先用 Pillow(快,支持 JPG/PNG,顺手缩到 1600 宽),没有就退回纯 Python 解码。

    纯 Python 解码一张 1200 万像素的 PNG 要 6 秒以上,界面会卡住,所以能借力就借力。
    """
    try:
        import io

        from PIL import Image
    except Exception:  # noqa: BLE001 - 没有 Pillow 只是慢一点
        return preview.decode_png(data)
    with Image.open(io.BytesIO(data)) as img:
        frame = img.convert("RGB")
        if frame.width > IMAGE_MAX_WIDTH:
            ratio = IMAGE_MAX_WIDTH / frame.width
            size = (IMAGE_MAX_WIDTH, max(1, round(frame.height * ratio)))
            resample: Any = getattr(Image, "Resampling", Image)
            frame = frame.resize(size, resample.LANCZOS)
        return preview.Raster(frame.width, frame.height, bytearray(frame.tobytes()))


def _use_image_text(active: bool) -> str:
    """开关文案把当前状态写清楚,不靠那个小方块去猜。"""
    if active:
        return "预览用我的图(点一下换回色卡)"
    return "预览用内置色卡(点一下用我的图)"


def _hex(colour: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*colour)


def _zoom(raster: preview.Raster, scale: float) -> preview.Raster:
    """按比例放大/缩小一张图(双线性);preview.fit 只缩不放,所以这里自己来。"""
    if abs(scale - 1.0) < 0.01:
        return raster
    import numpy as np

    width = max(1, int(round(raster.width * scale)))
    height = max(1, int(round(raster.height * scale)))
    flat = np.frombuffer(bytes(raster.pixels), dtype=np.uint8)
    source: Any = flat.reshape(raster.height, raster.width, 3).astype(np.float32)
    ys = np.clip((np.arange(height) + 0.5) / scale - 0.5, 0, raster.height - 1)
    xs = np.clip((np.arange(width) + 0.5) / scale - 0.5, 0, raster.width - 1)
    y0 = np.floor(ys).astype(int)
    x0 = np.floor(xs).astype(int)
    y1 = np.minimum(y0 + 1, raster.height - 1)
    x1 = np.minimum(x0 + 1, raster.width - 1)
    wy = (ys - y0)[:, None, None]
    wx = (xs - x0)[None, :, None]
    top = source[y0][:, x0] * (1 - wx) + source[y0][:, x1] * wx
    bottom = source[y1][:, x0] * (1 - wx) + source[y1][:, x1] * wx
    merged = np.clip(top * (1 - wy) + bottom * wy, 0, 255).astype(np.uint8)
    return preview.Raster(width, height, bytearray(merged.tobytes()))


class App(tk.Tk):
    """主窗口:左侧输入/设置/结果,右侧颜色预览。"""

    def __init__(self, theme_label: str = looktheme.DEFAULT_THEME_LABEL) -> None:
        super().__init__()
        self.title("A7M4 滤镜转换器")
        _set_window_icon(self)
        self._settings = _load_settings()
        saved_width = self._settings.get("panel_width2")
        self._panel_width = int(saved_width) if isinstance(saved_width, int) else PREVIEW_WIDTH
        self._panel_width = max(MIN_PANEL, min(720, self._panel_width))
        screen_w, screen_h, _scale = _logical_screen(self)
        width = min(1180, max(1040, screen_w - 40))
        height = min(940, max(820, screen_h - 40))
        left = max(0, (screen_w - width) // 2)
        top = max(0, (screen_h - height) // 3)
        self._place_sash()
        if os.environ.get("R5_SHOT") == "1":
            left, top = 20, 20
        self._window_width = width
        self._panel_width = max(MIN_PANEL, min(self._panel_width, width - MIN_LEFT - 40))
        self.geometry(f"{width}x{height}+{left}+{top}")
        self.minsize(1040, 820)
        self.configure(background=looktheme.FALLBACK["background"])

        self.theme = looktheme.apply(self, theme_label)
        self._queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._sources: list[Path] = []
        self._busy = False
        self._current_cube: Path | None = None
        self._swatch_cube: preview.Cube | None = None
        self._camera: tuple[Path, Any, Any, str] | None = None
        self._camera_cache: tuple[str, Any] | None = None
        self._source_image: preview.Raster | None = None
        self.use_image_var = tk.BooleanVar(value=True)
        self._camera_failed = False
        self._probe: tuple[preview.Raster, float, int, int] | None = None
        self._preview_job: str | None = None
        self._history: list[str] = []

        self.name_var = tk.StringVar()
        self.out_var = tk.StringVar()
        self.table_var = tk.StringVar(value=str(TABLE_STEPS_DEFAULT))
        self.samples_var = tk.StringVar(value=str(SAMPLES_DEFAULT))
        self.accuracy_var = tk.StringVar(value=ACCURACY_DEFAULT)
        self.status_var = tk.StringVar(value="选好 LUT 文件后点「开始转换」")
        self.theme_var = tk.StringVar(value=theme_label)

        self._build()
        self.after(60, self._drain)
        self.after(80, self._fit_screen)

    def _fit_screen(self) -> None:
        """按逻辑像素再核一次位置,避免高分屏上超出边界。"""
        self._place_sash()
        if os.environ.get("R5_SHOT") == "1":
            self.attributes("-topmost", True)
            self.lift()
            self.after(2500, self._save_shot)
            return
        self.update_idletasks()
        screen_w, screen_h, _scale = _logical_screen(self)
        width = self.winfo_width()
        height = self.winfo_height()
        if width > screen_w or height > screen_h:
            width = min(width, max(920, screen_w - 30))
            height = min(height, max(620, screen_h - 60))
            left = max(0, (screen_w - width) // 2)
            top = max(0, (screen_h - height) // 3)
            self.geometry(f"{width}x{height}+{left}+{top}")
            self.update_idletasks()
        x = self.winfo_x()
        y = self.winfo_y()
        if x < 0 or y < 0 or x + width > screen_w or y + height > screen_h:
            left = max(0, (screen_w - width) // 2)
            top = max(0, (screen_h - height) // 3)
            self.geometry(f"+{left}+{top}")
        self._place_sash()
        if os.environ.get("R5_SHOT") == "1":
            self.attributes("-topmost", True)
            self.lift()
            self.after(2500, self._save_shot)

    def _save_shot(self) -> None:
        """截图自检用:按窗口真实屏幕坐标存一份 PNG,再退出。"""
        from PIL import ImageGrab

        self.update()
        left = self.winfo_rootx()
        top = self.winfo_rooty()
        width = self.winfo_width()
        height = self.winfo_height()
        target = Path(os.environ.get("R5_SHOT_PATH", "out/ui-shot.png"))
        target.parent.mkdir(parents=True, exist_ok=True)
        ImageGrab.grab(bbox=(left, top, left + width, top + height), all_screens=True).save(target)
        ImageGrab.grab(all_screens=True).save(target.with_name(target.stem + "-full.png"))
        target.with_suffix(".txt").write_text(f"{left} {top} {width} {height}", encoding="utf-8")
        self.after(300, self.destroy)

    # ---------- 组装界面 ----------

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_header()

        body = ttk.Frame(self)
        body.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 12))
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        left = tk.PanedWindow(
            body,
            orient="vertical",
            bd=0,
            sashwidth=10,
            sashrelief="flat",
            background=self.theme.background,
        )
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        controls = ttk.Frame(left, width=700)
        left.add(controls, minsize=340, stretch="always")
        self._build_controls(controls)
        self._left_panes = left
        self._controls = controls

        results = ttk.Frame(left, width=700)
        left.add(results, minsize=120, stretch="always")
        self._build_results(results)
        self.after(120, self._place_sash)
        self.after(600, self._place_sash)
        self.after(1200, self._place_sash)

        handle = tk.Frame(
            body, width=7, cursor="sb_h_double_arrow", background=self.theme.colors["border"]
        )
        handle.grid(row=0, column=1, sticky="ns")
        handle.bind("<B1-Motion>", self._on_drag)
        self._handle = handle

        body.columnconfigure(2, minsize=self._panel_width)
        panel = ttk.Frame(body, width=self._panel_width)
        panel.grid(row=0, column=2, sticky="ns")
        panel.grid_propagate(False)
        panel.pack_propagate(False)
        self._panel = panel
        self._build_preview(panel)

    def _place_sash(self) -> None:
        """按内容给上半区留高度,免得「相机外观」那排按钮被结果区压掉。"""
        with contextlib.suppress(Exception):
            need = self._controls.winfo_reqheight()
            total = self._left_panes.winfo_height()
            position = min(max(360, need + 12), max(360, total - 118))
            widget = cast("Any", self._left_panes)
            widget.tk.call(widget._w, "sashpos", 0, position)  # noqa: SLF001

    def _save_settings(self) -> None:
        with contextlib.suppress(Exception):
            SETTINGS_PATH.write_text(
                json.dumps(self._settings, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    def _on_drag(self, event: tk.Event[Any]) -> None:
        """拖中间那条缝:左右改预览栏宽度,松手记住。"""
        body = self._handle.master
        total = body.winfo_width()
        right = total - (event.x_root - body.winfo_rootx())
        width = max(MIN_PANEL, min(max(MIN_PANEL, total - MIN_LEFT), right - 8))
        if width != self._panel_width:
            self._panel_width = width
            body.columnconfigure(2, minsize=width)
            self._panel.configure(width=width)
            self._schedule_preview()
            self._settings["panel_width2"] = width
            self._save_settings()

    def _build_header(self) -> None:
        header = ttk.Frame(self, padding=(18, 14, 18, 8))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        logo_image = _load_logo(40)
        if logo_image is None:
            logo: tk.Widget = tk.Canvas(
                header, width=30, height=30, highlightthickness=0, background=self.theme.background
            )
            for x in range(30):
                logo.create_line(  # type: ignore[attr-defined]
                    x, 0, x, 30, fill=_hex(preview.hsv_rgb(x / 29.0, 0.72, 0.98))
                )
        else:
            logo = ttk.Label(header, image=logo_image)
            logo.image = logo_image  # type: ignore[attr-defined]
        logo.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 14))

        title = ttk.Label(header, text="A7M4 滤镜转换器", font=looktheme.FONT_TITLE)
        title.grid(row=0, column=1, sticky="w")
        subtitle = ttk.Label(
            header,
            text="cube 转 json",
            style="Hint.TLabel",
        )
        subtitle.grid(row=1, column=1, sticky="w")

        picker = ttk.Frame(header)
        picker.grid(row=0, column=2, rowspan=2, sticky="e")
        ttk.Label(picker, text="主题", style="Hint.TLabel").pack(side="left", padx=(0, 6))
        self.theme_box = ttk.Combobox(
            picker,
            textvariable=self.theme_var,
            values=looktheme.theme_labels(),
            state="readonly",
            width=16,
            font=looktheme.FONT,
        )
        self.theme_box.pack(side="left")
        self.theme_box.bind("<<ComboboxSelected>>", self._on_theme)

    def _build_controls(self, parent: ttk.Frame) -> None:
        card = self.theme.card(parent, "输入(可多选:文件 / 文件夹 / zip)")
        card.pack(fill="x", pady=(0, 8))

        row = ttk.Frame(card)
        row.pack(fill="x")
        for text, command in (
            ("选择文件", self._pick_files),
            ("选择文件夹", self._pick_folder),
            ("选择 ZIP", self._pick_zip),
            ("清空", self._clear_sources),
        ):
            self.theme.button(row, text, command).pack(side="left", padx=(0, 6))

        holder = ttk.Frame(card)
        holder.pack(fill="x", pady=(8, 0))
        self.source_list = tk.Listbox(
            holder,
            height=1,
            activestyle="none",
            font=looktheme.FONT,
            bd=0,
            highlightthickness=1,
            highlightbackground=self.theme.colors["border"],
            selectmode="extended",
            exportselection=False,
        )
        bar = ttk.Scrollbar(holder, orient="vertical", command=self.source_list.yview)
        self.source_list.configure(yscrollcommand=bar.set)
        self.source_list.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.source_list.bind("<<ListboxSelect>>", self._on_source_select)

        self.source_hint = ttk.Label(card, text="还没有选文件", style="Hint.TLabel")
        self.source_hint.pack(anchor="w", pady=(6, 0))

        settings = self.theme.card(parent, "转换设置")
        settings.pack(fill="x", pady=(0, 8))
        settings.columnconfigure(0, minsize=88)
        settings.columnconfigure(1, weight=1)
        settings.columnconfigure(2, weight=0)

        def label(row: int, text: str) -> None:
            ttk.Label(settings, text=text).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=3)

        label(0, "精度")
        self.accuracy_box = ttk.Combobox(
            settings,
            textvariable=self.accuracy_var,
            values=list(ACCURACY),
            state="readonly",
            width=18,
            font=looktheme.FONT,
        )
        self.accuracy_box.grid(row=0, column=1, columnspan=2, sticky="w", pady=3)
        self.accuracy_box.bind("<<ComboboxSelected>>", self._on_accuracy)
        self.accuracy_note = ttk.Label(
            settings, text=ACCURACY_NOTE[ACCURACY_DEFAULT], style="Hint.TLabel"
        )
        self.accuracy_note.grid(row=1, column=1, columnspan=2, sticky="w", pady=(0, 4))

        label(2, "相机里的名字")
        ttk.Entry(settings, textvariable=self.name_var, font=looktheme.FONT).grid(
            row=2, column=1, columnspan=2, sticky="ew", pady=3
        )

        label(3, "采样数")
        ttk.Entry(settings, textvariable=self.samples_var, width=9, font=looktheme.FONT).grid(
            row=3, column=1, sticky="w", pady=3
        )
        ttk.Label(settings, text="最后修正").grid(
            row=3, column=2, sticky="e", padx=(16, 12), pady=3
        )
        ttk.Entry(settings, textvariable=self.table_var, width=9, font=looktheme.FONT).grid(
            row=3, column=3, sticky="w", pady=3
        )
        settings.columnconfigure(3, weight=0)

        label(4, "保存到")
        out_row = ttk.Frame(settings)
        out_row.grid(row=4, column=1, columnspan=3, sticky="ew", pady=3)
        out_row.columnconfigure(0, weight=1)
        ttk.Entry(out_row, textvariable=self.out_var, font=looktheme.FONT).grid(
            row=0, column=0, sticky="ew"
        )
        self.theme.button(out_row, "浏览…", self._pick_out).grid(row=0, column=1, padx=(6, 0))

        actions = ttk.Frame(parent)
        actions.pack(fill="x", pady=(0, 6))
        self.start_btn = self.theme.button(actions, "开始转换", self._run, kind="primary")
        self.start_btn.pack(side="left", padx=(0, 5))
        self.theme.button(actions, "输出目录", self._open_out).pack(side="left", padx=(0, 5))
        self.theme.button(actions, "导出报告", self._export_report).pack(side="left", padx=(0, 10))
        self.theme.button(actions, "检查成片", self._check_json).pack(side="left", padx=(0, 5))
        self.theme.button(actions, "成片", self._open_lut_dir).pack(side="left")

        self.progress = self.theme.progress(parent, mode="determinate", maximum=100, value=0)
        self.progress.pack(fill="x", pady=(4, 4))
        ttk.Label(parent, textvariable=self.status_var, style="Hint.TLabel").pack(anchor="w")

    def _build_results(self, parent: ttk.Frame) -> None:
        card = self.theme.card(parent, "结果")
        card.pack(fill="both", expand=True)
        card.rowconfigure(0, weight=1)
        card.columnconfigure(0, weight=1)

        columns = (
            ("文件", 165, True),
            ("名字", 145, True),
            ("色差", 56, False),
            ("平均偏差", 72, False),
            ("体积", 66, False),
            ("状态", 52, False),
        )
        with contextlib.suppress(tk.TclError):
            ttk.Style(self).configure("Treeview", rowheight=23)
        self.tree = ttk.Treeview(
            card,
            columns=[key for key, _, _ in columns],
            show="headings",
            height=5,
            style="Treeview",
        )
        for key, width, stretch in columns:
            self.tree.heading(key, text=key)
            self.tree.column(
                key,
                width=width,
                minwidth=width,
                stretch=stretch,
                anchor="w" if key in ("文件", "名字") else "center",
            )
        self.tree.tag_configure("ok", foreground="#2f9e6f")
        self.tree.tag_configure("fail", foreground="#d64545")
        self.tree.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Scrollbar(card, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        bar.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self._on_row_select)
        self.tree.bind("<Double-1>", lambda _event: self._open_out())

    def _build_preview(self, parent: ttk.Frame) -> None:
        card = self.theme.card(parent, " 颜色预览 ")
        card.pack(fill="both", expand=True)
        card.columnconfigure(0, weight=1)
        card.rowconfigure(4, weight=0)
        card.rowconfigure(7, weight=1)

        ttk.Label(card, text="原图").grid(row=0, column=0, sticky="w", pady=(0, 2))
        self.before_canvas = tk.Canvas(card, height=150, background="#ffffff", highlightthickness=0)
        self.before_canvas.grid(row=1, column=0, sticky="nsew")

        self.after_label = ttk.Label(card, text="套用 LUT 后")
        self.after_label.grid(row=2, column=0, sticky="w", pady=(10, 2))
        self.after_canvas = tk.Canvas(card, height=150, background="#ffffff", highlightthickness=0)
        self.after_canvas.grid(row=3, column=0, sticky="nsew")

        self.swatch_canvas = tk.Canvas(
            card, height=SWATCH_HEIGHT, background="#ffffff", highlightthickness=0
        )
        self.swatch_canvas.grid(row=4, column=0, sticky="ew", pady=(8, 0))

        probe = ttk.Frame(card)
        probe.grid(row=5, column=0, sticky="ew", pady=(8, 6))
        self.chip = tk.Canvas(
            probe,
            width=22,
            height=22,
            highlightthickness=1,
            highlightbackground=self.theme.colors["border"],
        )
        self.chip.pack(side="left", padx=(0, 8))
        self.preview_status = ttk.Label(
            probe, text="点图上任意位置看转换结果", style="Hint.TLabel", wraplength=250
        )
        self.preview_status.pack(side="left", fill="x", expand=True)

        self.use_image_box = ttk.Checkbutton(
            card,
            text=_use_image_text(True),
            variable=self.use_image_var,
            command=self._on_use_image,
        )
        self.use_image_box.grid(row=6, column=0, sticky="w", pady=(4, 0))

        spacer = ttk.Frame(card, height=6)
        spacer.grid(row=7, column=0, sticky="nsew")

        buttons = ttk.Frame(card)
        buttons.grid(row=8, column=0, sticky="ew")
        self.theme.button(buttons, "载入图…", self._load_image).pack(side="left", padx=(0, 6))
        self.theme.button(buttons, "保存预览", self._save_preview).pack(side="left", padx=(0, 6))
        self.theme.button(buttons, "刷新", self._refresh_preview).pack(side="left")

        self.swatch_canvas.bind("<Configure>", self._on_swatch_resize)
        self.before_canvas.bind("<Button-1>", self._probe_click)
        self.before_canvas.bind("<Configure>", lambda _event: self._schedule_preview())
        self.after_canvas.bind("<Configure>", lambda _event: self._schedule_preview())
        self.swatch_canvas.bind("<Configure>", lambda _event: self._schedule_preview())

    # ---------- 输入 ----------

    def _add_sources(self, paths: list[Path]) -> None:
        known = {str(item) for item in self._sources}
        added = 0
        for path in paths:
            if path.suffix.lower() != ".cube" or str(path) in known:
                continue
            self._sources.append(path)
            self.source_list.insert("end", str(path))
            known.add(str(path))
            added += 1
        if added:
            self._refresh_source_hint()
            if len(self._sources) == 1:
                self.name_var.set(_safe_name(self._sources[0].stem))
            self._current_cube = self._sources[0]
            self._schedule_preview()

    def _refresh_source_hint(self) -> None:
        count = len(self._sources)
        text = "还没有选文件" if not count else f"已选择 {count} 个来源"
        if count > 1:
            text += "(每个文件各出一份,名字取文件名)"
        self.source_hint.configure(text=text)

    def _pick_files(self) -> None:
        picked = filedialog.askopenfilenames(
            title="选择一个或多个 LUT", filetypes=[("CUBE", "*.cube")]
        )
        self._add_sources([Path(item) for item in picked])

    def _pick_folder(self) -> None:
        folder = filedialog.askdirectory(title="选择放 LUT 的文件夹")
        if folder:
            self._add_sources(sorted(Path(folder).rglob("*.cube")))

    def _pick_zip(self) -> None:
        archive = filedialog.askopenfilename(title="选择 ZIP", filetypes=[("ZIP", "*.zip")])
        if not archive:
            return
        import zipfile

        target = Path(self._tmp_dir()) / Path(archive).stem
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(target)
        self._add_sources(sorted(target.rglob("*.cube")))

    def _tmp_dir(self) -> Path:
        from .paths import resource_root

        base = Path(resource_root()) / "out" / "_unzip"
        base.mkdir(parents=True, exist_ok=True)
        return base

    def _clear_sources(self) -> None:
        self._sources.clear()
        self.source_list.delete(0, "end")
        self._current_cube = None
        self._forget_camera()
        self._refresh_source_hint()
        self._schedule_preview()

    def _pick_out(self) -> None:
        folder = filedialog.askdirectory(title="成片保存到哪个文件夹")
        if folder:
            self.out_var.set(folder)

    def _on_source_select(self, _event: tk.Event[Any]) -> None:
        picked = self.source_list.curselection()  # type: ignore[no-untyped-call]
        if not picked:
            return
        self._current_cube = self._sources[picked[0]]
        self._forget_camera()
        if len(self._sources) == 1:
            self.name_var.set(_safe_name(self._current_cube.stem))
        self._schedule_preview()

    def _on_row_select(self, _event: tk.Event[Any]) -> None:
        picked = self.tree.selection()
        if not picked:
            return
        cube = Path(picked[0])
        if cube.exists():
            self._current_cube = cube
            self._schedule_preview()

    def _on_accuracy(self, _event: tk.Event[Any]) -> None:
        self.accuracy_note.configure(text=ACCURACY_NOTE.get(self.accuracy_var.get(), ""))

    def _on_theme(self, _event: tk.Event[Any]) -> None:
        label = self.theme_var.get()
        self.theme.switch(label)
        self.configure(background=self.theme.background)
        self._schedule_preview()

    # ---------- 转换 ----------

    def _run(self) -> None:
        if self._busy:
            return
        if not self._sources:
            messagebox.showinfo(
                "还没有选文件", "先点「选择文件」挑一个 .cube,或选整个文件夹 / ZIP。"
            )
            return
        out_text = self.out_var.get().strip()
        if not out_text:
            messagebox.showinfo("还没有选保存位置", "点「保存到」右边的「浏览…」选一个文件夹。")
            return
        steps = ACCURACY.get(self.accuracy_var.get(), ACCURACY[ACCURACY_DEFAULT])
        try:
            samples = max(1024, int(self.samples_var.get() or SAMPLES_DEFAULT))
            table_steps = max(0, int(self.table_var.get() or 0))
        except ValueError:
            messagebox.showwarning("数字填错了", "采样数和最后修正要填数字。")
            return

        out = Path(out_text)
        out.mkdir(parents=True, exist_ok=True)
        cubes = list(self._sources)
        names = (
            [self.name_var.get() or _safe_name(cubes[0].stem)]
            if len(cubes) == 1
            else [_safe_name(cube.stem) for cube in cubes]
        )
        self._begin(len(cubes))
        worker = threading.Thread(
            target=self._work,
            args=(cubes, names, out, steps, samples, table_steps),
            daemon=True,
        )
        worker.start()

    def _begin(self, total: int) -> None:
        self._busy = True
        self.start_btn.configure(state="disabled")
        self.progress.configure(maximum=max(1, total), value=0)
        self.status_var.set(f"正在转换 1/{total}…")

    def _work(
        self,
        cubes: list[Path],
        names: list[str],
        out: Path,
        steps: int,
        samples: int,
        table_steps: int,
    ) -> None:
        done = 0
        failures = 0
        assets = Path(os.environ.get("R5_M4_ASSETS", "") or ".")
        for index, cube in enumerate(cubes):
            name = names[index]
            self._queue.put(("status", f"正在转换 {index + 1}/{len(cubes)}:{cube.name}"))
            state: dict[str, Any] = {}
            try:
                info = convert_one(
                    cube,
                    assets,
                    out,
                    name,
                    None,
                    steps,
                    table_steps,
                    self._log,
                    samples=samples,
                    state=state,
                )
                self._queue.put(("row", (cube, name, info, True)))
                self._queue.put(("camera", (cube, state)))
                done += 1
            except BaseException as exc:  # noqa: BLE001 - 单个失败不影响其他
                failures += 1
                reason = f"{type(exc).__name__}: {exc}"
                self._queue.put(("row", (cube, name, {"error": reason}, False)))
            self._queue.put(("progress", (index + 1, len(cubes))))
        self._queue.put(("done", (done, failures)))

    def _log(self, message: str) -> None:
        """工作线程只入队,界面文字由主线程更新。"""
        self._history.append(message)
        self._queue.put(("status", message))

    def _drain(self) -> None:
        while True:
            try:
                kind, payload = self._queue.get_nowait()
            except queue.Empty:
                break
            if kind == "status":
                self.status_var.set(str(payload))
            elif kind == "progress":
                current, total = payload
                self.progress.configure(maximum=max(1, total), value=current)
            elif kind == "row":
                self._add_row(*payload)
            elif kind == "camera":
                self._set_camera(*payload)
            elif kind == "done":
                self._finish(*payload)
            elif kind == "call":
                payload()
        self.after(60, self._drain)

    def _post(self, action: Callable[[], None]) -> None:
        self._queue.put(("call", action))

    def _add_row(self, cube: Path, name: str, info: dict[str, Any], ok: bool) -> None:
        if ok:
            fit = info.get("fit", {})
            values = (
                cube.name,
                name,
                f"{fit.get('de00', 0):.2f}",
                f"{fit.get('mae8', 0):.2f}",
                f"{info.get('bytes', 0) / 1024:.1f} KB",
                "完成",
            )
            tag = "ok"
        else:
            values = (cube.name, name, "-", "-", "-", "失败: " + str(info.get("error", "")))
            tag = "fail"
        if self.tree.exists(str(cube)):
            self.tree.delete(str(cube))
        self.tree.insert("", "end", iid=str(cube), values=values, tags=(tag,))
        self.tree.selection_set(str(cube))
        self.tree.see(str(cube))

    def _finish(self, done: int, failures: int) -> None:
        self._busy = False
        self.start_btn.configure(state="normal")
        total = done + failures
        if failures:
            self.status_var.set(f"完成:成功 {done} 个,失败 {failures} 个")
            last = self._history[-1] if self._history else ""
            if last:
                self.status_var.set(self.status_var.get() + f" · {last}")
        else:
            self.status_var.set(f"完成:共 {total} 个,已写进 {self.out_var.get().strip()}")
        self.progress.configure(value=total)
        self._schedule_preview()

    # ---------- 输出侧按钮 ----------

    def _out_dir(self) -> Path | None:
        text = self.out_var.get().strip()
        return Path(text) if text else None

    def _lut_dir(self) -> Path | None:
        base = self._out_dir()
        return base / "PRIVATE" / "M4ROOT" / "GENERAL" / "LUT" if base else None

    def _open_out(self) -> None:
        base = self._out_dir()
        if base and base.exists():
            looktheme.open_path(str(base))
        else:
            messagebox.showinfo("还没有输出", "先转一个文件,才会有输出目录。")

    def _open_lut_dir(self) -> None:
        folder = self._lut_dir()
        if folder and folder.exists():
            looktheme.open_path(str(folder))
            return
        messagebox.showinfo(
            "拷贝位置",
            "成片会放在:\nPRIVATE\\M4ROOT\\GENERAL\\LUT\\\n把整个 PRIVATE 文件夹拷到 SD 卡根目录。",
        )

    def _check_json(self) -> None:
        folder = self._lut_dir()
        picked = self.tree.selection()
        target: Path | None = None
        if picked:
            cube = Path(picked[0])
            guess = folder / f"{_safe_name(cube.stem)}.json" if folder else None
            if guess and guess.exists():
                target = guess
        if target is None and folder and folder.is_dir():
            files = sorted(folder.glob("*.json"), key=lambda item: item.stat().st_mtime)
            target = files[-1] if files else None
        if target is None:
            messagebox.showinfo("没有可检查的文件", "先转换一次,再点这里看相机能不能读。")
            return
        try:
            from .paths import ensure_path

            ensure_path("vendor", "m4")
            import look_v2  # noqa: PLC0415

            raw = target.read_bytes()
            value = look_v2.parse(raw)
            native = look_v2.compile_native(value)
            lines = [
                f"文件:{target.name}",
                f"体积:{len(raw):,} 字节(上限 131,072)",
                f"名字:{value['name']}",
                f"网格:{value['parameters']['grid']['mode']}",
                f"照片参数:{len(native['photo']):,} 字节",
                f"视频参数:{len(native['live']):,} 字节",
                f"自校验:{value['payload_sha256'][:16]}… 通过",
                "",
                "相机能读:公式自校验与官方编译器都过了。",
            ]
            messagebox.showinfo("检查结果", "\n".join(lines))
            self.status_var.set(f"检查通过:{target.name}")
        except BaseException as exc:  # noqa: BLE001 - 校验失败要如实报
            messagebox.showerror("检查没通过", f"{type(exc).__name__}: {exc}")
            self.status_var.set(f"检查失败:{target.name}")

    def _export_report(self) -> None:
        base = self._out_dir()
        if not base:
            messagebox.showinfo("还没有输出", "先转换一次再导出报告。")
            return
        rows = [self.tree.item(item, "values") for item in self.tree.get_children()]
        if not rows:
            messagebox.showinfo("还没有结果", "先转换一次再导出报告。")
            return
        import csv
        import json

        csv_path = base / "report.csv"
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["文件", "名字", "色差", "平均偏差", "体积", "状态"])
            writer.writerows(rows)
        json_path = base / "report.json"
        payload = [
            dict(zip(["file", "name", "de00", "mae8", "bytes", "state"], list(row), strict=False))
            for row in rows
        ]
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.status_var.set(f"报告已写到 {base}")
        looktheme.open_path(str(base))

    # ---------- 颜色预览 ----------

    def _schedule_preview(self) -> None:
        if self._preview_job is not None:
            with contextlib.suppress(tk.TclError):
                self.after_cancel(self._preview_job)
        self._preview_job = self.after(120, self._redraw_preview)

    def _preview_cube(self) -> preview.Cube | None:
        path = self._current_cube or (self._sources[0] if self._sources else None)
        if path is None or not path.exists():
            return None
        with contextlib.suppress(Exception):
            return preview.load_cube(path)
        return None

    def _forget_camera(self) -> None:
        """换了 LUT 就把上一次的相机渲染结果丢掉,避免张冠李戴。"""
        self._camera = None
        self._camera_cache = None

    def _set_camera(self, cube: Path, state: dict[str, Any]) -> None:
        """转换完成后拿到模型与网格,预览改走相机查表。"""
        model = state.get("model")
        grid = state.get("grid")
        if model is None or grid is None:
            return
        self._camera = (cube, model, grid, state.get("transfer", "display"))
        self._camera_cache = None
        self._schedule_preview()

    def _transfer_of(self, cube: preview.Cube) -> str:
        """这个 LUT 该用哪种输入域(优先用转换时记下的结果)。"""
        if self._camera is not None and self._camera[3]:
            path = self._current_cube or (self._sources[0] if self._sources else None)
            if path is not None and path == self._camera[0]:
                return str(self._camera[3])
        from . import transfer as transfer_mod

        name = ""
        path = self._current_cube or (self._sources[0] if self._sources else None)
        if path is not None:
            name = path.name
        return transfer_mod.detect(cube, name)

    def _camera_state(self) -> tuple[Any, Any, str] | None:
        if self._camera is None:
            return None
        path = self._current_cube or (self._sources[0] if self._sources else None)
        if path is None or path != self._camera[0]:
            return None
        return self._camera[1], self._camera[2], self._camera[3]

    def _camera_raster(self, raster: preview.Raster) -> preview.Raster | None:
        """按相机实际做法(129³ 表 + 三线性)重画整张图。

        只在缩略尺寸上算(CAMERA_MAX_PIXELS),再分块渲染:整张照片直接查表会
        吃掉几个 GB 内存,以前正是这样在批量转换时把预览弄没的。
        """
        state = self._camera_state()
        if state is None:
            return None
        import numpy as np

        from . import m4fit

        model, grid, _transfer = state
        pixels_total = max(1, raster.width * raster.height)
        scale = min(1.0, (CAMERA_MAX_PIXELS / pixels_total) ** 0.5)
        small = raster if scale > 0.999 else _zoom(raster, scale)
        key = f"{id(grid)}:{small.width}x{small.height}"
        if self._camera_cache is not None and self._camera_cache[0] == key:
            cached = self._camera_cache[1]
            return cached if isinstance(cached, preview.Raster) else None
        coords = np.asarray(small.pixels, dtype=np.float64).reshape(-1, 3)
        rendered = np.empty_like(coords)
        try:
            for start in range(0, len(coords), CAMERA_CHUNK):
                block = coords[start : start + CAMERA_CHUNK]
                rendered[start : start + len(block)] = m4fit.camera_render(model, block, grid)
        except BaseException as exc:  # noqa: BLE001 - 预览算不动就退回 LUT 直算
            if not self._camera_failed:
                self._camera_failed = True
                self.preview_status.configure(
                    text=f"相机查表没算动({type(exc).__name__}),先按 LUT 直算显示"
                )
            return None
        self._camera_failed = False
        pixels = bytearray(np.clip(np.rint(rendered), 0, 255).astype(np.uint8).tobytes())
        out = preview.Raster(small.width, small.height, pixels)
        self._camera_cache = (key, out)
        return out

    def _camera_colors(
        self, colours: list[tuple[int, int, int]]
    ) -> list[tuple[int, int, int]] | None:
        """对少量色块按相机查表算输出(色块条与点选读数用)。"""
        state = self._camera_state()
        if state is None:
            return None
        import numpy as np

        from . import m4fit

        model, grid, _transfer = state
        coords = np.asarray(colours, dtype=np.float64)
        rendered = m4fit.camera_render(model, coords, grid)
        clipped = np.clip(np.rint(rendered), 0, 255).astype(int)
        return [(int(row[0]), int(row[1]), int(row[2])) for row in clipped]

    def _redraw_preview(self) -> None:
        self._preview_job = None
        cube = self._preview_cube()
        if cube is None:
            self._placeholder(
                self.before_canvas, "还没有预览", "选一个 LUT 文件,这里显示转换前后的对照"
            )
            self._placeholder(self.after_canvas, "", "")
            self.swatch_canvas.delete("all")
            self.chip.configure(background="#ffffff")
            self.preview_status.configure(text="点图上任意位置看转换结果")
            return
        chart = self._chart()
        painted = self._camera_raster(chart)
        if painted is None:
            painted = preview.apply_cube(cube, chart, self._transfer_of(cube))
            self.after_label.configure(text="套用 LUT 后(LUT 直算)")
        else:
            self.after_label.configure(text="套用 LUT 后(相机实际查表)")
        self._probe = self._paint(self.before_canvas, chart)
        self._paint(self.after_canvas, painted)
        self._paint_swatches(cube)

    def _paint(
        self, canvas: tk.Canvas, raster: preview.Raster
    ) -> tuple[preview.Raster, float, int, int]:
        """铺满画布宽度(该放大就放大),但高度有上限,免得把下面的按钮挤出去。"""
        width = max(1, canvas.winfo_width())
        scale = min(width / max(1, raster.width), PREVIEW_CANVAS_MAX / max(1, raster.height))
        shown = _zoom(raster, scale)
        if abs(canvas.winfo_height() - shown.height) > 1:
            canvas.configure(height=shown.height)
        left = max(0, (width - shown.width) // 2)
        photo = tk.PhotoImage(data=base64.b64encode(preview.encode_png(shown)).decode("ascii"))
        canvas.delete("all")
        canvas.create_image(left, 0, image=photo, anchor="nw")
        canvas.image = photo  # type: ignore[attr-defined]
        return raster, scale, left, 0

    def _paint_swatches(self, cube: preview.Cube) -> None:
        self._swatch_cube = cube
        self.swatch_canvas.delete("all")
        pairs = preview.swatch_pairs(cube, self._transfer_of(cube))
        camera = self._camera_colors([before for before, _ in pairs])
        if camera is not None:
            pairs = [(before, camera[index]) for index, (before, _) in enumerate(pairs)]
        # 跟参考界面一致:高度固定 SWATCH_HEIGHT,横向按面板宽度等分
        width = max(1, self.swatch_canvas.winfo_width())
        count = max(1, len(pairs))
        cell = width / count
        half = SWATCH_HEIGHT / 2
        for index, (before, after) in enumerate(pairs):
            left = int(index * cell)
            right = int((index + 1) * cell) - 1
            self.swatch_canvas.create_rectangle(left, 0, right, half, fill=_hex(before), outline="")
            self.swatch_canvas.create_rectangle(
                left, half, right, SWATCH_HEIGHT, fill=_hex(after), outline=""
            )

    def _on_swatch_resize(self, _event: tk.Event[Any]) -> None:
        """色块尺寸固定,窗口变化只需要重画一次。"""
        cube = self._swatch_cube
        if cube is not None:
            self._paint_swatches(cube)

    def _placeholder(self, canvas: tk.Canvas, title: str, hint: str) -> None:
        canvas.delete("all")
        width = max(canvas.winfo_width(), 200)
        height = max(canvas.winfo_height(), 120)
        if title:
            canvas.create_text(
                width // 2,
                height // 2 - 12,
                text=title,
                font=looktheme.FONT_SECTION,
                fill="#3a3f45",
            )
        if hint:
            canvas.create_text(
                width // 2,
                height // 2 + 16,
                text=hint,
                font=looktheme.FONT,
                fill="#8a919a",
                width=width - 24,
                justify="center",
            )

    def _probe_click(self, event: tk.Event[Any]) -> None:
        cube = self._preview_cube()
        if cube is None or self._probe is None:
            return
        raster, scale, left, top = self._probe
        x = int((event.x - left) / scale) if scale else -1
        y = int((event.y - top) / scale)
        if not (0 <= x < raster.width and 0 <= y < raster.height):
            return
        red, green, blue = raster.get(x, y)
        camera = self._camera_colors([(red, green, blue)])
        if camera is not None:
            result = camera[0]
        else:
            mode = self._transfer_of(cube)
            out_red, out_green, out_blue = preview.sample(
                cube,
                preview.input_value(red / 255.0, mode),
                preview.input_value(green / 255.0, mode),
                preview.input_value(blue / 255.0, mode),
            )
            result = (
                max(0, min(255, round(out_red * 255))),
                max(0, min(255, round(out_green * 255))),
                max(0, min(255, round(out_blue * 255))),
            )
        self.chip.configure(background=_hex(result))
        self.preview_status.configure(
            text=f"输入 ({red},{green},{blue}) → 输出 ({result[0]},{result[1]},{result[2]})"
        )

    def _load_image(self) -> None:
        picked = filedialog.askopenfilename(
            title="选一张图片",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff"), ("所有文件", "*.*")],
        )
        if not picked:
            return
        try:
            raster = _decode_image(Path(picked).read_bytes())
        except BaseException as exc:  # noqa: BLE001 - 解码失败要告知
            messagebox.showerror("这张图读不了", f"{type(exc).__name__}: {exc}")
            return
        if raster.width > IMAGE_MAX_WIDTH:
            raster = _zoom(raster, IMAGE_MAX_WIDTH / raster.width)
        self._source_image = raster
        self.use_image_var.set(True)
        self._camera_cache = None
        self.status_var.set(
            f"预览改用你自己的图:{Path(picked).name}({raster.width}×{raster.height})"
        )
        self._schedule_preview()

    def _save_preview(self) -> None:
        cube = self._preview_cube()
        if cube is None:
            messagebox.showinfo("还没有预览", "先选一个 LUT 文件。")
            return
        target = filedialog.asksaveasfilename(
            title="预览存到哪", defaultextension=".png", filetypes=[("PNG", "*.png")]
        )
        if not target:
            return
        own = self._source_image if self.use_image_var.get() else None
        sheet = preview.compose_sheet(cube, source=own)
        Path(target).write_bytes(preview.encode_png(sheet))
        self.status_var.set(f"预览已保存:{target}")

    def _refresh_preview(self) -> None:
        """卸掉自己载入的图,回到内置色卡。"""
        self._source_image = None
        self.use_image_var.set(True)
        self._camera_cache = None
        self.status_var.set("预览回到内置色卡")
        self._schedule_preview()

    def _on_use_image(self) -> None:
        active = bool(self.use_image_var.get())
        self._camera_cache = None
        self.use_image_box.configure(text=_use_image_text(active))
        if self._source_image is not None:
            self.status_var.set("预览用你载入的图" if active else "预览暂时用内置色卡(图还留着)")
        self._schedule_preview()

    def _chart(self) -> preview.Raster:
        """当前预览该用哪张输入图:自己的图(开关打开时)或内置色卡。"""
        if self.use_image_var.get() and self._source_image is not None:
            return self._source_image
        return preview.test_chart()


def run() -> int:
    """程序入口:双击 exe 走这里。"""
    _enable_dpi_awareness()
    app = App()
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(run())
