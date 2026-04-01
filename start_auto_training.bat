@echo off
chcp 65001 >nul
title V12 ML Model Training Service

:: Set working directory
cd /d "%~dp0"

:main_menu
cls
echo.
echo ==========================================
echo    V12 ML Model Auto Training Service
echo    Version: 2025.04.01
echo ==========================================
echo.
echo [Data Mode Description]
echo   Sliding Window: Last 9 months (freshest, default)
echo   Fixed Start: All data after 2025-07-05 (more samples)
echo.
echo [Menu Options]
echo   [1] Schedule Auto Training (every 6 hours)
echo   [2] Update Data Only (no training)
echo   [3] Quick Train - Sliding Window (recommended)
echo   [4] Quick Train - Fixed Start
echo   [5] Full Train - Sliding Window (retrain from scratch)
echo   [6] Full Train - Fixed Start (retrain from scratch)
echo   [7] Train Market Regime Model (V2)
echo   [8] View Training Logs
echo   [9] Stop Scheduled Service
echo   [0] Exit
echo.
set /p choice="Select option: "

if "%choice%"=="1" goto schedule_menu
if "%choice%"=="2" goto download_only
if "%choice%"=="3" goto train_sliding
if "%choice%"=="4" goto train_fixed
if "%choice%"=="5" goto full_train_sliding
if "%choice%"=="6" goto full_train_fixed
if "%choice%"=="7" goto train_regime
if "%choice%"=="8" goto view_logs
if "%choice%"=="9" goto stop_service
if "%choice%"=="0" goto end
goto main_menu

:: ==========================================
:: Schedule Service Menu
:: ==========================================
:schedule_menu
cls
echo.
echo ==========================================
echo    Schedule Auto Training Service
echo ==========================================
echo.
echo ETH market is volatile, recommend retraining every 6 hours
echo.
echo [Options]
echo   [1] Install Schedule Task (every 6h: 02/08/14/20)
echo   [2] Remove Schedule Task
echo   [3] Check Task Status
echo   [4] Back to Main Menu
echo.
set /p sched_choice="Select option: "

if "%sched_choice%"=="1" goto install_schedule
if "%sched_choice%"=="2" goto remove_schedule
if "%sched_choice%"=="3" goto check_schedule
if "%sched_choice%"=="4" goto main_menu
goto main_menu

:install_schedule
echo.
echo Installing schedule task...
schtasks /Create /TN "V12-ML-Training" /TR "\"%~dp0quick_train.py\"" /SC HOURLY /MO 6 /F /ST 02:00 /RL HIGHEST 2>nul
if %ERRORLEVEL% EQU 0 (
    echo.
    echo [OK] Schedule task installed successfully!
    echo.
    echo Execution time: Daily 02:00, 08:00, 14:00, 20:00
    echo Command: quick_train.py (sliding window mode)
    echo Estimated time: 3-5 minutes
) else (
    echo.
    echo [FAIL] Installation failed
    echo Tip: Please run this script as Administrator
)
echo.
pause
goto main_menu

:remove_schedule
echo.
echo Removing schedule task...
schtasks /Delete /TN "V12-ML-Training" /F 2>nul
if %ERRORLEVEL% EQU 0 (
    echo [OK] Schedule task removed
) else (
    echo [INFO] Task does not exist
)
echo.
pause
goto main_menu

:check_schedule
echo.
echo ==========================================
echo Current schedule task status:
echo ==========================================
schtasks /Query /TN "V12-ML-Training" 2>nul
if %ERRORLEVEL% NEQ 0 echo Task does not exist
echo.
pause
goto main_menu

:: ==========================================
:: Update Data Only
:: ==========================================
:download_only
cls
echo.
echo ==========================================
echo    Update Data Only
echo ==========================================
echo.
python update_data_incremental.py
echo.
echo To check latest data timestamp:
echo   python check_freshness.py
echo.
pause
goto main_menu

