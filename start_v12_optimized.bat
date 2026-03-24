@echo off
chcp 65001 >nul
title V12优化版实盘交易系统
echo.
echo ==========================================
echo    V12-OPTIMIZED 优化版实盘交易系统
echo ==========================================
echo.

REM 检查Python环境
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到Python，请安装Python 3.8+
    pause
    exit /b 1
)

REM 创建日志目录
if not exist logs mkdir logs

REM 检查.env文件
if not exist .env (
    echo [警告] 未找到.env文件，请确保API密钥已配置
    echo.
)

echo [信息] 正在启动V12优化版交易系统...
echo [信息] 按 Ctrl+C 停止运行
echo.

python main_v12_live_optimized.py

echo.
echo [信息] 程序已退出
pause
