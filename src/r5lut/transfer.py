"""LUT 输入域识别:认出这家厂商的 log 曲线,先把显示值换成 log 码再查表。

相机给的是「显示域」像素(看起来正常的画面)。而各家的 log LUT 输入是「log 码」:
索尼 S-Log3、富士 F-Log、佳能 Canon Log、尼康 N-Log、松下 V-Log、
ARRI LogC、大疆 D-Log、影石 I-Log、徕卡 L-Log …… 曲线都不一样,
把显示值直接喂进去,整张图会又灰又淡,色差直接飙到 9 以上。

每条曲线都是 17 点表(显示值 0..1 等距 → log 码 0..1),存在 `curves.py` 里,
由各家官方「log → Rec709 / BT1886 / CMT709」转换 LUT 的灰阶轴反解得到
(生成脚本 `build/curve_build.py`)。富士官方包内没有纯 Gamma 转换,
用 ETERNA / ETERNA-BB / WDR 三张 look 的反解中位数近似。
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

from .curves import CURVES, GRID

if TYPE_CHECKING:
    from .preview import Cube

DISPLAY = "display"
SLOG3 = "slog3"

# 显示给用户看的名字
LABELS: dict[str, str] = {
    "display": "普通显示(Rec709)",
    "slog3": "索尼 S-Log3",
    "slog2": "索尼 S-Log2",
    "flog": "富士 F-Log",
    "flog2": "富士 F-Log2",
    "flog2c": "富士 F-Log2C",
    "clog2": "佳能 Canon Log2",
    "clog3": "佳能 Canon Log3",
    "nlog": "尼康 N-Log",
    "vlog": "松下 V-Log",
    "logc3": "ARRI LogC3",
    "logc4": "ARRI LogC4",
    "dlog": "大疆 D-Log",
    "dlogm": "大疆 D-Log M",
    "dlog2": "大疆 D-Log2",
    "ilog": "影石 I-Log",
    "llog": "徕卡 L-Log",
}

# 关键词 → 曲线;顺序要紧(先长后短,避免 f-log2 被 f-log 抢走)
HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("flog2c", ("f-log2c", "flog2c", "f log2c")),
    ("flog2", ("f-log2", "flog2", "f log2")),
    ("flog", ("f-log", "flog", "f log")),
    ("clog3", ("canonlog3", "canonlog 3", "c-log3", "clog3", "clog 3")),
    ("clog2", ("canonlog2", "canonlog 2", "c-log2", "clog2", "clog 2")),
    ("slog3", ("s-log3", "slog3", "slog 3")),
    ("slog2", ("s-log2", "slog2", "slog 2")),
    ("nlog", ("n-log", "nlog", "n log")),
    ("vlog", ("v-log", "vlog", "v log")),
    ("logc4", ("logc4", "log c4", "logc 4")),
    ("logc3", ("logc3", "log c3", "logc 3", "logc")),
    ("dlogm", ("d-logm", "d-log m", "dlogm", "d log m")),
    ("dlog2", ("d-log2", "dlog2", "d log2")),
    ("dlog", ("d-log", "dlog", "d log")),
    ("ilog", ("i-log", "ilog", "i log")),
    ("llog", ("l-log", "llog", "l log")),
)

# 出现这些字样说明已经是对显示域的 LUT,不能当 log 处理
DISPLAY_HINTS = ("rec709", "rec.709", "rec 709", "srgb", "display", "gamma")


def formats() -> list[str]:
    """所有认得的曲线键(不含 display)。"""
    return sorted(CURVES)


def _table_of(kind: str | Sequence[float]) -> Sequence[float] | None:
    """曲线既可以是名字,也可以直接是一张 17 点表(自校准曲线)。"""
    if isinstance(kind, str):
        return CURVES.get(kind)
    return kind


def display_to_code(value: float, kind: str | Sequence[float] = SLOG3) -> float:
    """显示值(0..1)→ 指定 log 曲线的码值(0..1),按 17 点表线性插值。"""
    table = _table_of(kind)
    if not table:
        return value
    if value <= 0.0:
        return table[0]
    if value >= 1.0:
        return table[-1]
    step = GRID[1] - GRID[0]
    index = int(value / step)
    index = max(0, min(len(table) - 2, index))
    left_d = GRID[index]
    blend = (value - left_d) / step
    return table[index] + (table[index + 1] - table[index]) * blend


def code_to_display(code: float, kind: str | Sequence[float] = SLOG3) -> float:
    """指定 log 曲线码值(0..1)→ 显示值(0..1),反查同一张表。"""
    if kind in ("pq", "hlg"):
        return hdr_to_display(code, kind)
    table = _table_of(kind)
    if not table:
        return code
    if code <= table[0]:
        return 0.0
    if code >= table[-1]:
        return 1.0
    for index in range(len(table) - 1):
        left_c, right_c = table[index], table[index + 1]
        if left_c <= code <= right_c:
            span = right_c - left_c
            blend = 0.0 if span <= 0 else (code - left_c) / span
            return GRID[index] + (GRID[index + 1] - GRID[index]) * blend
    return 1.0


def display_to_slog3(value: float) -> float:
    """兼容旧调用:显示值 → SLog3 码值。"""
    return display_to_code(value, SLOG3)


def slog3_to_display(code: float) -> float:
    """兼容旧调用:SLog3 码值 → 显示值。"""
    return code_to_display(code, SLOG3)


def label(kind: str) -> str:
    return LABELS.get(kind, kind)


def detect(cube: Cube, name: str = "") -> str:
    """判断这个 LUT 的输入域:返回曲线键,认不出就返回 "display"。

    先看名字与 TITLE(厂商都会写清楚曲线名),没线索时再看曲线行为 ——
    log 型 LUT 把中灰当 log 码处理,输入 0.5 出来的亮度会明显高于 0.5。
    """
    from . import preview

    text = f"{cube.title} {name}".lower().replace(" ", "")
    if any(word in text for word in DISPLAY_HINTS):
        # 名字里明确写了显式转换目标,但输入仍可能是 log(如"N-Log 转 Rec.709"),
        # 所以还要看有没有曲线关键词;没有才算显示域。
        for kind, words in HINTS:
            if any(word.replace(" ", "") in text for word in words):
                return kind
        return DISPLAY
    for kind, words in HINTS:
        if any(word.replace(" ", "") in text for word in words):
            return kind
    middle = preview.sample(cube, 0.5, 0.5, 0.5)[1]
    if middle > 0.5 * 1.22:
        # 只知道「是 log」但不知道是哪家:按最常见的 SLog3 处理
        return SLOG3
    return DISPLAY


# ---- 输出编码 -------------------------------------------------------------
# 有些官方 LUT 的「目标」不是显示画面,而是一个 log / HDR 编码
# (例:S-Log3 转 SLog2-709、Canon Log3 转 CMTPQ)。直接把这些码值当显示值用,
# 画面会又灰又淡,所以要先按目标编码解码回显示域。

OUTPUT_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("slog2", ("slog2-709", "slog2", "s-log2")),
    ("slog3", ("slog3", "s-log3")),
    ("clog3", ("cmtlog3", "clog3", "log3")),
    ("clog2", ("cmtlog2", "clog2", "log2")),
    ("logc4", ("logc4",)),
    ("logc3", ("logc3", "logc")),
    ("pq", ("cmtpq", "st2084", "pq", "hdr10")),
    ("hlg", ("cmthlg", "hlg", "bt2100")),
)


def detect_output(cube: Cube, name: str = "") -> str:
    """识别 LUT 的目标编码:普通显示返回 "display"。"""
    text = f"{getattr(cube, 'title', '')} {name}".lower().replace(" ", "")
    cut = max(text.rfind("转"), text.rfind("to"))
    tail = text[cut:] if cut >= 0 else text
    for kind, words in OUTPUT_HINTS:
        if any(word in tail for word in words):
            return kind
    return DISPLAY


# ---- 自校准 ---------------------------------------------------------------
# 各家曲线版本很多(同一家不同固件也会微调),靠关键词查表总有对不上的时候。
# 这里直接从 LUT 自己身上反解:把灰阶从 0 走到 1,二分找「输出正好等于这个灰」的码值。
# 如果反解出来的曲线喂进去后残差很小,说明这份 LUT 就是一条纯转换曲线,用它最准。

CALIBRATION_GRADES = GRID
CALIBRATION_TOLERANCE = 0.03


def _mean_output(cube: Cube, code: float, out_kind: str) -> float:
    from . import preview

    red, green, blue = preview.sample(cube, code, code, code)
    if out_kind != DISPLAY:
        red = code_to_display(float(red), out_kind)
        green = code_to_display(float(green), out_kind)
        blue = code_to_display(float(blue), out_kind)
    return (float(red) + float(green) + float(blue)) / 3.0


def solve(cube: Cube, out_kind: str = DISPLAY) -> tuple[tuple[float, ...] | None, float]:
    """反解这份 LUT 的输入曲线,返回 (17 点表, 残差);不像纯转换曲线就返回 (None, 残差)。"""
    # 端点单独处理:LUT 的黑位常常不是精确 0(可能是 0.001),拿它当二分目标会误判失败
    solved: list[float] = [0.0]
    for target in CALIBRATION_GRADES[1:-1]:
        low, high = 0.0, 1.0
        if _mean_output(cube, high, out_kind) < target:
            return None, 1.0
        for _ in range(24):
            middle = (low + high) / 2
            if _mean_output(cube, middle, out_kind) < target:
                low = middle
            else:
                high = middle
        solved.append(round((low + high) / 2, 6))
    solved.append(1.0)
    for index in range(1, len(solved)):
        if solved[index] <= solved[index - 1]:
            return None, 1.0

    residual = 0.0
    for value, code in zip(CALIBRATION_GRADES, solved, strict=True):
        residual += abs(_mean_output(cube, float(code), out_kind) - value)
    residual /= len(solved)
    if residual > CALIBRATION_TOLERANCE:
        return None, residual
    return tuple(solved), residual


def curve_label(table: Sequence[float]) -> str:
    """给自校准曲线起个能写进 provenance 的名字。"""
    return "calibrated:" + "-".join(f"{value:.3f}" for value in table[:3])


# ---- HDR 目标解码 ---------------------------------------------------------
# Canon 的 CMTPQ / CMTHLG、ARRI 的 St2084 / HLG 这些目标不是 SDR 显示值,
# 而是一条感知编码。这里按标准公式反解成「SDR 白 = 1.0」的相对亮度,再做 2.2 编码。

PQ_M1 = 2610 / 16384
PQ_M2 = 2523 / 32
PQ_C1 = 3424 / 4096
PQ_C2 = 2413 / 128
PQ_C3 = 2392 / 128
PQ_WHITE_NITS = 100.0
HLG_A = 0.17883277
HLG_B = 1 - 4 * HLG_A
HLG_C = 0.5 - HLG_A * math.log(4 * HLG_A)
HLG_WHITE = 0.75


def pq_to_relative(code: float) -> float:
    """ST.2084 码值 → 相对亮度(以 100 nit 为 1.0)。"""
    power = max(code, 0.0) ** (1 / PQ_M2)
    numerator = max(power - PQ_C1, 0.0)
    denominator = PQ_C2 - PQ_C3 * power
    if denominator <= 0:
        return 0.0
    nits = float((numerator / denominator) ** (1 / PQ_M1)) * 10000.0
    return float(nits / PQ_WHITE_NITS)


def hlg_to_relative(code: float) -> float:
    """HLG 码值 → 相对亮度(以 HLG 0.75 为 1.0)。"""
    value = max(code, 0.0)
    scene = value * value / 3 if value <= 0.5 else (math.exp((value - HLG_C) / HLG_A) + HLG_B) / 12
    return float(scene / HLG_WHITE)


def hdr_to_display(code: float, kind: str) -> float:
    """PQ / HLG 码值 → 显示值(0..1,gamma 2.2)。"""
    relative = pq_to_relative(code) if kind == "pq" else hlg_to_relative(code)
    return float(min(1.0, max(0.0, relative)) ** (1 / 2.2))
