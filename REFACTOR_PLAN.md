# V12 系统重构实施计划

> **目标**: 入场/出场信号分离 + 完善设计文档  
> **风险等级**: 中（需回测验证）  
> **预计工期**: 2-3天

---

## 方案选择

### 方案A: 激进重构（不推荐）
- 直接重写核心类
- 风险：引入新Bug，影响实盘

### 方案B: 渐进重构（✅ 推荐）
- 新旧系统并行运行
- 逐步切换
- 可随时回滚

---

## 渐进重构步骤

### 第1步：提取 PositionManager（1小时）

**新建文件**: `position_manager.py`

```python
class PositionManager:
    """
    持仓状态管理器 - 从 SignalGenerator 中提取
    
    2026-03-24 重构提取
    原位置: main_v12_live_optimized.py SignalGenerator.position_peak_pnl 等
    """
    
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.reset()
    
    def reset(self):
        self.has_position = False
        self.side = None
        self.entry_price = 0.0
        self.qty = 0.0
        self.entry_time = None
        self.peak_pnl = 0.0
        self.trailing_stop = 0.0
        self.holding_periods = 0
    
    def open(self, side: str, entry_price: float, qty: float):
        """开仓时调用"""
        self.has_position = True
        self.side = side
        self.entry_price = entry_price
        self.qty = qty
        self.entry_time = datetime.now()
        self.peak_pnl = 0.0
        self.trailing_stop = 0.0
        self.holding_periods = 0
        
        logger.info(f"[PositionManager] 开仓 {side} {qty} @ {entry_price}")
    
    def update(self, current_price: float) -> Dict:
        """
        每周期更新，返回当前状态
        
        Returns:
            dict: {pnl_pct, peak_pnl, trailing_stop, holding_periods}
        """
        if not self.has_position:
            return None
        
        self.holding_periods += 1
        
        # 计算盈亏
        if self.side in ['SELL', 'SHORT']:
            pnl_pct = (self.entry_price - current_price) / self.entry_price
        else:
            pnl_pct = (current_price - self.entry_price) / self.entry_price
        
        # 更新峰值和移动止损
        if pnl_pct > self.peak_pnl:
            self.peak_pnl = pnl_pct
            drawback = CONFIG.get("TRAILING_STOP_DRAWBACK_PCT", 0.30)
            self.trailing_stop = self.peak_pnl * (1 - drawback)
        
        return {
            'pnl_pct': pnl_pct,
            'peak_pnl': self.peak_pnl,
            'trailing_stop': self.trailing_stop,
            'holding_periods': self.holding_periods
        }
    
    def close(self, exit_price: float) -> Dict:
        """平仓时调用，返回交易记录"""
        if not self.has_position:
            return None
        
        # 计算最终盈亏
        if self.side in ['SELL', 'SHORT']:
            pnl_pct = (self.entry_price - exit_price) / self.entry_price
        else:
            pnl_pct = (exit_price - self.entry_price) / self.entry_price
        
        record = {
            'symbol': self.symbol,
            'side': self.side,
            'entry_price': self.entry_price,
            'exit_price': exit_price,
            'qty': self.qty,
            'pnl_pct': pnl_pct,
            'holding_periods': self.holding_periods,
            'entry_time': self.entry_time,
            'exit_time': datetime.now(),
            'max_pnl': self.peak_pnl,
        }
        
        logger.info(f"[PositionManager] 平仓 PnL: {pnl_pct*100:.2f}%, 持仓: {self.holding_periods}周期")
        
        self.reset()
        return record
    
    def get_context(self) -> Dict:
        """获取当前上下文（用于出场信号计算）"""
        return {
            'symbol': self.symbol,
            'side': self.side,
            'entry_price': self.entry_price,
            'qty': self.qty,
            'peak_pnl': self.peak_pnl,
            'trailing_stop': self.trailing_stop,
            'holding_periods': self.holding_periods,
        }
```

**修改** `main_v12_live_optimized.py`:

```python
# 在 V12OptimizedTrader.__init__ 中添加
from position_manager import PositionManager

# 替换原来的 position_peak_pnl 等字段
self.position_manager = PositionManager(self.symbol)

# 开仓时
self.position_manager.open(side, entry_price, qty)

# 每周期更新
pos_state = self.position_manager.update(current_price)
if pos_state:
    self.position_peak_pnl = pos_state['peak_pnl']  # 兼容旧代码
    self.position_trailing_stop = pos_state['trailing_stop']

# 平仓时
record = self.position_manager.close(exit_price)
```

