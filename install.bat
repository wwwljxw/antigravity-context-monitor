@echo off
setlocal
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

where python >nul 2>&1
if %ERRORLEVEL% equ 0 (
    python "%~dp0install.py"
    goto :done
)

where py >nul 2>&1
if %ERRORLEVEL% equ 0 (
    py "%~dp0install.py"
    goto :done
)

echo.
echo ========================================================
echo [ERROR] Python not found in system PATH!
echo Please install Python 3.9+ from https://www.python.org
echo Make sure to check "Add python.exe to PATH" during setup.
echo ========================================================
echo.

:done
pause
