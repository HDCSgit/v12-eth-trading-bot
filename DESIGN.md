# V12 交易系统架构设计文档

> **版本**: v12.4  
> **更新日期**: 2026-03-24  
> **设计原则**: SOLID + 高内聚低耦合

---

## 1. 系统架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          V12 Trading System                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐    │
│  │   Data Layer     │────▶│   Signal Layer   │────▶│ Execution Layer  │    │
│  │   (数据层)        │     │   (信号层)        │     │   (执行层)        │    │
│  └──────────────────┘     └──────────────────┘     └──────────────────┘    │
│          │                        │                        │               │
│          ▼                        ▼                        ▼               │
│  ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐    │
│  │ - Binance API    │     │ - EntrySignal    │     │ - OrderManager   │    │
│  │ - WebSocket      │     │ - ExitSignal     │     │ - PositionMgr    │    │
│  │ - MarketData     │     │ - ML Model       │     │ - RiskManager    │    │
│  └──────────────────┘     └──────────────────┘     └──────────────────┘    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 类图设计

### 2.1 当前架构（存在问题）

```
┌───────────────────────────────────────────────────────────────┐
│                    V12OptimizedTrader                          │
│                      (交易执行器 - God Class)                   │
├───────────────────────────────────────────────────────────────┤
│ - symbol: str                                                 │
│ - api: BinanceAPI                                             │
│ - signal_gen: SignalGenerator  ◄── 过于庞大                    │
│ - db: TradeDatabase                                           │
├───────────────────────────────────────────────────────────────┤
│ + run_cycle()                                                 │
│ + execute_open()                                              │
│ + execute_close()                                             │
│ + calculate_position_size()                                   │
└───────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌───────────────────────────────────────────────────────────────┐
│                    SignalGenerator                             │
│                    (信号生成器 - 违反单一职责)                   │
├───────────────────────────────────────────────────────────────┤
│ - ml_model: V12MLModel                                        │
│ - market_analyzer: MarketAnalyzer                             │
│ - market_data_feed: BinanceMarketData                         │
│ - position_peak_pnl: float      ◄── 出场相关混入               │
│ - position_trailing_stop: float ◄── 出场相关混入               │
├───────────────────────────────────────────────────────────────┤
│ + generate_signal()          ◄── 入场信号                      │
│ + _check_exit_signal()       ◄── 出场信号 (应该分离)            │
│ + check_spike_circuit_breaker()                               │
│ + reset_position_tracking()  ◄── 出场相关                      │
└───────────────────────────────────────────────────────────────┘
```

**问题分析**:
- ❌ `SignalGenerator` 同时负责入场和出场，违反单一职责原则(SRP)
- ❌ `V12OptimizedTrader` 是 God Class，包含过多职责
- ❌ 出场信号需要 `symbol`，但 `SignalGenerator` 原本设计为通用信号生成器

---

### 2.2 目标架构（推荐重构）

```
┌───────────────────────────────────────────────────────────────┐
│                    V12OptimizedTrader                          │
│                      (交易协调器 - 简化)                        │
├───────────────────────────────────────────────────────────────┤
│ - symbol: str                                                 │
│ - api: BinanceAPI                                             │
│ - entry_signal_gen: EntrySignalGenerator                      │
│ - exit_signal_gen: ExitSignalGenerator     ◄── 分离出场        │
│ - position_manager: PositionManager                           │
│ - order_executor: OrderExecutor                               │
│ - db: TradeDatabase                                           │
├───────────────────────────────────────────────────────────────┤
│ + run_cycle()        │ 简化：只负责协调                        │
│ + _execute_open()    │ 委托给 OrderExecutor                   │
│ + _execute_close()   │ 委托给 OrderExecutor                   │
└───────────────────────────────────────────────────────────────┘
        │                           │
        ▼                           ▼
┌─────────────────┐         ┌─────────────────┐
│ EntrySignalGen  │         │ ExitSignalGen   │
├─────────────────┤         ├─────────────────┤
│ 入场信号专用     │         │ 出场信号专用     │
│ - ml_model      │         │ - position_mgr  │
│ - market_analyzer│        │ - tp_strategies │
├─────────────────┤         ├─────────────────┤
│ + generate()    │         │ + check_exit()  │
└─────────────────┘         └─────────────────┘
                                     │
                                     ▼
┌───────────────────────────────────────────────────────────────┐
│                    PositionManager                             │
│                    (持仓状态管理 - 新增)                        │
├───────────────────────────────────────────────────────────────┤
│ - symbol: str                                                 │
│ - entry_price: float                                          │
│ - peak_pnl: float                                             │
│ - trailing_stop: float                                        │
│ - holding_periods: int                                        │
├───────────────────────────────────────────────────────────────┤
│ + update(current_price)                                       │
│ + reset()                                                     │
│ + get_exit_context(): ExitContext                             │
└───────────────────────────────────────────────────────────────┘
```

