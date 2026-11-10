"""SD 卡 JSON 合同的回归门禁。

覆盖 `methods/08-custom-lut/FORMAT.md` 与 `p4_json.h` / `p4_library.h` 的硬限制:
文件大小、目录条目、文件名与 name 的字节上限、字段语义、能力声明、
`payload_sha256` 复算,以及官方 `compile_native` 原生数组形状。

没有成品目录时跳过(用 `R5_M4_LUT_DIR` 指向要审计的目录)。
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
_VENDOR = Path(__file__).resolve().parents[1] / "vendor" / "m4"
for _path in (_SRC, _VENDOR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

MAX_BYTES = 131_072
MAX_ENTRIES = 256
MAX_SLOTS = 16
MAX_NAME_BYTES = 63


def _look_dir() -> Path | None:
    override = os.environ.get("R5_M4_LUT_DIR")
    candidates = [Path(override)] if override else []
    candidates.append(Path("out/m4-final2/PRIVATE/M4ROOT/GENERAL/LUT"))
    for candidate in candidates:
        if candidate.is_dir() and any(candidate.glob("*.json")):
            return candidate
    return None


@unittest.skipUnless(_look_dir() is not None, "没有可审计的 A7M4 成品目录")
class M4ContractTest(unittest.TestCase):
    """逐条验证 FORMAT.md 的导入合同。"""

    @classmethod
    def setUpClass(cls) -> None:
        import look_v2

        cls.look = look_v2
        cls.dir = _look_dir()
        assert cls.dir is not None
        cls.files = sorted(cls.dir.glob("*.json"))
        cls.values = [(path, cls.look.parse(path.read_bytes())) for path in cls.files]

    def test_entry_and_size_limits(self) -> None:
        entries = list(self.dir.iterdir())
        self.assertLessEqual(len(entries), MAX_ENTRIES, "SD 目录条目超过 256")
        for path in self.files:
            size = path.stat().st_size
            self.assertGreater(size, 0, f"{path.name} 是空文件")
            self.assertLessEqual(size, MAX_BYTES, f"{path.name} 超过 128 KiB")

    def test_filename_and_name_limits(self) -> None:
        for path, value in self.values:
            self.assertLessEqual(len(path.name.encode("utf-8")), MAX_NAME_BYTES)
            self.assertFalse(path.name.startswith("."), f"{path.name} 以点开头")
            self.assertEqual(path.suffix.lower(), ".json")
            self.assertLessEqual(len(value["name"].encode("utf-8")), MAX_NAME_BYTES)

    def test_core_fields(self) -> None:
        for path, value in self.values:
            self.assertEqual(value["format"], "camera-look", path.name)
            self.assertEqual(value["version"], 2, path.name)
            self.assertEqual(value["model"], "ILCE-7M4", path.name)
            self.assertEqual(value["engine_abi"], 131_072, path.name)
            self.assertEqual(value["mode"], "photo", path.name)
            self.assertIs(value["draft"], False, path.name)
            self.assertGreaterEqual(value["revision"], 1, path.name)
            self.assertEqual(value["id"], value["id"].lower(), path.name)
            self.assertNotEqual(set(value["id"]), {"0"}, path.name)

    def test_grid_and_capabilities(self) -> None:
        for path, value in self.values:
            grid = value["parameters"]["grid"]
            if grid["mode"] == "custom":
                self.assertEqual(grid["encoding"], "a7m4-grid405-native-s7-v1", path.name)
                for branch in ("photo", "live"):
                    table = grid[branch]
                    self.assertEqual(len(table), 3)
                    for channel in table:
                        self.assertEqual(len(channel), 5)
                        for row in channel:
                            self.assertEqual(len(row), 9)
                            for line in row:
                                self.assertEqual(len(line), 9)
                                for item in line:
                                    self.assertGreaterEqual(item, -64)
                                    self.assertLessEqual(item, 63)
                self.assertIn("native-grid405-separate-v1", value["required_capabilities"])
            else:
                self.assertEqual(grid["mode"], "disabled", path.name)
                self.assertNotIn("native-grid405-separate-v1", value["required_capabilities"])

    def test_payload_hash_recomputes(self) -> None:
        for path, value in self.values:
            self.assertEqual(
                self.look.runtime_hash(value), value["payload_sha256"], f"{path.name} 内容哈希不符"
            )

    def test_native_compile(self) -> None:
        for path, value in self.values:
            compiled = self.look.compile_native(value)
            self.assertEqual(len(compiled["photo"]), 4644, path.name)
            self.assertEqual(len(compiled["live"]), 1196, path.name)

    def test_slots_within_camera_capacity(self) -> None:
        self.assertLessEqual(len(self.files), MAX_ENTRIES)
        # 机内 16 槽;单批建议 ≤16,超过不算违规但会超出可见槽位
        self.assertGreater(len(self.files), 0)


if __name__ == "__main__":
    unittest.main()
