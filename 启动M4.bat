@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%~dp0vendor\m4;%~dp0engine\web"
if "%~1"=="" (
  echo 用法: 启动M4.bat --cube X.cube --assets ^<M4-training-assets^> --name 名称 -o out\look
  echo      启动M4.bat --batch --lut-dir ^<cube目录^> --assets ^<资产^> -o out\batch
  exit /b 1
)
py -3 -c "import torch, numpy, scipy, rawpy" 2>nul || (
  echo 首次运行:安装依赖...
  py -3 -m pip install --quiet torch numpy scipy rawpy
)
if "%~1"=="--batch" (
  shift
  py -3 -X utf8 "%~dp0tools\m4_batch.py" %*
) else (
  py -3 -X utf8 -m r5lut m4 %*
)
