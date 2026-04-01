# 动态仓位配置总结 (2026-03-27)

## 配置参数

```python
# 动态仓位（仅按置信度调整，不按环境简化）
USE_DYNAMIC_POSITION_SIZE = True     # 启用动态仓位
POSITION_SIZE_BASE_RISK = 0.025      # 基础风险2.5%
POSITION_SIZE_HIGH_CONF = 1.5        # 高置信度(>0.75)倍数
POSITION_SIZE_MID_CONF = 1.0         # 中等置信度(0.60-0.75)倍数
POSITION_SIZE_LOW_CONF = 0.5         # 低置信度(<0.60)倍数
POSITION_SIZE_HIGH_THRESHOLD = 0.75  # 高置信度阈值
POSITION_SIZE_LOW_THRESHOLD = 0.60   # 低置信度阈值
```

## 逻辑说明

### 三档置信度调整

| 置信度范围 | 倍数 | 仓位调整 | 说明 |
|-----------|------|---------|------|
| >= 0.75 | 1.5x | 增加50% | 高置信度，加大仓位 |
| 0.60 - 0.75 | 1.0x | 标准仓位 | 中等置信度，正常仓位 |
| < 0.60 | 0.5x | 减少50% | 低置信度，减小仓位 |

### 计算示例

```
基础风险: 2.5%
账户余额: $1000
入场价格: $2000

场景1: 高置信度(0.80)
  调整后风险 = 2.5% * 1.5 = 3.75%
  名义价值 = $1000 * 3.75% = $37.5
  qty = $37.5 / $2000 = 0.01875 ETH

场景2: 中等置信度(0.70)
  调整后风险 = 2.5% * 1.0 = 2.5%
  名义价值 = $1000 * 2.5% = $25
  qty = $25 / $2000 = 0.0125 ETH

场景3: 低置信度(0.55)
  调整后风险 = 2.5% * 0.5 = 1.25%
  名义价值 = $1000 * 1.25% = $12.5
  qty = $12.5 / $2000 = 0.00625 ETH
```

## 代码实现

### SignalGenerator 类中的方法

```python
def _calculate_position_size(self, base_risk: float, confidence: float, regime: MarketRegime = None) -> float:
    """动态仓位计算 - 仅按置信度调整，不按环境简化"""
    if not CONFIG.get("USE_DYNAMIC_POSITION_SIZE", False):
        return base_risk
    
    mult = 1.0
    high_threshold = CONFIG.get("POSITION_SIZE_HIGH_THRESHOLD", 0.75)
    low_threshold = CONFIG.get("POSITION_SIZE_LOW_THRESHOLD", 0.60)
    
    # 仅按置信度调整（三档）
    if confidence >= high_threshold:
        mult = CONFIG.get("POSITION_SIZE_HIGH_CONF", 1.5)
    elif confidence >= low_threshold:
        mult = CONFIG.get("POSITION_SIZE_MID_CONF", 1.0)
    else:
        mult = CONFIG.get("POSITION_SIZE_LOW_CONF", 0.5)
    
    return base_risk * mult
```

### execute_open 中的调用

```python
# 基础仓位计算
base_qty = self.risk_mgr.calculate_position_size(...)

# 动态仓位调整
if CONFIG.get("USE_DYNAMIC_POSITION_SIZE", False):
    adjusted_risk = self.signal_gen._calculate_position_size(
        CONFIG.get("POSITION_SIZE_BASE_RISK", 0.025),
        signal.confidence,
        signal.regime
    )
    notional_value = balance * adjusted_risk
    adjusted_qty = notional_value / price
    
    if adjusted_qty != base_qty:
        logger.info(f"[仓位调整] 基础:{base_qty:.4f} -> 调整后:{adjusted_qty:.4f} "
                   f"(置信度:{signal.confidence:.2f}, 风险:{adjusted_risk:.2%})")
    
    qty = adjusted_qty
```

## 关键特性

1. **仅按置信度调整**: 不区分环境类型，只看ML置信度
2. **三档调整**: 高(1.5x)/中(1.0x)/低(0.5x)
3. **可配置阈值**: 高置信度阈值(0.75)和低置信度阈值(0.60)可调
4. **日志记录**: 仓位调整时会输出日志

## 与之前方案的区别

| 特性 | 之前方案 | 当前方案 |
|-----|---------|---------|
| 调整依据 | 置信度 + 环境简化(4类) | 仅置信度 |
| 环境分类 | TREND_UP/DOWN/RANGE/CHAOS | 不简化，保持原11种 |
| 调整档位 | 2档(高/低) | 3档(高/中/低) |
| 高置信度倍数 | 1.5x | 1.5x |
| 低置信度倍数 | 0.5x | 0.5x |
| 中等置信度 | 无(默认1.0x) | 明确1.0x |

## 验证方法

```bash
# 检查配置
python -c "from config import CONFIG; print(CONFIG.get('USE_DYNAMIC_POSITION_SIZE'))"

# 检查方法
python -c "from main_v12_live_optimized import SignalGenerator; sg = SignalGenerator(); print(hasattr(sg, '_calculate_position_size'))"
```
