@echo off
chcp 65001 >nul
title 市场环境检测V2 - 优化训练
echo.
echo ==========================================
echo    市场环境检测 V2 - 优化版训练
echo    5分类优化模型（SIDEWAYS/TREND_UP/TREND_DOWN/BREAKOUT/EXTREME）
echo ==========================================
echo.

REM 查找数据文件
set "DATA_FILE=eth_usdt_15m_binance.csv"
if not exist "%DATA_FILE%" (
    for %%f in (data\ethusdt_15m_*.csv) do (
        set "DATA_FILE=%%f"
        goto found_data
    )
)
:found_data

echo 数据文件: %DATA_FILE%
echo.

REM 训练参数
set "MODEL_OUTPUT=models/regime_xgb_v2_optimized.pkl"
set "LOOKFORWARD=48"
set "TEST_SIZE=0.15"

echo [1/3] 检查依赖...
python -c "import xgboost; print(f'XGBoost: {xgboost.__version__}')" 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [!] 安装依赖...
    python -m pip install xgboost pandas numpy -q
)

echo.
echo [2/3] 开始训练...
echo 优化参数:
echo   - 类别数: 5 (合并稀有类别)
echo   - 特征数: 39
echo   - 树深度: 8
echo   - 学习率: 0.1
echo   - 树数量: 300
echo.

python train_regime_v2.py --data "%DATA_FILE%" --output %MODEL_OUTPUT% --lookforward %LOOKFORWARD% --test-size %TEST_SIZE%

if %ERRORLEVEL% EQU 0 (
    echo.
    echo [3/3] 训练完成!
    echo.
    echo 模型文件: %MODEL_OUTPUT%
    echo.
    echo 启用优化版V2:
    echo   config.py 修改:
    echo   ML_REGIME_VERSION = "v2"
    echo   ML_REGIME_V2_MODEL_PATH = "%MODEL_OUTPUT%"
    echo.
    echo 测试模型:
    echo   python test_regime_v2.py --model %MODEL_OUTPUT% --data "%DATA_FILE%"
) else (
    echo.
    echo [!] 训练失败
)

echo.
pause
