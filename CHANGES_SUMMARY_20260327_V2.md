# 增量优化修改总结 (2026-03-27 V2)

## 修改概览
基于回退后的版本，进行精准的增量优化，保留核心过滤功能。

---

## 1. 配置参数 (config.py)

### 新增配置项
```python
# 当日价格区间过滤
ENABLE_DAILY_POSITION_FILTER = True   # 启用当日区间过滤
DAILY_POSITION_SHORT_MIN = 0.70       # 做空需在当日70%分位以上
DAILY_POSITION_LONG_MAX = 0.30        # 做多需在当日30%分位以下

# 固定盈亏比 + EVT追踪止盈
USE_FIXED_RR_WITH_EVT = True          # 启用固定盈亏比+EVT追踪
FIXED_STOP_PCT = 0.008                # 固定止损 0.8%
FIXED_TP_PCT = 0.016                  # 固定止盈 1.6%
EVT_TRAILING_AFTER_TP = True          # 达到1.6%后启用EVT追踪
EVT_TRAILING_PCT = 0.016              # 回退1.6%止盈

# ML逆势交易阈值调整
COUNTER_TREND_ML_THRESHOLD_SIDEWAYS = 0.85  # 震荡市逆势阈值(原为0.98)
COUNTER_TREND_ML_THRESHOLD_TREND = 0.90     # 趋势市逆势阈值(原为0.98)
```

---

## 2. 新增核心方法 (main_v12_live_optimized.py)

### 2.1 当日区间位置计算
```python
_get_daily_position_pct(current_price, df) -> float
# 计算价格位于当日高低点区间的百分比
```

### 2.2 位置过滤器
```python
_check_daily_position_filter(action, current_price, df) -> (bool, str)
# 做空：必须在当日70%高位以上
# 做多：必须在当日30%低位以下
```

### 2.3 固定盈亏比SL/TP计算
```python
_calculate_fixed_sl_tp(entry, action, atr) -> (sl, tp)
# 止损 = 0.8%
# 止盈 = 1.6%
```

---

## 3. 策略修改详情

### 3.1 震荡市策略 (_sideways_strategy)

**修改内容：**
1. **逆势ML阈值**：从0.98降至0.85（更宽松）
2. **区间过滤**：顺势交易添加当日位置检查
3. **固定盈亏比**：使用0.8%/1.6%代替ATR动态计算

**代码逻辑：**
```python
# 上轨做空顺势交易
if is_with_trend:
    # 1. 区间位置过滤
    pos_allowed, pos_reason = self._check_daily_position_filter('SELL', close, df)
    if not pos_allowed:
        return HOLD(f'被过滤({pos_reason})')
    
    # 2. 使用固定盈亏比
    sl_price, tp_price = self._calculate_fixed_sl_tp(close, 'SELL', atr)
```

### 3.2 趋势市策略 (generate_signal)

**修改内容：**
- **逆势ML阈值**：从0.98降至0.90（更宽松）

```python
counter_trend_threshold = CONFIG.get("COUNTER_TREND_ML_THRESHOLD_TREND", 0.90)
```

### 3.3 止盈逻辑 (_check_exit_signal)

**新增：固定止盈 + EVT追踪**

```python
# 超过1.6%固定止盈点后，启用EVT追踪
if pnl_pct >= fixed_tp_pct:  # 1.6%
    # 启动追踪
    self._evt_trailing_active = True
    self._evt_trailing_peak = pnl_pct
    
    # 如果回退1.6%，止盈出场
    if pnl_pct <= self._evt_trailing_peak - evt_trailing_pct:
        return CLOSE('EVT追踪止盈')
```

**流程：**
1. 盈利达到1.6% → 启动EVT追踪
2. 继续盈利 → 更新峰值，让利润奔跑
3. 回退1.6% → 止盈出场

---

## 4. 关键参数对比

| 参数 | 原值 | 新值 | 说明 |
|------|------|------|------|
| 震荡市逆势阈值 | 0.98 | **0.85** | 更宽松，允许更多逆势交易 |
| 趋势市逆势阈值 | 0.98 | **0.90** | 更宽松 |
| 区间过滤 | 无 | **70%/30%** | 只交易当日高低位 |
| 止损 | ATR×1.5 | **0.8%** | 固定、明确 |
| 止盈 | ATR×4.0/BB中轨 | **1.6%** | 固定，+EVT追踪 |
| EVT追踪触发 | 无 | **>1.6%** | 超过后启用回退止盈 |

---

## 5. 交易流程示例

### 场景：震荡下行做空

**修改前：**
1. 价格触及布林带上轨
2. RSI > 60
3. 做空入场
4. 止损：ATR×1.5 ≈ 1.5%
5. 止盈：布林带中轨（约1-2%）
6. 盈亏比：约1:1

**修改后：**
1. 价格触及布林带上轨
2. RSI > 60
3. **检查位置**：必须在当日70%高位以上
4. **满足条件**，做空入场 @ $2069
5. 止损：$2069 × 1.008 = $2085 (0.8%)
6. 止盈：$2069 × 0.984 = $2036 (1.6%)
7. **盈亏比：1:2**
8. 价格跌至$2030（盈利1.9%）
9. **启动EVT追踪**，峰值1.9%
10. 价格反弹至$2050（回退1.5%）
11. **EVT追踪止盈出场**，实际盈利0.9%

---

## 6. 预期效果

### 入场质量提升
- **位置过滤**：阻止中部位置（40-60%）的入场
- **固定盈亏比**：确保每笔交易至少1:2
- **ML阈值降低**：更多高置信度逆势交易被允许

### 止盈优化
- **固定1.6%**：明确、可预期
- **EVT追踪**：超过1.6%后让利润奔跑，回退1.6%止盈
- **避免早止盈**：不会因为小波动就出场

### 风险控制
- **止损收紧**：从1.5%降至0.8%
- **硬性止损**：通过固定百分比确保

---

## 7. 验证方法

```bash
# 检查配置
python -c "from config import CONFIG; print(CONFIG.get('USE_FIXED_RR_WITH_EVT'))"

# 检查方法
python -c "from main_v12_live_optimized import SignalGenerator; sg = SignalGenerator(); print(hasattr(sg, '_check_daily_position_filter'))"

# 运行回测或实盘测试
```

---

## 8. 注意事项

1. **EVT追踪状态**：每新开仓会自动重置
2. **固定盈亏比**：仅在震荡市策略中启用（趋势市保持原有逻辑）
3. **区间过滤**：需要当日有足够K线数据（至少5根）
4. **ML阈值**：0.85/0.90仍高于普通顺势阈值（0.56），只是相对原0.98更宽松

---

**修改完成时间**: 2026-03-27 18:45
**修改文件**: 
- config.py
- main_v12_live_optimized.py