---

### 第2步：提取 ExitSignalGenerator（2小时）

**新建文件**: `exit_signals.py`

```python
"""
出场信号生成器 - 从 SignalGenerator 中提取

2026-03-24 重构:
- 原 _check_exit_signal 方法拆分为策略类
- 使用策略模式，每个策略独立
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict
import pandas as pd

@dataclass
class ExitContext:
    """出场决策上下文"""
    symbol: str
    entry_price: float
    current_price: float
    side: str  # 'LONG' or 'SHORT'
    qty: float
    peak_pnl: float
    trailing_stop: float
    holding_periods: int
    atr: float
    regime: str
    funding_rate: float

@dataclass
class ExitSignal:
    """出场信号"""
    should_exit: bool
    reason: str = ""
    strategy_type: str = ""
    params: Dict = None
    
    def __post_init__(self):
        if self.params is None:
            self.params = {}

class ExitStrategy(ABC):
    """出场策略基类"""
    
    @abstractmethod
    def check(self, ctx: ExitContext, df: pd.DataFrame) -> ExitSignal:
        """检查是否触发出场"""
        pass
    
    @property
    @abstractmethod
    def priority(self) -> int:
        """优先级，数字越小越优先"""
        pass

class StopLossStrategy(ExitStrategy):
    """动态止损策略"""
    priority = 1  # 最高优先级
    
    def check(self, ctx: ExitContext, df: pd.DataFrame) -> ExitSignal:
        sl_mult = CONFIG.get("STOP_LOSS_ATR_MULT", 1.5)
        sl_pct = -sl_mult * ctx.atr / ctx.entry_price
        
        # 计算当前盈亏
        if ctx.side in ['SELL', 'SHORT']:
            pnl_pct = (ctx.entry_price - ctx.current_price) / ctx.entry_price
        else:
            pnl_pct = (ctx.current_price - ctx.entry_price) / ctx.entry_price
        
        if pnl_pct <= sl_pct:
            return ExitSignal(
                should_exit=True,
                reason=f"动态止损触发({pnl_pct*100:.2f}%)",
                strategy_type="STOP_LOSS_DYNAMIC",
                params={'sl_atr_mult': sl_mult, 'sl_pct': sl_pct}
            )
        return ExitSignal(should_exit=False)

class ProfitProtectionStrategy(ExitStrategy):
    """利润保护策略（回撤50%）"""
    priority = 2
    
    def check(self, ctx: ExitContext, df: pd.DataFrame) -> ExitSignal:
        enable_pct = CONFIG.get("PROFIT_PROTECTION_ENABLE_PCT", 0.005)
        drawback_pct = CONFIG.get("PROFIT_PROTECTION_DRAWBACK_PCT", 0.50)
        
        # 计算当前盈亏
        if ctx.side in ['SELL', 'SHORT']:
            pnl_pct = (ctx.entry_price - ctx.current_price) / ctx.entry_price
        else:
            pnl_pct = (ctx.current_price - ctx.entry_price) / ctx.entry_price
        
        if ctx.peak_pnl > enable_pct and pnl_pct < ctx.peak_pnl * (1 - drawback_pct):
            return ExitSignal(
                should_exit=True,
                reason=f"利润保护触发(峰值{ctx.peak_pnl*100:.2f}%, 回撤{drawback_pct*100:.0f}%)",
                strategy_type="PROFIT_PROTECTION",
                params={'peak_pnl': ctx.peak_pnl, 'drawback_pct': drawback_pct}
            )
        return ExitSignal(should_exit=False)

class TrailingStopStrategy(ExitStrategy):
    """移动止盈策略（回撤30%）"""
    priority = 3
    
    def check(self, ctx: ExitContext, df: pd.DataFrame) -> ExitSignal:
        # 计算当前盈亏
        if ctx.side in ['SELL', 'SHORT']:
            pnl_pct = (ctx.entry_price - ctx.current_price) / ctx.entry_price
        else:
            pnl_pct = (ctx.current_price - ctx.entry_price) / ctx.entry_price
        
        if pnl_pct < ctx.trailing_stop and ctx.peak_pnl > 0:
            return ExitSignal(
                should_exit=True,
                reason=f"移动止盈触发(峰值{ctx.peak_pnl*100:.2f}%, 当前{pnl_pct*100:.2f}%)",
                strategy_type="TRAILING_STOP",
                params={'peak_pnl': ctx.peak_pnl, 'trailing_stop': ctx.trailing_stop}
            )
        return ExitSignal(should_exit=False)

class ExitSignalGenerator:
    """
    出场信号生成器
    
    使用责任链模式，按优先级检查各出场策略
    """
    
    def __init__(self):
        self.strategies: List[ExitStrategy] = [
            StopLossStrategy(),
            ProfitProtectionStrategy(),
            TrailingStopStrategy(),
            # TODO: 添加其他策略
            # EVTExtremeStrategy(),
            # ATRFixedStrategy(),
            # MLReversalStrategy(),
        ]
        # 按优先级排序
        self.strategies.sort(key=lambda s: s.priority)
    
    def check_exit(self, ctx: ExitContext, df: pd.DataFrame) -> ExitSignal:
        """
        检查出场信号
        
        Args:
            ctx: 出场上下文（包含持仓状态）
            df: K线数据
        
        Returns:
            ExitSignal: 出场信号
        """
        for strategy in self.strategies:
            signal = strategy.check(ctx, df)
            if signal.should_exit:
                return signal
        
        return ExitSignal(should_exit=False)
```

