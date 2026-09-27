@echo off
setlocal
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

where python >nul 2>&1
if %ERRORLEVEL% equ 0 (
    python "%~dp0uninstall.py"
    goto :done
)

where py >nul 2>&1
if %ERRORLEVEL% equ 0 (
    py "%~dp0uninstall.py"
    goto :done
)

echo.
echo ========================================================
echo [ERROR] Python not found in system PATH!
echo ========================================================
echo.

:done
pause
