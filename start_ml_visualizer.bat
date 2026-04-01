@echo off
chcp 65001 >nul
title V12 ML模型可视化监控
echo.
echo ==========================================
echo    V12 ML模型可视化监控窗口
echo ==========================================
echo.
echo 选择可视化模式:
echo.
echo [1] Matplotlib桌面窗口 (简单，实时)
echo [2] Web仪表盘 (推荐，功能丰富)
echo.
set /p choice="请选择 (1/2): "

if "%choice%"=="1" goto matplotlib
if "%choice%"=="2" goto web
goto end

:matplotlib
echo.
echo 启动Matplotlib桌面窗口...
echo 关闭窗口即可停止
echo.
python ml_visualizer.py
goto end

:web
echo.
echo 启动Web仪表盘...
echo 请打开浏览器访问: http://127.0.0.1:8050
echo 按Ctrl+C停止
echo.
python ml_dashboard.py
goto end

:end
echo.
pause
