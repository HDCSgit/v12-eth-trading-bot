@echo off
chcp 65001 >nul
title V12 ML模型优化工具 (15分钟版本)
echo.
echo ==========================================
echo    V12 ML模型数据与训练优化
echo    版本: 15分钟K线框架
echo ==========================================
echo.
echo 本工具将帮助您:
echo   1. 下载90天15分钟历史数据 (约8000条)
echo   2. 离线训练15分钟ML模型
echo   3. 评估模型性能
echo   4. 设置定时自动训练
echo.
echo 预计用时: 15-20分钟
echo.
pause
cls

echo.
echo [步骤 1/4] 下载15分钟历史数据...
echo ==========================================
echo 正在下载90天15分钟K线数据...
python download_historical_data.py --interval 15m --days 90
if errorlevel 1 (
    echo [错误] 数据下载失败
    pause
    exit /b 1
)
echo.
echo [✓] 15分钟数据下载完成
echo.
pause
cls

echo.
echo [步骤 2/4] 离线训练15分钟模型...
echo ==========================================
echo 使用15分钟数据训练ML模型...
echo 预测目标: 未来30分钟 (2根15分钟K线)
echo 收益阈值: 0.5%%
python offline_training.py --interval 15m --forecast 2 --threshold 0.005
if errorlevel 1 (
    echo [错误] 模型训练失败
    pause
    exit /b 1
)
echo.
echo [✓] 15分钟模型训练完成
echo.
pause
cls

echo.
echo [步骤 3/4] 查看训练结果...
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
echo   - historical_data.db (15分钟历史数据库)
echo   - ml_model_trained.pkl (15分钟训练好的模型)
echo   - ml_training_metrics.json (训练指标)
echo.
echo 下一步:
echo   将 ml_model_trained.pkl 集成到交易系统中
echo   参考: DATA_TRAINING_GUIDE.md
echo.

REM 步骤4: 设置定时训练
echo.
echo [步骤 4/4] 设置定时自动训练...
echo ==========================================
echo.
echo 是否设置定时自动训练?
echo 这将每6小时自动重新训练ML模型
echo.
set /p schedule="设置定时训练? (yes/no): "

if /i "%schedule%"=="yes" (
    echo.
    echo 创建定时训练任务...
    
    REM 创建定时训练脚本
    echo @echo off > auto_retrain.bat
    echo echo [%date% %time%] 开始自动训练... >> auto_retrain.bat
    echo python offline_training.py --interval 15m --incremental >> auto_retrain.bat
    echo echo [%date% %time%] 训练完成 >> auto_retrain.bat
    echo echo 训练完成，新模型已保存 >> auto_retrain.bat
    
    echo.
    echo [✓] 已创建 auto_retrain.bat
    echo.
    echo 手动执行定时训练:
    echo   每6小时运行一次: auto_retrain.bat
    echo.
    echo 或使用Windows任务计划程序:
    echo   1. 打开 任务计划程序
echo   2. 创建基本任务
echo   3. 触发器: 每6小时一次
echo   4. 操作: 启动程序 auto_retrain.bat
echo.
)

echo ==========================================
echo    全部完成!
echo ==========================================
echo.
echo 15分钟框架已配置完成!
echo.
echo 重要提示:
echo 1. 已修改 config.py 为15分钟配置
echo 2. 已下载15分钟历史数据
echo 3. 已训练15分钟ML模型
echo 4. 可以启动交易系统了
echo.
echo 启动命令:
echo   python main_v12_live_optimized.py
echo.
pause
