# V12 ML模型自检与维护系统指南

> **版本**: 1.0  
> **更新日期**: 2026-03-24  
> **状态**: 生产就绪

---

## 📋 系统概述

### 为什么需要ML自检系统？

当前问题：
- ❌ ML模型在胜率下降时无感知
- ❌ 交易参数固定，无法适应市场变化
- ❌ 模型退化时发现太晚，已造成大亏损
- ❌ 需要人工监控，无法24/7值守

解决方案：
- ✅ 实时监控模型性能指标
- ✅ 自动检测胜率下降、回撤过大
- ✅ 自动调整参数或暂停交易
- ✅ 异常时发送警报

---

## 🏗️ 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                     ML自检与维护系统                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────┐  │
│  │  指标计算引擎    │───▶│  健康诊断引擎    │───▶│  自动维护    │  │
│  │  (实时计算)     │    │  (阈值判断)     │    │  (参数调整)  │  │
│  └─────────────────┘    └─────────────────┘    └─────────────┘  │
│           │                      │                    │         │
│           ▼                      ▼                    ▼         │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  监控指标                                                  │  │
│  │  - 胜率(10/20/50笔)                                        │  │
│  │  - 回撤 / 盈亏比 / 夏普比率                                 │  │
│  │  - ML置信度 / 信号频率                                     │  │
│  │  - 预测准确度 / 特征稳定性                                  │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │  交易参数动态调整  │
                    │  - ML阈值         │
                    │  - 止损倍数       │
                    │  - 仓位大小       │
                    │  - 交易开关       │
                    └─────────────────┘
```

---

## 🎯 核心功能

### 1. 健康状态分级

| 状态 | 条件 | 动作 |
|-----|------|------|
| 🟢 **健康** | 胜率≥40%，回撤<10% | 维持现状，逐步恢复参数 |
| 🟡 **警告** | 胜率30-40%，或回撤10-20% | 提高阈值，收紧止损 |
| 🔴 **危险** | 胜率<30%，或回撤>20% | 暂停交易，紧急维护 |
| ⚪ **未知** | 数据不足 | 保守策略，提高门槛 |

### 2. 自动维护动作

**警告状态时的调整**:
```python
# 胜率下降 → 提高ML阈值
ml_threshold: 0.80 → 0.82 → 0.85

# 回撤过大 → 收紧止损
stop_loss_mult: 2.0x → 1.8x → 1.5x

# 信号过少 → 略微降低阈值
ml_threshold: 0.85 → 0.83 (仅当信号<2笔/小时)
```

**危险状态时的紧急维护**:
```python
# 立即执行
ml_threshold: → 0.90 (几乎暂停新信号)
stop_loss_mult: → 1.5x (严格止损)
position_size: → 50% (降低仓位)
trading_enabled: → False (如果胜率<10%)
```

### 3. 参数自适应恢复

**健康状态时的逐步恢复**:
```python
# 每30分钟检查一次
if 连续3次健康:
    ml_threshold: -= 0.01 (逐步恢复正常)
    
if 胜率稳定>40% 且 回撤<5%:
    恢复交易权限
```

---

## 🚀 快速开始

### 方式1: 命令行工具（推荐测试）

```bash
# 启动交互式菜单
start_ml_monitor.bat
```

选项：
- `1` - 立即生成诊断报告
- `2` - 启动自动监控（后台运行）
- `3` - 查看历史警报
- `4` - 手动恢复交易

### 方式2: 集成到交易系统

在 `main_v12_live_optimized.py` 中添加：

```python
# 1. 导入
from ml_monitor_integration import MLMonitorBridge

# 2. 初始化
class V12OptimizedTrader:
    def __init__(self):
        # ... 原有代码 ...
        
        # 启动ML监控
        self.ml_monitor = MLMonitorBridge(self)
        self.ml_monitor.start()
        
    # 3. 交易前检查
    def generate_signal(self, ...):
        # 检查是否允许交易
        can_trade, reason = self.ml_monitor.can_trade()
        if not can_trade:
            logger.warning(f'[MLMonitor] 交易被阻止: {reason}')
            return TradingSignal('HOLD', ...)
        
        # ... 生成信号 ...
        
    # 4. 定期检查和调整
    def run_cycle(self):
        # ... 原有代码 ...
        
        # ML自检和调整
        self.ml_monitor.check_and_adjust()
```

---

## 📊 监控指标详解

### 核心指标

#### 1. 胜率趋势
```python
win_rate_10  # 最近10笔胜率 (短期敏感度)
win_rate_20  # 最近20笔胜率 (中期趋势)
win_rate_50  # 最近50笔胜率 (长期稳定性)

# 健康标准
win_rate_10 > 40%  # 短期正常
win_rate_20 > 35%  # 中期正常
win_rate_50 > 30%  # 长期底线
```

#### 2. 回撤控制
```python
max_drawdown  # 最大回撤

# 分级
< 5%   # 优秀 ✅
5-10%  # 正常 ✅
10-20% # 警告 ⚠️
> 20%  # 危险 🚨 暂停交易
```

#### 3. ML信号质量
```python
avg_confidence    # 平均置信度
high_conf_ratio   # 高置信度(>0.8)比例
signal_frequency  # 信号频率(笔/小时)

# 健康标准
avg_confidence > 0.70
high_conf_ratio > 20%
signal_frequency > 2 笔/小时
```

#### 4. 预测准确度
```python
prediction_accuracy  # 预测方向准确率
calibration_error    # 置信度校准误差

