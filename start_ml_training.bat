@echo off
chcp 65001 >nul 2>&1
title V12 ML Training Service
cls

echo ==========================================
echo    V12 ML Model Auto Training Service
echo ==========================================
echo.
echo    Auto retrain every 6 hours
echo.
echo ==========================================
echo.

:: Try to find and activate conda
if exist "%USERPROFILE%\anaconda3\Scripts\activate.bat" (
    call "%USERPROFILE%\anaconda3\Scripts\activate.bat" base
    echo [OK] Conda activated: base
) else if exist "%USERPROFILE%\miniconda3\Scripts\activate.bat" (
    call "%USERPROFILE%\miniconda3\Scripts\activate.bat" base
    echo [OK] Conda activated: base
) else if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat >nul 2>&1
    echo [OK] Virtual env activated
) else (
    echo [INFO] Using system Python
)

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found
    pause
    exit /b 1
)

:MENU
echo.
echo ------------------------------------------
echo  Select Option:
echo ------------------------------------------
echo.
echo    1 - Start scheduled training service
echo    2 - Train once now
echo    3 - View training logs
echo    4 - Stop training service
echo    5 - Exit
echo.
echo ------------------------------------------
set /p choice=Enter 1-5: 

if "%choice%"=="1" goto START
if "%choice%"=="2" goto ONCE
if "%choice%"=="3" goto LOGS
if "%choice%"=="4" goto STOP
if "%choice%"=="5" goto EXIT

echo.
echo [ERROR] Invalid choice, enter 1-5
goto MENU

:START
echo.
echo [*] Starting scheduled training service...
echo [*] Will retrain every 6 hours
echo [*] Press Ctrl+C to stop
echo.
timeout /t 2 >nul
python auto_ml_trainer.py --daemon --hours 6
goto END

:ONCE
echo.
echo [*] Training once...
echo.
timeout /t 1 >nul
python auto_ml_trainer.py --once
echo.
echo [*] Training complete
echo.
pause
goto MENU

:LOGS
echo.
echo [*] Viewing logs...
echo.
if exist "ml_auto_training.log" (
    echo === Last 20 lines ===
    echo.
    powershell -Command "Get-Content ml_auto_training.log -Tail 20"
    echo.
    echo === Log file: ml_auto_training.log ===
) else (
    echo [WARN] Log file not found
)
echo.
pause
goto MENU

:STOP
echo.
echo [*] Stopping service...
taskkill /F /IM python.exe /FI "WINDOWTITLE eq V12 ML Training Service*" >nul 2>&1
echo [OK] Service stopped
echo.
pause
goto MENU

:EXIT
echo.
echo [*] Exiting...
goto END

:END
echo.
pause
