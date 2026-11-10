"""颜色预览:cube 套到测试图上的前后对照(自带 CUBE 解析、采样与 PNG 编解码)。

    cube = parse_cube(Path("x.cube").read_text())
    sheet = compose_sheet(cube)          # 原图 + 套用后 + 色块对照
    data  = encode_png(sheet)

预览把 cube 直接作用在 sRGB 显示值上(与剪辑软件里的观感一致);训练管线按
官方方法在 S-Log3 域解释它,两者用途不同,界面上有说明。
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
RGB = tuple[int, int, int]


@dataclass(frozen=True)
class Cube:
    title: str
    size: int
    points: tuple[tuple[float, float, float], ...]
    domain_min: tuple[float, float, float] = (0.0, 0.0, 0.0)
    domain_max: tuple[float, float, float] = (1.0, 1.0, 1.0)


@dataclass(frozen=True)
class Raster:
    width: int
    height: int
    pixels: bytearray

    def get(self, x: int, y: int) -> RGB:
        offset = (y * self.width + x) * 3
        return (self.pixels[offset], self.pixels[offset + 1], self.pixels[offset + 2])


def _triple(line: str, keyword: str) -> tuple[float, float, float]:
    """解析 DOMAIN_MIN / DOMAIN_MAX 后面的三个浮点数。"""
    parts = line.split()
    if len(parts) != 4:
        raise ValueError(f"{keyword} 需要三个数值:{line!r}")
    return float(parts[1]), float(parts[2]), float(parts[3])


def parse_cube(text: str) -> Cube:
    """解析 .cube(3D):TITLE / LUT_3D_SIZE / DOMAIN_MIN / DOMAIN_MAX + 点行。"""
    title = ""
    size = None
    dmin = (0.0, 0.0, 0.0)
    dmax = (1.0, 1.0, 1.0)
    points: list[tuple[float, float, float]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        upper = line.upper()
        if upper.startswith("TITLE"):
            title = line.split(None, 1)[1].strip().strip('"') if " " in line else ""
        elif upper.startswith("LUT_3D_SIZE"):
            size = int(line.split()[1])
        elif upper.startswith("DOMAIN_MIN"):
            dmin = _triple(line, upper)
        elif upper.startswith("DOMAIN_MAX"):
            dmax = _triple(line, upper)
        elif upper.startswith("LUT_1D_SIZE"):
            raise ValueError("只支持 3D cube(LUT_1D_SIZE 不支持)")
        else:
            parts = line.split()
            if len(parts) >= 3:
                points.append((float(parts[0]), float(parts[1]), float(parts[2])))
    if size is None:
        raise ValueError("缺少 LUT_3D_SIZE")
    expected = size**3
    if len(points) != expected:
        raise ValueError(f"点数量不对:期望 {expected},实际 {len(points)}")
    # 有的 .cube 是「蓝最快」而不是规范的「红最快」,照规范读会整块转置、色差飙到 9~10。
    # 判据:快轴应该主要改红、慢轴主要改蓝(对角占优);反过来就是写法不同,需要转一次。
    if size > 1:
        profile = _axis_profile(points, size)
        diagonal = profile[0][0] + profile[1][1] + profile[2][2]
        reversed_diagonal = profile[0][2] + profile[1][1] + profile[2][0]
        if reversed_diagonal > diagonal * 1.25:
            points = _reorder(points, size)
    return Cube(title, size, tuple(points), dmin, dmax)


def _axis_profile(points: list[tuple[float, float, float]], size: int) -> list[list[float]]:
    """沿 快/中/慢 三根轴各走一步,看每个输出通道变化多少。

    读对顺序时,快轴推的是红、慢轴推的是蓝 → 近似对角;读错成「蓝最快」就整块错位,
    对角和反对角的强弱正好反过来,据此判定。
    """
    profile: list[list[float]] = []
    for stride in (1, size, size * size):
        totals = [0.0, 0.0, 0.0]
        count = 0
        for index in range(len(points) - stride):
            if (index // stride) % size == size - 1:  # 跨块那一步不算
                continue
            first, second = points[index], points[index + stride]
            totals[0] += abs(first[0] - second[0])
            totals[1] += abs(first[1] - second[1])
            totals[2] += abs(first[2] - second[2])
            count += 1
        profile.append([total / max(1, count) for total in totals])
    return profile


def _reorder(
    points: list[tuple[float, float, float]], size: int
) -> list[tuple[float, float, float]]:
    """把「蓝最快」的写法换成「红最快」(CUBE 规范顺序)。"""
    out: list[tuple[float, float, float]] = [points[0]] * len(points)
    for red in range(size):
        for green in range(size):
            base = red * size * size + green * size
            for blue in range(size):
                out[blue * size * size + green * size + red] = points[base + blue]
    return out


def sample(cube: Cube, r: float, g: float, b: float) -> tuple[float, float, float]:
    """三线性采样(红最快,CUBE 规范顺序)。"""
    span = cube.size - 1
    axes = (r, g, b)
    out_axes = []
    for axis, lo, hi in zip(axes, cube.domain_min, cube.domain_max, strict=False):
        value = (axis - lo) / (hi - lo) if hi != lo else 0.0
        out_axes.append(0.0 if value < 0 else 1.0 if value > 1 else value)
    px, py, pz = (v * span for v in out_axes)
    ix, iy, iz = int(px), int(py), int(pz)
    if ix >= span:
        ix = span - 1
    if iy >= span:
        iy = span - 1
    if iz >= span:
        iz = span - 1
    fx, fy, fz = px - ix, py - iy, pz - iz
    stride = cube.size
    plane = cube.size * cube.size
    base = ix + stride * iy + plane * iz
    p000, p100 = cube.points[base], cube.points[base + 1]
    p010, p110 = cube.points[base + stride], cube.points[base + stride + 1]
    p001, p101 = cube.points[base + plane], cube.points[base + plane + 1]
    p011, p111 = cube.points[base + plane + stride], cube.points[base + plane + stride + 1]
    result = []
    for channel in range(3):
        c00 = p000[channel] + (p100[channel] - p000[channel]) * fx
        c10 = p010[channel] + (p110[channel] - p010[channel]) * fx
        c01 = p001[channel] + (p101[channel] - p001[channel]) * fx
        c11 = p011[channel] + (p111[channel] - p011[channel]) * fx
        c0 = c00 + (c10 - c00) * fy
        c1 = c01 + (c11 - c01) * fy
        result.append(c0 + (c1 - c0) * fz)
    return result[0], result[1], result[2]


def _clamp_byte(value: float) -> int:
    if value <= 0.0:
        return 0
    if value >= 255.0:
        return 255
    return int(round(value))


def hsv_rgb(hue: float, saturation: float, value: float) -> RGB:
    hue = hue % 1.0
    sector = int(hue * 6.0) % 6
    fraction = hue * 6.0 - int(hue * 6.0)
    p = value * (1.0 - saturation)
    q = value * (1.0 - saturation * fraction)
    t = value * (1.0 - saturation * (1.0 - fraction))
    table = {
        0: (value, t, p),
        1: (q, value, p),
        2: (p, value, t),
        3: (p, q, value),
        4: (t, p, value),
        5: (value, p, q),
    }
    r, g, b = table[sector]
    return (int(round(r * 255)), int(round(g * 255)), int(round(b * 255)))


SKIN_TONES: tuple[RGB, ...] = (
    (58, 34, 26),
    (94, 58, 42),
    (134, 86, 62),
    (176, 124, 94),
    (210, 165, 134),
    (238, 205, 178),
)
NEUTRAL_LEVELS = (0, 26, 51, 77, 102, 128, 153, 179, 204, 230, 255)
NEUTRALS: tuple[RGB, ...] = tuple((v, v, v) for v in NEUTRAL_LEVELS)
PRIMARIES: tuple[RGB, ...] = (
    (255, 0, 0),
    (0, 255, 0),
    (0, 0, 255),
    (0, 255, 255),
    (255, 0, 255),
    (255, 255, 0),
)


def test_chart(width: int = 320, height: int = 180) -> Raster:
    """测试图:色相带 + 11 级灰阶 + 肤色/原色块。"""
    pixels = bytearray(width * height * 3)
    top = int(height * 0.46)
    middle = int(height * 0.70)
    for y in range(height):
        for x in range(width):
            if y < top:
                colour = hsv_rgb(x / max(1, width - 1), 0.92, 0.98)
            elif y < middle:
                step = min(len(NEUTRALS) - 1, x * len(NEUTRALS) // max(1, width))
                colour = NEUTRALS[step]
            else:
                cell = min(11, x * 12 // max(1, width))
                colour = (SKIN_TONES + PRIMARIES)[cell]
            offset = (y * width + x) * 3
            pixels[offset : offset + 3] = bytes(colour)
    return Raster(width, height, pixels)


def input_value(value: float, transfer: str = "display") -> float:
    """按 LUT 输入域把显示值换成它要的输入值。"""
    if transfer == "slog3":
        from . import transfer as transfer_mod

        return transfer_mod.display_to_slog3(value)
    return value


def apply_cube(cube: Cube, raster: Raster, transfer: str = "display") -> Raster:
    pixels = bytearray(len(raster.pixels))
    for index in range(0, len(raster.pixels), 3):
        r = input_value(raster.pixels[index] / 255.0, transfer)
        g = input_value(raster.pixels[index + 1] / 255.0, transfer)
        b = input_value(raster.pixels[index + 2] / 255.0, transfer)
        out = sample(cube, r, g, b)
        pixels[index] = _clamp_byte(out[0] * 255.0)
        pixels[index + 1] = _clamp_byte(out[1] * 255.0)
        pixels[index + 2] = _clamp_byte(out[2] * 255.0)
    return Raster(raster.width, raster.height, pixels)


def swatch_colors() -> list[RGB]:
    return [
        (0, 0, 0),
        (64, 64, 64),
        (128, 128, 128),
        (192, 192, 192),
        (255, 255, 255),
        (255, 0, 0),
        (0, 255, 0),
        (0, 0, 255),
        (0, 255, 255),
        (255, 0, 255),
        (255, 255, 0),
        *SKIN_TONES[1:6],
    ]


def swatch_pairs(cube: Cube, transfer: str = "display") -> list[tuple[RGB, RGB]]:
    pairs: list[tuple[RGB, RGB]] = []
    for colour in swatch_colors():
        red, green, blue = sample(
            cube,
            input_value(colour[0] / 255.0, transfer),
            input_value(colour[1] / 255.0, transfer),
            input_value(colour[2] / 255.0, transfer),
        )
        after: RGB = (
            _clamp_byte(red * 255.0),
            _clamp_byte(green * 255.0),
            _clamp_byte(blue * 255.0),
        )
        pairs.append((colour, after))
    return pairs


def encode_png(raster: Raster) -> bytes:
    width, height = raster.width, raster.height
    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)
        raw.extend(raster.pixels[y * stride : (y + 1) * stride])

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        PNG_SIGNATURE
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


class PngError(ValueError):
    pass


def decode_png(data: bytes) -> Raster:
    if not data.startswith(PNG_SIGNATURE):
        raise PngError("不是 PNG 文件")
    offset = len(PNG_SIGNATURE)
    width = height = bit_depth = colour_type = None
    interlace = 0
    idat = bytearray()
    while offset + 8 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if kind == b"IHDR":
            width, height, bit_depth, colour_type, _, _, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
        elif kind == b"IDAT":
            idat.extend(payload)
        elif kind == b"IEND":
            break
    if width is None or height is None:
        raise PngError("PNG 缺少 IHDR")
    if bit_depth != 8:
        raise PngError(f"只支持 8bit PNG,实际 {bit_depth}bit")
    if colour_type not in (0, 2, 4, 6):
        raise PngError(f"不支持的 PNG 颜色类型 {colour_type}")
    if interlace:
        raise PngError("不支持隔行 PNG")
    channels = {0: 1, 2: 3, 4: 2, 6: 4}[colour_type]
    stride = width * channels
    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error as exc:
        raise PngError(f"PNG 数据解不开:{exc}") from None
    if len(raw) < (stride + 1) * height:
        raise PngError("PNG 数据不完整")
    previous = bytearray(stride)
    rows: list[bytearray] = []
    position = 0
    for _ in range(height):
        filter_type = raw[position]
        position += 1
        line = bytearray(raw[position : position + stride])
        position += stride
        _unfilter(filter_type, line, previous, channels)
        rows.append(line)
        previous = line
    pixels = bytearray(width * height * 3)
    for y, line in enumerate(rows):
        base = y * width * 3
        if channels == 3:
            pixels[base : base + width * 3] = line
        elif channels == 4:
            for x in range(width):
                source = x * 4
                target = base + x * 3
                pixels[target : target + 3] = line[source : source + 3]
        else:
            for x in range(width):
                value = line[x * channels]
                target = base + x * 3
                pixels[target : target + 3] = bytes((value, value, value))
    return Raster(width, height, pixels)


def _unfilter(filter_type: int, line: bytearray, previous: bytearray, channels: int) -> None:
    stride = len(line)
    if filter_type == 0:
        return
    if filter_type == 1:
        for index in range(channels, stride):
            line[index] = (line[index] + line[index - channels]) & 0xFF
        return
    if filter_type == 2:
        for index in range(stride):
            line[index] = (line[index] + previous[index]) & 0xFF
        return
    if filter_type == 3:
        for index in range(stride):
            left = line[index - channels] if index >= channels else 0
            line[index] = (line[index] + ((left + previous[index]) >> 1)) & 0xFF
        return
    if filter_type == 4:
        for index in range(stride):
            left = line[index - channels] if index >= channels else 0
            up = previous[index]
            up_left = previous[index - channels] if index >= channels else 0
            estimate = left + up - up_left
            pa, pb, pc = abs(estimate - left), abs(estimate - up), abs(estimate - up_left)
            predictor = left if (pa <= pb and pa <= pc) else (up if pb <= pc else up_left)
            line[index] = (line[index] + predictor) & 0xFF
        return
    raise PngError(f"未知 PNG 过滤器 {filter_type}")


def fit(raster: Raster, max_width: int, max_height: int) -> Raster:
    scale = min(max_width / raster.width, max_height / raster.height, 1.0)
    if scale >= 1.0:
        return raster
    width = max(1, int(raster.width * scale))
    height = max(1, int(raster.height * scale))
    pixels = bytearray(width * height * 3)
    for y in range(height):
        source_y = min(raster.height - 1, int(y / scale))
        for x in range(width):
            source_x = min(raster.width - 1, int(x / scale))
            source = (source_y * raster.width + source_x) * 3
            target = (y * width + x) * 3
            pixels[target : target + 3] = raster.pixels[source : source + 3]
    return Raster(width, height, pixels)


def compose_sheet(
    cube: Cube,
    *,
    source: Raster | None = None,
    label_height: int = 6,
) -> Raster:
    """原图在上、套用后在中、色块对照在下。"""
    chart = source or test_chart()
    painted = apply_cube(cube, chart)
    swatches = swatch_pairs(cube)
    cell = max(1, chart.width // len(swatches))
    band = cell
    width = chart.width
    height = chart.height * 2 + label_height * 2 + band
    pixels = bytearray(width * height * 3)

    def blit(raster: Raster, top: int) -> None:
        stride = raster.width * 3
        for y in range(raster.height):
            start = (top + y) * width * 3
            pixels[start : start + stride] = raster.pixels[y * stride : (y + 1) * stride]

    blit(chart, 0)
    blit(painted, chart.height + label_height)
    band_top = chart.height * 2 + label_height * 2
    for index, (before, after) in enumerate(swatches):
        left = index * cell
        for y in range(band):
            row = (band_top + y) * width * 3
            colour = before if (y * 2) // band == 0 else after
            for x in range(cell):
                target = row + (left + x) * 3
                if target + 3 <= len(pixels):
                    pixels[target : target + 3] = bytes(colour)
    return Raster(width, height, pixels)


def load_cube(path: Path | str) -> Cube:
    return parse_cube(Path(path).read_text(encoding="utf-8", errors="replace"))
