@echo off
chcp 65001 >nul
title V12 ML模型优化工具
echo.
echo ==========================================
echo    V12 ML模型数据与训练优化
echo ==========================================
echo.
echo 本工具将帮助您:
echo   1. 下载30天历史数据 (约4.3万条)
echo   2. 离线训练ML模型
echo   3. 评估模型性能
echo.
echo 预计用时: 10-15分钟
echo.
pause
cls

echo.
echo [步骤 1/3] 下载历史数据...
echo ==========================================
python download_historical_data.py
if errorlevel 1 (
    echo [错误] 数据下载失败
    pause
    exit /b 1
)
echo.
echo [✓] 数据下载完成
echo.
pause
cls

echo.
echo [步骤 2/3] 离线训练模型...
echo ==========================================
python offline_training.py
if errorlevel 1 (
    echo [错误] 模型训练失败
    pause
    exit /b 1
)
echo.
echo [✓] 模型训练完成
echo.
pause
cls

echo.
echo [步骤 3/3] 查看训练结果...
echo ==========================================
if exist ml_training_metrics.json (
    type ml_training_metrics.json
) else (
    echo 未找到训练指标文件
)
echo.

echo ==========================================
echo    优化完成!
echo ==========================================
echo.
echo 生成的文件:
echo   - historical_data.db (历史数据库)
echo   - ml_model_trained.pkl (训练好的模型)
echo   - ml_training_metrics.json (训练指标)
echo.
echo 下一步:
echo   将 ml_model_trained.pkl 集成到交易系统中
echo   参考: DATA_TRAINING_GUIDE.md
echo.
pause
