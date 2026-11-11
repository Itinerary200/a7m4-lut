# A7M4 滤镜转换器

把调色用的 `.cube` LUT 转成索尼 **A7M4** 机内「创意外观」认识的 JSON，拷进 SD 卡就能用 ——
照片直出即是所见即所得，不用回电脑调色。

[![version](https://img.shields.io/badge/版本-1.4.0-0a84ff)](https://github.com/Itinerary200/a7m4-lut/releases)
[![license](https://img.shields.io/badge/许可-MIT-2f9e6f)](LICENSE)
[![platform](https://img.shields.io/badge/平台-Windows%2010%2F11-555)](https://github.com/Itinerary200/a7m4-lut/releases)
[![python](https://img.shields.io/badge/Python-3.10%2B-3776ab)](pyproject.toml)

![界面](docs/images/ui.png)

---

## 目录

- [快速开始](#快速开始)
- [它解决什么](#它解决什么)
- [支持哪些 LUT](#支持哪些-lut)
- [精度](#精度)
- [命令行](#命令行)
- [源码运行](#源码运行)
- [项目结构](#项目结构)
- [资产与许可](#资产与许可)
- [致谢](#致谢)

---

## 快速开始

1. 从 [Releases](https://github.com/Itinerary200/a7m4-lut/releases) 下载 `A7M4LUT.exe`，双击运行（免安装，不用装 Python）。
2. 「选择文件」挑 `.cube`（支持多选 / 文件夹 / ZIP）；填一个相机里显示的名字；选保存位置，点 **开始转换**。
3. 把输出文件夹里的 `PRIVATE/` 整个拷到 **SD 卡根目录**：

   ```
   SD 卡根目录/
   └─ PRIVATE/M4ROOT/GENERAL/LUT/<名字>.json
   ```

4. 插卡 → 相机菜单里选这个外观（机内共 16 槽）。

右侧「颜色预览」是 **原图 / 相机实际查表后的画面 / 色块对照**，点图上任意位置能读出
「转换前 → 转换后」的 RGB。两栏中间的竖条可以拖动改宽，预览图会跟着放大。

---

## 它解决什么

A7M4 的机内外观不是 `.cube`，而是一个 `camera-look v2` 的 JSON —— 里面不是 LUT 表，
而是 **405 个整数参数**（`parameters.grid`，3×5×9×9）。相机把这张网格烘焙成 129³ 的表，
再用三线性插值出画面。

所以「把 cube 塞进相机」不是格式转换，而是**反解**：

> 找一组 405 个整数，让「相机的烘焙 + 查表」输出尽量等于 cube 的结果。

本工具把相机这条真实路径写成可微形式，直接在冻结的官方响应模型上拟合这 405 个参数。
优化目标就是相机真实的 129³ 表 + 三线性插值，与官方 `bake + sample` 逐位一致（mae8 0.00）。

> **适用范围**：机内创意外观只作用在**照片 / 普通显示链路**。视频模式的 PP 值不在
> 这套机制里，因此它与 S-Log3 的高动态范围不兼容 —— 想要风格化就用普通模式直出，
> 想要 log 就别套风格。

---

## 支持哪些 LUT

### 输入：各家 log 曲线自动适配

不同品牌的 LUT 是按**自家 log 曲线**编码输入的，同一条曲线套错，画面立刻偏色。
工具内置 16 条曲线，并会自己判断这份 LUT 属于哪一种：

| 品牌 | 曲线 |
| --- | --- |
| 索尼 | S-Log3、S-Log2 |
| 佳能 | Canon Log2、Canon Log3 |
| 尼康 | N-Log |
| 松下 | V-Log |
| 富士 | F-Log、F-Log2、F-Log2C |
| ARRI | LogC3、LogC4 |
| 大疆 | D-Log、D-Log2、D-Log M |
| 影石 | I-Log |
| 徕卡 | L-Log |

判断方式有三层，逐层兜底：

1. 看文件名与 LUT 的 `TITLE` 关键词（`N-Log 转 Rec.709` 这种名字里带 Rec.709 的，
   也能认出输入其实是 N-Log）；
2. 从 **LUT 自身**反解曲线：灰阶从 0 走到 1，二分找「输出正好等于这个灰」的码值，
   残差 < 0.03 就采信（尼康实测 0.0010、索尼 LC-709 0.0003、佳能 CMTPQ 0.0000）；
3. 两条曲线各算一版，取色差更小的那版。

### 输出：普通显示 / PQ / HLG 都能算对

目标域是 HDR 的（佳能 CMTPQ、ARRI St2084、Insta360 HLG 等）时，按 ST.2084 与 HLG
标准公式解码后再比对，不会被当成普通显示值算错。

### 风格 LUT

柯达 / 富士胶片 / 其他胶片 / 理光 GR / 哈苏 HNCS 这类纯风格 LUT 走显示域，
无需曲线，直接拟合。黑白 LUT 会自动切到 ACROS 起点（中性起点拟不出整块去色）。

---

## 精度

76 个抽样 LUT（9 个品牌 + 5 个胶片风格组，覆盖 21 个规格），**转化率 100%**：

| 指标 | 数值 |
| --- | --- |
| 色差 ΔE00 中位 | **1.51** |
| 均值 / 最好 | 1.48 / **0.41** |
| 达标（ΔE00 ≤ 2.40） | **69/76 = 90.8%** |
| 单张耗时 | 13 秒（CPU，无需显卡） |

几个代表性规格：

| 平台 / 规格 | 达标 | 色差中位 | 最差 |
| --- | --- | --- | --- |
| 哈苏 HNCS（显示域） | 4/4 | 0.46 | 0.50 |
| 理光 GR（显示域） | 4/4 | 0.50 | 0.58 |
| 松下 V-Log | 1/1 | 0.59 | 0.59 |
| 大疆 D-Log | 4/4 | 0.82 | 1.30 |
| ARRI LogC4 | 4/4 | 1.29 | 1.37 |
| 佳能 Canon Log2 | 4/4 | 1.39 | 2.17 |
| 富士 F-Log | 4/4 | 1.70 | 1.94 |
| 索尼 S-Log3 S-Gamut3.Cine | 4/4 | 1.86 | 2.33 |
| 尼康 N-Log 转 Rec.709 | 0/4 | 3.26 | 3.56 |
| 索尼 S-Log2 S-Gamut | 2/4 | 2.12 | 3.04 |

> **关于没达标的 7 个**：`N-Log → Rec.709`、`S-Log2 → Rec.709` 这类是**宽色域转窄色域**，
> 本身要求大幅提饱和。实测目标彩度 141、405 参数网格能给出的上限约 125，网格里有
> 300/1215 个格子已经顶到 ±64 边界；加步数、加采样、换起点都不再改善。这是这块参数
> 网格的表达力上限，不是调参没调好。

全量明细见 [docs/全品牌适配.md](docs/全品牌适配.md)：76 个样本逐条色差、按规格达标率、最差 12 个清单。

---

## 命令行

```bat
:: 单个
A7M4LUT.exe m4 --cube X.cube --name "我的外观" -o out\look

:: 整批（一个目录里的所有 cube）
A7M4LUT.exe m4-batch --lut-dir .\cubes -o out\batch --table-steps 150

:: 指定输入域（默认自动判断）
A7M4LUT.exe m4 --cube nikon.cube --name "N-Log 版" --transfer nlog -o out\nikon
```

`--transfer` 可选 `auto`（默认）、`display`，或上表里的任一曲线名。

---

## 源码运行

```bat
py -3 -m pip install numpy torch ttkbootstrap pillow
set PYTHONPATH=%CD%\src
py -3 -m r5lut.m4gui
```

需要 `models/` 与 `charts/`（索尼官方 M4 训练资产，不随仓库分发，见下节）。
也可以在界面「显示更多设置 → 模型数据」里指向本地目录。

打包成单文件 exe：

```bat
py -3 -m PyInstaller build\A7M4.spec --noconfirm --distpath dist --workpath build
```

---

## 项目结构

```
src/r5lut/
  m4gui.py      界面(ttkbootstrap)+ 转换流程 + 颜色预览
  m4fit.py      405 参数拟合:相机 129³ 表路径的可微实现、拟合、抛光
  transfer.py   log 曲线库接口:识别 / 换算 / 自校准(solve) / PQ-HLG 解码
  curves.py     16 条曲线(从各家官方转换 LUT 反解得到)
  m4json.py     camera-look v2 的构建、封签、写出
  preview.py    cube 解析(含轴序自动纠正)、取样、色卡、PNG 编解码
  cli.py        命令行入口
vendor/m4/      camera-look v2 编解码与响应模型(上游逐字副本)
engine/         A7R V 侧训练引擎(AGPL-3.0,见许可)
docs/           格式规范、使用说明、训练方法
```

---

## 资产与许可

- 本仓库**代码**：MIT，见 [LICENSE](LICENSE)。
- `engine/`（A7R V 侧训练引擎）：[Hearts-Ace/sony-r5-colorlab](https://github.com/Hearts-Ace/sony-r5-colorlab)
  的 vendored 副本，**AGPL-3.0**，见 [engine/VENDORED-NOTES.md](engine/VENDORED-NOTES.md)。
- `vendor/m4/`：来自 [Erlla/sony-a7m4-custom-firmware](https://github.com/Erlla/sony-a7m4-custom-firmware)，
  见 [vendor/m4/PROVENANCE.md](vendor/m4/PROVENANCE.md)。
- `models/`、`charts/`、`native16/`：索尼官方训练资产，**版权归索尼，不在本仓库分发**。
- 各品牌 LUT 的版权归各自厂商 / 作者，本仓库不附带任何 LUT 文件。

详见 [THIRD_PARTY.md](THIRD_PARTY.md)。

---

## 致谢

这个项目能成立，靠的是下面这些公开成果，特此致谢：

### 格式与算法

- **[Erlla/sony-a7m4-custom-firmware](https://github.com/Erlla/sony-a7m4-custom-firmware)**
  —— camera-look v2 的 JSON 结构、`payload_sha256` 封签规则、原生编解码器，以及
  `response_network` / `pixel_bridge` / `host_grid` 这套相机响应模型。
  没有它，405 参数的反解无从下手。
- **[Hearts-Ace/sony-r5-colorlab](https://github.com/Hearts-Ace/sony-r5-colorlab)** 与
  **[Hearts-Ace/sony-a7r5-custom-firmware](https://github.com/Hearts-Ace/sony-a7r5-custom-firmware)**
  —— A7R V 侧的训练方法、129³ 表烘焙与三线性插值路径、色卡与评估口径（`engine/`，AGPL-3.0）。

### 工具与依赖

- [PyTorch](https://pytorch.org/) —— 拟合与自动微分
- [NumPy](https://numpy.org/)、[Pillow](https://python-pillow.org/)
- [ttkbootstrap](https://github.com/israel-dryer/ttkbootstrap) —— 界面主题
- [PyInstaller](https://pyinstaller.org/) —— 单文件打包
- [Ruff](https://github.com/astral-sh/ruff)、[mypy](https://mypy-lang.org/)、[pytest](https://pytest.org/) —— 工程质量门禁

### 曲线与素材

- 各家 `log → 显示` 官方转换 LUT 的提供方（索尼 / 佳能 / 尼康 / 松下 / 富士 / ARRI /
  大疆 / 影石 / 徕卡）—— 16 条曲线是从这些官方 LUT 的灰阶反解出来的。
- [colour-science](https://www.colour-science.org/) 与 CIE 的 ΔE2000 / Lab 公开定义。

---

## 免责

非索尼官方工具，与索尼公司无关。修改机内外观属于自行承担风险的操作，请先备份相机
设置、保留原始 LUT 与原始 JSON。商标归各自所有者。
