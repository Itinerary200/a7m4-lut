@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%~dp0vendor\m4;%~dp0engine\web"
py -3 -X utf8 "%~dp0tools\m4_batch.py" %*
