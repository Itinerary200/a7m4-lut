# 一条命令把本仓库推到 GitHub 并发 Release。
#
#   pwsh -File tools\publish_github.ps1 -Repo a7m4-lut -Visibility public
#
# 需要:git、GitHub 账号;gh 未装会自动用 winget 装。

param(
    [string]$Repo = "a7m4-lut",
    [ValidateSet("public", "private")]
    [string]$Visibility = "public",
    [string]$Owner = "",
    [string]$Tag = "",
    [string]$Message = "A7M4 滤镜转换器"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }

# 版本号取自 pyproject.toml
$version = (Select-String -Path "pyproject.toml" -Pattern '^version\s*=\s*"([^"]+)"' |
    Select-Object -First 1).Matches.Groups[1].Value
if (-not $version) { throw "读不到 pyproject.toml 里的 version" }
if (-not $Tag) { $Tag = "v$version" }
Write-Host "仓库: $Repo   版本: $version   标签: $Tag   可见性: $Visibility"

# 1) gh
Step "检查 GitHub CLI"
$gh = Get-Command gh -ErrorAction SilentlyContinue
if (-not $gh) {
    Write-Host "没装 gh,用 winget 装…"
    winget install --id GitHub.cli --accept-source-agreements --accept-package-agreements --silent
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")
    $gh = Get-Command gh -ErrorAction SilentlyContinue
    if (-not $gh) { throw "gh 装完仍找不到,重开一个终端再跑本脚本" }
}

# 2) 登录
Step "检查登录状态"
gh auth status 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "需要登录 GitHub(浏览器会弹出授权页)…"
    gh auth login --hostname github.com --git-protocol https --web
    if ($LASTEXITCODE -ne 0) { throw "登录失败" }
}

# 3) 本地仓库
Step "准备本地仓库"
if (-not (Test-Path ".git")) {
    git init | Out-Null
    git branch -M main
}
if (-not (git config user.name)) { git config user.name "A7M4 LUT Converter" }
if (-not (git config user.email)) { git config user.email "noreply@users.noreply.github.com" }
git add -A
$staged = git diff --cached --name-only
if ($staged) {
    git commit -m "$Message $version" | Out-Null
    Write-Host "已提交 $(($staged | Measure-Object).Count) 个文件"
} else {
    Write-Host "没有新改动可提交"
}

# 4) 建仓库并推
Step "创建远端仓库并推送"
if (-not $Owner) {
    $Owner = (gh api user --jq .login)
}
$exists = gh repo view "$Owner/$Repo" 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "远端已存在,直接推 main"
    if (-not (git remote)) { git remote add origin "https://github.com/$Owner/$Repo.git" }
    git push -u origin main
} else {
    gh repo create "$Owner/$Repo" "--$Visibility" --source . --remote origin --push --description $Message
}

# 5) Release
Step "发 Release $Tag"
$assets = @()
foreach ($name in @("dist\A7M4LUT.exe", "dist\A7M4LUT-$version.zip")) {
    if (Test-Path $name) { $assets += $name } else { Write-Host "跳过(不存在): $name" }
}
if ($assets.Count -gt 0) {
    $notes = @"
## 安装
下载 `A7M4LUT.exe` 双击即可(Windows 10/11 x64,无需 Python)。
也可以下 `A7M4LUT-$version.zip`,解压后运行 `A7M4LUT.exe`。

## 用法
1. 选 `.cube` → 填名字 → 选保存位置 → 开始转换
2. 把输出里的 `PRIVATE\` 整个拷到 SD 卡根目录
3. 相机里就能选到这个外观

命令行:`A7M4LUT.exe m4 --cube X.cube --name 名字 -o out\look`
"@
    gh release create $Tag @assets --title "$Message $version" --notes $notes
} else {
    Write-Host "没有可上传的产物,只发空 Release"
    gh release create $Tag --title "$Message $version" --notes "源码发布 $version"
}

Step "完成"
gh release view $Tag --json url --jq .url
