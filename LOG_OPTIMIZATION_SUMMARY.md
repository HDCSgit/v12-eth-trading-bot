# 日志优化总结 (2026-03-27)

## 问题分析

### 优化前日志问题
```
[ML-V2] ⬜ SIDEWAYS     [████░░░░░░] 44%   <- 连续重复10+次
[ML-V2] ⬜ SIDEWAYS     [████░░░░░░] 44%
[ML-V2] ⬜ SIDEWAYS     [████░░░░░░] 46%
...
[交易周期] 无持仓, 价格=2011.11, 环境=趋势下跌  <- 每周期输出
[交易周期] 无持仓, 价格=2011.12, 环境=趋势下跌
...
[ML过滤] ML方向不一致，等待信号稳定  <- 连续重复15+次
[ML过滤] ML方向不一致，等待信号稳定
...
```

**问题：**
1. V2可视化：每次循环都输出，大量重复
2. 交易周期：每周期输出，即使无变化
3. ML过滤：同一原因连续重复输出

---

## 优化措施

### 1. V2可视化输出去重

**位置：** `main_v12_live_optimized.py` 第883-896行

**优化逻辑：**
```python
# 生成可视化key：环境类型_置信度(取整)
current_viz_key = f"{self.ml_regime_result.regime.name}_{int(self.ml_regime_result.confidence*10)}"

# 只有key变化时才输出
if not hasattr(self, '_last_viz_key') or self._last_viz_key != current_viz_key:
    print(f"\n{viz_output}")
    self._last_viz_key = current_viz_key
# else: 相同状态，跳过输出
```

**效果：**
- 置信度变化>10%或环境类型变化时才输出
- 从每秒1次降至约每10-30秒1次

---

### 2. 交易周期日志优化

**位置：** `main_v12_live_optimized.py` 第3582-3598行

**优化前：**
```python
# 每30周期输出一次，或状态变化时
if not hasattr(self, '_last_cycle_state') or self._last_cycle_state != current_cycle_state or self.cycle_count % 30 == 0:
```

**优化后：**
```python
# 每60周期(约60秒)输出一次，或状态变化时
if not hasattr(self, '_last_cycle_state') or self._last_cycle_state != current_cycle_state or self.cycle_count % 60 == 0:

# 增强状态key，包含环境类型
current_cycle_state = f"{has_pos}_{pos_side}_{entry_px_int}_{signal.regime.value if signal else 'unknown'}"

# 无持仓时增加ML信息显示
ml_str = f"ML{'多' if ml_dir==1 else '空' if ml_dir==-1 else '观'}({ml_conf:.2f})" if ml_dir != 0 else ""
logger.info(f"[交易周期] 无持仓, 价格={current_price:.2f}, 环境={regime_val} {ml_str}")
```

**效果：**
- 频率从30秒降至60秒
- 状态变化更敏感（包含环境类型）
- 信息更丰富（增加ML方向）

---

### 3. ML过滤日志去重

**位置1：** `main_v12_live_optimized.py` 第1016-1028行（趋势市逆势过滤）

**优化逻辑：**
```python
# 生成阻止原因key
block_reason = f"逆势_{regime.value}_{ml_direction}"

# 同一原因不重复输出
if not hasattr(self, '_last_ml_block_reason') or self._last_ml_block_reason != block_reason:
    logger.info(f"[ML过滤] 逆势交易被阻止...")
    self._last_ml_block_reason = block_reason
else:
    logger.debug(f"[ML过滤] 逆势阻止中(同前): ...")
```

**位置2：** `main_v12_live_optimized.py` 第1375-1383行（震荡市位置过滤）

**优化逻辑：**
```python
# 位置过滤去重
pos_block_key = f"BUY_{position_pct:.0f}"
if not hasattr(self, '_last_pos_block_key') or self._last_pos_block_key != pos_block_key:
    logger.info(f"[位置过滤] 下轨做多被阻止: {pos_reason}")
    self._last_pos_block_key = pos_block_key
```

**效果：**
- 同一阻止原因只输出一次
- 后续相同原因降至debug级别
- 原因变化时立即输出

---

## 优化后效果

### 预期日志输出
```
# V2可视化（变化时）
[ML-V2] ⬜ SIDEWAYS     [████░░░░░░] 44%
                    ... 10秒后 ...
[ML-V2] ⚪ WEAK_UP      [██████░░░░] 61%   <- 变化了，输出
                    ... 30秒后 ...
[ML-V2] ⬜ SIDEWAYS     [████░░░░░░] 42%   <- 变化了，输出

# 交易周期（60秒或状态变化）
[交易周期] 无持仓, 价格=2011.11, 环境=趋势下跌 ML多(0.62)
                    ... 60秒后 ...
[交易周期] 无持仓, 价格=2010.80, 环境=趋势下跌 ML多(0.62)

# ML过滤（首次阻止）
[ML过滤] 逆势交易被阻止，尝试技术指标: 趋势下跌 + ML看多 (置信度:0.62 < 阈值:0.90)
                    ... 后续相同原因 ...
[ML过滤] 逆势阻止中(同前)   <- debug级别，不显示
                    ... 原因变化 ...
[ML过滤] 逆势交易被阻止，尝试技术指标: 趋势下跌 + ML看空 (置信度:0.85 < 阈值:0.90)
```

---

## 关键优化点

| 日志类型 | 优化前频率 | 优化后频率 | 优化方法 |
|---------|-----------|-----------|---------|
| V2可视化 | 每秒1次 | 约10-30秒1次 | 置信度取整比较 |
| 交易周期 | 每30秒 | 每60秒 | 周期数翻倍 |
| ML过滤 | 每次阻止 | 首次阻止 | 原因key去重 |
| 位置过滤 | 每次阻止 | 首次阻止 | 位置区间去重 |

---

## 注意事项

1. **状态重置**：新开仓时会重置所有日志状态
2. **变化敏感**：环境或置信度变化时立即输出
3. **Debug日志**：被过滤的日志可在debug级别查看
4. **内存占用**：新增状态变量占用极小内存

---

**优化完成时间**: 2026-03-27 18:48
