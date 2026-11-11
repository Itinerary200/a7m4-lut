# 许可范围说明

本仓库的 [LICENSE](LICENSE)（MIT）**只覆盖本仓库自有代码**：`src/`、`tools/`、`tests/`、
`docs/`、`build/` 下的脚本与文档。

不覆盖以下内容：

| 内容 | 许可 | 说明 |
| --- | --- | --- |
| `engine/` | **GNU AGPL-3.0** | vendored 自 [Hearts-Ace/sony-r5-colorlab](https://github.com/Hearts-Ace/sony-r5-colorlab)，见 `engine/LICENSE.orig-agpl3.txt`、`engine/VENDORED-NOTES.md` |
| `vendor/m4/` | 遵循上游 | vendored 自 [Erlla/sony-a7m4-custom-firmware](https://github.com/Erlla/sony-a7m4-custom-firmware)，见 `vendor/m4/PROVENANCE.md` |
| `models/`、`charts/`、`native16/` | 版权归索尼 | 官方 M4 训练资产，**不在本仓库分发** |
| 第三方 LUT（`.cube`） | 归各自作者 / 厂商 | 本仓库不附带任何 LUT 文件 |
| 相机固件相关数据 | 归各自所有者 | — |

如果要把本仓库用于商业分发，请注意 `engine/` 的 AGPL-3.0 传染性：移除 `engine/`，
或按 AGPL-3.0 公开相应源码。见 [THIRD_PARTY.md](THIRD_PARTY.md)。
