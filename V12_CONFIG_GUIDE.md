# V12优化版 - 参数配置指南

## 配置文件位置
`config.py` - 所有可调参数集中管理

---

## 一、基础交易参数

| 参数 | 默认值 | 说明 | 调优建议 |
|------|--------|------|----------|
| `SYMBOLS` | ["ETHUSDT"] | 交易对列表 | 不建议改，ETH流动性最好 |
| `INTERVAL` | "1m" | K线周期 | 1m适合日内，5m更稳定 |
| `LEVERAGE` | 5 | 杠杆倍数 | 5-10倍平衡型，>10倍高风险 |
| `MODE` | "PAPER" | 模式 | 实盘前务必测试用PAPER |

---

## 二、风控参数（核心）

### 日风控
```python
MAX_DAILY_LOSS_PCT = 0.05      # 日亏损5%停止交易
MAX_DAILY_TRADES = 50          # 日最多50笔
MAX_DD_LIMIT = 0.15            # 回撤15%熔断
```

### 单笔风控
```python
MAX_RISK_PCT = 0.03            # 单笔风险3%
POSITION_SIZE_PCT_MIN = 0.20   # 最小仓位20%
POSITION_SIZE_PCT_MAX = 0.60   # 最大仓位60%
```

**效果示例**（余额$100）：
- 最小开仓：$20（0.01ETH @ $2000）
- 最大开仓：$60（0.03ETH @ $2000）

---

## 三、止盈止损参数（盈利关键）

### 止损设置
```python
STOP_LOSS_ATR_MULT = 2.0       # 止损倍数
STOP_LOSS_MIN_PCT = 0.008      # 最小0.8%
```

### 止盈设置
```python
# 震荡市：保守
TP_SIDEWAYS_ATR_MULT = 4.0     # 4倍ATR

# 趋势市：激进
TP_TRENDING_ATR_MULT = 8.0     # 8倍ATR
```

### 移动止盈
```python
TRAILING_STOP_ENABLE_PCT = 0.008    # 盈利>0.8%启用
TRAILING_STOP_DRAWBACK_PCT = 0.30   # 回撤30%止盈
```

**场景对比**：
- 盈利2% → 回撤到1.4%触发移动止盈（锁定70%利润）

### 盈利保护
```python
PROFIT_PROTECTION_ENABLE_PCT = 0.005   # 浮盈>0.5%启用
PROFIT_PROTECTION_DRAWBACK_PCT = 0.50  # 回撤50%平仓
```

**场景**：峰值1% → 回撤到0.5%强制平仓（防盈利变亏损）

---

## 四、信号参数

### ML模型
```python
ML_CONFIDENCE_THRESHOLD = 0.56      # ML信号门槛
ML_MIN_TRAINING_SAMPLES = 30        # 最小训练样本
ML_TRAINING_INTERVAL_HOURS = 4      # 每4小时重训练
```

**门槛调整**：
- 0.50 = 所有ML信号都参与（激进）
- 0.56 = 平衡（推荐）
- 0.65 = 仅高确信（保守）

### 技术指标
```python
TECH_RSI_OVERSOLD = 30        # RSI超卖
TECH_RSI_OVERBOUGHT = 70      # RSI超买
TECH_BB_WIDTH_THRESHOLD = 0.05  # 布林带收窄判断
TECH_ADX_TREND_THRESHOLD = 25   # 趋势强度
```

---

## 五、冷却期参数

```python
COOLDOWN_HIGH_CONFIDENCE = 5    # >0.75置信度：5秒
COOLDOWN_MID_CONFIDENCE = 15    # 0.65-0.75：15秒
COOLDOWN_LOW_CONFIDENCE = 25    # <0.65：25秒
COOLDOWN_MAX_SECONDS = 60       # 最高封顶60秒
COOLDOWN_AFTER_LOSS = 15        # 亏损后+15秒
```

---

## 六、插针保护（ETH合约必备）

```python
SPIKE_DETECTION_WINDOW_SECONDS = 60   # 检测窗口1分钟
SPIKE_PRICE_CHANGE_THRESHOLD = 0.02   # 波动>2%熔断
SPIKE_CIRCUIT_BREAKER_MINUTES = 5     # 暂停5分钟
```

---

## 七、三套推荐配置

### 【保守型】适合小资金/新手
```python
MAX_RISK_PCT = 0.02
POSITION_SIZE_PCT_MAX = 0.40
STOP_LOSS_ATR_MULT = 1.8
TP_SIDEWAYS_ATR_MULT = 3.0
ML_CONFIDENCE_THRESHOLD = 0.60
```

### 【平衡型】（当前默认）
```python
MAX_RISK_PCT = 0.03
POSITION_SIZE_PCT_MAX = 0.60
STOP_LOSS_ATR_MULT = 2.0
TP_SIDEWAYS_ATR_MULT = 4.0
ML_CONFIDENCE_THRESHOLD = 0.56
```

### 【激进型】适合大资金/经验丰富
```python
MAX_RISK_PCT = 0.05
POSITION_SIZE_PCT_MAX = 0.80
STOP_LOSS_ATR_MULT = 2.5
TP_SIDEWAYS_ATR_MULT = 5.0
ML_CONFIDENCE_THRESHOLD = 0.52
```

---

## 八、常见问题

### Q1: 为什么仓位总是固定值？
**A**: 余额太小被 `MIN_NOTIONAL=21` 截断。建议余额>$100或调整 `POSITION_SIZE_PCT_MIN` 到0.15。

### Q2: 如何降低交易频率？
**A**: 增加冷却期参数：
```python
COOLDOWN_HIGH_CONFIDENCE = 15
COOLDOWN_MID_CONFIDENCE = 30
COOLDOWN_LOW_CONFIDENCE = 60
```

### Q3: 如何捕获更大趋势？
**A**: 放宽止盈：
```python
TRAILING_STOP_DRAWBACK_PCT = 0.40  # 40%回撤才止盈
TP_TRENDING_ATR_MULT = 10.0        # 趋势市10倍ATR
```

---

## 九、参数修改后重启

```bash
python main_v12_live_optimized.py
```

修改 `config.py` 后必须重启程序才能生效！
