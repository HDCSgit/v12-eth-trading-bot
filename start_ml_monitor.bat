@echo off
chcp 65001 >nul
title V12 ML模型自检与维护系统
echo.
echo ==========================================
echo    V12 ML模型自检与维护系统
echo ==========================================
echo.
echo 功能:
echo   1. 实时诊断ML模型健康状况
echo   2. 自动调整交易参数
echo   3. 异常时自动暂停交易
echo   4. 生成维护报告
echo.
echo 选项:
echo   [1] 立即诊断报告
echo   [2] 启动自动监控
echo   [3] 查看历史警报
echo   [4] 手动恢复交易
echo.
set /p choice="请选择 (1/2/3/4): "

if "%choice%"=="1" goto diagnose
if "%choice%"=="2" goto monitor
if "%choice%"=="3" goto history
if "%choice%"=="4" goto resume
goto end

:diagnose
echo.
echo 生成诊断报告...
python -c "from ml_self_diagnosis import MLSelfDiagnosis; d = MLSelfDiagnosis(); print(d.generate_report())"
goto end

:monitor
echo.
echo 启动自动监控 (每30分钟检查一次)...
echo 按Ctrl+C停止
echo.
python -c "from ml_self_diagnosis import MLAutoMaintenance, MLSelfDiagnosis; m = MLAutoMaintenance(MLSelfDiagnosis()); m.start_monitoring(30); import time; 
while True: time.sleep(60)"
goto end

:history
echo.
echo 历史警报文件:
dir /b ml_alert_*.txt 2>nul || echo 暂无警报文件
dir /b ml_diagnosis_*.txt 2>nul || echo 暂无诊断报告
goto end

:resume
echo.
echo 手动恢复交易...
python -c "from ml_monitor_integration import MLMonitorBridge; m = MLMonitorBridge(None); m.resume_trading(); print('交易已恢复')"
goto end

:end
echo.
pause
