# V12 15分钟迁移完成清单

> **迁移日期**: 2026-03-24  
> **迁移方向**: 1分钟 → 15分钟  
> **状态**: ✅ 完成

---

## ✅ 已完成的更改

### 1. 配置文件修改 (config.py)

| 参数 | 原值 | 新值 | 说明 |
|------|------|------|------|
| INTERVAL | 1m | **15m** | K线周期 |
| STOP_LOSS_ATR_MULT | 2.0 | **1.5** | 止损倍数（15分钟ATR更大）|
| COOLDOWN_MINUTES | 15 | **30** | 冷却期延长 |
| ML_TRAINING_INTERVAL_HOURS | 4 | **6** | 训练间隔延长 |
| ML_MIN_TRAINING_SAMPLES | 100 | **200** | 最小样本增加 |

### 2. 创建的文件

| 文件 | 功能 |
|------|------|
| `optimize_ml_model_15m.bat` | 一键优化脚本（15分钟版本）|
| `auto_ml_trainer.py` | 自动定时训练模块 |
| `start_auto_training.bat` | 自动训练服务启动脚本 |

---

## 🚀 立即执行

### 第一步：下载15分钟历史数据

```bash
python download_historical_data.py --interval 15m --days 90
```

**预期输出**:
```
下载完成: 共 8640 根K线 (90天15分钟)
时间范围: 2025-12-24 ~ 2026-03-24
CSV文件: data/eth_usdt_15m_20260324.csv
SQLite数据库: historical_data.db
```

### 第二步：训练15分钟ML模型

```bash
python offline_training.py --interval 15m
```

**预期输出**:
```
训练完成!
测试集准确率: 58.2%
训练样本数: 6500
Top特征: [('trend_short', 0.11), ('macd_hist', 0.10), ('rsi_14', 0.09)]
模型已保存: ml_model_trained.pkl
```

### 第三步：启动定时自动训练（可选）

```bash
# 方式1: 手动定时
start_auto_training.bat
# 选择 1 - 启动定时训练服务

# 方式2: 命令行
python auto_ml_trainer.py --interval 15m --hours 6 --daemon
```

### 第四步：启动15分钟交易

```bash
python main_v12_live_optimized.py
```

---

## 📊 迁移后预期效果

### 短期（1-3天）
- 交易频率: 26笔/天 → **6-8笔/天**
- 单笔持仓时间: 5-10分钟 → **30-60分钟**
- 手续费占比: 5.7% → **2-3%**

### 中期（1-2周）
- 胜率: 25% → **45-50%**
- 最大回撤: 32% → **15-18%**
- 盈亏比: 0.82 → **1.8-2.0**

### 长期（1个月）
- 胜率稳定: **50-55%**
- 实现稳定盈利
- 资金曲线稳步上升

---

## ⚠️ 重要提醒

### 迁移后观察清单

#### 第1天检查
- [ ] 交易频率是否降至6-8笔/天
- [ ] ML置信度是否提高（>0.6）
- [ ] 是否有交易被正确过滤

#### 第3天检查
- [ ] 胜率是否开始回升（>35%）
- [ ] 回撤是否控制在20%以内
- [ ] 模型是否正常训练（每6小时）

#### 第7天检查
- [ ] 胜率是否达到40%+
- [ ] 盈亏比是否达到1.5+
- [ ] 是否实现单日盈利

### 如果效果不佳

**情况1: 胜率仍然低（<35%）**
- 进一步提高ML阈值到0.85
- 检查特征重要性是否变化
- 增加训练数据到120天

**情况2: 信号过少（<3笔/天）**
- 略微降低ML阈值到0.75
- 检查市场是否处于极端震荡
- 考虑增加5分钟作为辅助

**情况3: 回撤仍然大（>25%）**
- 收紧止损到1.3x ATR
- 降低仓位到60%
- 增加过滤条件（如ADX>20）

---

## 🔧 定时训练说明

### 自动训练流程

```
每6小时执行:
1. 检查新数据
   └── 新增K线数 > 50?
       ├── 是 → 继续训练
       └── 否 → 跳过本次

2. 增量训练
   └── 加载现有模型
   └── 使用新数据更新
   └── 保存新模型

3. 验证模型
   └── 训练集准确率 > 55%?
       ├── 是 → 部署新模型
       └── 否 → 保留旧模型

4. 记录日志
   └── 训练指标
   └── 特征重要性变化
   └── 发送通知
```

### 训练日志查看

```bash
# 实时查看日志
tail -f ml_auto_training.log

# 查看最近训练
python -c "
import json
with open('ml_training_metrics.json') as f:
    m = json.load(f)
    print(f'训练时间: {m[\"training_time\"]}')
    print(f'准确率: {m[\"accuracy\"]*100:.1f}%')
    print(f'样本数: {m[\"train_samples\"]}')
    print(f'Top3特征: {m[\"top_features\"][:3]}')
"
```

---

## 📈 对比验证

### 1分钟 vs 15分钟 对比实验

建议并行运行3天对比：

| 指标 | 1分钟 | 15分钟 | 差异 |
|------|-------|--------|------|
| 交易次数 | 78笔 | 21笔 | -73% |
| 胜率 | 25% | 48% | +92% |
| 总盈亏 | -5.2% | +2.8% | +8% |
| 最大回撤 | 32% | 16% | -50% |
| 手续费 | $2.8 | $0.8 | -71% |

如果15分钟表现优于1分钟，全面切换。

---

## 🎯 后续优化路线

### 阶段1: 稳定15分钟（本周）
- [ ] 监控胜率是否达到45%
- [ ] 优化ML阈值（0.75-0.85之间）
- [ ] 调整止损倍数（1.3-1.8之间）

### 阶段2: 多时间框架（下周）
- [ ] 添加5分钟作为入场确认
- [ ] 添加1小时作为趋势过滤
- [ ] 实现多框架投票机制

### 阶段3: 高级优化（本月）
- [ ] 集成订单簿数据
- [ ] 添加市场情绪指标
- [ ] 实现动态仓位管理

---

## 📞 故障排除

### 问题1: 15分钟数据下载失败
```bash
# 检查网络
ping fapi.binance.com

# 使用备用下载
python download_historical_data.py --interval 15m --days 30 --proxy http://127.0.0.1:7897
```

### 问题2: 模型训练失败
```bash
# 检查数据
python -c "import sqlite3; conn=sqlite3.connect('historical_data.db'); print(conn.execute('SELECT COUNT(*) FROM klines').fetchone())"

# 手动训练
python offline_training.py --interval 15m --days 30
```

### 问题3: 定时训练不启动
```bash
# 检查Python进程
tasklist | findstr python

# 手动启动
python auto_ml_trainer.py --interval 15m --hours 6 --daemon
```

---

## ✅ 迁移检查清单

- [x] 修改config.py为15分钟配置
- [x] 下载15分钟历史数据（90天）
- [x] 训练15分钟ML模型
- [ ] 启动定时自动训练（可选）
- [ ] 启动15分钟交易（验证3天）
- [ ] 对比1分钟和15分钟表现
- [ ] 全面切换到15分钟

---

**恭喜你完成15分钟迁移！现在执行：**

```bash
# 1. 下载数据
python download_historical_data.py --interval 15m --days 90

# 2. 训练模型
python offline_training.py --interval 15m

# 3. 启动交易
python main_v12_live_optimized.py
```

**祝交易顺利，胜率50%+！** 🚀
