@echo off
chcp 65001 >nul
title JD AutomaticEvaluate - Trial Run (fill only, NO submit)
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

echo ============================================================
echo   JD AutomaticEvaluate - step 2: TRIAL RUN
echo ============================================================
echo.
echo   This run FILLS the review form but does NOT submit.
echo   (flag: -cac / --close-auto-commit)
echo.
echo   It processes ONE order and ONE product only, so you can
echo   eyeball the result in the browser before going full auto.
echo.
echo   *** RUN THIS ONLY ONCE PER SESSION ***
echo   Repeated trial runs can trigger JD risk control and get
echo   the review area soft-blocked ("under maintenance").
echo   If that happens, stop and wait a few hours. Do NOT retry.
echo.
echo   Default order number: 3620277019820006
echo   Press ENTER to use it, or type another order number.
echo.
echo ============================================================
echo.

set "PY=C:\Users\Administrator\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if not exist "%PY%" set "PY=python"

set "ORDER_ID="
set /p "ORDER_ID=Order number (ENTER = 3620277019820006): "
if "%ORDER_ID%"=="" set "ORDER_ID=3620277019820006"

echo.
echo   Running trial for order %ORDER_ID% ...
echo.

"%PY%" "JDpc-AutomaticEvaluate.py" -cac -mt 1 -wl %ORDER_ID% -L DEBUG

echo.
echo   Trial finished. Browser left open on purpose - check the form.
echo   Log file: pc\logs\
pause
