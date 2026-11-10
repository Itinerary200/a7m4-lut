"""LUT 输入域识别:SLog3 型 LUT 要先把显示值换成 log 码再查表。

相机给的是「显示域」像素(Rec709 / sRGB 编码,0..1 表示黑到白)。
SLog3 型 LUT 的输入是「log 码」:0 约等于 -inf 黑,0.41 约等于 18% 灰。
直接把显示值喂进去等于用错曲线,整张图会又灰又淡。

这里的映射曲线不是照公式抄的,是用同一套 look 的
「Rec709_to_Ricoh」与「SLog3_to_Ricoh」两个版本互相对齐反推出来的:
让两边输出相等的那个 log 码,就是该显示值真正对应的码值。
实测样本(d 为显示值,c 为 log 码):
0.05→0.1553 0.10→0.2158 0.20→0.2998 0.30→0.3613 0.40→0.4111
0.50→0.4639 0.60→0.5186 0.70→0.5732 0.80→0.6309 0.90→0.7051
曲线两端(纯黑、高光)在 LUT 里已经饱和、量不出来,按已测段的斜率外推,
结果与 SLog3 的公认端点(黑约 0.09、白约 0.8)吻合。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .preview import Cube

# (显示值, log 码) 锚点,按第一列升序
SLOG3_CURVE: tuple[tuple[float, float], ...] = (
    (0.0000, 0.09500),
    (0.0625, 0.17042),
    (0.1250, 0.23875),
    (0.1875, 0.29028),
    (0.2500, 0.34000),
    (0.3125, 0.36765),
    (0.3750, 0.39890),
    (0.4375, 0.43090),
    (0.5000, 0.46700),
    (0.5625, 0.49805),
    (0.6250, 0.53225),
    (0.6875, 0.56638),
    (0.7500, 0.60100),
    (0.8125, 0.63920),
    (0.8750, 0.68460),
    (0.9375, 0.74830),
    (1.0000, 0.80000),
)

DISPLAY = "display"
SLOG3 = "slog3"

# 文件名 / TITLE 里出现这些字样,基本可以断定输入是 log 域
LOG_HINTS = (
    "slog3",
    "s-log3",
    "slog2",
    "s-log2",
    "slog",
    "s-gamut",
    "sgamut",
    "cine->",
    "_to_cine",
    "log3",
    "log to",
    "log-",
    "-log",
)
# 反过来,出现这些字样说明已经是对显示域的 LUT,不能当 log 处理
DISPLAY_HINTS = ("rec709", "rec.709", "rec 709", "srgb", "display", "gamma")


def display_to_slog3(value: float) -> float:
    """显示值(0..1)→ SLog3 log 码(0..1),按锚点线性插值。"""
    if value <= 0.0:
        return SLOG3_CURVE[0][1]
    if value >= 1.0:
        return SLOG3_CURVE[-1][1]
    for index in range(len(SLOG3_CURVE) - 1):
        left_d, left_c = SLOG3_CURVE[index]
        right_d, right_c = SLOG3_CURVE[index + 1]
        if left_d <= value <= right_d:
            span = right_d - left_d
            blend = 0.0 if span <= 0 else (value - left_d) / span
            return left_c + (right_c - left_c) * blend
    return SLOG3_CURVE[-1][1]


def slog3_to_display(code: float) -> float:
    """SLog3 log 码(0..1)→ 显示值(0..1),反查上面的曲线。"""
    if code <= SLOG3_CURVE[0][1]:
        return 0.0
    if code >= SLOG3_CURVE[-1][1]:
        return 1.0
    for index in range(len(SLOG3_CURVE) - 1):
        left_d, left_c = SLOG3_CURVE[index]
        right_d, right_c = SLOG3_CURVE[index + 1]
        if left_c <= code <= right_c:
            span = right_c - left_c
            blend = 0.0 if span <= 0 else (code - left_c) / span
            return left_d + (right_d - left_d) * blend
    return 1.0


def _halo(text: str, words: tuple[str, ...]) -> float:
    """算一组关键词的命中分数;越具体(越长)的词分数越高。"""
    score = 0.0
    for word in words:
        if word in text:
            score = max(score, len(word) / 10.0)
    return score


def detect(cube: Cube, name: str = "") -> str:
    """判断这个 LUT 的输入域:返回 "display" 或 "slog3"。

    先看名字与 TITLE(最可靠:厂商都会写清楚),
    名字没线索时再看曲线行为 —— log 型 LUT 会把中灰当 log 码处理,
    所以输入 0.5 出来的亮度明显高于 0.5。
    """
    from . import preview

    text = f"{cube.title} {name}".lower().replace(" ", "")
    log_score = _halo(text, LOG_HINTS)
    display_score = _halo(text, tuple(word.replace(" ", "") for word in DISPLAY_HINTS))
    if log_score > 0 and log_score >= display_score:
        return SLOG3
    if display_score > 0:
        return DISPLAY
    # 名字没写:看中灰增益
    middle = preview.sample(cube, 0.5, 0.5, 0.5)[1]
    if middle > 0.5 * 1.22:
        return SLOG3
    return DISPLAY
