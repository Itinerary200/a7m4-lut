@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%~dp0vendor\m4;%~dp0engine\web"
py -3 -c "import torch, numpy, scipy" 2>nul || (
  echo 首次运行:安装依赖 ^(torch/numpy/scipy,首次约 5-10 分钟^)...
  py -3 -m pip install --quiet torch numpy scipy
)
if "%~1"=="" (
  py -3 -X utf8 -m r5lut.m4gui
) else (
  py -3 -X utf8 -m r5lut m4 %*
)
