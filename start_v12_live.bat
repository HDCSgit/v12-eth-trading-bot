@echo off
chcp 65001
title V12-LIVE 实盘交易
echo ==========================================
echo    V12-LIVE 实盘交易系统
echo ==========================================
echo.

:: 检查虚拟环境
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
    echo [√] 虚拟环境已激活
) else (
    echo [!] 未找到虚拟环境，使用系统Python
)

:: 检查日志目录
if not exist "logs" mkdir logs

echo.
echo [1/3] 检查API连接...
python verify_api.py
if %errorlevel% neq 0 (
    echo [X] API连接失败，请检查配置
    pause
    exit /b 1
)

echo.
echo [2/3] 检查资金费率...
python -c "from binance_api import BinanceExpertAPI; api = BinanceExpertAPI(); rate = api.get_funding_rate('ETHUSDT'); print(f'当前资金费率: {rate:.4%}')"

echo.
echo [3/3] 启动实盘交易...
echo [!] 请确认已阅读风险警告
echo [!] 按Ctrl+C可随时停止
echo.
timeout /t 3 >nul

python main_v12_live.py

echo.
echo 交易已停止
pause