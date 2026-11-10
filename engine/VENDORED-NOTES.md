# vendored 说明(R5 训练引擎)

本目录是 [Hearts-Ace/sony-r5-colorlab](https://github.com/Hearts-Ace/sony-r5-colorlab)
(其为 [Hearts-Ace/sony-a7r5-custom-firmware](https://github.com/Hearts-Ace/sony-a7r5-custom-firmware)
的滤镜训练与网格工作台)的 vendored 副本,zipball 取自 main 分支(2026-11-08)。

## 许可

- 上游代码与数据: **GNU AGPL v3**(`LICENSE.orig-agpl3.txt`);数值来源见 `PROVENANCE.md`,
  训练方法见 `TRAINING.md`。
- 我们加的文件:`_r5_runner.py`(子进程调用入口,供 `cubejson.r5` 使用)、本说明。
- 引用本目录的发行物须按 AGPL-3.0 的传染性处理;`cubejson` 其余部分不受影响(MIT)。

## 与本仓库的边界

- `cubejson/r5.py` **不 import** 本目录任何模块;一律通过
  `python _r5_runner.py <stage> <job.json>` 子进程调用,stdout 为 UTF-8 JSON。
- 数据资产:模型 `web/data/r5/paired-20261107-nonlinear-he3.json`
  (sha256 `936af0b2…e677`)、色卡 `web/data/chart/sony100mp_5300k_v45/`
  (pairs.npz 预计算,99,372 色块)、PT 基线 `…/capture/`。
  原始 RAW(.gz)与 `data/training/frontend_capture` 未随包,训练不需要它们。

## 对上游的兼容性改动(最小集)

1. `web/gpu_runtime.py` `available()`:
   原代码在无 torch 时直接访问 `torch.backends.mps`;Windows/Linux CPU 构建没有该属性。
   已加 `hasattr` 守卫,行为不变(Mac Metal 仍可用)。
2. `web/measured_response.py` `_inference_ast()`:
   原代码用 locale 编码读自身源码算推理哈希;GBK locale 的 Windows 读 UTF-8
   中文注释会抛 UnicodeDecodeError。已固定 `encoding="utf-8"`(源码本身是 UTF-8,
   哈希值不变,与上游在 macOS 上的行为一致)。
3. `_r5_runner.py` 的 `compile`/`grid` stage:上游编译器用 locale 编码读 JSON,
   中文名称在 GBK/UTF-8 混合环境下会坏;runner 先以 utf-8(-sig) 读入、locale 兜底,
   再转 ASCII 转义临时文件喂给编译器;grid 阶段临时转 locale 副本供
   `firmware_config` 读取,结束后恢复 UTF-8。上游代码未动。
4. `web/fit_anchor_native.py`:梯度线程数原为硬编码 8;改为读环境变量
   `R5_GRADIENT_WORKERS`(1..64,缺省 8),用于多核机器单任务提速。
   `cubejson.r5` 的 `--gradient-workers`/批次工具会按并发数自动设置:
   单任务 16、并发 8。
5. GPU 设备选择(本地兼容改动):上游只支持 Apple Metal(MPS)与 AMD ROCm,
   `device='mps'` 在多处硬编码。已改为运行时解析 `gpu_runtime.device()`
   (mps → cuda → cpu),涉及 `gpu_runtime/apple_gpu/gpu_tensor/gpu_alternation/
   gpu_optimizer/gpu_color/gpu_grid/gpu_grid_refine/gamma_global_correction/
   gamma_color_recovery/continuity_grid/compute_backend/batch_multiround/
   compressed_alternation/stack_training`;`gpu_native` 仍是 Metal 专用,
   `render_native` 仅在 device=='mps' 时调用它。实测 RTX 4060 上 quick 单任务
   11 分钟 → 5.3 分钟(约 2.1x)。

其余文件与上游逐字节一致;上游自带的 `smoke_fit.py`、`formal_profile.json`
保留在 `src/r5colorlab/` 供对照。

## 依赖

- 必需:numpy、scipy、threadpoolctl(上游 requirements.txt 漏列)、tifffile(TIFF 目标)。
- 可选:torch(`pip install torch --index-url https://download.pytorch.org/whl/cpu`)。
  `gamma_global_correction` 阶段的自动微分在 CPU 上走 torch-cpu;
  无 torch 时该阶段报错,因此训练机上建议装 torch-cpu。
