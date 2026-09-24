@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Antigravity 上下文容量监控插件 - 安装程序

echo ========================================================
echo   Antigravity 2.0 上下文容量动态监控插件 - 一键安装
echo ========================================================
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] 系统中未找到 Python 环境！
    echo 请先安装 Python 3.9 或以上版本，并务必勾选 "Add python.exe to PATH"。
    echo.
    pause
    exit /b 1
)

python install.py
pause
