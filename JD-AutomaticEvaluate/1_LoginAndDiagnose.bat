@echo off
chcp 65001 >nul
title JD AutomaticEvaluate - Login and Diagnose
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

echo ============================================================
echo   JD AutomaticEvaluate - step 1: login and dump structure
echo ============================================================
echo.
echo   A browser window will open.
echo   Please LOG IN to JD.com inside it (QR code recommended).
echo   After login, leave it alone - the script does the rest.
echo.
echo ============================================================
echo.

set "PY=C:\Users\Administrator\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" "_login_and_diagnose.py"

echo.
echo   Done. See folder: _diagnose
pause
