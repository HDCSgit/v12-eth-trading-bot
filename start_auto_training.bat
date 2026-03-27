@echo off
chcp 65001 >nul
title V12 ML自动训练服务 - ETH高波动适配版
echo.
echo ==========================================
echo    V12 ML模型自动训练服务
echo    ETH高波动适配 - 每6小时快速重训练
echo ==========================================
echo.
echo 启动选项:
echo   [1] 启动定时服务 (每6小时自动重训练)
echo   [2] 仅下载最新数据 (增量更新)
echo   [3] 立即快速重训练V2 (3-4分钟, 推荐)
echo   [4] 立即完整训练V2 (5-8分钟)
echo   [5] 训练交易信号模型
echo   [6] 训练所有模型 (交易信号 + V2环境)
echo   [7] 查看训练日志
echo   [8] 停止定时服务
echo.
set /p choice="请选择 (1/2/3/4/5/6/7/8): "

if "%choice%"=="1" goto schedule_service
if "%choice%"=="2" goto download_only
if "%choice%"=="3" goto quick_retrain
if "%choice%"=="4" goto full_retrain
if "%choice%"=="5" goto train_signal
if "%choice%"=="6" goto train_all
if "%choice%"=="7" goto view_logs
if "%choice%"=="8" goto stop_service
goto end

:schedule_service
echo.
echo ==========================================
echo 设置定时自动重训练服务
echo ==========================================
echo.
echo ETH市场波动大，建议每6小时重训练一次
echo 已配置: 每6小时自动执行 (02:00, 08:00, 14:00, 20:00)
echo.
echo [1] 安装/重装定时任务 (每6小时)
echo [2] 删除定时任务
echo [3] 查看当前任务状态
echo [4] 返回主菜单
echo.
set /p sched_choice="请选择: "

if "%sched_choice%"=="1" goto install_schedule
if "%sched_choice%"=="2" goto remove_schedule
if "%sched_choice%"=="3" goto check_schedule
if "%sched_choice%"=="4" goto end
goto end

:install_schedule
echo.
echo 正在安装定时任务 (每6小时执行)...
schtasks /Create /TN "V2-6H-快速训练" /TR "D:\openclaw\binancepro\quick_retrain_v2.py" /SC HOURLY /MO 6 /F /ST 02:00 2>nul
if %ERRORLEVEL% EQU 0 (
    echo [✓] 定时任务安装成功!
    echo.
    echo 执行时间: 每天 02:00, 08:00, 14:00, 20:00
    echo 预计耗时: 3-4分钟
    echo 特点: 增量更新数据 + 快速训练
) else (
    echo [!] 安装失败，请检查权限或以管理员身份运行
)
echo.
pause
goto end

:remove_schedule
echo.
echo 正在删除定时任务...
schtasks /Delete /TN "V2-6H-快速训练" /F 2>nul
if %ERRORLEVEL% EQU 0 (
    echo [✓] 定时任务已删除
) else (
    echo [!] 任务不存在或删除失败
)
echo.
pause
goto end

:check_schedule
echo.
echo 当前定时任务状态:
echo ==========================================
schtasks /Query /TN "V2-6H-快速训练" 2>nul || echo 任务不存在
echo.
pause
goto end

:download_only
echo.
echo ==========================================
echo 增量更新数据 (只下载缺失的最新数据)
echo ==========================================
echo.
python update_data_incremental.py
echo.
echo 如需查看数据新鲜度:
echo   python -c "import pandas as pd; df=pd.read_csv('eth_usdt_15m_binance.csv'); print(f'数据截止: {df[\"timestamp\"].max()}')"
echo.
pause
goto end

:quick_retrain
echo.
echo ==========================================
echo V2快速重训练 (推荐 - 仅需3-4分钟)
echo ==========================================
echo.
echo 特点:
echo   - 增量更新数据 (30-60秒)
echo   - 快速训练 (2-3分钟)
echo   - 自动热加载 (无需重启交易程序)
echo.
echo 适合ETH高波动环境，每6小时执行一次
echo.
pause
python quick_retrain_v2.py
echo.
pause
goto end

:full_retrain
echo.
echo ==========================================
echo V2完整重训练 (5-8分钟)
echo ==========================================
echo.
echo 特点:
echo   - 全量数据验证
echo   - 完整交叉验证 (可选)
echo   - 更准确的模型评估
echo.
echo 适合每日深度优化，或快速训练效果不佳时使用
echo.
call :train_regime_internal
echo.
pause
goto end

