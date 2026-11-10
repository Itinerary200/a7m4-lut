"""A7M4「camera-look」v2 JSON:导出、封签与结构校验。

规范以官方 vendored 实现为准(`vendor/m4/look_v2.py`,来源 Erlla/sony-a7m4-custom-firmware);
本模块只做三件事:
1. 从合法种子 JSON 派生新 look(替换 405 网格、名称、UUID);
2. 按 `CAMLOOK2\\0` 规范化哈希封 `payload_sha256`;
3. 用官方校验器验证并写出 ≤128 KiB 的文件。

相机侧的导入目录是 `PRIVATE/M4ROOT/GENERAL/LUT/`(卡根目录下的相对路径),
每文件一个滤镜,机内最多 16 槽。
"""

from __future__ import annotations

import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from .paths import ensure_path

ensure_path("vendor", "m4")

import look_v2  # noqa: E402  vendored 官方实现

MAX_BYTES = look_v2.MAX_BYTES
GRID_ENCODING = look_v2.GRID_ENCODING
ADJUSTMENTS = look_v2.ADJUSTMENTS


class M4Error(ValueError):
    """格式或内容不符合 camera-look v2 合同。"""


def load_seed(path: Path | str) -> dict[str, Any]:
    """读入合法 M4 look JSON(官方解析 + 校验)。"""
    raw = Path(path).read_bytes()
    try:
        value = look_v2.parse(raw)
    except look_v2.FormatError as exc:
        raise M4Error(f"种子 JSON 不合格:{exc}") from exc
    if not isinstance(value, dict):
        raise M4Error("种子 JSON 顶层不是对象")
    return value


def grid_to_branch(values: Any) -> list[list[list[list[int]]]]:
    """405×3 结点系数 → [3][5][9][9](通道优先,node = y*81+u*9+v)。"""
    flat = list(values)
    if len(flat) != 405 and len(flat) != 3 * 405:
        raise M4Error(f"网格长度不对:{len(flat)}")
    table = [[[[0] * 9 for _ in range(9)] for _ in range(5)] for _ in range(3)]
    if len(flat) == 405:
        # 405 项三元组 (node-major, (r,g,b))
        for node, item in enumerate(flat):
            y, u, v = node // 81, (node // 9) % 9, node % 9
            for channel in range(3):
                table[channel][y][u][v] = int(item[channel])
    else:
        # 已按表展开
        index = 0
        for channel in range(3):
            for y in range(5):
                for u in range(9):
                    for v in range(9):
                        table[channel][y][u][v] = int(flat[index])
                        index += 1
    return table


def branch_to_grid(table: list[list[list[list[int]]]]) -> list[tuple[int, int, int]]:
    """[3][5][9][9] → 405 个 (r,g,b)(node-major)。"""
    result: list[tuple[int, int, int]] = []
    for node in range(405):
        y, u, v = node // 81, (node // 9) % 9, node % 9
        result.append((int(table[0][y][u][v]), int(table[1][y][u][v]), int(table[2][y][u][v])))
    return result


def build(
    seed: dict[str, Any],
    *,
    name: str,
    author: str,
    description: str,
    grid: list[list[list[list[int]]]] | None = None,
    live_grid: list[list[list[list[int]]]] | None = None,
    new_id: bool = True,
    revision: int | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """从种子派生新 look(默认替换网格、换 UUID、封哈希)。"""
    value = deepcopy(seed)
    value["name"] = name
    value["author"] = author
    value["description"] = description
    if new_id:
        value["id"] = str(uuid.uuid4())
    if revision is not None:
        value["revision"] = int(revision)
    elif new_id:
        value["revision"] = 1
    if grid is not None:
        parameters = value["parameters"]
        if parameters["grid"].get("mode") != "custom":
            parameters["grid"] = {
                "mode": "custom",
                "encoding": GRID_ENCODING,
                "photo": grid,
                "live": live_grid if live_grid is not None else grid,
            }
        else:
            parameters["grid"]["photo"] = grid
            parameters["grid"]["live"] = live_grid if live_grid is not None else grid
    value["draft"] = False
    if provenance is not None:
        value["provenance"] = provenance
    return seal(value)


def seal(value: dict[str, Any]) -> dict[str, Any]:
    """重算 payload_sha256 并校验(不是签名,不代表生产资格)。"""
    try:
        sealed = look_v2.seal(value)
    except look_v2.FormatError as exc:
        raise M4Error(f"封签失败:{exc}") from exc
    if not isinstance(sealed, dict):
        raise M4Error("封签结果不是对象")
    return sealed


def validate(value: dict[str, Any]) -> dict[str, Any]:
    try:
        report = look_v2.validate(value)
    except look_v2.FormatError as exc:
        raise M4Error(str(exc)) from exc
    if not isinstance(report, dict):
        raise M4Error("校验报告不是对象")
    return report


def encode(value: dict[str, Any], *, pretty: bool = False) -> bytes:
    try:
        raw = look_v2.encode(value, pretty=pretty)
    except look_v2.FormatError as exc:
        raise M4Error(str(exc)) from exc
    if not isinstance(raw, bytes):
        raise M4Error("编码结果不是字节")
    if len(raw) > MAX_BYTES:
        raise M4Error(f"编码后 {len(raw)} 字节,超过 {MAX_BYTES}")
    return raw


def write(path: Path | str, value: dict[str, Any], *, pretty: bool = False) -> dict[str, Any]:
    raw = encode(value, pretty=pretty)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return {
        "path": str(target),
        "bytes": len(raw),
        "sha256": _sha256(raw),
        "payload_sha256": value["payload_sha256"],
        "name": value["name"],
        "id": value["id"],
        "revision": value["revision"],
        "grid_mode": value["parameters"]["grid"]["mode"],
    }


def _sha256(raw: bytes) -> str:
    import hashlib

    return hashlib.sha256(raw).hexdigest()


def sd_path(name: str) -> str:
    """相机侧导入目录(相对卡根)。"""
    return f"PRIVATE/M4ROOT/GENERAL/LUT/{name}"
