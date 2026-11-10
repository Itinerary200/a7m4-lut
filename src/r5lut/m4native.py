"""A7M4 原生参数联合搜索:用官方 116 个方向补掉网格够不到的残差。

每一步都走官方合同:
  `native_family.safe()` 生成合法原生点(单调性/幅度检查 + `verify_raw`),
  `chart_native()` 重算相机前段,
  网格在冻结模型上重拟合,
  最终分数按相机 129³ 表路径计算。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .paths import ensure_path

ensure_path("vendor", "m4")


@dataclass
class Round:
    index: int
    de00: float
    mae8: float
    weights_l1: float
    note: str = ""


@dataclass
class Result:
    native: dict[str, Any]
    grid: np.ndarray
    de00: float
    mae8: float
    rounds: list[Round] = field(default_factory=list)


class NativeSearch:
    """在 116 个官方原生方向上做整数步进 + 网格重拟合。"""

    def __init__(
        self,
        camera: Any,
        model: Any,
        seed: dict[str, Any],
        target: Any,
        neutral_base: Any,
        mask: Any,
        *,
        fit_steps: int = 1000,
        table_steps: int = 150,
        samples: int = 2048,
    ) -> None:
        from . import m4fit

        self.camera = camera
        self.model = model
        self.m4fit = m4fit
        self.family = __import__("native_family")
        self.seed = seed
        self.target = np.asarray(target, dtype=np.float64)
        self.neutral_base = np.asarray(neutral_base, dtype=np.float64)
        self.mask = mask
        self.fit_steps = fit_steps
        self.table_steps = table_steps
        self.samples = samples
        self._paths: dict[int, Any] = {}
        self._front, self._split, _design = m4fit.load_front(Path(str(model.assets)))

    # ---- 相机前段与评分 -------------------------------------------------
    def base_of(self, native: dict[str, Any]) -> Any:
        return self.model.native_base(self.camera.chart_native(native))

    def path_of(self, base: Any, samples: int | None = None) -> Any:
        if samples is None:
            key = -1
            if key not in self._paths:
                self._paths[key] = self.m4fit.TablePath(self.model, base)
            return self._paths[key]
        return self.m4fit.TablePath(self.model, base, self._subset(samples))

    def _subset(self, samples: int) -> Any:
        rng = np.random.default_rng(20261110)
        return np.sort(rng.choice(len(self.target), min(samples, len(self.target)), replace=False))

    def evaluate(self, base: Any, grid: Any) -> Any:
        path = self.path_of(base)
        return np.asarray(path.outputs(grid).detach().cpu().numpy())

    def fit(self, base: Any, centre: Any | None = None) -> tuple[Any, dict[str, Any]]:
        grid, audit = self.m4fit.fit(
            Path(str(self.model.assets)),
            self.target,
            self._front,
            steps=self.fit_steps,
            samples=8192,
            base=base,
            centre=centre,
            stratified=False,
        )
        refiner = self.m4fit.TableFit(self.model, base, self.target, samples=8192)
        grid, _ = refiner.refine(grid, steps=self.table_steps)
        return grid, audit

    def score(self, base: Any, grid: Any) -> tuple[float, float]:
        from perceptual import de2000, to_lab

        pred = self.evaluate(base, grid)
        a = np.clip(pred[self.mask], 0, 255)
        b = np.clip(self.target[self.mask], 0, 255)
        return (
            float(de2000(to_lab(a), to_lab(b)).mean()),
            float(np.abs(a - b).mean()),
        )

    # ---- 116 方向雅可比与整数贪心 ---------------------------------------
    def jacobian(self, native: dict[str, Any], base: Any, grid: Any, ids: Any) -> tuple[Any, Any]:
        baseline = np.asarray(
            self.m4fit.TablePath(self.model, base, ids).outputs(grid).detach().cpu().numpy()
        )
        zero = np.zeros(self.family.DIMENSION)
        columns = []
        for axis in range(self.family.DIMENSION):
            probe = zero.copy()
            probe[axis] = 1.0
            try:
                _, candidate = self.family.safe(native, zero, probe)
                moved_base = self.base_of(candidate)
                moved = np.asarray(
                    self.m4fit.TablePath(self.model, moved_base, ids)
                    .outputs(grid)
                    .detach()
                    .cpu()
                    .numpy()
                )
            except ValueError:
                moved = baseline
            columns.append(moved - baseline)
        return baseline, np.stack(columns)

    @staticmethod
    def greedy(residual: Any, columns: Any, budget: int = 12, amplitude: int = 2) -> np.ndarray:
        weights = np.zeros(columns.shape[0])
        current = np.asarray(residual, dtype=np.float64).reshape(-1)
        best_cost = float((current**2).sum())
        for _ in range(budget):
            choice: tuple[int, int, float, Any] | None = None
            for axis, column in enumerate(columns):
                flat = np.asarray(column, dtype=np.float64).reshape(-1)
                for direction in (-1, 1):
                    if abs(weights[axis] + direction) > amplitude:
                        continue
                    trial = current + direction * flat
                    cost = float((trial**2).sum())
                    if choice is None or cost < choice[2]:
                        choice = (axis, direction, cost, trial)
            if choice is None or choice[2] >= best_cost - 1e-12:
                break
            axis, direction, best_cost, current = choice
            weights[axis] += direction
        return weights

    # ---- 主循环 ---------------------------------------------------------
    def run(self, rounds: int = 3, budget: int = 12) -> Result:
        native = self.seed
        weights = np.zeros(self.family.DIMENSION)
        history: list[Round] = []
        best: Result | None = None
        grid: Any = None
        for index in range(rounds):
            base = self.base_of(native)
            grid, _ = self.fit(base, centre=grid)
            de00, mae8 = self.score(base, grid)
            total = float(np.abs(weights).sum())
            history.append(Round(index, round(de00, 3), round(mae8, 3), total))
            if best is None or de00 < best.de00:
                best = Result(native, grid, de00, mae8, list(history))
            if index == rounds - 1 or best.de00 < 1.0:
                break
            ids = self._subset(self.samples)
            baseline, columns = self.jacobian(native, base, grid, ids)
            residual = self.target[ids] - baseline
            step = self.greedy(residual, columns, budget=budget)
            history.append(
                Round(
                    index,
                    round(de00, 3),
                    round(mae8, 3),
                    float(np.abs(weights).sum()),
                    f"雅可比L1={float(np.abs(step).sum()):.0f} "
                    f"残差={float(np.linalg.norm(residual)):.0f}",
                )
            )
            if not np.any(step):
                history.append(
                    Round(
                        index,
                        round(de00, 3),
                        round(mae8, 3),
                        float(np.abs(weights).sum()),
                        "无有效方向",
                    )
                )
                break
            try:
                point, candidate = self.family.safe(native, weights, weights + step)
            except ValueError as exc:
                history.append(
                    Round(
                        index,
                        round(de00, 3),
                        round(mae8, 3),
                        float(np.abs(weights).sum()),
                        f"拒绝:{exc}",
                    )
                )
                break
            native, weights = candidate, point
        assert best is not None
        best.rounds = history
        return best
