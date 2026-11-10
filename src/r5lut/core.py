"""R5 固件滤镜转换:cube / 色卡目标图 → native_config.json + R5NATIVE.BIN。

训练方法来自 Hearts-Ace/sony-a7r5-custom-firmware 的官方训练台
(sony-r5-colorlab,AGPL-3.0,vendored 在 engine/)。
"""

from __future__ import annotations

import contextlib
import functools
import hashlib
import json
import os
import struct
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__version__ = "1.0.0"

MODEL_PRESET = "r5-paired-20261107-nonlinear-he3"
MODEL_SHA256 = "936af0b27f3c5f1ff422c20dd7c1436f92458407d1dd492a4edca2e5ef45e677"
DATASET_ID = "v4.5-sony100mp-5300k-sim-center5-20261029"
CHART_FOLDER = "sony100mp_5300k_v45"
BIN_MAGIC = b"R5CUST4\0"
BIN_BYTES_PER_RECORD = 2580

ProgressFn = Callable[[dict[str, Any]], None]


class R5Error(RuntimeError):
    """管线失败;message 面向用户,detail 保留原始输出。"""

    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.detail = detail


@dataclass
class TrainResult:
    out_dir: Path
    audit: dict[str, Any]
    fit_heldout: dict[str, Any]
    finish: dict[str, Any]
    diagnostics: dict[str, Any] | None = None
    files: dict[str, Path] = field(default_factory=dict)
    early_stop: dict[str, Any] | None = None
    package: dict[str, Any] | None = None


def official_profile() -> dict[str, Any]:
    """官方正式训练 profile(逐字副本;机器可读权威配置)。"""
    from .paths import resource_root

    path = resource_root() / "profiles" / "formal.json"
    if not path.is_file():
        raise R5Error(f"缺少官方 profile:{path}")
    profile = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(profile, dict):
        raise R5Error(f"profile 不是 JSON 对象:{path}")
    return profile


def engine_root() -> Path:
    """训练引擎根目录。frozen 版找 exe 同级 engine/,或 R5_ENGINE_ROOT。"""
    env = os.environ.get("R5_ENGINE_ROOT", "").strip()
    if env:
        root = Path(env)
    elif getattr(sys, "frozen", False):
        bundled = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "engine"
        root = Path(sys.executable).resolve().parent / "engine"
        if not (root / "web" / "core.py").is_file() and (bundled / "web" / "core.py").is_file():
            root = bundled
    else:
        root = Path(__file__).resolve().parent.parent.parent / "engine"
    if not (root / "web" / "core.py").is_file():
        raise R5Error(
            f"训练引擎缺失:{root}\n"
            "源码运行需 engine/ 完整;打包版需把 engine/ 放在 exe 同级,或设 R5_ENGINE_ROOT"
        )
    return root


@functools.lru_cache(maxsize=1)
def _python_cmd() -> list[str]:
    """引擎子进程的 Python:frozen 时按 R5_PYTHON → py -3 → python 实测选一个。"""
    if not getattr(sys, "frozen", False):
        return [sys.executable]
    import shutil as _shutil

    candidates: list[list[str]] = []
    env = os.environ.get("R5_PYTHON", "").strip()
    if env:
        candidates.append([env])
    launcher = _shutil.which("py")
    if launcher:
        candidates.append([launcher, "-3"])
    for name in ("python", "python3"):
        found = _shutil.which(name)
        if found:
            candidates.append([found])
    for command in candidates:
        if _probe_python(command):
            return command
    raise R5Error("需要系统 Python 3(py -3)运行训练引擎;可设 R5_PYTHON 指定")


@functools.lru_cache(maxsize=1)
def _torch_available() -> bool:
    if getattr(sys, "frozen", False):
        try:
            return _probe_python([*_python_cmd(), "-c", "import torch"])
        except R5Error:
            return False
    try:
        import torch  # noqa: F401

        return True
    except ImportError:
        return False


