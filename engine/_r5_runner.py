"""R5 训练引擎的子进程入口（CubeLUT Studio 公共缝的调用端）。

用法: python _r5_runner.py <stage> <job.json> [--out-dir DIR]

每个 stage 读 job 参数、跑 vendored colorlab 引擎、把精简结果以 UTF-8 JSON
写到 stdout；大数据（preview、完整诊断）落盘到 out-dir 下固定文件名。
退出码: 0 成功, 1 用法错误, 2 运行失败。

这是本仓库自己加的薄层；引擎本体保持 AGPL-3.0 原样。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT), str(ROOT / "web"), str(ROOT / "scripts")]

# Windows 控制台是 GBK；强制 stdout/stderr 用 UTF-8，避免 JSON 里的中文损坏。
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _trim_finish(result: dict) -> dict:
    return {
        "binary_bytes": result["binary_bytes"],
        "binary_sha256": result["binary_sha256"],
        "white_balance": result.get("white_balance"),
        "heldout": result.get("heldout"),
        "config_schema": result["config"]["schema"],
        "config_entries": len(result["config"]["entries"]),
    }


def _trim_grid_report(report: dict) -> dict:
    keys = ("key", "algorithm", "grid_sha256", "bytes", "report")
    return {k: report[k] for k in keys if k in report}


def run(stage: str, job: dict, out_dir: Path) -> dict:
    if stage == "prepare":
        import core
        import shutil
        core.prepare_target(Path(job["cube"]), job["gamut"], out_dir)
        # vendored 的 pc/grid 阶段要求目标 cube 留在任务目录(input.cube),
        # 且哈希与 input_audit.lut_sha256 一致。
        shutil.copyfile(Path(job["cube"]), out_dir / "input.cube")
        return json.loads((out_dir / "input_audit.json").read_text(encoding="utf-8"))

    if stage == "prepare-chart":
        import chart_target
        # 目标图(色卡同尺寸 TIFF/JPG)路径:decode → ICC 浮点转 sRGB →
        # 色块中心横向 5 点均值 → 0_target;与官方 chart-image 目标一致。
        chart_target.prepare(
            Path(job["image"]).read_bytes(), out_dir, source_path=Path(job["image"])
        )
        return json.loads((out_dir / "input_audit.json").read_text(encoding="utf-8"))

    if stage == "fit":
        raise ValueError("fit 由 r5.py 直接调用 fit_anchor_native.py,不走 runner")

    if stage == "finish":
        import core
        # 幂等端点保护:如果拟合的 Gamma 末端超过原生 ST 端点,官方 from_fit
        # 会因单调性报错;这里取 max(原生端点, 拟合末端对应值) 作为第 129 点。
        endpoint = job.get("gamma_endpoint") or 131071
        if endpoint is None:
            try:
                recipe = json.loads((out_dir / "fit" / "recipe.json").read_text(
                    encoding="utf-8", errors="replace"))
                target = recipe["parameters"]["gamma_7806_y"]
                preset = json.loads((ROOT / "data" / "presets.json").read_text(encoding="utf-8"))
                native = int(preset["ST_gamma"][128])
                needed = (int(target[-1]) + 1) // 2
                endpoint = max(native, needed)
            except Exception:  # noqa: BLE001 - 读不到就走官方默认端点
                endpoint = None
        result = core.finish_fit(
            out_dir, int(job["number"]), job["short_name"], job["full_name"],
            endpoint,
        )
        # vendored 用 locale 编码写交付 JSON;这里统一归一化为 UTF-8,
        # 保证任何机器上交付文件都是可移植的 UTF-8。
        # 注意 bytes.decode() 无参数默认 utf-8;按 utf-8 → gbk → latin-1 链兜底。
        for path in (out_dir / "native_config.json", out_dir / "conversion_audit.json"):
            raw = path.read_bytes()
            for encoding in ("utf-8", "gbk", "latin-1"):
                try:
                    text = raw.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                text = raw.decode("utf-8", errors="replace")
            path.write_text(text, encoding="utf-8")
        (out_dir / "finish_result.json").write_text(
            json.dumps(result, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return _trim_finish(result)

    if stage == "pc":
        import pc_compensation
        pc_compensation.generate(out_dir)
        payload = (out_dir / "pc_compensation.json").read_bytes()
        return {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}

    if stage == "package-set":
        import zipfile
        from compilers import custom_filter_v4 as compiler
        single = compiler.unpack(Path(job["single"]).read_bytes())
        base = compiler.unpack(Path(job["base"]).read_bytes())
        if len(base["entries"]) != 12:
            raise ValueError("整套基座必须是 12 槽")
        entry = single["entries"][0]
        entries = [entry if e["number"] == entry["number"] else e for e in base["entries"]]
        config = compiler.config(entries)
        blob = compiler.pack(config)
        back = compiler.unpack(blob)
        if compiler.pack(back) != blob:
            raise ValueError("整套 BIN 解码/重编不一致")
        target = out_dir / "R5NATIVE.SET.BIN"
        target.write_bytes(blob)
        config_text = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
        (out_dir / "native_config.json").write_text(config_text, encoding="utf-8")
        grid_values = [
            v for channel in entry["grid_5x9x9"]["coefficients"]
            for row in channel for column in row for v in column
        ]
        audit = {
            "schema": "r5lut-export-audit/1",
            "generated_by": "r5lut",
            "slot": entry["number"],
            "slot_name": entry["short_name"],
            "full_name": entry["full_name"],
            "entries": len(back["entries"]),
            "base_set_sha256": hashlib.sha256(Path(job["base"]).read_bytes()).hexdigest(),
            "bin_sha256": hashlib.sha256(blob).hexdigest(),
            "bin_bytes": len(blob),
            "grid_nonzero": sum(1 for v in grid_values if v != 0),
            "grid_min": min(grid_values),
            "grid_max": max(grid_values),
            "replaced_slot": next(
                (e["short_name"] for e in base["entries"] if e["number"] == entry["number"]),
                None,
            ),
        }
        audit_text = json.dumps(audit, ensure_ascii=False, indent=2) + "\n"
        (out_dir / "export_audit.json").write_text(audit_text, encoding="utf-8")
        zip_path = out_dir / "v4-config.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(target, "R5NATIVE.BIN")
            archive.writestr("native_config.json", config_text)
            archive.writestr("export_audit.json", audit_text)
        return {
            "bytes": len(blob),
            "sha256": hashlib.sha256(blob).hexdigest(),
            "entries": len(back["entries"]),
            "slot": entry["number"],
            "slot_name": entry["short_name"],
            "replaced": next(
                (e["short_name"] for e in base["entries"] if e["number"] == entry["number"]),
                None,
            ),
            "package": str(zip_path),
        }

    if stage == "grid":
        import grid_distillation
        from measured_response import hybrid_response
        # main 分支的 response_json() 只接受固定 Hybrid 响应身份;
        # 旧 smoke_fit 传 np.eye(3) 的写法已不适用。
        # firmware_config 用 locale 编码读 native_config.json;这里先转成
        # locale 副本供其读取,结束后恢复 UTF-8 交付。
        import locale as _locale
        config_path = out_dir / "native_config.json"
        raw = config_path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode(_locale.getpreferredencoding(False))
        config_path.write_text(text)
        try:
            objective = job.get("objective", "fuji-target")
            report = grid_distillation.generate(
                out_dir, hybrid_response(), objective=objective
            )
            blob = grid_distillation.firmware_config(out_dir, report["key"])
            exported = grid_distillation.firmware_config(
                out_dir, report["key"], configuration_only=True
            )
        finally:
            config_path.write_text(text, encoding="utf-8")
        # 带网格的配置写回 native_config.json:后续整套打包读的就是这份。
        config_path.write_text(
            json.dumps(exported, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (out_dir / "v4-config.zip").write_bytes(blob)
        (out_dir / "grid_report.json").write_text(
            json.dumps(report, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return _trim_grid_report(report)

    if stage == "diagnostics":
        import core
        result = core.diagnostics(
            out_dir,
            pc=bool(job.get("pc")),
            grid_key=job.get("grid_key"),
            include_preview=bool(job.get("include_preview")),
        )
        (out_dir / "diagnostics.json").write_text(
            json.dumps(result, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        native = result.get("native_tonal", {})
        final = result.get("tonal", {})
        def _groups(source):
            return {k: v.get("metrics") for k, v in source.get("groups", {}).items()
                    if v.get("metrics")}
        return {
            "algorithm": result.get("algorithm"),
            "native_tonal": _groups(native),
            "final_tonal": _groups(final),
            "recipe_sha256": result.get("recipe_sha256"),
            "dataset": result.get("dataset"),
        }

    if stage == "compile":
        from compilers import custom_filter_v4 as compiler
        config_path = Path(job["config"])
        # vendored 编译器用 locale 编码读 JSON;这里先以 utf-8(-sig) 读入,
        # 失败则退回 locale,再写成 ASCII 转义的临时文件,保证任何 locale 下安全。
        try:
            raw = config_path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            raw = config_path.read_text()
        value = json.loads(raw)
        temp = out_dir / f"_compile_{config_path.stem}.json"
        temp.write_text(json.dumps(value, ensure_ascii=True), encoding="ascii")
        packed = compiler.pack(compiler.load(temp))
        temp.unlink(missing_ok=True)
        Path(job["output"]).write_bytes(packed)
        return {"bytes": len(packed), "sha256": hashlib.sha256(packed).hexdigest()}

    if stage == "inspect-bin":
        from compilers import custom_filter_v4 as compiler
        data = Path(job["bin"]).read_bytes()
        value = compiler.unpack(data)
        (out_dir / "bin_unpacked.json").write_text(
            json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        entries = []
        for entry in value["entries"]:
            grid = entry["grid_5x9x9"]["coefficients"]
            flat = [v for ch in grid for y in ch for u in y for v in u]
            entries.append({
                "number": entry["number"],
                "short_name": entry["short_name"],
                "full_name": entry["full_name"],
                "grid_min": min(flat),
                "grid_max": max(flat),
            })
        return {"schema": value["schema"], "model": value["model"],
                "bytes": len(data), "entries": entries}

    raise ValueError("未知 stage: " + stage)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 2:
        print("用法: python _r5_runner.py <stage> <job.json>", file=sys.stderr)
        return 1
    stage, job_path = argv[0], Path(argv[1])
    out_dir = Path(job_path).resolve().parent
    try:
        job = json.loads(job_path.read_text(encoding="utf-8"))
        result = run(stage, job, out_dir)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except Exception as exc:  # noqa: BLE001 —— 边界进程,任何失败都要报出去
        print(json.dumps({"error": str(exc), "type": type(exc).__name__},
                         ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
