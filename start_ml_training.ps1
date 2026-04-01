# V12 ML模型自动训练服务 - PowerShell版本
# 在PowerShell中运行: .\start_ml_training.ps1

$Host.UI.RawUI.WindowTitle = "V12 ML自动训练服务"

function Show-Menu {
    Clear-Host
    Write-Host "==========================================" -ForegroundColor Cyan
    Write-Host "   V12 ML模型自动训练服务" -ForegroundColor Green
    Write-Host "==========================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  每6小时自动重新训练ML模型" -ForegroundColor Gray
    Write-Host ""
    Write-Host "==========================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  [1] 启动定时训练服务 - 每6小时" -ForegroundColor Yellow
    Write-Host "  [2] 立即训练一次" -ForegroundColor Yellow
    Write-Host "  [3] 查看训练日志" -ForegroundColor Yellow
    Write-Host "  [4] 停止训练服务" -ForegroundColor Yellow
    Write-Host "  [5] 退出" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "==========================================" -ForegroundColor Cyan
}

function Start-TrainingService {
    Write-Host ""
    Write-Host "[*] 启动定时训练服务..." -ForegroundColor Green
    Write-Host "[*] 将每6小时自动训练一次" -ForegroundColor Gray
    Write-Host "[*] 按 Ctrl+C 可停止服务" -ForegroundColor Gray
    Write-Host ""
    Start-Sleep -Seconds 2
    python auto_ml_trainer.py --daemon --hours 6
}

function Train-Once {
    Write-Host ""
    Write-Host "[*] 开始单次训练..." -ForegroundColor Green
    Write-Host ""
    Start-Sleep -Seconds 1
    python auto_ml_trainer.py --once
    Write-Host ""
    Write-Host "[*] 训练完成" -ForegroundColor Green
    Write-Host ""
    pause
}

function View-Logs {
    Write-Host ""
    Write-Host "[*] 查看训练日志..." -ForegroundColor Green
    Write-Host ""
    if (Test-Path "ml_auto_training.log") {
        Write-Host "=== 最近20行日志 ===" -ForegroundColor Cyan
        Write-Host ""
        Get-Content "ml_auto_training.log" -Tail 20
        Write-Host ""
        Write-Host "=== 日志文件: ml_auto_training.log ===" -ForegroundColor Cyan
    } else {
        Write-Host "[WARN] 日志文件不存在，请先运行训练" -ForegroundColor Red
    }
    Write-Host ""
    pause
}

function Stop-Service {
    Write-Host ""
    Write-Host "[*] 停止训练服务..." -ForegroundColor Yellow
    $process = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*auto_ml_trainer*" }
    if ($process) {
        Stop-Process -Id $process.Id -Force
        Write-Host "[OK] 服务已停止" -ForegroundColor Green
    } else {
        Write-Host "[!] 未找到运行中的训练服务" -ForegroundColor Gray
    }
    Write-Host ""
    pause
}

# 检查Python
$pythonCheck = python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Python未安装或未添加到PATH" -ForegroundColor Red
    pause
    exit 1
}

# 激活虚拟环境
if (Test-Path "venv\Scripts\Activate.ps1") {
    .\venv\Scripts\Activate.ps1
    Write-Host "[OK] 虚拟环境已激活" -ForegroundColor Green
} else {
    Write-Host "[!] 使用系统Python" -ForegroundColor Gray
}

# 主循环
while ($true) {
    Show-Menu
    $choice = Read-Host "请输入数字 1-5"
    
    switch ($choice) {
        "1" { Start-TrainingService; break }
        "2" { Train-Once }
        "3" { View-Logs }
        "4" { Stop-Service }
        "5" { Write-Host ""; Write-Host "[*] 退出" -ForegroundColor Gray; exit }
        default { 
            Write-Host ""
            Write-Host "[ERROR] 无效选择，请输入 1-5" -ForegroundColor Red
            Start-Sleep -Seconds 1
        }
    }
}