:train_signal
echo.
echo ==========================================
echo 训练交易信号模型
echo ==========================================
echo.

REM 先检查是否有数据文件
if not exist "historical_data.db" (
    echo [!] 未找到数据文件，先下载数据...
    python download_binance_data.py --update --interval 15m
)

python auto_ml_trainer.py --interval 15m --once
echo.
echo 交易信号模型训练完成!
echo.
pause
goto end

:train_regime_internal
echo [1/5] 检查XGBoost依赖...
python -c "import xgboost; print(f'XGBoost版本: {xgboost.__version__}')" 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [!] XGBoost未安装，正在安装...
    python -m pip install xgboost pandas numpy -q
)

echo.
echo [2/5] 增量更新数据（只下载缺失的最新数据）...
python update_data_incremental.py

echo.
echo [3/5] 准备训练数据...
REM 查找最新的数据文件
set "DATA_FILE="
for %%f in (eth_usdt_15m_binance.csv data\ethusdt_15m_*.csv) do (
    if exist "%%f" (
        set "DATA_FILE=%%f"
        goto found_data
    )
)
:found_data

if "%DATA_FILE%"=="" (
    echo [!] 未找到数据文件，先下载数据...
    python download_binance_data.py --update --interval 15m
    set "DATA_FILE=eth_usdt_15m_binance.csv"
)

echo 使用数据文件: %DATA_FILE%

echo.
echo [4/5] 开始训练市场环境判断模型...
echo 训练参数: lookforward=48 (12小时), 15分钟周期
echo.

python train_regime_v2.py --data "%DATA_FILE%" --output models/regime_xgb_v1.pkl --lookforward 48 --test-size 0.15

if %ERRORLEVEL% EQU 0 (
    echo.
    echo [5/5] 训练完成!
    echo.
    echo 模型文件: models/regime_xgb_v1.pkl
    echo.
    echo 热加载说明:
    echo   交易程序会自动检测新模型 (60秒内)
    echo   无需重启程序！
    echo.
    echo 测试模型:
    echo   python test_regime_v2.py --model models/regime_xgb_v1.pkl --data "%DATA_FILE%"
) else (
    echo.
    echo [!] 训练失败，请检查错误信息
)

goto :eof

:train_all
echo.
echo ==========================================
echo 训练所有模型 (完整流程)
echo ==========================================
echo.

REM 检查/下载数据
if not exist "historical_data.db" (
    echo [准备] 下载最新数据...
    python download_binance_data.py --update --interval 15m
)

echo.
echo [1/2] 训练交易信号模型...
python auto_ml_trainer.py --interval 15m --once
if %ERRORLEVEL% NEQ 0 (
    echo [!] 交易信号模型训练失败
) else (
    echo [✓] 交易信号模型训练完成
)

echo.
echo [2/2] 训练市场环境判断模型 (V2)...
call :train_regime_internal
if %ERRORLEVEL% NEQ 0 (
    echo [!] 市场环境模型训练失败
) else (
    echo [✓] 市场环境模型训练完成
)

echo.
echo ==========================================
echo 所有模型训练完成!
echo ==========================================
echo.
echo 模型文件列表:
if exist "ml_model_trained.pkl" echo   - ml_model_trained.pkl (交易信号模型)
if exist "models\regime_xgb_v1.pkl" echo   - models\regime_xgb_v1.pkl (市场环境V2模型)
echo.
echo 提示: 交易程序会自动加载新模型 (热加载)
echo.
pause
goto end

:view_logs
echo.
echo 训练日志 (最近50行):
echo ==========================================
if exist ml_auto_training.log (
    powershell -Command "Get-Content ml_auto_training.log -Tail 50"
) else if exist models\regime_v2_last_training.txt (
    type models\regime_v2_last_training.txt
) else (
    echo 暂无日志文件
)
echo.
pause
goto end

:stop_service
echo.
echo ==========================================
echo 停止定时服务
echo ==========================================
echo.
schtasks /Delete /TN "V2-6H-快速训练" /F 2>nul
if %ERRORLEVEL% EQU 0 (
    echo [✓] 定时任务已删除
) else (
    echo [!] 任务不存在或删除失败
)
echo.
pause
goto end

:end
