@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "runtime\python.exe" (
    "runtime\python.exe" "tools\launcher.py"
) else (
    echo 找不到 runtime\python.exe，分发包不完整，请重新解压。
    pause
)
