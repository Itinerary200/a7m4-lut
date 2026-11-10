# JSON 格式说明(固件规范)

> 对应固件项目 [sony-a7r5-custom-firmware](https://github.com/Hearts-Ace/sony-a7r5-custom-firmware)
> 的 `r5-custom-filter-config/4`。本工具输出严格按此规范,并用官方编译器双向验证
> （`load → pack → unpack → pack` 恒等）。

## 一、native_config.json

```json
{
  "schema": "r5-custom-filter-config/4",
  "model": "ILCE-7RM5",
  "baseline_ap_sha256": "8ee4d587…",
  "baseline_cp_sha256": "8e9e26bf…",
  "entries": [ { …一个滤镜槽位… } ]
}
```

- `schema` / `model` / 两个基线哈希：固定值，编译器拒绝不符者
- `entries`：0..12 条，每条一个槽位（`number` 1..12，不可重复）

条目字段（全整数）：

| 字段 | 形状 | 范围 | 含义 |
| --- | --- | --- | --- |
| `number` | 标量 | 1..12 | 槽位号 |
| `short_name` | 文本 | 1..23 UTF-8 字节 | 菜单简称 |
| `full_name` | 文本 | 1..63 UTF-8 字节 | 全称 |
| `cc1_delta` | [3][8] | −32768..32767（组内绝对值另有校验） | CC1 系数（第一行基准，后两行增量） |
| `block13` | [3][16][6] | −8192..8191 | 16 色相块 × 6 系数 |
| `gamma_native_129` | [129] | 0..131071，首项 0、单调不减 | 原生 Gamma 表 |
| `grid_5x9x9.coefficients` | [3][5][9][9] | −64..63 | signed7 残差网格（405 点/通道） |

> 网格是**相对相机原生响应的残差**，不是绝对颜色；同一组网格配不同原生参数就是
> 不同颜色。所以不能把 `.cube` 的数值直接抄进网格——必须经过训练拟合。

## 二、R5NATIVE.BIN 布局

| 区段 | 长度 | 说明 |
| --- | --- | --- |
| 头 | 128 字节 | `R5CUST4\0`(8) + 版本 4(4) + 头长 128(4) + 总长(4) + 记录数(4) + 槽位位掩码(4) + 保留(4) + `ILCE-7RM5`(16) + AP_SHA(32) + CP_SHA(32)；偏移 112 为全体 CRC32 |
| 记录 ×N | 每条 2452 字节 | `'<I24s64s24h288h129I1215b'`：槽位(4)+短名(24)+全名(64)+cc1(24×2)+block13(288×2)+gamma(129×4)+grid(1215×1) |
| 总计 | 128 + 2452×N | 一条 2580 字节；上限 12 条 = 29552 字节 |

解码按规范重建再逐字节比对（CRC、基线、顺序、文本填充、保留位任一不符即拒），
不存在半解码状态。`r5lut inspect` 可把 BIN 完整读回 JSON。

## 三、导入

- 把 `R5NATIVE.BIN`（或 `v4-config.zip` 里的那份）按固件 release 说明导入
- 导入策略 `replace-entire-set`（整包替换）；缺槽位会关闭自定义滤镜
- BIN 只含整数参数 + 网格，响应模型不写入固件
