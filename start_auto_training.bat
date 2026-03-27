@echo off
chcp 65001 >nul
title V12 ML自动训练服务
echo.
echo ==========================================
echo    V12 ML模型自动训练服务
echo    交易信号模型 + 市场环境判断模型
echo ==========================================
echo.
echo 启动选项:
echo   [1] 启动完整服务 (先下载数据 + 定时训练)
echo   [2] 仅下载最新数据
echo   [3] 立即训练交易信号模型
ec
ho   [4] 立即训练市场环境判断模型 (V2 XGBoost)
echo   [5] 训练所有模型 (交易信号 + 市场环境)
echo   [6] 查看训练日志
echo   [7] 停止训练服务
echo.
set /p choice="请选择 (1/2/3/4/5/6/7): "

if "%choice%"=="1" goto full_service
if "%choice%"=="2" goto download_only
if "%choice%"=="3" goto train_signal
if "%choice%"=="4" goto train_regime
if "%choice%"=="5" goto train_all
if "%choice%"=="6" goto view_logs
if "%choice%"=="7" goto stop_service
goto end

:full_service
echo.
echo ==========================================
echo 步骤 1/3: 下载最新数据
echo ==========================================
echo.

python download_binance_data.py --update --interval 15m

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [!] 数据下载可能有问题，是否继续训练?
    set /p continue="继续训练? (y/n): "
    if /I not "%continue%"=="y" goto end
)

echo.
echo ==========================================
echo 步骤 2/3: 训练交易信号模型
echo ==========================================
echo.

python auto_ml_trainer.py --interval 15m --once
if %ERRORLEVEL% NEQ 0 (
    echo [!] 交易信号模型训练失败
)

echo.
echo ==========================================
echo 步骤 3/3: 训练市场环境判断模型 (V2)
echo ==========================================
echo.

call :train_regime_internal

echo.
echo ==========================================
echo 启动定时训练服务 (每6小时)
echo ==========================================
echo.
echo 日志文件: ml_auto_training.log
echo.
echo 按Ctrl+C停止服务
echo.

python -m pip install schedule -q && python auto_ml_trainer.py --interval 15m --hours 6 --daemon
echo.
echo 服务已停止
echo.
pause
goto end

:download_only
echo.
echo 下载最新数据...
echo.
python download_binance_data.py --update --interval 15m
echo.
echo 数据下载完成!
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

:train_regime
echo.
echo ==========================================
echo 训练市场环境判断模型 (V2 XGBoost)
echo ==========================================
echo.
call :train_regime_internal
echo.
pause
goto end

:train_regime_internal
echo [1/4] 检查XGBoost依赖...
python -c "import xgboost; print(f'XGBoost版本: {xgboost.__version__}')" 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [!] XGBoost未安装，正在安装...
    python -m pip install xgboost pandas numpy -q
)

echo.
echo [2/4] 准备训练数据...
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
echo [3/4] 开始训练市场环境判断模型...
echo 训练参数: lookforward=48 (12小时), 15分钟周期
echo.

python train_regime_v2.py --data "%DATA_FILE%" --output models/regime_xgb_v1.pkl --lookforward 48 --test-size 0.15

if %ERRORLEVEL% EQU 0 (
    echo.
    echo [4/4] 训练完成!
    echo.
    echo 模型文件: models/regime_xgb_v1.pkl
    echo.
    echo 启用V2方法:
    echo   修改 config.py:
    echo   ML_REGIME_VERSION = "v2"
    echo   ML_REGIME_V2_MODEL_PATH = "models/regime_xgb_v1.pkl"
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
echo 训练所有模型
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
pause
goto end

:view_logs
echo.
echo 训练日志 (最近50行):
echo ==========================================
if exist ml_auto_training.log (
    powershell -Command "Get-Content ml_auto_training.log -Tail 50"
) else (
    echo 暂无日志文件
)
echo.
pause
goto end

:stop_service
echo.
echo 要停止服务，请在服务窗口按 Ctrl+C
echo 或者关闭训练窗口
echo.
pause
goto end

:end