:: ==========================================
:: Quick Train - Sliding Window
:: ==========================================
:train_sliding
cls
echo.
echo ==========================================
echo    Quick Train - Sliding Window Mode
echo ==========================================
echo.
echo Mode: Use last 9 months data (freshest)
echo Type: Incremental training (keep existing knowledge)
echo.
python quick_train.py
echo.
pause
goto main_menu

:: ==========================================
:: Quick Train - Fixed Start
:: ==========================================
:train_fixed
cls
echo.
echo ==========================================
echo    Quick Train - Fixed Start Mode
echo ==========================================
echo.
echo Mode: Use all data after 2025-07-05
echo Type: Incremental training (keep existing knowledge)
echo.
python quick_train.py --fixed
echo.
pause
goto main_menu

:: ==========================================
:: Full Train - Sliding Window
:: ==========================================
:full_train_sliding
cls
echo.
echo ==========================================
echo    Full Train - Sliding Window Mode
echo ==========================================
echo.
echo Mode: Use last 9 months data
echo Type: Full training (backup and remove old model)
echo WARNING: This will backup and delete existing model!
echo.
set /p confirm="Confirm? (y/n): "
if /i not "%confirm%"=="y" goto main_menu
python quick_train.py --full
echo.
pause
goto main_menu

:: ==========================================
:: Full Train - Fixed Start
:: ==========================================
:full_train_fixed
cls
echo.
echo ==========================================
echo    Full Train - Fixed Start Mode
echo ==========================================
echo.
echo Mode: Use all data after 2025-07-05
echo Type: Full training (backup and remove old model)
echo WARNING: This will backup and delete existing model!
echo.
set /p confirm="Confirm? (y/n): "
if /i not "%confirm%"=="y" goto main_menu
python quick_train.py --fixed --full
echo.
pause
goto main_menu

:: ==========================================
:: Train Market Regime Model (V2)
:: ==========================================
:train_regime
cls
echo.
echo ==========================================
echo    Train Market Regime Model (V2)
echo ==========================================
echo.
echo [NOTE] Current system has ML Regime disabled
echo        Using V1 rule-based MarketAnalyzer
echo.
echo Still want to train V2 model? (for backup)
set /p confirm="Continue? (y/n): "
if /i not "%confirm%"=="y" goto main_menu

echo.
echo [1/4] Checking dependencies...
python -c "import xgboost; print('XGBoost OK')" 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo Installing dependencies...
    python -m pip install xgboost -q
)

echo.
echo [2/4] Updating data...
python update_data_incremental.py

echo.
echo [3/4] Training model...
if not exist "models" mkdir models
python train_regime_v2.py --data "eth_usdt_15m_binance.csv" --output "models/regime_xgb_v1.pkl" --lookforward 48 --test-size 0.15

echo.
echo [4/4] Done!
if exist "models\regime_xgb_v1.pkl" (
    echo [OK] Model saved: models\regime_xgb_v1.pkl
) else (
    echo [FAIL] Training failed
)
echo.
pause
goto main_menu

:: ==========================================
:: View Logs
:: ==========================================
:view_logs
cls
echo.
echo ==========================================
echo    Training Logs (last 30 lines)
echo ==========================================
echo.
if exist ml_auto_training.log (
    powershell -Command "Get-Content ml_auto_training.log -Tail 30"
) else (
    echo No training logs found
)
echo.
echo ==========================================
echo Press any key to return to main menu
echo ==========================================
pause >nul
goto main_menu

:: ==========================================
:: Stop Service
:: ==========================================
:stop_service
cls
echo.
echo ==========================================
echo    Stop Scheduled Service
echo ==========================================
echo.
schtasks /Delete /TN "V12-ML-Training" /F 2>nul
if %ERRORLEVEL% EQU 0 (
    echo [OK] Schedule task removed
) else (
    echo [INFO] Task does not exist
)
echo.
pause
goto main_menu

:: ==========================================
:: End
:: ==========================================
:end
cls
echo.
echo Thank you for using V12 ML Training Service
echo.
timeout /t 2 >nul
exit