---

### 第3步：验证和切换（1小时）

**创建回测验证脚本**:

```python
# test_refactor.py
"""
验证重构后的系统与原系统信号一致性
"""

import pandas as pd
from main_v12_live_optimized import SignalGenerator as OldSignalGen
from exit_signals import ExitSignalGenerator, ExitContext
from position_manager import PositionManager

def test_exit_signals():
    """测试出场信号是否一致"""
    # 加载测试数据
    df = pd.read_csv("eth_usdt_1h.csv")
    
    # 模拟持仓
    pm = PositionManager("ETHUSDT")
    pm.open("SELL", 2149.20, 0.018)
    
    # 新系统检查出场
    exit_gen = ExitSignalGenerator()
    
    results = []
    for i in range(100):  # 测试100个周期
        price = df['close'].iloc[i]
        atr = df['ATR'].iloc[i] if 'ATR' in df.columns else 10.0
        
        # 更新持仓状态
        pm.update(price)
        
        # 新系统检查
        ctx = ExitContext(
            symbol="ETHUSDT",
            entry_price=pm.entry_price,
            current_price=price,
            side=pm.side,
            qty=pm.qty,
            peak_pnl=pm.peak_pnl,
            trailing_stop=pm.trailing_stop,
            holding_periods=pm.holding_periods,
            atr=atr,
            regime="TRENDING_DOWN",
            funding_rate=0.0001
        )
        
        signal = exit_gen.check_exit(ctx, df.iloc[:i+1])
        
        results.append({
            'price': price,
            'pnl_pct': (pm.entry_price - price) / pm.entry_price,
            'peak_pnl': pm.peak_pnl,
            'should_exit': signal.should_exit,
            'reason': signal.reason
        })
    
    return pd.DataFrame(results)

if __name__ == "__main__":
    df = test_exit_signals()
    print(df[df['should_exit']])  # 打印出场信号
    df.to_csv("refactor_test_results.csv", index=False)
```

---

## 文件变更清单

### 新增文件
| 文件 | 说明 | 状态 |
|-----|------|------|
| `DESIGN.md` | 架构设计文档 | ✅ 已创建 |
| `REFACTOR_PLAN.md` | 重构计划 | ✅ 已创建 |
| `position_manager.py` | 持仓管理器 | ⏳ 待创建 |
| `exit_signals.py` | 出场信号生成器 | ⏳ 待创建 |
| `entry_signals.py` | 入场信号生成器（可选）| ⏳ 待创建 |

### 修改文件
| 文件 | 修改内容 | 风险 |
|-----|---------|------|
| `main_v12_live_optimized.py` | 使用新的 PositionManager | 低 |
| `main_v12_live_optimized.py` | 可选：使用新的 ExitSignalGenerator | 中 |

---

## 风险控制

### 回滚方案
```bash
# 如果新系统有问题，立即回滚
git checkout main_v12_live_optimized.py
python main_v12_live_optimized.py
```

### 验证检查点
- [ ] PositionManager 状态与原系统一致
- [ ] 出场信号触发时机与原系统一致
- [ ] 数据库记录格式不变
- [ ] 日志输出格式不变

---

## 建议实施时间

**最佳时间**: 周末或非交易时段
- 避免在持仓时切换系统
- 确保有2-3小时观察期

---

**是否开始实施第1步？** 可以先创建 `PositionManager` 并与现有系统并行运行验证。