---

## 3. 详细类设计

### 3.1 入场信号生成器 (EntrySignalGenerator)

```python
class EntrySignalGenerator:
    """
    入场信号生成器
    职责: 分析市场状态，生成开多/开空/观望信号
    原则: 只读，不维护任何持仓状态
    """
    
    def __init__(self):
        self.ml_model = V12MLModel()
        self.market_analyzer = MarketAnalyzer()
        self.data_feed = BinanceMarketData()  # 可选辅助数据
    
    def generate(self, df: pd.DataFrame, current_price: float, 
                 funding_rate: float) -> EntrySignal:
        """
        生成入场信号
        
        Returns:
            EntrySignal: 包含 action(BUY/SELL/HOLD), confidence, reason
        """
        # 1. 市场状态分析
        regime = self.market_analyzer.analyze(df)
        
        # 2. ML预测
        ml_result = self.ml_model.predict(df)
        
        # 3. 策略路由
        signal = self._route_strategy(regime, ml_result, ...)
        
        # 4. 风控过滤
        signal = self._risk_filter(signal, ...)
        
        return signal
    
    def _route_strategy(self, regime: MarketRegime, ...) -> EntrySignal:
        """根据市场状态路由到对应策略"""
        strategy_map = {
            MarketRegime.TRENDING_UP: self._trend_following_long,
            MarketRegime.TRENDING_DOWN: self._trend_following_short,
            MarketRegime.SIDEWAYS: self._mean_reversion,
            # ...
        }
        return strategy_map.get(regime, self._default_hold)()
```

### 3.2 出场信号生成器 (ExitSignalGenerator)

```python
@dataclass
class ExitContext:
    """出场决策所需上下文"""
    symbol: str
    entry_price: float
    current_price: float
    position_side: str
    peak_pnl: float
    trailing_stop: float
    holding_periods: int
    atr: float
    regime: MarketRegime
    funding_rate: float

class ExitSignalGenerator:
    """
    出场信号生成器
    职责: 检查止损、止盈、反转等出场条件
    依赖: PositionManager 提供持仓状态
    """
    
    def __init__(self, position_manager: PositionManager):
        self.pm = position_manager
        self.tp_manager = UnifiedTakeProfitManager()
        
        # 出场策略链（责任链模式）
        self.exit_strategies = [
            StopLossStrategy(),      # 1. 止损
            ProfitProtectionStrategy(), # 2. 利润保护
            TrailingStopStrategy(),  # 3. 移动止盈
            EVTExtremeStrategy(),    # 4. EVT极端值
            ATRFixedStrategy(),      # 5. ATR固定
            MLReversalStrategy(),    # 6. ML反转
            FundingExtremeStrategy(), # 7. 资金费率
        ]
    
    def check_exit(self, current_price: float, df: pd.DataFrame) -> ExitSignal:
        """
        检查是否需要出场
        
        Returns:
            ExitSignal: 包含 should_exit, reason, strategy_type
        """
        # 获取完整上下文
        context = self.pm.get_exit_context(current_price)
        
        # 遍历策略链
        for strategy in self.exit_strategies:
            signal = strategy.check(context, df)
            if signal.should_exit:
                # 记录到止盈管理器
                self.tp_manager.record_signal(signal)
                return signal
        
        return ExitSignal(should_exit=False)

# ========== 具体出场策略实现（策略模式）==========

class StopLossStrategy:
    """动态止损策略"""
    def check(self, ctx: ExitContext, df: pd.DataFrame) -> ExitSignal:
        sl_mult = CONFIG.get("STOP_LOSS_ATR_MULT", 1.5)
        sl_pct = -sl_mult * ctx.atr / ctx.entry_price
        
        current_pnl = self._calc_pnl(ctx)
        if current_pnl <= sl_pct:
            return ExitSignal(
                should_exit=True,
                reason=f"动态止损触发({current_pnl*100:.2f}%)",
                strategy_type=ExitType.STOP_LOSS,
                params={'sl_atr_mult': sl_mult}
            )
        return ExitSignal(should_exit=False)

class TrailingStopStrategy:
    """移动止盈策略"""
    def check(self, ctx: ExitContext, df: pd.DataFrame) -> ExitSignal:
        current_pnl = self._calc_pnl(ctx)
        
        # 更新峰值
        if current_pnl > ctx.peak_pnl:
            ctx.peak_pnl = current_pnl
            ctx.trailing_stop = current_pnl * 0.7  # 回撤30%
        
        # 检查回撤
        if current_pnl < ctx.trailing_stop:
            return ExitSignal(
                should_exit=True,
                reason=f"移动止盈触发(峰值{ctx.peak_pnl*100:.2f}%, 回撤30%)",
                strategy_type=ExitType.TRAILING_STOP,
                params={'peak_pnl': ctx.peak_pnl, 'drawback': 0.30}
            )
        return ExitSignal(should_exit=False)
```

