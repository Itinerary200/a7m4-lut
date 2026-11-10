"""R5 创意外观转换 · 图形界面(单窗口,无历史包袱)。"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from . import core, preview


def _enable_dpi_awareness() -> None:
    """让 Windows 按物理像素渲染,否则高分屏上字体是位图拉伸,发虚。"""
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor v2
        except Exception:  # noqa: BLE001
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:  # noqa: BLE001 - 纯显示效果,失败无害
        pass


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("R5 创意外观转换 · cube → 固件滤镜 JSON/BIN")
        self.geometry("760x560")
        self.minsize(680, 480)
        try:
            dpi = self.winfo_fpixels("1i")
            self.tk.call("tk", "scaling", dpi / 72.0)
        except Exception:  # noqa: BLE001
            pass
        self.queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.out_dir: Path | None = None
        self._build()
        self.after(150, self._drain)

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.geometry("1280x800")

        main = ttk.Frame(self)
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(3, weight=1)

        left = ttk.Frame(main)
        left.grid(row=0, column=0, rowspan=2, sticky="nsew")
        left.columnconfigure(0, weight=1)
        left.rowconfigure(3, weight=1)

        head = ttk.Frame(left, padding=(14, 12, 14, 4))
        head.grid(row=0, column=0, sticky="ew")
        ttk.Label(
            head,
            text="目标:.cube(创意外观 S-Log3 变换)或色卡同尺寸 TIFF/JPG(11648×8736);"
            "输出:固件格式 native_config.json + R5NATIVE.BIN",
            wraplength=680,
        ).pack(anchor="w")

        form = ttk.LabelFrame(left, text=" 参数 ", padding=(10, 6))
        form.grid(row=1, column=0, sticky="ew", padx=14)
        form.columnconfigure(1, weight=1)

        self.target_var = tk.StringVar()
        ttk.Label(form, text="目标 .cube").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Entry(form, textvariable=self.target_var).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(form, text="选…", command=self._pick_cube).grid(row=0, column=2)

        self.image_var = tk.StringVar()
        ttk.Label(form, text="或目标图 TIFF/JPG").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(form, textvariable=self.image_var).grid(row=1, column=1, sticky="ew", padx=6)
        ttk.Button(form, text="选…", command=self._pick_image).grid(row=1, column=2)

        self.number_var = tk.IntVar(value=1)
        self.short_var = tk.StringVar()
        self.full_var = tk.StringVar()
        row = ttk.Frame(form)
        row.grid(row=2, column=0, columnspan=3, sticky="ew", pady=3)
        ttk.Label(row, text="槽位").pack(side="left")
        spin = ttk.Spinbox(row, from_=1, to=12, textvariable=self.number_var, width=5)
        spin.pack(side="left", padx=(4, 12))
        ttk.Label(row, text="简称").pack(side="left")
        ttk.Entry(row, textvariable=self.short_var, width=12).pack(side="left", padx=(4, 12))
        ttk.Label(row, text="全称").pack(side="left")
        full_entry = ttk.Entry(row, textvariable=self.full_var)
        full_entry.pack(side="left", fill="x", expand=True, padx=(4, 0))

        self.out_var = tk.StringVar()
        ttk.Label(form, text="输出目录").grid(row=3, column=0, sticky="w", pady=3)
        ttk.Entry(form, textvariable=self.out_var).grid(row=3, column=1, sticky="ew", padx=6)
        ttk.Button(form, text="选…", command=self._pick_out).grid(row=3, column=2)

        flags = ttk.Frame(form)
        flags.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        self.quick_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(flags, text="草稿档(快速拟合,不带 PC/网格)", variable=self.quick_var).pack(
            side="left"
        )
        ttk.Label(flags, text="   预算").pack(side="left")
        self.budget_var = tk.StringVar(value="balanced")
        ttk.Combobox(
            flags,
            textvariable=self.budget_var,
            width=10,
            state="readonly",
            values=("balanced", "formal"),
        ).pack(side="left", padx=(2, 12))
        ttk.Label(flags, text="目标 mae8").pack(side="left")
        self.aim_var = tk.StringVar(value="6")
        ttk.Entry(flags, textvariable=self.aim_var, width=6).pack(side="left", padx=(2, 0))
        ttk.Label(flags, text="(验证集达标即提前停止,留空=不限)").pack(side="left", padx=(4, 0))

        actions = ttk.Frame(left, padding=(14, 8))
        actions.grid(row=2, column=0, sticky="new")
        actions.columnconfigure(1, weight=1)
        self.run_button = ttk.Button(actions, text="开始转换", command=self._start)
        self.run_button.grid(row=0, column=0, sticky="w")
        self.verify_button = ttk.Button(actions, text="资产检查", command=self._verify)
        self.verify_button.grid(row=0, column=1, sticky="w", padx=8)
        self.open_button = ttk.Button(
            actions, text="打开输出目录", command=self._open_out, state="disabled"
        )
        self.open_button.grid(row=0, column=2, sticky="w")

        log_frame = ttk.LabelFrame(left, text=" 进度与结果 ", padding=(8, 4))
        log_frame.grid(row=3, column=0, sticky="nsew", padx=14, pady=(0, 12))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log = tk.Text(log_frame, height=10, wrap="word", state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.grid(row=0, column=1, sticky="ns")
        self.status = ttk.Label(left, text="就绪", padding=(14, 0, 14, 6))
        self.status.grid(row=4, column=0, sticky="w")

        # ---- 右侧:颜色预览 ----
        right = ttk.LabelFrame(main, text=" 颜色预览 ", padding=(8, 6))
        right.grid(row=0, column=1, rowspan=2, sticky="ns", padx=(0, 12), pady=(12, 0))
        self.photo: tk.PhotoImage | None = None
        self.preview_source: preview.Raster | None = None
        self.preview_cube: preview.Cube | None = None
        self.preview_sheet: preview.Raster | None = None
        self.preview_scale: float = 1.0

        self.preview_canvas = tk.Canvas(
            right, width=340, height=420, background="#f2f2f2", highlightthickness=0
        )
        self.preview_canvas.grid(row=0, column=0, sticky="n")
        self.preview_canvas.bind("<Button-1>", self._preview_click)
        self.preview_info = ttk.Label(right, text="选一个 .cube 目标后自动生成预览", wraplength=340)
        self.preview_info.grid(row=1, column=0, sticky="w", pady=(6, 0))
        buttons = ttk.Frame(right)
        buttons.grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Button(buttons, text="载入图…", command=self._pick_preview_image).pack(side="left")
        ttk.Button(buttons, text="保存预览", command=self._save_preview).pack(side="left", padx=6)
        ttk.Button(buttons, text="刷新", command=self._refresh_preview).pack(side="left")

    def _say(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _pick_cube(self) -> None:
        chosen = filedialog.askopenfilename(
            title="选择目标 .cube", filetypes=[("CUBE", "*.cube"), ("全部", "*.*")]
        )
        if chosen:
            self.target_var.set(chosen)
            self.image_var.set("")
            stem = Path(chosen).stem
            self.short_var.set(stem[:23]) if not self.short_var.get() else None
            self.full_var.set(stem) if not self.full_var.get() else None
            self._refresh_preview()

    def _pick_image(self) -> None:
        chosen = filedialog.askopenfilename(
            title="选择目标图(11648×8736)", filetypes=[("图像", "*.tif *.tiff *.jpg *.jpeg")]
        )
        if chosen:
            self.image_var.set(chosen)
            self.target_var.set("")
            stem = Path(chosen).stem
            self.short_var.set(stem[:23]) if not self.short_var.get() else None
            self.full_var.set(stem) if not self.full_var.get() else None

    def _refresh_preview(self) -> None:
        cube_path = self.target_var.get().strip()
        if not cube_path or not Path(cube_path).is_file():
            self.preview_info.configure(text="选一个 .cube 目标后自动生成预览")
            self.preview_canvas.delete("all")
            return
        try:
            cube = preview.load_cube(cube_path)
        except Exception as exc:  # noqa: BLE001
            self.preview_info.configure(text=f"读不了 cube:{exc}")
            return
        self.preview_cube = cube
        source = self.preview_source or preview.test_chart()
        sheet = preview.compose_sheet(cube, source=source)
        self.preview_sheet = sheet
        display = preview.fit(sheet, 340, 420)
        self.preview_scale = display.width / sheet.width
        png = preview.encode_png(display)
        self.photo = tk.PhotoImage(data=png)
        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(0, 0, anchor="nw", image=self.photo)
        self.preview_info.configure(text="点图上任意位置看转换结果")

    def _preview_click(self, event: tk.Event[tk.Misc]) -> None:
        sheet = self.preview_sheet
        cube = self.preview_cube
        if sheet is None or cube is None:
            return
        scale = self.preview_scale or 1.0
        x = min(sheet.width - 1, max(0, int(event.x / scale)))
        y = min(sheet.height - 1, max(0, int(event.y / scale)))
        chart = self.preview_source or preview.test_chart()
        chart_h = chart.height
        if y >= chart_h + 6:
            y = max(0, y - chart_h - 6)
        if y >= chart_h:
            y = chart_h - 1
        before = chart.get(min(chart.width - 1, x), y)
        after_f = preview.sample(cube, before[0] / 255.0, before[1] / 255.0, before[2] / 255.0)
        after = tuple(int(round(max(0.0, min(1.0, c)) * 255)) for c in after_f)
        self.preview_info.configure(
            text=f"原图 RGB({before[0]},{before[1]},{before[2]})  →  "
            f"套用后 RGB({after[0]},{after[1]},{after[2]})"
        )

    def _pick_preview_image(self) -> None:
        chosen = filedialog.askopenfilename(
            title="选择预览图(PNG)", filetypes=[("PNG", "*.png"), ("全部", "*.*")]
        )
        if not chosen:
            return
        try:
            data = Path(chosen).read_bytes()
            raster = preview.decode_png(data)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("读图失败", str(exc))
            return
        self.preview_source = preview.fit(raster, 640, 360)
        self._refresh_preview()

    def _save_preview(self) -> None:
        sheet = self.preview_sheet
        if sheet is None:
            messagebox.showinfo("没有预览", "先选一个 .cube 目标")
            return
        chosen = filedialog.asksaveasfilename(
            title="保存预览", defaultextension=".png", filetypes=[("PNG", "*.png")]
        )
        if not chosen:
            return
        Path(chosen).write_bytes(preview.encode_png(sheet))
        self._say(f"预览已保存: {chosen}")

    def _pick_out(self) -> None:
        chosen = filedialog.askdirectory(title="选择输出目录")
        if chosen:
            self.out_var.set(chosen)

    def _verify(self) -> None:
        try:
            checks = core.verify()
        except core.R5Error as exc:
            messagebox.showerror("检查失败", str(exc))
            return
        self._say("资产检查:" + ("全部通过" if checks["passed"] else "未通过"))
        for key, value in checks.items():
            if isinstance(value, dict) and "available" in value:
                self._say(f"  {key}: 可用={value['available']}")

    def _start(self) -> None:
        target = self.target_var.get().strip()
        image = self.image_var.get().strip()
        if bool(target) == bool(image):
            messagebox.showerror("参数不对", "目标 .cube 与 目标图 二选一")
            return
        source = Path(target or image)
        if not source.is_file():
            messagebox.showerror("参数不对", "目标文件不存在")
            return
        out_text = self.out_var.get().strip()
        out = Path(out_text) if out_text else source.parent / ("r5-" + source.stem)
        self.out_var.set(str(out))
        if (out / "input_audit.json").is_file():
            messagebox.showerror("输出目录冲突", "该目录已有训练任务")
            return
        quick = self.quick_var.get()
        if quick:
            budget = core.quick_budget()
        else:
            if self.budget_var.get() == "balanced":
                budget = core.balanced_budget()
            else:
                budget = core.formal_budget()
        aim = None
        aim_text = self.aim_var.get().strip()
        if aim_text and not quick:
            try:
                aim = float(aim_text)
            except ValueError:
                messagebox.showerror("参数不对", "目标 mae8 必须是数字")
                return
        self.run_button.configure(state="disabled")
        self.status.configure(text="转换中…")

        def work() -> None:
            try:
                result = core.train(
                    target or None,
                    out,
                    int(self.number_var.get()),
                    self.short_var.get().strip(),
                    self.full_var.get().strip(),
                    target_image=image or None,
                    budget=budget,
                    aim=aim,
                    pc=not quick,
                    grid=not quick,
                    progress=lambda p: self.queue.put(("progress", p)),
                )
                self.queue.put(("done", result))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("error", str(exc)))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _drain(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "progress" and isinstance(payload, dict):
                    stage = payload.get("stage", "")
                    extra = payload.get("round", "")
                    self.status.configure(text=f"{stage} {extra}".strip())
                elif kind == "done" and isinstance(payload, core.TrainResult):
                    result: core.TrainResult = payload
                    self.out_dir = result.out_dir
                    self._say(f"完成: {result.out_dir}")
                    self._say(
                        f"BIN: {result.finish['binary_bytes']} 字节 "
                        f"sha={result.finish['binary_sha256'][:16]}…"
                    )
                    final = (result.diagnostics or {}).get("final_tonal", {}).get("all")
                    if final:
                        self._say(
                            f"最终指标: mae8={final.get('mae'):.2f} "
                            f"dE00={final.get('perceptual', {}).get('delta_e00_mean'):.2f}"
                        )
                    for key, path in result.files.items():
                        self._say(f"产物 {key}: {path}")
                    self.open_button.configure(state="normal")
                    self.run_button.configure(state="normal")
                    self.status.configure(text="完成")
                elif kind == "error":
                    self.run_button.configure(state="normal")
                    self.status.configure(text="出错")
                    self._say(f"失败: {payload}")
                    messagebox.showerror("转换失败", str(payload))
        except queue.Empty:
            pass
        self.after(150, self._drain)

    def _open_out(self) -> None:
        if self.out_dir and self.out_dir.is_dir():
            import subprocess

            subprocess.Popen(["explorer", str(self.out_dir)])


def run() -> int:
    _enable_dpi_awareness()
    App().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
