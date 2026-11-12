"""R5 固件滤镜转换 CLI。

    r5lut verify                          资产身份检查
    r5lut convert --target X.cube ...     转换(默认正式档 + PC + 网格)
    r5lut inspect BIN                     解码 BIN 回 JSON
    r5lut compile config.json -o BIN      编译 JSON → BIN
    r5lut status OUT_DIR                  查看训练进度与产物
    r5lut batch list.json -o OUT_ROOT     批量转换

退出码:0 成功,1 用法错误,2 运行失败。
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from pathlib import Path
from typing import Any, cast

from . import __version__, core, transfer


def _utf8() -> None:
    """控制台统一 UTF-8;非 TextIOWrapper 对象安静跳过。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = cast("Any", getattr(stream, "reconfigure", None))
        if reconfigure is None:
            continue
        with contextlib.suppress(Exception):
            reconfigure(encoding="utf-8", errors="replace")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="r5lut",
        description="R5 创意外观转换:cube/TIFF → 固件滤镜 JSON/BIN",
    )
    parser.add_argument("--version", action="version", version=f"r5lut {__version__}")
    subs = parser.add_subparsers(dest="command", required=True)

    subs.add_parser("verify", help="检查资产身份(模型/色卡/基线)与依赖").add_argument(
        "--json", action="store_true"
    )

    subs.add_parser("gui", help="打开图形界面")
    subs.add_parser("dpi", help="打印 DPI 感知状态(诊断用)")

    batch4 = subs.add_parser(
        "m4-batch", help="A7M4 批量:cube 目录 → camera-look v2 JSON(整包进 SD 目录)"
    )
    batch4.add_argument("--lut-dir", required=True, help=".cube 所在目录")
    batch4.add_argument("--assets", default="", help="M4-training-assets 目录(留空用内置)")
    batch4.add_argument("-o", "--out", required=True, help="输出根目录")
    batch4.add_argument("--steps", type=int, default=1000)
    batch4.add_argument("--samples", type=int, default=8192)
    batch4.add_argument("--limit", type=int, default=0)
    batch4.add_argument("--resume", action="store_true", help="跳过已存在的 JSON")
    batch4.add_argument("--table-steps", type=int, default=150, dest="table_steps")
    batch4.add_argument(
        "--layout",
        default="camera",
        choices=["camera", "mirror"],
        help="camera=PRIVATE\\M4ROOT\\GENERAL\\LUT;mirror=跟来源目录一样",
    )

    m4 = subs.add_parser("m4", help="A7M4:cube → camera-look v2 JSON(冻结 M4 模型上拟合 405 网格)")
    m4.add_argument("--cube", required=True, help="目标 .cube")
    m4.add_argument("--assets", default="", help="M4-training-assets 目录(留空用内置)")
    m4.add_argument(
        "--seed", default=None, help="原生参数种子 JSON(默认 models/bridge/anchor.json)"
    )
    m4.add_argument("--name", required=True, help="滤镜名(≤63 UTF-8 字节)")
    m4.add_argument("--author", default="r5lut")
    m4.add_argument("--description", default="")
    m4.add_argument("-o", "--out", required=True, help="输出目录")
    m4.add_argument("--steps", type=int, default=1000)
    m4.add_argument("--samples", type=int, default=8192)
    m4.add_argument("--native16", default=None, help="chart_native 输出的 .npy(相机原生链,推荐)")
    m4.add_argument(
        "--layout",
        default="camera",
        choices=["camera", "mirror"],
        help="camera=PRIVATE\\M4ROOT\\GENERAL\\LUT;mirror=直接放在 -o 目录",
    )
    m4.add_argument(
        "--transfer",
        default="auto",
        choices=["auto", "display", *transfer.formats()],
        help="LUT 输入域:auto 自动识别(默认),display 显示域,其余为各家 log 曲线",
    )
    m4.add_argument(
        "--table-steps",
        type=int,
        default=150,
        dest="table_steps",
        help="按相机 129³ 表路径再优化的步数",
    )

    convert = subs.add_parser(
        "convert", help="转换:cube/TIFF → native_config.json + R5NATIVE.BIN(默认正式档,含 PC+网格)"
    )
    convert.add_argument("--target", default=None, help="目标 .cube(S-Log3 域)")
    convert.add_argument(
        "--target-image", default=None, help="目标图 TIFF/JPG(色卡同尺寸 11648×8736)"
    )
    convert.add_argument("--number", type=int, required=True, help="滤镜槽位 1..12")
    convert.add_argument("--name", required=True, help="菜单简称(≤23 UTF-8 字节)")
    convert.add_argument("--full-name", required=True, help="全称(≤63 UTF-8 字节)")
    convert.add_argument("--gamut", default="S-Gamut3", choices=["S-Gamut3", "S-Gamut3.Cine"])
    convert.add_argument("-o", "--out", required=True)
    convert.add_argument("--quick", action="store_true", help="草稿档:快速拟合,不带 PC/网格")
    convert.add_argument(
        "--budget",
        choices=["quick", "balanced", "formal"],
        default="formal",
        help="预算档:quick 草稿 / balanced 平衡(40 评估) / formal 官方正式(2000 评估)",
    )
    convert.add_argument(
        "--aim", type=float, default=None, help="目标质量:验证集 mae8 ≤ AIM 即提前停止(例如 8)"
    )
    convert.add_argument(
        "--grid-objective",
        choices=["fuji-target", "pc-teacher"],
        default="fuji-target",
        help="目标网格求解方式;官方正式值为 fuji-target(直接对目标拟合)",
    )
    convert.add_argument("--gradient-workers", type=int, default=None)

    train = subs.add_parser("train", help="分步参数版训练(预算/PC/网格可单独控制)")
    train.add_argument("--target", default=None)
    train.add_argument("--target-image", default=None)
    train.add_argument("--number", type=int, required=True)
    train.add_argument("--name", required=True)
    train.add_argument("--full-name", required=True)
    train.add_argument("--gamut", default="S-Gamut3", choices=["S-Gamut3", "S-Gamut3.Cine"])
    train.add_argument("-o", "--out", required=True)
    train.add_argument("--quick", action="store_true")
    train.add_argument("--evaluations", type=int, default=None)
    train.add_argument("--starts", type=int, default=None)
    train.add_argument("--pc", action="store_true", help="启用 PC 残差补偿")
    train.add_argument("--grid", action="store_true", help="网格蒸馏并输出 v4-config.zip")
    train.add_argument(
        "--aim", type=float, default=None, help="目标质量:验证集 mae8 ≤ AIM 即提前停止"
    )
    train.add_argument("--no-diagnostics", action="store_true")
    train.add_argument("--gradient-workers", type=int, default=None)

    inspect = subs.add_parser("inspect", help="解码 R5NATIVE.BIN 回 JSON 结构")
    inspect.add_argument("bin")

    compile_p = subs.add_parser("compile", help="r5-custom-filter-config/4 JSON → R5NATIVE.BIN")
    compile_p.add_argument("config")
    compile_p.add_argument("-o", "--out", required=True)

    status = subs.add_parser("status", help="查看输出目录的训练进度与产物")
    status.add_argument("out_dir")

    batch = subs.add_parser("batch", help="批量转换(列表 JSON,串行,可断点续跑)")
    batch.add_argument("list", help="列表 JSON")
    batch.add_argument("-o", "--out", required=True, help="输出根目录")
    batch.add_argument("--quick", action="store_true")
    batch.add_argument("--workers", type=int, default=1)
    return parser