def _probe_python(command: Sequence[str]) -> bool:
    """该命令能否真正启动 Python(WindowsApps 的 python.exe 只是占位 stub)。"""
    try:
        probe = subprocess.run(
            [*command, "-c", "import sys"],
            capture_output=True,
            timeout=30,
            check=False,
            **_spawn_options(),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return probe.returncode == 0


def _decode_json(raw: bytes, encoding: str) -> dict[str, Any] | None:
    """单编码解码;失败返回 None(供多编码回退链使用)。"""
    try:
        value = json.loads(raw.decode(encoding))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _loads_json_bytes(raw: bytes) -> dict[str, Any]:
    """按 utf-8 → gbk → latin-1 回退解析 JSON(Windows 编码兼容层)。"""
    for encoding in ("utf-8", "gbk", "latin-1"):
        value = _decode_json(raw, encoding)
        if value is not None:
            return value
    return {}


def _pump_guard(progress_path: Path, progress: ProgressFn | None, last: dict[str, Any]) -> None:
    """轮询线程的单步包装:任何异常都不得终止训练。"""
    with contextlib.suppress(Exception):  # 进度线程永不拖垮训练
        _pump_once(progress_path, progress, last)


def _pump_once(progress_path: Path, progress: ProgressFn | None, last: dict[str, Any]) -> None:
    """读一次进度文件;有变化才回调。异常由轮询线程统一吞掉。"""
    if progress is None or not progress_path.is_file():
        return
    current = _loads_json_bytes(progress_path.read_bytes())
    if not current or current == last:
        return
    last.clear()
    last.update(current)
    progress(current)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify() -> dict[str, Any]:
    """资产身份与依赖检查;全部通过才训练。"""
    root = engine_root()
    checks: dict[str, Any] = {}

    model = root / "web" / "data" / "r5" / "paired-20261107-nonlinear-he3.json"
    checks["model_present"] = model.is_file()
    if model.is_file():
        observed = _sha256(model)
        checks["model_sha256"] = {
            "passed": observed == MODEL_SHA256,
            "expected": MODEL_SHA256,
            "observed": observed,
        }

    chart = root / "web" / "data" / "chart" / CHART_FOLDER
    manifest_path = chart / "manifest.json"
    checks["chart_manifest_present"] = manifest_path.is_file()
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        pairs = chart / "pairs.npz"
        checks["pairs_present"] = pairs.is_file()
        if pairs.is_file():
            observed = _sha256(pairs)
            expected = manifest.get("pairs_sha256", "")
            checks["pairs_sha256"] = {
                "passed": observed == expected,
                "expected": expected,
                "observed": observed,
            }
        capture_report = chart / "capture" / "report.json"
        checks["capture_report_present"] = capture_report.is_file()
        if capture_report.is_file():
            observed = _sha256(capture_report)
            expected = manifest.get("capture_report_sha256", "")
            checks["capture_report_sha256"] = {
                "passed": observed == expected,
                "expected": expected,
                "observed": observed,
            }
        edit = manifest.get("edit_validation", {})
        runtime_report = chart / edit.get("report_file", "runtime-validation.json")
        checks["runtime_validation_present"] = runtime_report.is_file()
        if runtime_report.is_file():
            observed = _sha256(runtime_report)
            expected = edit.get("report_sha256", "")
            checks["runtime_validation_sha256"] = {
                "passed": observed == expected,
                "expected": expected,
                "observed": observed,
            }

    try:
        import numpy  # noqa: F401
        import scipy  # noqa: F401

        checks["dependencies"] = {"passed": True, "detail": "numpy + scipy 可用"}
    except ImportError as exc:
        checks["dependencies"] = {
            "passed": False,
            "detail": f"缺少依赖:{exc.name};安装 py -3 -m pip install numpy scipy tifffile",
        }
    checks["torch_optional"] = {
        "available": _torch_available(),
        "note": "无 torch 时自动禁用 gamma_global_correction 阶段;GPU 设置 R5_GPU_TRAINING=1",
    }
    checks["fitter_present"] = (root / "web" / "fit_anchor_native.py").is_file()
    checks["runner_present"] = (root / "_r5_runner.py").is_file()
    informational = ("torch_optional",)
    checks["passed"] = all(
        v is True or (isinstance(v, dict) and bool(v.get("passed")))
        for k, v in checks.items()
        if k != "passed" and k not in informational
    )
    return checks


def _spawn_options() -> dict[str, Any]:
    """窗口版 exe 里避免弹出控制台黑窗;源码运行保持原样。"""
    if getattr(sys, "frozen", False) and os.name == "nt":
        return {"creationflags": 0x08000000}  # CREATE_NO_WINDOW
    return {}


def _run_runner(
    stage: str, job: dict[str, Any], out_dir: Path, timeout: float = 3600.0
) -> dict[str, Any]:
    root = engine_root()
    job_path = out_dir / f"_job_{stage}.json"
    job_path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    completed = subprocess.run(
        [*_python_cmd(), str(root / "_r5_runner.py"), stage, str(job_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        **_spawn_options(),
    )
    if completed.returncode != 0:
        raise R5Error(
            f"{stage} 阶段失败(退出码 {completed.returncode})",
            completed.stderr or completed.stdout,
        )
    try:
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        raise R5Error(f"{stage} 输出无法解析", completed.stdout[-2000:]) from None
    if not isinstance(payload, dict):
        raise R5Error(f"{stage} 输出不是 JSON 对象", completed.stdout[-2000:])
    return payload


def prepare_target(
    cube: Path | str, out_dir: Path | str, gamut: str = "S-Gamut3"
) -> dict[str, Any]:
    """把 .cube 目标投影到 99,372 个色卡色块,写 pairs.npz + input_audit.json。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cube_path = Path(cube)
    if not cube_path.is_file():
        raise R5Error(f"找不到目标 cube:{cube_path}")
    return _run_runner("prepare", {"cube": str(cube_path.resolve()), "gamut": gamut}, out)


def prepare_chart_target(image: Path | str, out_dir: Path | str) -> dict[str, Any]:
    """色卡同尺寸 TIFF/JPG(创意外观渲染)转训练目标:ICC→sRGB、中心 5 点均值。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    image_path = Path(image)
    if not image_path.is_file():
        raise R5Error(f"找不到目标图:{image_path}")
    if image_path.suffix.lower() not in (".tif", ".tiff", ".jpg", ".jpeg"):
        raise R5Error("目标图只支持 TIFF 或 JPG,且必须与 v4.5 色卡同尺寸(11648×8736)")
    return _run_runner("prepare-chart", {"image": str(image_path.resolve())}, out)


def _gradient_workers(explicit: int | None = None) -> int:
    value = explicit
    if value is None:
        raw = os.environ.get("R5_GRADIENT_WORKERS", "")
        if raw.strip():
            try:
                value = int(raw)
            except ValueError:
                raise R5Error(f"R5_GRADIENT_WORKERS 必须是整数:{raw}") from None
    value = 8 if value is None else int(value)
    if not 1 <= value <= 64:
        raise R5Error("梯度线程数必须在 1..64")
    return value


def fit(
    out_dir: Path | str,
    *,
    evaluations: int = 120,
    starts: int = 12,
    perceptual_weight: float = 0.35,
    parameter_smoothing: float = 0.0,
    hue_direction_strength: float = 0.0,
    search_options: dict[str, Any] | None = None,
    gradient_workers: int | None = None,
    pc_compensation: bool = False,
    aim: float | None = None,
    progress: ProgressFn | None = None,
    timeout: float = 86400.0,
) -> dict[str, Any]:
    """拟合:连续松弛 + 整数评估,产 fit/recipe.json。返回 heldout 指标。"""
    out = Path(out_dir)
    root = engine_root()
    audit = json.loads((out / "input_audit.json").read_text(encoding="utf-8"))
    capture = root / "web" / "data" / "chart" / CHART_FOLDER / "capture"
    context = int(audit["context"])
    workers = _gradient_workers(gradient_workers)
    extra_search = dict(search_options or {})
    search: dict[str, Any] = {
        "starts": int(starts),
        "adaptive_rounds": 8,
        "perceptual_weight": float(perceptual_weight),
        "quantization_sweeps": 3,
        "parameter_smoothing": float(parameter_smoothing),
        "output_continuity": 0.0,
        "target_neighborhood": 0.0,
        "hue_direction_strength": float(hue_direction_strength),
        "target_polish_rounds": 2,
        "postfit_deburr": True,
        "gamma_monotone_concave": True,
        "gamma_global_correction": True,
        "gamma_color_recovery": True,
        "native_strict_stopping": True,
        "gamma_color_rounds": 3,
        "primary_tonal_weight": 1.0,
        "hue24_tonal_weight": 1.0,
    }
    if extra_search:
        search.update(extra_search)
    if not _torch_available():
        search["gamma_global_correction"] = False
        search["gamma_color_recovery"] = False
    command = [
        *_python_cmd(),
        str(root / "web" / "fit_anchor_native.py"),
        str(out / "pairs.npz"),
        "--capture",
        str(capture),
        "--context",
        str(context),
        "--gamut",
        "0",
        "--output",
        str(out / "fit"),
        "--evaluations",
        str(int(evaluations)),
        "--search-options",
        json.dumps(search),
    ]
    if pc_compensation:
        command.append("--pc-compensation")
    env = dict(os.environ)
    env["R5_GRADIENT_WORKERS"] = str(workers)
    if aim is not None:
        if aim <= 0:
            raise R5Error("aim(mae8 目标)必须大于 0")
        env["R5_STOP_MAE8"] = repr(float(aim))
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )

    progress_path = out / "training_progress.json"
    stopped = threading.Event()

    def _read_progress() -> dict[str, Any]:
        raw = progress_path.read_bytes()
        return _loads_json_bytes(raw)

    def _pump() -> None:
        last: dict[str, Any] = {}
        while not stopped.is_set():
            _pump_guard(progress_path, progress, last)
            stopped.wait(2.0)

    thread = None
    if progress is not None:
        thread = threading.Thread(target=_pump, daemon=True)
        thread.start()
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        raise R5Error("拟合超时已终止", str(out_dir)) from None
    finally:
        stopped.set()
        if thread is not None:
            thread.join(timeout=3)

    if process.returncode != 0:
        raise R5Error(f"拟合失败(退出码 {process.returncode})", (stderr or stdout)[-4000:])
    lines = stdout.strip().splitlines()
    for index in range(len(lines) - 1, -1, -1):
        if lines[index].strip() == "{":
            try:
                payload = json.loads("\n".join(lines[index:]))
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
    try:
        payload = json.loads(stdout.strip())
        if not isinstance(payload, dict):
            raise R5Error("heldout 指标不是 JSON 对象", stdout[-500:])
        return payload
    except json.JSONDecodeError:
        raise R5Error("heldout 指标不是合法 JSON", stdout[-1000:]) from None


def finish(
    out_dir: Path | str,
    number: int,
    short_name: str,
    full_name: str,
    gamma_endpoint: int | None = None,
) -> dict[str, Any]:
    """量化成固件 JSON + BIN;写 native_config.json / R5NATIVE.BIN。"""
    out = Path(out_dir)
    job = {"number": int(number), "short_name": short_name, "full_name": full_name}
    if gamma_endpoint is not None:
        job["gamma_endpoint"] = int(gamma_endpoint)
    return _run_runner("finish", job, out)


def generate_pc(out_dir: Path | str) -> dict[str, Any]:
    """PC 残差补偿(明暗曲线 + 灰阶染色 + 色网格)。"""
    return _run_runner("pc", {}, Path(out_dir))


def distill_grid(out_dir: Path | str, *, objective: str = "fuji-target") -> dict[str, Any]:
    """405 网格求解 + 压缩;写 v4-config.zip。

    objective 取官方 profile 的 compression_objective:
    - fuji-target:直接对目标色卡拟合(官方正式值)
    - pc-teacher:对 PC 变换蒸馏(历史行为)
    """
    return _run_runner("grid", {"objective": objective}, Path(out_dir))


def diagnostics(
    out_dir: Path | str,
    *,
    pc: bool = False,
    grid_key: str | None = None,
    include_preview: bool = False,
) -> dict[str, Any]:
    """独立 test 集指标;完整结果落盘 out/diagnostics.json。"""
    out = Path(out_dir)
    job: dict[str, Any] = {"pc": bool(pc), "include_preview": bool(include_preview)}
    if grid_key:
        job["grid_key"] = grid_key
    result = _run_runner("diagnostics", job, out)
    result["full_report"] = str(out / "diagnostics.json")
    return result


def compile_config(config_path: Path | str, out_bin: Path | str) -> dict[str, Any]:
    """r5-custom-filter-config/4 JSON → R5NATIVE.BIN。"""
    out = Path(out_bin)
    out.parent.mkdir(parents=True, exist_ok=True)
    job = {"config": str(Path(config_path).resolve()), "output": str(out.resolve())}
    return _run_runner("compile", job, out.parent)


def package_set(out_dir: Path | str, base_set: Path | str | None = None) -> dict[str, Any]:
    """把单槽结果注入「12 槽整套」并重建 v4-config.zip。

    固件按整套导入(BIN 头 count=12, mask=0xfff);单槽文件相机不认。
    基座默认取 samples/base-12slot.bin(官方 12 滤镜整套),只替换目标槽位。
    """
    out = Path(out_dir)
    entry_bin = out / "R5NATIVE.BIN"
    if not entry_bin.is_file():
        raise R5Error(f"缺少单槽 BIN:{entry_bin}")
    payload = entry_bin.read_bytes()
    if len(payload) < 128:
        raise R5Error(f"单槽 BIN 太小:{len(payload)} 字节")
    # 头布局: magic(8) version(4) header_len(4) total(4) count(4) mask(4) ...
    count = struct.unpack_from("<I", payload, 20)[0]
    if count != 1:
        raise R5Error(
            f"package_set 需要单槽 BIN(当前 count={count});"
            "整套 BIN 不能再当输入,请用 finish 重新导出单槽"
        )
    default_base = Path(__file__).resolve().parents[2] / "samples" / "base-12slot.bin"
    config_path = out / "native_config.json"
    if config_path.is_file():
        config = json.loads(config_path.read_text(encoding="utf-8"))
        for item in config.get("entries", []):
            grid = item.get("grid_5x9x9", {}).get("coefficients", [])
            values = [v for channel in grid for row in channel for line in row for v in line]
            if values and not any(values):
                raise R5Error("该条目的网格全为零(疑似网格阶段未回写);拒绝打包整套,请重跑网格阶段")
    base = Path(base_set) if base_set else default_base
    if not base.is_file():
        raise R5Error(
            f"缺少整套基座:{base}\n"
            "整套导入需要 12 槽基座(官方 R5NATIVE.BIN);"
            "用 --base-set 指定,或在 samples/ 放 base-12slot.bin"
        )
    job = {
        "single": str(entry_bin.resolve()),
        "base": str(base.resolve()),
        "output": str((out / "R5NATIVE.SET.BIN").resolve()),
    }
    return _run_runner("package-set", job, out)


def inspect_bin(bin_path: Path | str) -> dict[str, Any]:
    """解码 R5NATIVE.BIN 回 JSON 结构。"""
    out = Path(bin_path).resolve().parent
    job = {"bin": str(Path(bin_path).resolve())}
    result = _run_runner("inspect-bin", job, out)
    result["full_report"] = str(out / "bin_unpacked.json")
    return result


def quick_budget() -> dict[str, Any]:
    """草稿预算:快速拟合(不带 PC/网格,产物是合法 BIN)。"""
    return {
        "evaluations": 1,
        "starts": 2,
        "perceptual_weight": 0.35,
        "parameter_smoothing": 30.0,
        "hue_direction_strength": 0.0,
    }


def balanced_budget() -> dict[str, Any]:
    """平衡档:40 评估 / 6 起点,配合 --aim 早停,通常 10-20 分钟收敛。"""
    return {
        "evaluations": 40,
        "starts": 6,
        "perceptual_weight": 0.35,
        "parameter_smoothing": 0.0,
        "hue_direction_strength": 30.0,
    }


def formal_budget() -> dict[str, Any]:
    """正式预算:逐项取自官方 profile(options / search_options)。"""
    profile = official_profile()
    options = profile.get("options", {})
    search = dict(options.get("search_options", {}))
    return {
        "evaluations": int(options.get("evaluations", 2000)),
        "starts": int(search.get("starts", 12)),
        "perceptual_weight": float(search.get("perceptual_weight", 0.35)),
        "parameter_smoothing": float(search.get("parameter_smoothing", 0.0)),
        "hue_direction_strength": float(search.get("hue_direction_strength", 0.0)),
        "search_options": search,
        "gamma_endpoint128": int(options.get("gamma_endpoint128", 131071)),
        "grid_objective": str(options.get("compression_objective", "fuji-target")),
        "pc_compensation": bool(options.get("pc_compensation", True)),
        "white_balance": bool(options.get("white_balance", False)),
    }


def train(
    cube: Path | str | None = None,
    out_dir: Path | str | None = None,
    number: int = 1,
    short_name: str = "",
    full_name: str = "",
    *,
    gamut: str = "S-Gamut3",
    target_image: Path | str | None = None,
    budget: dict[str, Any] | None = None,
    gradient_workers: int | None = None,
    aim: float | None = None,
    pc: bool = False,
    grid: bool = False,
    with_diagnostics: bool = True,
    base_set: Path | str | None = None,
    gamma_endpoint: int = 131071,
    grid_objective: str = "fuji-target",
    progress: ProgressFn | None = None,
) -> TrainResult:
    """端到端:prepare → fit → finish → 编译 BIN → (pc → grid) → diagnostics。

    目标二选一:cube(S-Log3 域创意外观变换)或 target_image(色卡同尺寸 TIFF/JPG)。
    """
    if cube is None and target_image is None:
        raise R5Error("必须给 cube 或 target_image 其中之一")
    if cube is not None and target_image is not None:
        raise R5Error("cube 与 target_image 只能二选一")
    if out_dir is None:
        raise R5Error("必须给 out_dir(输出目录)")
    out = Path(out_dir)
    if (out / "input_audit.json").is_file():
        raise R5Error(f"输出目录已有训练任务,拒绝覆盖:{out}")
    options = dict(formal_budget())
    if budget:
        options.update(budget)

    checks = verify()
    if not checks["passed"]:
        raise R5Error("资产身份检查未通过,拒绝训练:" + json.dumps(checks, ensure_ascii=False))

    def notify(stage: str) -> None:
        if progress:
            progress({"stage": stage, "message": f"{stage} 进行中", "time": time.time()})

    notify("prepare")
    if target_image is not None:
        audit = prepare_chart_target(target_image, out)
    else:
        assert cube is not None  # 由上面的二选一校验保证
        audit = prepare_target(cube, out, gamut=gamut)

    notify("fit")
    heldout = fit(
        out,
        pc_compensation=bool(pc),
        gradient_workers=gradient_workers,
        search_options=options.get("search_options"),
        aim=aim,
        progress=progress,
        **{
            k: options[k]
            for k in (
                "evaluations",
                "starts",
                "perceptual_weight",
                "parameter_smoothing",
                "hue_direction_strength",
            )
        },
    )

    notify("finish")
    finished = finish(out, number, short_name, full_name, gamma_endpoint)
    compiled = compile_config(out / "native_config.json", out / "R5NATIVE.BIN")
    if (
        compiled["sha256"] != finished["binary_sha256"]
        or compiled["bytes"] != finished["binary_bytes"]
    ):
        raise R5Error("编译出的 BIN 与 finish 记录不一致,拒绝交付")

    grid_key = None
    if pc:
        notify("pc")
        generate_pc(out)
    if grid:
        notify("grid")
        report = distill_grid(out, objective=grid_objective)
        grid_key = report.get("key")

    early_stop = None
    try:
        recipe = json.loads((out / "fit" / "recipe.json").read_text(encoding="utf-8"))
        early_stop = recipe.get("fitting", {}).get("early_stop")
    except (OSError, json.JSONDecodeError):
        pass
    result = TrainResult(
        out_dir=out, audit=audit, fit_heldout=heldout, finish=finished, early_stop=early_stop
    )
    result.files = {
        "json": out / "native_config.json",
        "bin": out / "R5NATIVE.BIN",
        "audit": out / "conversion_audit.json",
    }
    if grid and (out / "v4-config.zip").is_file():
        result.files["zip"] = out / "v4-config.zip"
    if with_diagnostics:
        notify("diagnostics")
        result.diagnostics = diagnostics(out, pc=bool(pc), grid_key=grid_key)

    # 固件按整套导入(12 槽);单槽文件相机不认,这里默认注入整套基座。
    base = (
        Path(base_set)
        if base_set
        else (Path(__file__).resolve().parents[2] / "samples" / "base-12slot.bin")
    )
    if grid and base.is_file():
        notify("package-set")
        packaged = package_set(out, base)
        result.files["package"] = Path(packaged["package"])
        result.files["set_bin"] = out / "R5NATIVE.SET.BIN"
        result.package = packaged

    notify("done")
    return result
