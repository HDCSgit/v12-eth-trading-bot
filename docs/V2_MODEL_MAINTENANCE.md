# V2市场环境模型维护指南

## 问题：数据滞后

当前模型训练数据截止到文件最后时间，如果不定期更新，模型会对最新市场环境判断滞后。

## 解决方案（ETH高波动适配）

### 🆕 推荐方案：每6小时快速重训练

ETH市场波动大，建议**每6小时**更新模型：

**已配置自动任务**:
```
任务名: V2-6H-快速训练
执行频率: 每6小时
执行时间: 02:00, 08:00, 14:00, 20:00
预计耗时: 3-4分钟
```

**手动立即执行**:
```bash
# 快速重训练（3-4分钟）
python quick_retrain_v2.py

# 或完整训练（5-8分钟）
python train_regime_v2_auto.py
```

或在Python中实现定时：

```python
# train_scheduler.py
import schedule
import time

def daily_training():
    print("开始每日自动训练...")
    import subprocess
    subprocess.run("python train_regime_v2_auto.py", shell=True)

schedule.every().day.at("02:00").do(daily_training)

while True:
    schedule.run_pending()
    time.sleep(60)
```

### 方案3：实时监控数据新鲜度

在交易程序中添加数据新鲜度检查：

```python
# 在main_v12_live_optimized.py中添加
import pandas as pd
from datetime import datetime, timedelta

def check_data_freshness():
    df = pd.read_csv('eth_usdt_15m_binance.csv')
    last_time = pd.to_datetime(df['timestamp'].max())
    hours_ago = (datetime.now() - last_time).total_seconds() / 3600
    
    if hours_ago > 12:
        logger.warning(f"⚠️ 数据已滞后{hours_ago:.1f}小时，建议更新模型")
        # 发送通知或自动触发更新
```

## 最佳实践

| 频率 | 操作 | 命令 |
|------|------|------|
| **每次交易前** | 检查数据新鲜度 | 看日志中的最后数据时间 |
| **每12小时** | 增量更新数据 | `python update_data_incremental.py` |
| **每天1次** | 重新训练模型 | `python train_regime_v2_auto.py` |
| **每周1次** | 完整数据重下载 | `python download_binance_data.py --days 90` |

## 快速修复当前滞后

立即执行：

```bash
# 1. 增量更新（约1-2分钟）
python update_data_incremental.py

# 2. 重新训练（约3-5分钟）
python train_regime_v2_auto.py

# 3. 重启交易程序加载新模型
# 不需要重启，模型会自动加载
```

## 监控指标

在交易日志中关注：

```
[INFO] 数据最后时间: 2026-03-27 00:15:00  ← 如果超过12小时，需要更新
[INFO] 模型训练时间: 2026-03-27 12:30:00  ← 应该接近当前时间
```

## 自动化脚本

已提供的自动化工具：

| 脚本 | 功能 |
|------|------|
| `update_data_incremental.py` | 只下载缺失的最新数据 |
| `train_regime_v2_auto.py` | 自动训练并备份旧模型 |
| `auto_train_scheduler.bat` | 一键更新+训练 |
| `start_auto_training.bat` | 交互式训练菜单 |