def main(argv: list[str] | None = None) -> int:
    _utf8()
    args = build_parser().parse_args(argv)

    if args.command == "gui":
        from .gui import run

        return run()

    if args.command == "m4-batch":
        from . import m4fit, m4gui

        cubes = sorted(Path(args.lut_dir).rglob("*.cube"))
        if args.limit:
            cubes = cubes[: args.limit]
        if not cubes:
            raise SystemExit(f"{args.lut_dir} 下没有 .cube")
        batch_assets = m4fit.resolve_assets(Path(args.assets) if args.assets else Path())
        out_root = Path(args.out)
        out_root.mkdir(parents=True, exist_ok=True)
        batch_native = getattr(args, "native16", None)
        print(f"资产: {batch_assets} | 待转换 {len(cubes)} 个")
        rows = []
        layout = str(getattr(args, "layout", "camera"))
        for index, cube in enumerate(cubes, 1):
            if layout == "mirror":
                try:
                    batch_out = out_root / cube.parent.relative_to(Path(args.lut_dir))
                except ValueError:
                    batch_out = out_root
            else:
                batch_out = out_root / f"{index:02d}"
            try:
                info = m4gui.convert_one(
                    cube,
                    batch_assets,
                    batch_out,
                    cube.stem[:40],
                    batch_native,
                    args.steps,
                    args.table_steps,
                    print,
                    layout=layout,
                )
                rows.append(
                    {
                        "name": info["name"],
                        "bytes": info["bytes"],
                        "de00": round(info["fit"]["de00"], 3),
                        "mae8": round(info["fit"]["mae8"], 3),
                    }
                )
                print(f"[{index}/{len(cubes)}] {cube.name} → ΔE00 {info['fit']['de00']:.2f}")
            except BaseException as exc:  # noqa: BLE001 - 单张失败继续
                print(f"[{index}/{len(cubes)}] 跳过 {cube.name}: {exc}")
        (out_root / "report.json").write_text(
            json.dumps({"rows": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"完成 {len(rows)}/{len(cubes)} | 输出 {out_root}")
        return 0

    if args.command == "dpi":
        import ctypes
        import tkinter as tk

        from .m4gui import _enable_dpi_awareness

        _enable_dpi_awareness()
        root = tk.Tk()
        root.withdraw()
        aware: Any = None
        try:
            ctx = ctypes.windll.user32.GetThreadDpiAwarenessContext()
            aware = int(ctypes.windll.user32.GetAwarenessFromDpiAwarenessContext(ctx))
        except Exception as exc:  # noqa: BLE001
            aware = f"不可用:{exc}"
        root.destroy()
        from .m4gui import App

        app = App()
        app.update()
        app.update_idletasks()
        print(
            json.dumps(
                {
                    "awareness": aware,
                    "fpixels_per_inch": round(app.winfo_fpixels("1i"), 2),
                    "screen": [app.winfo_screenwidth(), app.winfo_screenheight()],
                    "frozen": bool(getattr(sys, "frozen", False)),
                    "window": [app.winfo_width(), app.winfo_height()],
                    "position": [app.winfo_rootx(), app.winfo_rooty()],
                    "preview_panel": app._panel.winfo_width(),  # noqa: SLF001 - 自检用
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        app.destroy()
        return 0

    if args.command == "m4":
        from . import m4gui

        assets = Path(args.assets) if args.assets else Path()
        out = Path(args.out)
        info = m4gui.convert_one(
            Path(args.cube),
            assets,
            out,
            args.name,
            args.native16,
            args.steps,
            args.table_steps,
            lambda message: print(message, file=sys.stderr),
            samples=args.samples,
            input_transfer=args.transfer,
            layout=args.layout,
        )
        print(
            json.dumps(
                {
                    "json": info,
                    "sd_path": info.get("sd_path"),
                    "fit": info.get("fit"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "verify":
        try:
            checks = core.verify()
        except core.R5Error as exc:
            print(f"失败:{exc}", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(checks, ensure_ascii=False))
        else:
            for key, value in checks.items():
                if key == "passed":
                    continue
                if value is True or (isinstance(value, dict) and value.get("passed")):
                    print(f"OK   {key}")
                elif isinstance(value, dict) and "available" in value:
                    print(f"INFO {key}  可用={value['available']} {value.get('note', '')}")
                else:
                    print(f"FAIL {key}  {value}")
            print("全部通过" if checks["passed"] else "未通过,拒绝训练", file=sys.stderr)
        return 0 if checks["passed"] else 2

    if args.command in ("convert", "train"):
        if bool(args.target) == bool(args.target_image):
            print("错误:--target 与 --target-image 必须二选一", file=sys.stderr)
            return 1
        if args.command == "convert":
            if args.quick:
                budget = core.quick_budget()
                pc = grid = False
            else:
                budget = {
                    "quick": core.quick_budget(),
                    "balanced": core.balanced_budget(),
                    "formal": core.formal_budget(),
                }[args.budget]
                pc = grid = True
            no_diagnostics = False
        else:
            budget = core.quick_budget() if args.quick else core.formal_budget()
            for key in ("evaluations", "starts"):
                value = getattr(args, key)
                if value is not None:
                    budget[key] = value
            pc, grid = args.pc, args.grid
            no_diagnostics = args.no_diagnostics
        try:
            result = core.train(
                args.target,
                args.out,
                args.number,
                args.name,
                args.full_name,
                gamut=args.gamut,
                target_image=args.target_image,
                budget=budget,
                gradient_workers=args.gradient_workers,
                aim=args.aim,
                pc=pc,
                grid=grid,
                grid_objective=args.grid_objective,
                with_diagnostics=not no_diagnostics,
            )
        except core.R5Error as exc:
            print(f"失败:{exc}", file=sys.stderr)
            if exc.detail:
                print(exc.detail, file=sys.stderr)
            return 2
        print(
            json.dumps(
                {
                    "out_dir": str(result.out_dir),
                    "firmware_json": str(result.files["json"]),
                    "firmware_bin": str(result.files["bin"]),
                    "package_zip": str(result.files.get("zip", "")),
                    "heldout_mae8": result.fit_heldout.get("after", {}).get("mae_8bit"),
                    "binary_bytes": result.finish["binary_bytes"],
                    "binary_sha256": result.finish["binary_sha256"],
                    "early_stop": result.early_stop,
                    "set_bin": str(result.files.get("set_bin", "")),
                    "set_bytes": (result.package or {}).get("bytes"),
                    "set_slots": (result.package or {}).get("entries"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        if result.diagnostics:
            final = result.diagnostics.get("final_tonal", {}).get("all")
            if final:
                print(
                    json.dumps(
                        {
                            "final_mae8": final.get("mae"),
                            "final_dE00": final.get("perceptual", {}).get("delta_e00_mean"),
                        },
                        ensure_ascii=False,
                    )
                )
        return 0

    if args.command == "inspect":
        try:
            decoded = core.inspect_bin(args.bin)
        except core.R5Error as exc:
            print(f"失败:{exc}", file=sys.stderr)
            if exc.detail:
                print(exc.detail, file=sys.stderr)
            return 2
        print(json.dumps(decoded, ensure_ascii=False, indent=2))
        return 0

    if args.command == "compile":
        try:
            packed = core.compile_config(args.config, args.out)
        except core.R5Error as exc:
            print(f"失败:{exc}", file=sys.stderr)
            if exc.detail:
                print(exc.detail, file=sys.stderr)
            return 2
        print(json.dumps(packed, ensure_ascii=False, indent=2))
        return 0

    if args.command == "status":
        return _status(Path(args.out_dir))

    if args.command == "batch":
        return _batch(args)

    return 1


def _status(job: Path) -> int:
    if not job.is_dir():
        print(f"目录不存在: {job}", file=sys.stderr)
        return 1
    print(f"任务: {job}")
    progress = job / "training_progress.json"
    if progress.is_file():
        raw = progress.read_bytes()
        data = {}
        for encoding in ("utf-8", "gbk", "latin-1"):
            try:
                data = json.loads(raw.decode(encoding))
                break
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
        if data:
            print(f"阶段: {data.get('stage', '?')}")
            print(
                f"轮次: {data.get('round', '?')}/{data.get('total_rounds', '?')} "
                f"state={data.get('state', '?')}"
            )
            print(f"更新: {time.strftime('%H:%M:%S', time.localtime(progress.stat().st_mtime))}")
    markers = [
        ("fit/recipe.json", "拟合完成"),
        ("native_config.json", "JSON 已导出"),
        ("R5NATIVE.BIN", "BIN 已编译"),
        ("pc_compensation.json", "PC 完成"),
        ("v4-config.zip", "网格蒸馏完成"),
        ("diagnostics.json", "诊断完成"),
    ]
    print("产物:")
    for rel, label in markers:
        path = job / rel
        mark = "✓" if path.is_file() else "·"
        size = f"{path.stat().st_size:,}B" if path.is_file() else "-"
        print(f"  {mark} {label}: {rel} ({size})")
    return 0


def _batch(args: argparse.Namespace) -> int:
    entries = json.loads(Path(args.list).read_text(encoding="utf-8-sig"))
    root = Path(args.out)
    root.mkdir(parents=True, exist_ok=True)
    results = []
    for entry in entries:
        name = f"{entry['number']:02d}-{entry['short']}"
        job = root / name
        if (job / "R5NATIVE.BIN").is_file():
            results.append({"name": name, "skipped": True})
            print(f"[skip] {name}", flush=True)
            continue
        if job.is_dir():
            import shutil

            shutil.rmtree(job, ignore_errors=True)
        print(f"[convert] {name} <- {entry['target']}", flush=True)
        budget = core.quick_budget() if args.quick else core.formal_budget()
        try:
            result = core.train(
                entry["target"],
                job,
                int(entry["number"]),
                entry["short"],
                entry["full"],
                budget=budget,
                pc=not args.quick,
                grid=not args.quick,
            )
            results.append(
                {"name": name, "ok": True, "binary_bytes": result.finish["binary_bytes"]}
            )
            print(f"[ok] {name}", flush=True)
        except core.R5Error as exc:
            results.append({"name": name, "ok": False, "error": str(exc)})
            print(f"[fail] {name}: {exc}", flush=True)
        (root / "batch_report.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