### 3.3 持仓管理器 (PositionManager)

```python
class PositionManager:
    """
    持仓状态管理
    职责: 维护单个持仓的全部状态
    """
    
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.reset()
    
    def reset(self):
        """新开仓时重置"""
        self.has_position = False
        self.side = None
        self.entry_price = 0.0
        self.qty = 0.0
        self.entry_time = None
        self.peak_pnl = 0.0
        self.trailing_stop = 0.0
        self.holding_periods = 0
    
    def open(self, side: str, entry_price: float, qty: float):
        """记录开仓"""
        self.has_position = True
        self.side = side
        self.entry_price = entry_price
        self.qty = qty
        self.entry_time = datetime.now()
        self.peak_pnl = 0.0
        self.trailing_stop = 0.0
        self.holding_periods = 0
    
    def update(self, current_price: float):
        """每周期更新持仓状态"""
        if not self.has_position:
            return
        
        self.holding_periods += 1
        
        # 计算当前盈亏
        pnl_pct = self._calc_pnl(current_price)
        
        # 更新峰值和移动止损
        if pnl_pct > self.peak_pnl:
            self.peak_pnl = pnl_pct
            drawback = CONFIG.get("TRAILING_STOP_DRAWBACK_PCT", 0.30)
            self.trailing_stop = self.peak_pnl * (1 - drawback)
    
    def get_exit_context(self, current_price: float) -> ExitContext:
        """生成出场决策上下文"""
        return ExitContext(
            symbol=self.symbol,
            entry_price=self.entry_price,
            current_price=current_price,
            position_side=self.side,
            peak_pnl=self.peak_pnl,
            trailing_stop=self.trailing_stop,
            holding_periods=self.holding_periods,
            # ... 其他字段
        )
    
    def close(self) -> Dict:
        """记录平仓，返回交易记录"""
        record = {
            'symbol': self.symbol,
            'side': self.side,
            'entry_price': self.entry_price,
            'exit_price': self.exit_price,
            'holding_periods': self.holding_periods,
            'max_pnl': self.peak_pnl,
        }
        self.reset()
        return record
```

---

## 4. 调用流程图

### 4.1 入场流程

