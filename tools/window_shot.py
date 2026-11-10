"""按窗口句柄截取整个窗口(PrintWindow,支持被遮挡或半出屏的窗口)。"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def find_window(title_part: str) -> int:
    """按标题片段找第一个可见顶层窗口。"""
    result: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        if title_part in buffer.value:
            result.append(hwnd)
            return False
        return True

    user32.EnumWindows(callback, 0)
    return result[0] if result else 0


def capture(hwnd: int, out: Path) -> tuple[int, int]:
    """PrintWindow 抓完整窗口内容,返回像素尺寸。"""
    rect = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 0 or height <= 0:
        raise RuntimeError(f"窗口尺寸异常:{width}x{height}")

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", ctypes.c_uint32),
            ("biWidth", ctypes.c_int32),
            ("biHeight", ctypes.c_int32),
            ("biPlanes", ctypes.c_uint16),
            ("biBitCount", ctypes.c_uint16),
            ("biCompression", ctypes.c_uint32),
            ("biSizeImage", ctypes.c_uint32),
            ("biXPelsPerMeter", ctypes.c_int32),
            ("biYPelsPerMeter", ctypes.c_int32),
            ("biClrUsed", ctypes.c_uint32),
            ("biClrImportant", ctypes.c_uint32),
        ]

    header = BITMAPINFOHEADER()
    header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    header.biWidth = width
    header.biHeight = -height
    header.biPlanes = 1
    header.biBitCount = 32

    hdc_window = user32.GetWindowDC(hwnd)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_window)
    bitmap = gdi32.CreateCompatibleBitmap(hdc_window, width, height)
    gdi32.SelectObject(hdc_mem, bitmap)
    user32.PrintWindow(hwnd, hdc_mem, 2)  # PW_RENDERFULLCONTENT

    buffer = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(hdc_mem, bitmap, 0, height, buffer, ctypes.byref(header), 0)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(hwnd, hdc_window)

    # BGRA → PNG(用项目自带的编码器,避免额外依赖)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from r5lut import preview

    pixels = bytearray(width * height * 3)
    raw = buffer.raw
    for y in range(height):
        row = y * width * 4
        target = y * width * 3
        for x in range(width):
            source = row + x * 4
            pixels[target + x * 3] = raw[source + 2]
            pixels[target + x * 3 + 1] = raw[source + 1]
            pixels[target + x * 3 + 2] = raw[source]
    raster = preview.Raster(width=width, height=height, pixels=pixels)
    out.write_bytes(preview.encode_png(raster))
    return width, height


def main() -> int:
    title = sys.argv[1] if len(sys.argv) > 1 else "A7M4 LUT"
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "out/window.png")
    hwnd = find_window(title)
    if not hwnd:
        print(f"未找到窗口:{title}")
        return 1
    width, height = capture(hwnd, out)
    print(f"已截图 {out} ({width}x{height})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
