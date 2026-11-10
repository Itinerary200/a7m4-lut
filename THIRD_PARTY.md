# 第三方组件与许可

本仓库只分发自有代码。下面这些是被引用或 vendored 的第三方内容，各自遵循原许可。

## 代码

| 位置 | 来源 | 许可 | 说明 |
|---|---|---|---|
| `engine/` | [Hearts-Ace/sony-r5-colorlab](https://github.com/Hearts-Ace/sony-r5-colorlab) | **AGPL-3.0** | A7R V 侧训练引擎的 vendored 副本。引用它的发行物须按 AGPL-3.0 传染性处理。原文见 `engine/LICENSE.orig-agpl3.txt`，改动见 `engine/VENDORED-NOTES.md`。 |
| `vendor/m4/` | [Erlla/sony-a7m4-custom-firmware](https://github.com/Erlla/sony-a7m4-custom-firmware) | 遵循上游 | `look_v2.py`、`native_codec.py`、`response_network.py`、`pixel_bridge.py`、`host_grid.py`、`grid_base.py`、`grid_math.py`、`photo_profiles.json` 逐字副本，见 `vendor/m4/PROVENANCE.md`。 |
| `src/r5lut/looktheme.py` | 本项目改写自 [CubeLUT Studio](https://github.com/) 的主题层 | MIT | 只取外观与控件封装，不依赖其包。 |

## 运行时依赖（不 vendored，用户自行安装）

| 包 | 许可 | 用途 |
|---|---|---|
| PyTorch | BSD-3-Clause | 拟合 405 参数用的自动微分 |
| NumPy | BSD-3-Clause | 数组与三线性插值 |
| ttkbootstrap | MIT | 主题控件 |
| Pillow | HPND | 预览图编码 / 截图 |
| PyInstaller | GPL-2.0 + 例外条款 | 打包 exe（仅构建期） |

## 数据资产（不分发）

| 资产 | 归属 | 说明 |
|---|---|---|
| `models/`（forward_model、grid_response、bridge/*） | 索尼 | M4 训练资产包内的冻结响应模型，仓库不包含 |
| `charts/`（sony_input.npz、design_pairs.npz） | 索尼 | 测量色卡与设计对，仓库不包含 |
| `native16/*.npy` | 本项目生成 | 由训练资产推算的 16bit 中性/黑白起点 |
| 各 `.cube` LUT | 各自作者 | 用户自备 |

## 商标

「SONY」「α」「A7M4」「S-Log3」「S-Gamut3」为索尼集团公司商标。
本项目为非官方工具，与索尼无隶属或背书关系。
