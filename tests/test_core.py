"""r5lut 核心测试:资产身份、预算、CLI 用法、BIN 编解码。

期望值来自官方固定哈希、BIN v4 文档与手写字面量。慢测试用 R5_SLOW=1 开启。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from r5lut import core

AP_SHA = "8ee4d5876b7e127df39f8f820b9d21834c300ff895e02ca522636ed4733efc4b"
CP_SHA = "8e9e26bf2e4b93fa5142e961dcf21cb0f43f8871283814be2dcfb0a694cb5a32"


def _run(*argv: str) -> tuple[int, str, str]:
    completed = subprocess.run(
        [sys.executable, "-m", "r5lut", *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    return completed.returncode, completed.stdout, completed.stderr


class AssetIdentityTest(unittest.TestCase):
    def test_model_sha256_pinned(self):
        root = core.engine_root()
        model = root / "web" / "data" / "r5" / "paired-20261107-nonlinear-he3.json"
        self.assertEqual(core.MODEL_SHA256, hashlib.sha256(model.read_bytes()).hexdigest())

    def test_verify_reports_checks(self):
        checks = core.verify()
        for key in ("model_sha256", "pairs_sha256", "capture_report_sha256", "passed"):
            self.assertIn(key, checks)


class BudgetTest(unittest.TestCase):
    def test_quick_is_smoke_level(self):
        quick = core.quick_budget()
        self.assertEqual(1, quick["evaluations"])
        self.assertEqual(2, quick["starts"])

    def test_formal_matches_profile(self):
        profile = core.official_profile()
        formal = core.formal_budget()
        self.assertEqual(profile["options"]["evaluations"], formal["evaluations"])
        self.assertEqual(profile["options"]["search_options"]["starts"], formal["starts"])
        self.assertEqual(131071, formal["gamma_endpoint128"])
        self.assertEqual("fuji-target", formal["grid_objective"])

    def test_balanced_is_middle(self):
        balanced = core.balanced_budget()
        self.assertEqual(40, balanced["evaluations"])
        self.assertEqual(6, balanced["starts"])
        self.assertLess(balanced["evaluations"], core.formal_budget()["evaluations"])

    def test_gradient_workers_precedence(self):
        self.assertEqual(8, core._gradient_workers())
        self.assertEqual(16, core._gradient_workers(16))
        with unittest.mock.patch.dict(os.environ, {"R5_GRADIENT_WORKERS": "12"}):
            self.assertEqual(12, core._gradient_workers())


class CliUsageTest(unittest.TestCase):
    def test_convert_requires_one_target(self):
        code, _, stderr = _run(
            "convert", "--number", "1", "--name", "x", "--full-name", "y", "-o", "out"
        )
        self.assertEqual(1, code)
        self.assertIn("二选一", stderr)

    def test_verify_json(self):
        code, stdout, _ = _run("verify", "--json")
        self.assertIn(code, (0, 2))
        self.assertIn("passed", json.loads(stdout))

    def test_inspect_missing_bin(self):
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(core.R5Error):
            core.inspect_bin(Path(folder) / "R5NATIVE.BIN")


class BinCodecTest(unittest.TestCase):
    def _config(self):
        grid = {"coefficients": [[[[0] * 9 for _ in range(9)] for _ in range(5)] for _ in range(3)]}
        return {
            "schema": "r5-custom-filter-config/4",
            "model": "ILCE-7RM5",
            "baseline_ap_sha256": AP_SHA,
            "baseline_cp_sha256": CP_SHA,
            "entries": [
                {
                    "number": 1,
                    "short_name": "测试",
                    "full_name": "全名测试",
                    "cc1_delta": [[0] * 8, [0] * 8, [0] * 8],
                    "block13": [[[0] * 6 for _ in range(16)] for _ in range(3)],
                    "gamma_native_129": [min(131071, i * 1024) for i in range(129)],
                    "grid_5x9x9": grid,
                }
            ],
        }

    def test_compile_and_inspect(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = Path(folder) / "c.json"
            cfg.write_text(json.dumps(self._config(), ensure_ascii=False), encoding="utf-8")
            bin_path = Path(folder) / "R5NATIVE.BIN"
            result = core.compile_config(cfg, bin_path)
            self.assertEqual(core.BIN_BYTES_PER_RECORD, result["bytes"])
            payload = bin_path.read_bytes()
            self.assertEqual(core.BIN_MAGIC, payload[:8])
            decoded = core.inspect_bin(bin_path)
            self.assertEqual("r5-custom-filter-config/4", decoded["schema"])
            self.assertEqual("测试", decoded["entries"][0]["short_name"])


@unittest.skipUnless(os.environ.get("R5_SLOW") == "1", "R5_SLOW=1 才跑真训练")
class SlowTest(unittest.TestCase):
    def test_quick_convert(self):
        root = Path(__file__).resolve().parents[1]
        sample = root / "samples" / "示例目标.cube"
        if not sample.is_file():
            self.skipTest("缺少样例 cube")
        with tempfile.TemporaryDirectory() as folder:
            result = core.train(
                sample,
                Path(folder) / "job",
                1,
                "测试",
                "测试",
                budget=core.quick_budget(),
                with_diagnostics=False,
            )
            self.assertEqual(core.BIN_BYTES_PER_RECORD, result.finish["binary_bytes"])


class M4GridTest(unittest.TestCase):
    """M4 网格布局往返(不上相机、不需种子 JSON)。"""

    def test_grid_roundtrip(self):
        from r5lut import m4json

        flat = [(i % 7 - 3, i % 5 - 2, i % 3 - 1) for i in range(405)]
        table = m4json.grid_to_branch(flat)
        shape = (len(table), len(table[0]), len(table[0][0]), len(table[0][0][0]))
        self.assertEqual((3, 5, 9, 9), shape)
        back = m4json.branch_to_grid(table)
        self.assertEqual([tuple(map(int, item)) for item in flat], back)


class PreviewTest(unittest.TestCase):
    """颜色预览:cube 解析、三线性采样、组图、PNG 往返。"""

    def _cubes(self):
        return Path(__file__).resolve().parents[1] / "samples"

    def test_parse_and_sample_identity_cube(self):
        from r5lut import preview

        text = "LUT_3D_SIZE 2\n" + "\n".join(
            f"{r} {g} {b}" for b in (0, 1) for g in (0, 1) for r in (0, 1)
        )
        cube = preview.parse_cube(text)
        self.assertEqual(2, cube.size)
        for colour in ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (0.25, 0.5, 0.75)):
            out = preview.sample(cube, *colour)
            for a, b in zip(out, colour, strict=False):
                self.assertAlmostEqual(a, b, places=6)

    def test_apply_and_png_roundtrip(self):
        from r5lut import preview

        text = "LUT_3D_SIZE 2\n" + "\n".join(
            f"{r} {g} {b}" for b in (0, 1) for g in (0, 1) for r in (0, 1)
        )
        cube = preview.parse_cube(text)
        chart = preview.test_chart(64, 36)
        painted = preview.apply_cube(cube, chart)
        self.assertEqual(painted.pixels, chart.pixels)  # 恒等 cube 不改变像素
        png = preview.encode_png(chart)
        back = preview.decode_png(png)
        self.assertEqual((chart.width, chart.height), (back.width, back.height))
        self.assertEqual(chart.pixels, back.pixels)


if __name__ == "__main__":
    unittest.main()
