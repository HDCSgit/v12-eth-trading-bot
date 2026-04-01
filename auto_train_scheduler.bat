@echo off
chcp 65001 >nul
title V2模型定时自动训练
echo.
echo ==========================================
echo    V2市场环境模型 - 定时自动训练
echo ==========================================
echo.

REM 检查是否应该运行（避免过于频繁）
set "TIMESTAMP_FILE=models\regime_v2_last_training.txt"
set "SHOULD_RUN=1"

if exist "%TIMESTAMP_FILE%" (
    for /f "tokens=3" %%a in ('type "%TIMESTAMP_FILE%" ^| findstr "Last training"') do (
        set "LAST_TRAIN=%%a"
    )
    
    echo 上次训练: %LAST_TRAIN%
    
    REM 计算时间差（简化：只比较日期）
    for /f "tokens=1-3 delims=-" %%a in ("%date:~0,10%") do (
        set "TODAY=%%a%%b%%c"
    )
    
    REM 如果时间相同，询问是否继续
    echo 今天日期: %date:~0,10%
    
    REM 简化逻辑：询问用户
    echo.
    echo 是否立即训练新模型?
    echo [1] 立即训练（推荐：每天1次）
    echo [2] 跳过
    echo.
    set /p choice="选择 (1/2): "
    
    if "%choice%"=="2" goto end
)

echo.
echo [开始自动训练流程]
echo.

REM 步骤1: 更新数据
python download_binance_data.py --symbol ETHUSDT --interval 15m --days 90

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [!] 数据下载失败，使用现有数据继续...
)

REM 步骤2: 训练模型
python train_regime_v2_auto.py --auto-replace

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ==========================================
    echo ✅ 训练成功完成！
    echo ==========================================
    echo.
    echo 新模型已生效，正在运行的交易程序将自动加载。
    echo.
    echo 建议:
    echo   - 查看训练日志确认准确率
    echo   - 观察1-2个交易周期验证预测质量
) else (
    echo.
    echo ==========================================
    echo [!] 训练失败
    echo ==========================================
    echo.
    echo 已自动恢复旧模型。
)

echo.
pause

:end
