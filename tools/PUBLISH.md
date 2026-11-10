# 发布到 GitHub:一条命令

本仓库已经准备好（README / LICENSE / THIRD_PARTY / CI / .gitignore），缺的只是把代码推上去。
下面这个脚本会：装 gh → 登录 → 建仓库 → 推送 → 发 Release（带 exe 和 zip）。

## 前置

- Windows PowerShell 5.1+ 或 pwsh 7+
- 一个 GitHub 账号（有建仓库权限）
- 已在本地打好包：`dist\A7M4LUT.exe`、`dist\A7M4LUT-<版本>.zip`

## 用法

```powershell
cd D:\ai逆向\r5lut
pwsh -File tools\publish_github.ps1 -Repo a7m4-lut -Visibility public
```

脚本会让浏览器弹出 GitHub 授权页，按提示输入一次性代码即可。之后：

| 步骤 | 做什么 |
|---|---|
| 1 | `winget install GitHub.cli`（已装则跳过） |
| 2 | `gh auth login --web`（已登录则跳过） |
| 3 | `git init` + 首次提交（已初始化则跳过） |
| 4 | `gh repo create <账号>/<Repo> --public --source . --push` |
| 5 | `gh release create v1.2.10` 附上 exe 与 zip |

## 只想本地建仓、自己推

```powershell
cd D:\ai逆向\r5lut
git init
git add .
git commit -m "feat: A7M4 滤镜转换器 1.2.10"
git branch -M main
git remote add origin https://github.com/<账号>/<仓库>.git
git push -u origin main
```

## 注意

- 仓库**不含** `models/ charts/ native16/` 之外的训练资产，也不含 `out/ dist/ backups/`（见 `.gitignore`）。
  exe 和 zip 通过 Release 附件分发，不进 git 历史（单文件 150 MB，超过 git 单文件建议上限）。
- `engine/` 是 AGPL-3.0 vendored 代码，仓库公开时保留 `engine/LICENSE.orig-agpl3.txt`，
  否则许可链就断了。
- 如果不想公开 AGPL 部分，可把 `engine/` 移出仓库、仅保留 `src/`、`tools/`、`docs/`，
  但那时 `r5lut convert`（A7R V 侧）不可用，A7M4 侧不受影响。