# 理想值
prediction_accuracy > 55%  # 高于随机
calibration_error < 0.10   # 置信度校准良好
```

---

## ⚙️ 配置文件

### 自适应参数文件

文件: `ml_adaptive_config.json`

```json
{
  "ml_threshold": 0.85,
  "stop_loss_mult": 1.8,
  "position_size_pct": 0.60,
  "trading_enabled": true,
  "last_update": "2026-03-24T18:30:00",
  "reason": null
}
```

### 阈值配置

在 `ml_self_diagnosis.py` 中修改：

```python
THRESHOLDS = {
    'win_rate_warning': 0.30,      # 胜率警告线
    'win_rate_critical': 0.20,     # 胜率危险线
    'drawdown_warning': 0.10,      # 回撤警告线
    'drawdown_critical': 0.20,     # 回撤危险线
    'profit_factor_min': 1.0,      # 盈亏比最小值
    'confidence_min': 0.70,        # 最小平均置信度
}
```

---

## 🚨 警报与响应

### 警报类型

#### 1. 警告警报（WARNING）
- 触发条件: 胜率<35% 或 回撤>10%
- 自动动作: 提高阈值，收紧止损
- 人工干预: 可选，观察即可

#### 2. 危险警报（CRITICAL）
- 触发条件: 胜率<20% 或 回撤>20%
- 自动动作: 暂停交易，降低仓位
- 人工干预: **必需**，检查模型后手动恢复

#### 3. 维护报告
- 生成频率: 每10次检查
- 内容: 完整性能指标、趋势分析、建议
- 保存位置: `ml_diagnosis_YYYYMMDD_HHMMSS.txt`

### 查看警报历史

```bash
# 查看所有警报
dir ml_alert_*.txt

# 查看最新诊断
type ml_diagnosis_*.txt | more
```

---

## 🔧 故障排除

### 问题1: 监控未启动

**检查**:
```python
# 在Python控制台
from ml_monitor_integration import MLMonitorBridge
m = MLMonitorBridge(None)
print(m.get_status())
```

**解决**: 确保在 `run_cycle` 中调用了 `check_and_adjust()`

### 问题2: 参数未生效

**检查**: 
```bash
type ml_adaptive_config.json
```

**解决**:
```python
# 手动应用参数
trader.ml_monitor._apply_to_trader()
```

### 问题3: 误报频繁

**调整阈值**:
```python
# 在 ml_self_diagnosis.py 中
THRESHOLDS['win_rate_warning'] = 0.25  # 放宽到25%
```

### 问题4: 无法恢复交易

**手动恢复**:
```bash
start_ml_monitor.bat
# 选择 4 - 手动恢复交易
```

或在Python中：
```python
trader.ml_monitor.resume_trading()
```

---

## 📈 实战案例

### 案例1: 胜率持续下降

**现象**:
- win_rate_10: 50% → 40% → 30% → 20%
- 连续4次检查下降

**系统自动响应**:
1. 触发WARNING，提高ML阈值 0.80 → 0.84
2. 触发WARNING，收紧止损 2.0x → 1.8x
3. 触发CRITICAL，暂停交易

**人工处理**:
1. 检查特征重要性是否变化
2. 查看最近交易记录
3. 必要时重新训练模型
4. 确认后手动恢复: `trader.ml_monitor.resume_trading()`

### 案例2: 单笔大亏损

**现象**:
- 单笔亏损 -8% (远超预期)
- 最大回撤突破 20%

**系统自动响应**:
1. 立即触发CRITICAL
2. 暂停所有新交易
3. 降低仓位到50%
4. 收紧止损到1.5x

**人工处理**:
1. 分析该笔交易原因
2. 检查是否是黑天鹅事件
3. 调整风控参数
4. 逐步恢复交易

### 案例3: 市场变化适应

**现象**:
- 原特征重要性: trend_short (0.11)
- 现特征重要性: volume_ratio (0.15)
- 市场环境从趋势市转为量价驱动

**系统响应**:
1. 信号频率下降
2. 自动略微降低ML阈值
3. 增加仓位以抓住机会

**人工优化**:
1. 更新特征工程
2. 添加订单簿特征
3. 重新训练模型

---

## 🎯 最佳实践

### 1. 监控频率设置

```python
# 高波动市场
check_interval_minutes = 15  # 15分钟检查一次

# 正常市场
check_interval_minutes = 30  # 30分钟检查一次

# 低波动市场
check_interval_minutes = 60  # 60分钟检查一次
```

### 2. 渐进式参数调整

```python
# 避免大幅跳跃
ml_threshold: 0.80 → 0.82 → 0.85  (每次+0.02)

# 给市场适应时间
调整后观察至少3个周期再调
```

### 3. 人工审核清单

收到CRITICAL警报后：
- [ ] 查看最近10笔交易明细
- [ ] 检查ML特征重要性变化
- [ ] 确认是否是市场异常（如黑天鹅）
- [ ] 检查数据源是否正常
- [ ] 必要时重新训练模型
- [ ] 手动恢复交易并密切观察

### 4. 备份策略

```bash
# 定期备份配置
copy ml_adaptive_config.json ml_adaptive_config.backup.json

# 备份交易记录
sqlite3 v12_optimized.db ".dump trades" > trades_backup.sql
```

---

## 🔮 未来规划

- [ ] 集成微信/钉钉实时通知
- [ ] A/B测试框架（新旧模型对比）
- [ ] 自动特征选择
- [ ] 在线学习（增量更新模型）
- [ ] 多模型集成投票

---

**遇到问题？** 查看日志 `logs/` 目录或运行诊断工具。

**重要提示**: 本系统是辅助工具，关键决策仍需人工审核。
