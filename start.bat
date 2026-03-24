@echo off
chcp 65001 >nul
echo ==========================================
echo ETH/USDT 量化交易系统启动器
echo ==========================================
echo.

:: 检查Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到Python，请先安装Python 3.8+
    pause
    exit /b 1
)

:: 检查依赖
echo [1/3] 检查依赖...
pip show requests pandas numpy websocket-client python-dotenv prometheus-client >nul 2>&1
if errorlevel 1 (
    echo 安装依赖中...
    pip install -r requirements.txt
)

:: 创建日志目录
echo [2/3] 创建日志目录...
if not exist logs mkdir logs

:: 启动系统
echo [3/3] 启动交易系统...
echo.
echo 模式: LIVE (实盘交易)
echo 交易对: ETHUSDT, BTCUSDT, SOLUSDT
echo 日志目录: ./logs/
echo 数据库: elite_trades.db
echo.
echo 按 Ctrl+C 停止系统
echo ==========================================
echo.

python main.py

pause
