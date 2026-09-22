@echo off
chcp 65001 >nul
title JD AutomaticEvaluate - FULL AUTO (will submit)
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

echo ============================================================
echo   JD AutomaticEvaluate - step 3: FULL AUTO RUN
echo ============================================================
echo.
echo   WARNING: this WILL SUBMIT reviews for EVERY pending order.
echo   Reviews cannot be edited after submission.
echo.
echo   If you only want to try one order first, use the trial
echo   script (2_TrialRun_NoSubmit.bat) instead.
echo.
echo   Optional: type order numbers to EXCLUDE (space separated),
echo   or just press ENTER to process everything.
echo.
echo ============================================================
echo.

set "PY=C:\Users\Administrator\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if not exist "%PY%" set "PY=python"

set "BL="
set /p "BL=Exclude order numbers (ENTER = none): "

echo.
echo   Starting full auto run ...
echo.

if "%BL%"=="" (
    "%PY%" "JDpc-AutomaticEvaluate.py" -L INFO
) else (
    "%PY%" "JDpc-AutomaticEvaluate.py" -L INFO -bl %BL%
)

echo.
echo   Finished. Log file: pc\logs\
pause
