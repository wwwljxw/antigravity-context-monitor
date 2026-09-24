@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Antigravity 上下文容量监控插件 - 卸载程序

echo ========================================================
echo   Antigravity 2.0 上下文容量动态监控插件 - 卸载
echo ========================================================
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] 系统中未找到 Python 环境！
    pause
    exit /b 1
)

python uninstall.py
pause
