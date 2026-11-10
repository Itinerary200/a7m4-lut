"""视觉层:照搬 CubeLUT Studio 的界面外观。

装了开源主题引擎 ttkbootstrap(MIT)就借用它的主题与强调色;没装时同一套布局
退回原生 ttk,程序照样能跑。

    theme = apply(root, "浅色 · Bootstrap")
    theme.button(parent, "开始转换", command, kind="primary")
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

_tb: Any = None
try:  # 可选依赖,永不强制
    import ttkbootstrap as _tb_engine

    _tb = _tb_engine
except Exception:  # noqa: BLE001 - 导入失败只意味着"没有主题引擎"
    _tb = None

HAVE_THEME_ENGINE = _tb is not None

IS_MAC = sys.platform == "darwin"
IS_WINDOWS = sys.platform.startswith("win")

THEMES: dict[str, str] = {
    "浅色 · Bootstrap": "bootstrap-light",
    "深色 · Bootstrap": "bootstrap-dark",
    "浅色 · One": "one-light",
    "深色 · One": "one-dark",
    "浅色 · Nord": "nord-light",
    "深色 · Catppuccin": "catppuccin-dark",
    "浅色 · Gruvbox": "gruvbox-light",
    "深色 · Dracula": "dracula-dark",
}
DEFAULT_THEME_LABEL = "浅色 · Bootstrap"

FALLBACK = {
    "background": "#f6f7f9",
    "surface": "#ffffff",
    "text": "#1f2328",
    "muted": "#5b6470",
    "accent": "#0d6efd",
    "border": "#d7dbe0",
}


def ui_fonts() -> tuple[tuple[Any, ...], tuple[Any, ...], tuple[Any, ...]]:
    """本机存在的正文/标题/等宽字体(缺字体只是不够精致,不会出错)。"""
    if IS_MAC:
        return (("PingFang SC", 13), ("PingFang SC", 24, "bold"), ("Menlo", 11))
    if IS_WINDOWS:
        return (("Microsoft YaHei UI", 10), ("Microsoft YaHei UI", 18, "bold"), ("Consolas", 9))
    return (("Noto Sans CJK SC", 10), ("Noto Sans CJK SC", 18, "bold"), ("DejaVu Sans Mono", 9))


FONT, FONT_TITLE, FONT_MONO = ui_fonts()
FONT_SECTION = (FONT[0], FONT[1], "bold")


def theme_labels() -> list[str]:
    """主题下拉框的选项(没主题引擎时只有一项)。"""
    return list(THEMES) if HAVE_THEME_ENGINE else ["原生 ttk"]


def open_path(path: str) -> None:
    """在资源管理器/Finder 里打开目录。"""
    if IS_MAC:
        subprocess.Popen(["open", path])
    elif IS_WINDOWS:
        os.startfile(path)  # 只在 Windows 上存在
    else:
        subprocess.Popen(["xdg-open", path])


def wants_ico() -> bool:
    """Windows 用 .ico 设窗口图标,macOS/X11 用 PNG。"""
    return IS_WINDOWS


class Theme:
    """薄封装:颜色 + 界面需要的几个控件工厂。"""

    def __init__(self, root: tk.Misc, label: str = DEFAULT_THEME_LABEL) -> None:
        self.root = root
        self.name = label if HAVE_THEME_ENGINE else "原生 ttk"
        self._style: Any = None
        if HAVE_THEME_ENGINE:
            self._style = _tb.Style(themename=THEMES.get(label, THEMES[DEFAULT_THEME_LABEL]))
        else:
            self._style = ttk.Style(root)
            self._apply_fallback()
        self.colors = self._read_colors()

    def _read_colors(self) -> dict[str, str]:
        if self._style is None:
            return dict(FALLBACK)
        colors = dict(FALLBACK)
        for key, style_name, option in (
            ("background", "TFrame", "background"),
            ("surface", "TFrame", "background"),
            ("text", "TLabel", "foreground"),
            ("muted", "TLabel", "foreground"),
            ("accent", "TButton", "background"),
            ("border", "TLabelframe", "bordercolor"),
        ):
            value = self._style.lookup(style_name, option)
            if isinstance(value, str) and value.startswith("#"):
                colors[key] = value
        return colors

    @property
    def background(self) -> str:
        return self.colors["background"]

    @property
    def surface(self) -> str:
        return self.colors["surface"]

    def button(
        self, parent: Any, text: str, command: Callable[[], None], *, kind: str = "default"
    ) -> Any:
        if HAVE_THEME_ENGINE:
            return _tb.Button(
                parent,
                text=text,
                command=command,
                bootstyle="primary" if kind == "primary" else "secondary-outline",
            )
        return ttk.Button(parent, text=text, command=command)

    def label(self, parent: Any, text: str, *, kind: str = "body", **kwargs: Any) -> Any:
        style_map = {"title": "Title.TLabel", "hint": "Hint.TLabel", "body": "Body.TLabel"}
        if HAVE_THEME_ENGINE:
            bootstyle = {"hint": "secondary", "body": "default", "title": "default"}.get(
                kind, "default"
            )
            font = {"title": FONT_TITLE, "hint": FONT, "body": FONT}.get(kind, FONT)
            return _tb.Label(parent, text=text, bootstyle=bootstyle, font=font, **kwargs)
        return ttk.Label(parent, text=text, style=style_map.get(kind, "Body.TLabel"), **kwargs)

    def frame(self, parent: Any, **kwargs: Any) -> Any:
        return ttk.Frame(parent, **kwargs)

    def card(self, parent: Any, title: str) -> Any:
        if HAVE_THEME_ENGINE:
            return _tb.Labelframe(parent, text=title, bootstyle="secondary", padding=10)
        return ttk.Labelframe(parent, text=title, padding=10)

    def configure(self, style_name: str, **options: Any) -> None:
        """通过当前主题引擎配置 ttk 样式,避免另起一个 Style。"""
        if self._style is not None:
            self._style.configure(style_name, **options)

    def progress(self, parent: Any, **kwargs: Any) -> Any:
        if HAVE_THEME_ENGINE:
            return _tb.Progressbar(parent, bootstyle="primary", **kwargs)
        return ttk.Progressbar(parent, **kwargs)

    def switch(self, label: str) -> None:
        if not HAVE_THEME_ENGINE:
            return
        theme_id = THEMES.get(label)
        if theme_id is None:
            return
        self.name = label
        self._style.theme_use(theme_id)
        self.colors = self._read_colors()

    def _apply_fallback(self) -> None:
        style = self._style
        assert style is not None
        with contextlib.suppress(tk.TclError):
            style.theme_use("vista")
        style.configure(".", font=FONT)
        style.configure("Body.TLabel", font=FONT, foreground=FALLBACK["text"])
        style.configure("Title.TLabel", font=FONT_TITLE, foreground=FALLBACK["text"])
        style.configure("Hint.TLabel", font=FONT, foreground=FALLBACK["muted"])


def apply(root: tk.Misc, label: str = DEFAULT_THEME_LABEL) -> Theme:
    """给窗口装上主题,返回对应的 Theme。"""
    return Theme(root, label)
