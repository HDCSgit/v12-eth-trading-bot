# 综合评分入场机制集成指南

## 概述
将原有的"3周期确认"机制替换为"综合评分"机制，更灵活地评估入场位置质量。

## 主要变化

### 1. 移除旧机制
**原代码位置**: main_v12_live_optimized.py 第645-667行

```python
# 删除以下代码：
# ========== 趋势确认机制（防止连续反向开仓）==========
# 记录最近的环境判断
if not hasattr(self, '_recent_regimes'):
    self._recent_regimes = []
self._recent_regimes.append(regime)
...
```

### 2. 添加新机制

#### 步骤1: 导入模块
在 main_v12_live_optimized.py 文件顶部添加：
```python
from entry_quality_checker import EntryQualityChecker, get_entry_checker
```

#### 步骤2: 初始化检查器
在 SignalGenerator 的 __init__ 方法中添加：
```python
self.entry_checker = get_entry_checker()
```

#### 步骤3: 修改 generate_signal 方法
在 generate_signal 方法中，在返回信号前添加评估逻辑：

```python
def generate_signal(...):
    # ... 原有信号生成逻辑 ...
    
    # 新增：入场质量评估（仅在要开仓时）
    if not has_position and signal.action in ['BUY', 'SELL']:
        # 准备评估数据
        current_rsi = df['rsi_12'].iloc[-1] if 'rsi_12' in df.columns else 50
        recent_prices = df['close'].tail(20).tolist()
        
        # 更新趋势信息
        self.entry_checker.update_trend_info(signal.action)
        
        # 进行综合评分
        should_enter, msg, score, details = self.entry_checker.comprehensive_check(
            signal_action=signal.action,
            current_price=current_price,
            recent_prices=recent_prices,
            current_rsi=current_rsi
        )
        
        # 根据评分调整信号
        if not should_enter:
            # 评分<0.2，禁止入场
            logger.warning(f"[入场评估] 评分{score:.2f}<0.2，禁止入场")
            return TradingSignal(
                'HOLD', 0.5, SignalSource.TECHNICAL,
                f'入场评估拒绝({score:.2f})',
                atr, regime=regime, funding_rate=funding_rate
            )
        elif score < 0.5:
            # 0.2-0.5，降低仓位（标记在信号中）
            signal._suggested_position_pct = 0.3
            signal.reason += f" [评分{score:.2f},建议仓位30%]"
        elif score < 0.7:
            # 0.5-0.7，正常偏低仓位
            signal._suggested_position_pct = 0.6
            signal.reason += f" [评分{score:.2f},建议仓位60%]"
        else:
            # >0.7，正常入场
            signal.reason += f" [评分{score:.2f}]"
    
    return signal
```

#### 步骤4: 修改仓位计算
在 calculate_position_size 方法中，使用建议的仓位比例：

```python
def calculate_position_size(...):
    # ... 原有计算逻辑 ...
    
    # 新增：应用建议仓位比例
    if hasattr(signal, '_suggested_position_pct'):
        limited_pct *= signal._suggested_position_pct
        logger.info(f"[仓位调整] 根据入场评分，仓位调整为{signal._suggested_position_pct*100:.0f}%")
    
    return qty
```

## 评分标准

| 综合评分 | 决策 | 仓位比例 | 说明 |
|---------|------|---------|------|
| < 0.2 | ❌ 禁止入场 | 0% | 风险过高 |
| 0.2-0.5 | ⚠️ 谨慎入场 | 30% | 位置一般 |
| 0.5-0.7 | ✅ 正常入场 | 60% | 位置良好 |
| 0.7-0.85 | ✅ 积极入场 | 80% | 位置优秀 |
| > 0.85 | ✅ 全力入场 | 100% | 位置极佳 |

## 留痕机制

所有评估记录自动保存到数据库 `entry_check_records` 表：

```sql
SELECT * FROM entry_check_records 
WHERE decision = '拒绝入场'
ORDER BY timestamp DESC;
```

记录内容包括：
- 评分详情（位置、RSI、趋势时长）
- 决策结果
- 建议仓位
- 后续实际结果（平仓后更新）

## 测试建议

1. **回测验证**：对比新旧机制的历史表现
2. **模拟运行**：Paper模式测试1-2天
3. **逐步放量**：先小仓位验证效果

## 回退方案

如需恢复旧机制，只需注释掉新增代码，取消原代码的注释即可。