```
┌─────────────┐     ┌──────────────────────┐     ┌─────────────────┐
│  新K线到来   │────▶│ EntrySignalGenerator │────▶│   风控检查      │
└─────────────┘     └──────────────────────┘     └─────────────────┘
                            │                            │
                            ▼                            ▼
                    ┌───────────────┐           ┌──────────────┐
                    │ 1. 市场状态分析 │           │ 仓位计算     │
                    │ 2. ML预测      │           │ 冷却检查     │
                    │ 3. 策略路由    │           │ 回撤检查     │
                    │ 4. 信号生成    │           └──────────────┘
                    └───────────────┘                  │
                                                       ▼
                                              ┌──────────────┐
                                              │  执行开仓    │
                                              │ OrderExecutor │
                                              └──────────────┘
                                                       │
                                                       ▼
                                              ┌──────────────┐
                                              │ PositionManager│
                                              │   .open()    │
                                              └──────────────┘
```

### 4.2 出场流程

```
┌─────────────┐     ┌──────────────────────┐     ┌─────────────────┐
│  新K线到来   │────▶│  PositionManager     │────▶│ ExitSignalGenerator│
│ (有持仓)    │     │     .update()        │     │    .check_exit()   │
└─────────────┘     └──────────────────────┘     └─────────────────┘
                            │                             │
                            │ (更新peak_pnl等状态)         ▼
                            │                    ┌─────────────────┐
                            │                    │ 遍历出场策略链  │
                            │                    │ 1. 止损        │
                            │                    │ 2. 利润保护    │
                            │                    │ 3. 移动止盈    │
                            │                    │ ...            │
                            │                    └─────────────────┘
                            │                             │
                            │                             ▼
                            │                    ┌─────────────────┐
                            │                    │ should_exit?    │
                            │                    └─────────────────┘
                            │                          │ Yes
                            ▼                          ▼
                     ┌──────────────┐       ┌─────────────────┐
                     │  更新持仓状态  │       │  执行平仓       │
                     │  (无变化)     │       │ OrderExecutor   │
                     └──────────────┘       └─────────────────┘
                                                      │
                                                      ▼
                                              ┌──────────────┐
                                              │ PositionManager│
                                              │   .close()   │
                                              └──────────────┘
```

---

## 5. 重构好处

### 5.1 当前问题 vs 重构后

| 问题 | 当前 | 重构后 |
|-----|------|-------|
| 单一职责 | ❌ `SignalGenerator` 做两件事 | ✅ 入场/出场完全分离 |
| 状态管理 | ❌ 散落在各处 | ✅ `PositionManager` 统一管理 |
| 可测试性 | ❌ 难以单元测试 | ✅ 各组件独立可测 |
| 扩展性 | ❌ 新增出场策略需改多处 | ✅ 新增策略只需添加类 |
| 可维护性 | ❌ God Class | ✅ 每个类<200行 |

### 5.2 代码量对比

| 组件 | 当前行数 | 重构后行数 | 变化 |
|-----|---------|-----------|------|
| SignalGenerator | ~900行 | 删除，拆分到两个类 | -900 |
| EntrySignalGenerator | - | ~300行 | +300 |
| ExitSignalGenerator | - | ~400行 | +400 |
| PositionManager | - | ~150行 | +150 |
| **总计** | **900** | **850** | **更精简** |

---

## 6. 迁移计划

### 阶段1: 创建新类（并行开发，不影响现有交易）
- [ ] 创建 `PositionManager`
- [ ] 创建 `EntrySignalGenerator`
- [ ] 创建 `ExitSignalGenerator` + 策略类

### 阶段2: 单元测试
- [ ] 为每个新类编写单元测试
- [ ] 对比新旧系统信号一致性

### 阶段3: 回测验证
- [ ] 用历史数据验证新系统表现一致
- [ ] 性能测试确保无延迟增加

### 阶段4: 切换（交易低峰期）
- [ ] 停止交易
- [ ] 切换到新架构
- [ ] 观察2-3小时

---

## 7. 更新记录

| 日期 | 版本 | 变更 |
|-----|------|------|
| 2026-03-24 | v12.4 | 创建设计文档，提出重构方案 |
| 2026-03-24 | v12.4.1 | 修复 `SignalGenerator.symbol` 缺失 |

---

**下一步**: 是否开始阶段1重构？建议先用回测验证新架构的正确性。
