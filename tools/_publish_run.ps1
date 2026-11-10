# 一次性:登录 → 建仓库 → 推 main → 发 Release
$ErrorActionPreference = "Continue"
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
Set-Location "D:\ai逆向\r5lut"
$log = "out\publish.log"
"=== $(Get-Date -Format 'HH:mm:ss') 开始 ===" | Out-File $log -Encoding UTF8

function Note($text) {
    $line = "$(Get-Date -Format 'HH:mm:ss')  $text"
    Write-Host $line
    Add-Content -Path $log -Value $line -Encoding UTF8
}

$version = (Select-String -Path "pyproject.toml" -Pattern '^version\s*=\s*"([^"]+)"' | Select-Object -First 1).Matches.Groups[1].Value
$tag = "v$version"
Note "版本 $version / 标签 $tag"

gh auth status 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    for ($attempt = 1; $attempt -le 4; $attempt++) {
        Note "需要登录 (第 $attempt 次);浏览器会打开 github.com/login/device,请用给出的设备码授权"
        gh auth login --hostname github.com --git-protocol https --web --skip-ssh-key 2>&1 |
            ForEach-Object { Note $_ }
        gh auth status 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { Note "登录成功"; break }
        Note "本次没成功,5 秒后重试"
        Start-Sleep -Seconds 5
    }
}
gh auth status 2>&1 | ForEach-Object { Note $_ }
gh auth status 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { Note "登录未完成,退出"; exit 1 }

$owner = (gh api user --jq .login)
Note "账号 $owner"
$repo = "a7m4-lut"

gh repo view "$owner/$repo" 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
    Note "远端已存在,推送 main"
    $remote = git remote
    if (-not $remote) { git remote add origin "https://github.com/$owner/$repo.git" }
    git push -u origin main 2>&1 | ForEach-Object { Note $_ }
} else {
    Note "创建仓库 $owner/$repo"
    gh repo create "$owner/$repo" --public --source . --remote origin --push `
        --description "把 .cube LUT 转成索尼 A7M4 机内创意外观(camera-look v2 JSON)" 2>&1 | ForEach-Object { Note $_ }
}

Note "发 Release $tag"
$assets = @()
foreach ($name in @("dist\A7M4LUT.exe", "dist\A7M4LUT-$version.zip")) {
    if (Test-Path $name) { $assets += $name } else { Note "缺 $name" }
}
$notes = @"
## 安装
下载 ``A7M4LUT.exe`` 双击即可(Windows 10/11 x64,不需要装 Python)。
也可以下 ``A7M4LUT-$version.zip``,解压后运行里面的 ``A7M4LUT.exe``。

## 用法
1. 选 ``.cube`` → 填相机里显示的名字 → 选保存位置 → 开始转换
2. 把输出里的 ``PRIVATE\`` 整个拷到 SD 卡根目录
3. 相机里就能选到这个外观

命令行:``A7M4LUT.exe m4 --cube X.cube --name 名字 -o out\look``

## 本次包含
- cube → camera-look v2 JSON(405 参数反解,彩色 ΔE00 中位 1.32)
- S-Log3 输入的 LUT 自动识别,输出可选 Rec709 / S-Log3
- 理光 GR 全套实测:Rec709 0.57 / SLog3 输入 1.21 / SLog3 输出 1.19
"@
if ($assets.Count -gt 0) {
    gh release create $tag @assets --title "A7M4 滤镜转换器 $version" --notes $notes 2>&1 | ForEach-Object { Note $_ }
} else {
    gh release create $tag --title "A7M4 滤镜转换器 $version" --notes $notes 2>&1 | ForEach-Object { Note $_ }
}

$url = (gh release view $tag --json url --jq .url)
Note "完成: $url"
