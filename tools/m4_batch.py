"""A7M4 批量转换:.cube 目录 → camera-look v2 JSON(卡可直接导入)。

语义(与单张转换一致):
    base   = N00 锚点原生参数下、零网格时的相机输出(正确意义的"中性底")
    target = 目标 .cube 作用在该 base 上
    grid   = 冻结 M4 模型上拟合 405 网格(Adam/STE → 量化 → 整数抛光)
    JSON   = 锚点原生参数 + 拟合网格,官方校验器回读通过后写盘

用法:
    py -3 tools/m4_batch.py --lut-dir "C:\\...\\lut" --out "D:\\out\\m4-batch" ^
        --assets "D:\\ai逆向\\a7r5-ref\\a7m4\\assets\\M4-training-assets"

输出:
    <out>/PRIVATE/M4ROOT/GENERAL/LUT/*.json    可直接拷卡
    <out>/report.json / report.csv             每个 look 的 mae8 / ΔE00 / 耗时
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

import numpy as np

MODEL_MATH_CONTRACT = "4e516ebced9075eba9a4a69a89f410606abb87434077c4ac8986ca0690968e6d"
GRID_WEIGHTS_SHA256 = "5ee40982e75a42ebd5acd201d6a239208d5d00fb28486b1aad026ed3cee6cf2f"


def _sha256(raw: bytes) -> str:
    import hashlib

    return hashlib.sha256(raw).hexdigest()


def _sanitize(name: str, limit: int = 55) -> str:
    """文件名/显示名:去掉路径非法字符,并按 UTF-8 字节截断。"""
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip(" .")
    if not cleaned:
        cleaned = "look"
    raw = cleaned.encode("utf-8")
    if len(raw) > limit:
        cleaned = raw[:limit].decode("utf-8", "ignore").rstrip()
    return cleaned


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A7M4 批量 cube → camera-look v2 JSON")
    parser.add_argument("--lut-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--assets", required=True, type=Path)
    parser.add_argument("--steps", type=int, default=1000)
    parser.add_argument("--samples", type=int, default=8192)
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 个(调试用)")
    parser.add_argument("--resume", action="store_true", help="跳过已存在的 JSON")
    parser.add_argument("--native16", default=None, help="chart_native 输出的 .npy(正确基准)")
    parser.add_argument(
        "--table-steps",
        type=int,
        default=150,
        dest="table_steps",
        help="按相机 129³ 表路径再优化的步数(0 关闭)",
    )
    args = parser.parse_args(argv)

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from r5lut import m4fit, m4json, preview

    cubes = sorted(p for p in args.lut_dir.glob("*.cube"))
    if args.limit:
        cubes = cubes[: args.limit]
    if not cubes:
        raise SystemExit(f"{args.lut_dir} 下没有 .cube")

    lut_out = args.out / "PRIVATE" / "M4ROOT" / "GENERAL" / "LUT"
    lut_out.mkdir(parents=True, exist_ok=True)

    started = time.time()
    front, split, _design = m4fit.load_front(args.assets)
    model = m4fit.Model(args.assets)
    if args.native16:
        base = model.native_base(np.load(args.native16))
        print(f"前段输入: {args.native16}(相机原生链)", flush=True)
    else:
        base = model.render(front, None)
    full_path = m4fit.TablePath(model, base) if args.table_steps else None
    seed = m4json.load_seed(args.assets / "models" / "bridge" / "anchor.json")
    mask = split == "test"

    rows: list[dict[str, object]] = []
    failures: list[dict[str, str]] = []
    for _index, cube_path in enumerate(cubes, 1):
        name = _sanitize(cube_path.stem)
        target_path = lut_out / f"{name}.json"
        if args.resume and target_path.is_file():
            continue
        tick = time.time()
        try:
            cube = preview.load_cube(cube_path)
            target = m4fit.cube_target(base, cube)
            grid, audit = m4fit.fit(
                args.assets,
                target,
                front,
                steps=args.steps,
                samples=args.samples,
                base=base,
                stratified=False,
            )
            if args.table_steps:
                refiner = m4fit.TableFit(model, base, target, samples=8192)
                grid, audit["table_loss"] = refiner.refine(grid, steps=args.table_steps)
            table = [
                [[[int(grid[c, y, u, v]) for v in range(9)] for u in range(9)] for y in range(5)]
                for c in range(3)
            ]
            if full_path is not None:
                pred = np.asarray(full_path.outputs(grid).detach().cpu().numpy())
            else:
                pred = model.render_base(base, grid)
            error = pred - target
            from perceptual import de2000, to_lab

            de = de2000(to_lab(np.clip(pred[mask], 0, 255)), to_lab(np.clip(target[mask], 0, 255)))
            provenance = {
                "generator": "r5lut m4-batch",
                "conversion": "cube -> camera-look v2,405 网格在冻结 M4 模型上拟合",
                "source": {
                    "cube": cube_path.name,
                    "cube_sha256": _sha256(cube_path.read_bytes()),
                    "cube_size": getattr(cube, "size", None),
                    "cube_title": getattr(cube, "title", ""),
                    "target_semantics": "cube 作用在 N00 中性原生输出上",
                },
                "model": {
                    "bridge_schema": "m4-camera-forward/1",
                    "math_contract": MODEL_MATH_CONTRACT,
                    "grid_weights_sha256": GRID_WEIGHTS_SHA256,
                    "native_seed": "models/bridge/anchor.json (N00 基准)",
                    "native16": "chart_native(seed)",
                },
                "fit": {
                    "grid_nonzero": audit["grid_nonzero"],
                    "grid_min": audit["grid_min"],
                    "grid_max": audit["grid_max"],
                    "table_mae8": round(float(np.abs(error[mask]).mean()), 3),
                    "table_de00": round(float(de.mean()), 3),
                    "steps": args.steps,
                    "table_steps": args.table_steps,
                    "chart": "v4.5-100MP-5300K (99372 采样,test 17343)",
                },
                "limits": {
                    "physical_camera_verified": False,
                    "live_branch": "沿用照片网格(与官方 15 个参考 look 相同做法)",
                    "defaults": "继承原生种子,未作为拟合变量",
                    "accuracy_claim": "以上为冻结模型上的实测值,不构成实机颜色保证",
                },
            }
            value = m4json.build(
                seed,
                name=name,
                author="r5lut",
                description=f"{cube_path.stem} · cube→A7M4(M4 冻结模型网格拟合)",
                grid=table,
                live_grid=table,
                provenance=provenance,
            )
            info = m4json.write(target_path, value)

            if full_path is not None:
                pred = np.asarray(full_path.outputs(grid).detach().cpu().numpy())
            else:
                pred = model.render_base(base, grid)
            error = pred - target
            from perceptual import de2000, to_lab

            de = de2000(to_lab(np.clip(pred[mask], 0, 255)), to_lab(np.clip(target[mask], 0, 255)))
            row = {
                "name": name,
                "source": cube_path.name,
                "bytes": info["bytes"],
                "grid_nonzero": audit["grid_nonzero"],
                "grid_min": audit["grid_min"],
                "grid_max": audit["grid_max"],
                "test_mae8": round(float(np.abs(error[mask]).mean()), 3),
                "test_rmse8": round(float(np.sqrt((error[mask] ** 2).mean())), 3),
                "test_de00": round(float(de.mean()), 3),
                "seconds": round(time.time() - tick, 1),
            }
            rows.append(row)
        except Exception as exc:  # noqa: BLE001 - 单个失败不影响整批
            failures.append({"source": cube_path.name, "error": str(exc)})

        (args.out / "report.json").write_text(
            json.dumps(
                {
                    "schema": "r5lut-m4-batch/1",
                    "lut_dir": str(args.lut_dir),
                    "assets": str(args.assets),
                    "total": len(cubes),
                    "done": len(rows),
                    "failed": len(failures),
                    "rows": rows,
                    "failures": failures,
                    "seconds": round(time.time() - started, 1),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    if rows:
        with (args.out / "report.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    sorted(rows, key=lambda r: r["test_de00"])[:5]
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
