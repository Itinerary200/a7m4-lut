@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
echo === ruff check ===
py -3 -m ruff check src tests
echo === ruff format check ===
py -3 -m ruff format --check src tests
echo === mypy ===
py -3 -m mypy
echo === pytest ===
py -3 -m pytest -q
