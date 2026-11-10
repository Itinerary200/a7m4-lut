"""界面基础件:临界阻尼弹簧、淡入、进度条与排版比例。

依据 apple-design 的几条硬规则:
  * 反馈在按下瞬间发生,不等松开;
  * 动效数值走弹簧(damping 1.0、response 0.30–0.40),天然可被中断/改目标;
  * 每次动画都从当前屏幕值起步,不跳变;
  * 系统关闭动画时(减少动效)直接落到终值。
"""

from __future__ import annotations

import time
import tkinter as tk
from collections.abc import Callable
from typing import Any

FRAME_MS = 16
DEFAULT_RESPONSE = 0.32
DEFAULT_DAMPING = 1.0


def reduce_motion(root: tk.Misc) -> bool:
    """Windows 的"显示动画"关闭时按减少动效处理。"""
    try:
        import ctypes

        enabled = ctypes.c_int(1)
        ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0)
        return not bool(enabled.value)
    except Exception:  # noqa: BLE001 - 非 Windows 或无权限
        return False


class Spring:
    """一维临界阻尼弹簧:retarget 时不跳变,速度连续。"""

    def __init__(
        self,
        start: float,
        on_update: Callable[[float], None],
        *,
        response: float = DEFAULT_RESPONSE,
        damping: float = DEFAULT_DAMPING,
        root: tk.Misc | None = None,
        instant: bool = False,
    ) -> None:
        self.value = float(start)
        self.target = float(start)
        self.velocity = 0.0
        self.on_update = on_update
        self.response = response
        self.damping = damping
        self.instant = instant
        self._root = root
        self._running = False
        self._last = time.monotonic()

    def retarget(self, value: float, *, velocity: float | None = None) -> None:
        self.target = float(value)
        if velocity is not None:
            self.velocity = float(velocity)
        if self.instant:
            self.value = self.target
            self.on_update(self.value)
            return
        if not self._running:
            self._running = True
            self._last = time.monotonic()
            self._schedule()

    def snap(self, value: float) -> None:
        self.target = value
        self.value = value
        self.velocity = 0.0
        self.on_update(self.value)

    # 弹簧积分:ω = 2π/response,ζ = damping
    def _schedule(self) -> None:
        if self._root is not None:
            self._root.after(FRAME_MS, self._tick)
        else:
            self._tick()

    def _tick(self) -> None:
        now = time.monotonic()
        dt = min(0.05, now - self._last)
        self._last = now
        omega = 6.283185307179586 / max(0.05, self.response)
        zeta = self.damping
        displacement = self.value - self.target
        accel = -omega * omega * displacement - 2.0 * zeta * omega * self.velocity
        self.velocity += accel * dt
        self.value += self.velocity * dt
        if abs(self.value - self.target) < 0.25 and abs(self.velocity) < 2.0:
            self.value = self.target
            self.velocity = 0.0
            self._running = False
            self.on_update(self.value)
            return
        self.on_update(self.value)
        self._schedule()


class FadeIn:
    """预览入场:弹簧位移(Canvas 图像不支持 stipple/alpha,所以用位移表达"落位")。"""

    def __init__(self, canvas: tk.Canvas, root: tk.Misc, instant: bool = False) -> None:
        self.canvas = canvas
        self.root = root
        self.instant = instant
        self.item: int | None = None
        self.image: Any = None

    def show(self, image: Any, *, offset: int = 14) -> None:
        self.canvas.delete("all")
        self.image = image
        self.item = self.canvas.create_image(
            0, 0 if self.instant else -offset, image=image, anchor="nw"
        )
        if self.instant:
            return
        spring = Spring(float(offset), self._move, root=self.root, response=0.32)
        spring.retarget(0.0)

    def _move(self, value: float) -> None:
        if self.item is not None:
            self.canvas.coords(self.item, 0, -int(round(value)))


class ProgressBar(tk.Canvas):
    """细进度条:确定值走弹簧,不确定时走来回扫。"""

    def __init__(self, parent: tk.Misc, *, width: int = 320, height: int = 4) -> None:
        super().__init__(
            parent, width=width, height=height, highlightthickness=0, bd=0, background="#f2f2f2"
        )
        self._track = self.create_rectangle(0, 0, width, height, fill="#e6e6e6", width=0)
        self._fill = self.create_rectangle(0, 0, 0, height, fill="#0a84ff", width=0)
        self._width = width
        self._height = height
        self._fraction = 0.0
        self._marquee = False
        self._marquee_pos = 0.0
        self._root = parent.winfo_toplevel()
        self._instant = reduce_motion(self._root)
        self._spring = Spring(
            0.0, self._render, root=self._root, response=0.3, instant=self._instant
        )

    def set_fraction(self, value: float) -> None:
        self._fraction = max(0.0, min(1.0, value))
        self._spring.retarget(self._fraction)

    def start_indeterminate(self) -> None:
        self._marquee = True
        self._animate_marquee()

    def stop_indeterminate(self) -> None:
        self._marquee = False
        self.set_fraction(1.0)

    def _render(self, value: float) -> None:
        self.coords(self._fill, 0, 0, max(0.0, value) * self._width, self._height)

    def _animate_marquee(self) -> None:
        if not self._marquee:
            return
        span = 0.3
        self._marquee_pos = (self._marquee_pos + 0.03) % 1.0
        left = max(0.0, self._marquee_pos - span / 2)
        right = min(1.0, self._marquee_pos + span / 2)
        self.coords(self._fill, left * self._width, 0, right * self._width, self._height)
        step = 40 if self._instant else 24
        self.after(step, self._animate_marquee)


FONTS: dict[str, tuple[str, int, str]] = {
    "display": ("Segoe UI Variable Display", 16, "bold"),
    "title": ("Segoe UI Variable Text", 12, "bold"),
    "body": ("Segoe UI Variable Text", 10, "normal"),
    "caption": ("Segoe UI Variable Text", 9, "normal"),
    "mono": ("Cascadia Mono", 9, "normal"),
}
