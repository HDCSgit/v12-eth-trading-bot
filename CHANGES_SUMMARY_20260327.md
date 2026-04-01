# 入场机制优化 - 修改总结 (2026-03-27)

## 修改概览
除了动态止损外，已实施所有讨论过的优化方案。

---

## 1. 配置参数调整 (config.py)

### 新增配置项
```python
# 当日价格区间过滤
ENABLE_DAILY_POSITION_FILTER = True  # 启用当日区间过滤
DAILY_POSITION_SHORT_MIN = 0.70      # 做空需在当日70%分位以上
DAILY_POSITION_LONG_MAX = 0.30       # 做多需在当日30%分位以下

# 硬性止损（独立于动态止损）
ENABLE_HARD_STOP = True              # 启用硬性止损
HARD_STOP_MAX_PCT = 0.015            # 最大允许亏损1.5%

# 盈亏比控制
MIN_RR_RATIO = 2.0                   # 最小盈亏比 1:2
FIXED_RR_MODE = True                 # 使用固定盈亏比模式
FIXED_STOP_PCT = 0.008               # 固定止损 0.8%
FIXED_TP_PCT = 0.016                 # 固定止盈 1.6%

# ML信号优化
ML_CONFIDENCE_THRESHOLD = 0.70       # 从0.56提高到0.70
ML_CONSISTENCY_MIN_BARS = 2          # ML方向需连续2根K线一致
ML_TREND_ALIGN_FILTER = True         # ML方向必须与趋势一致

# 动态仓位
USE_DYNAMIC_POSITION_SIZE = True
POSITION_SIZE_BASE_RISK = 0.025
POSITION_SIZE_HIGH_CONF = 1.5        # 高置信度仓位倍数
POSITION_SIZE_LOW_CONF = 0.5         # 低置信度仓位倍数
POSITION_SIZE_TREND_MULT = 1.2       # 趋势市加成
POSITION_SIZE_RANGE_MULT = 0.8       # 震荡市缩减
```

---

## 2. 新增核心方法 (main_v12_live_optimized.py)

### 2.1 当日区间位置计算
```python
_get_daily_position_pct(current_price, df) -> float
# 计算价格位于当日高低点区间的百分比 (0-100%)
```

### 2.2 位置过滤器
```python
_check_daily_position_filter(action, current_price, df) -> (bool, str)
# 做空：必须在当日70%高位以上
# 做多：必须在当日30%低位以下
```

### 2.3 硬性止损检查
```python
_check_hard_stop(sl_price, entry_price, action) -> (float, str)
# 确保止损不超过最大允许亏损（1.5%）
# 如果计算止损过宽，自动调整
```

### 2.4 盈亏比检查
```python
_check_rr_ratio(entry, sl, tp, action) -> (bool, float)
# 检查潜在盈亏比是否 >= 2.0
# 不满足则阻止入场
```

### 2.5 固定盈亏比SL/TP计算
```python
_calculate_fixed_sl_tp(entry, action, atr) -> (sl, tp)
# 固定止损：0.8%
# 固定止盈：1.6% (2倍)
# R:R = 1:2
```

### 2.6 简化环境分类
```python
_simplify_regime(regime) -> str
# 11种环境 -> 4类
# TREND_UP, TREND_DOWN, RANGE, CHAOS
```

### 2.7 动态仓位计算
```python
_calculate_position_size(base_risk, confidence, regime) -> float
# 根据置信度和环境调整仓位
```

### 2.8 ML一致性检查
```python
_check_ml_consistency(df, min_bars) -> (bool, int)
# 检查ML方向是否连续多根K线一致
```

---

## 3. 策略修改详情

### 3.1 震荡市策略 (_sideways_strategy)

**下轨做多新增过滤：**
1. 当日区间位置检查（必须在30%低位以下）
2. 使用固定盈亏比计算SL/TP
3. 硬性止损检查（最大1.5%）
4. 盈亏比检查（必须>=2.0）

**上轨做空新增过滤：**
1. 当日区间位置检查（必须在70%高位以上）
2. 使用固定盈亏比计算SL/TP
3. 硬性止损检查（最大1.5%）
4. 盈亏比检查（必须>=2.0）

### 3.2 趋势市策略 (generate_signal)

**ML信号增强：**
1. 阈值从0.56提高到0.70
2. 添加ML方向一致性检查（需连续2根K线）
3. 添加ML与趋势方向对齐检查
4. 使用固定盈亏比计算SL/TP
5. 硬性止损检查

### 3.3 开仓执行 (execute_open)

**动态仓位调整：**
```python
# 根据置信度和环境调整仓位大小
基础qty -> 调整后qty
风险比例: 2.5% * 动态倍数
```

---

## 4. 预期效果

### 入场质量提升
| 指标 | 之前 | 之后 | 改善 |
|------|------|------|------|
| 入场位置 | 随机(30-70%) | 优化(<30%或>70%) | 避免中部入场 |
| 止损宽度 | 2-3% | 最大1.5% | 限制单笔亏损 |
| 盈亏比 | 1:5.3 | 1:2 | 强制正期望 |
| ML阈值 | 0.56 | 0.70 | 减少错误信号 |

### 风险控制增强
- **硬性止损**：无论何种情况，亏损不超过1.5%
- **盈亏比过滤**：不满足1:2的交易直接放弃
- **位置过滤**：只交易当日区间极端位置
- **ML一致性**：需要多根K线确认方向

### 仓位管理优化
- **高置信度(>0.75)**：仓位放大至1.5倍
- **低置信度(<0.60)**：仓位缩减至0.5倍
- **趋势市**：仓位加成1.2倍
- **震荡市**：仓位缩减至0.8倍
- **混乱市**：仓位减半

---

## 5. 日志输出示例

```
[位置过滤] 上轨做空被阻止: 不在当日高位(55.3% < 70%)
[止损调整] 止损过宽(2.10%)，调整至1.50%
[盈亏比过滤] R:R=1.5 < 2.0, 放弃入场
[ML过滤] ML方向不一致，等待信号稳定
[仓位调整] 基础qty:0.0180 -> 调整后qty:0.0270 (风险:3.75%, 置信度:0.78, 环境:TREND_DOWN)
```

---

## 6. 回测验证建议

修改后需要验证的指标：
1. **入场位置分布**：确认多数在<30%或>70%
2. **单笔最大亏损**：确认不超过-1.5%
3. **平均盈亏比**：目标达到1:1.5以上
4. **胜率变化**：可能下降，但整体盈利应改善
5. **交易频率**：可能降低（过滤增多）

---

## 7. 注意事项

1. **动态止损未修改**：原有的移动止损逻辑保持不变
2. **配置可调**：所有参数可在config.py中调整
3. **向后兼容**：可通过开关启用/禁用新功能
4. **日志增加**：新过滤器会产生更多日志，便于调试

---

**修改完成时间**: 2026-03-27 18:16
**修改文件**: 
- config.py
- main_v12_live_optimized.py
