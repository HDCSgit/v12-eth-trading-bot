#!/usr/bin/env python3
"""
ExitSignalGenerator - 出场信号生成器
========================================
重构日期: 2026-03-24
原位置: main_v12_live_optimized.py SignalGenerator._check_exit_signal

职责:
    - 检查止损、止盈、反转等出场条件
    - 使用策略模式，每个策略独立
    - 与 PositionManager 解耦，通过 ExitContext 获取状态

设计原则:
    - 策略模式: 每种出场策略独立成类
    - 责任链: 按优先级检查，触发即返回
    - 可扩展: 新增策略只需添加类

Author: AI Assistant
Version: 1.0.0
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Literal
from datetime import datetime
from enum import Enum
import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


class ExitType(Enum):
    """出场类型枚举"""
    STOP_LOSS_DYNAMIC = "动态止损_ATR"
    STOP_LOSS_FIXED = "固定止损"
    PROFIT_PROTECTION = "盈利保护_回撤50"
    TRAILING_STOP = "移动止盈_回撤30"
    EVT_EXTREME = "EVT极值止盈"
    ATR_FIXED = "ATR固定止盈"
    ML_REVERSAL = "ML趋势反转"
    FUNDING_HIGH = "资金费率_过高"
    FUNDING_LOW = "资金费率_过低"
    TIMEOUT = "超时平仓"
    MANUAL = "手动平仓"


@dataclass
class ExitContext:
    """
    出场决策上下文
    
    从 PositionManager 获取的完整持仓状态
    """
    # 基础信息
    symbol: str
    side: Literal['LONG', 'SHORT']
    entry_price: float
    current_price: float
    qty: float
    
    # 盈亏状态
    current_pnl_pct: float
    peak_pnl: float
    trailing_stop: float
    
    # 持仓时间
    holding_periods: int
    
    # 市场环境
    atr: float
    regime: str
    funding_rate: float
    
    # 可选数据
    df: Optional[pd.DataFrame] = None
    ml_prediction: Optional[Dict] = None
    extra: Dict = field(default_factory=dict)


@dataclass  
class ExitSignal:
    """出场信号"""
    should_exit: bool
    exit_type: ExitType = ExitType.MANUAL
    reason: str = ""
    params: Dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict:
        """转为字典"""
        return {
            'should_exit': self.should_exit,
            'exit_type': self.exit_type.value,
            'reason': self.reason,
            'params': self.params,
            'timestamp': self.timestamp.isoformat(),
        }


class ExitStrategy(ABC):
    """出场策略基类"""
    
    @property
    @abstractmethod
    def priority(self) -> int:
        """优先级，数字越小越优先"""
        pass
    
    @abstractmethod
    def check(self, ctx: ExitContext) -> ExitSignal:
        """检查是否触发出场"""
        pass
    
    def _calc_pnl(self, ctx: ExitContext) -> float:
        """计算当前盈亏百分比（辅助方法）"""
        if ctx.side in ['SELL', 'SHORT']:
            return (ctx.entry_price - ctx.current_price) / ctx.entry_price
        else:
            return (ctx.current_price - ctx.entry_price) / ctx.entry_price


class StopLossStrategy(ExitStrategy):
    """
    动态止损策略
    
    基于ATR的动态止损，根据市场波动率调整
    """
    priority = 1  # 最高优先级
    
    def __init__(self, atr_mult: float = 1.5):
        self.atr_mult = atr_mult
    
    def check(self, ctx: ExitContext) -> ExitSignal:
        current_pnl = self._calc_pnl(ctx)
        
        # 计算止损线
        sl_pct = -self.atr_mult * ctx.atr / ctx.entry_price
        
        if current_pnl <= sl_pct:
            return ExitSignal(
                should_exit=True,
                exit_type=ExitType.STOP_LOSS_DYNAMIC,
                reason=f"动态止损触发({current_pnl*100:.2f}%)",
                params={
                    'atr_mult': self.atr_mult,
                    'atr_value': ctx.atr,
                    'sl_pct': sl_pct,
                    'current_pnl': current_pnl,
                }
            )
        return ExitSignal(should_exit=False)


class ProfitProtectionStrategy(ExitStrategy):
    """
    利润保护策略
    
    当浮盈达到一定阈值后，回撤50%即止盈
    """
    priority = 2
    
    def __init__(self, enable_pct: float = 0.005, drawback_pct: float = 0.50):
        self.enable_pct = enable_pct    # 激活阈值 (0.5%)
        self.drawback_pct = drawback_pct  # 回撤比例 (50%)
    
    def check(self, ctx: ExitContext) -> ExitSignal:
        current_pnl = self._calc_pnl(ctx)
        
        # 需要达到激活阈值
        if ctx.peak_pnl < self.enable_pct:
            return ExitSignal(should_exit=False)
        
        # 计算回撤后的止盈线
        stop_level = ctx.peak_pnl * (1 - self.drawback_pct)
        
        if current_pnl < stop_level:
            return ExitSignal(
                should_exit=True,
                exit_type=ExitType.PROFIT_PROTECTION,
                reason=f"利润保护触发(峰值{ctx.peak_pnl*100:.2f}%, 回撤{self.drawback_pct*100:.0f}%)",
                params={
                    'peak_pnl': ctx.peak_pnl,
                    'current_pnl': current_pnl,
                    'stop_level': stop_level,
                    'drawback_pct': self.drawback_pct,
                }
            )
        return ExitSignal(should_exit=False)


class TrailingStopStrategy(ExitStrategy):
    """
    移动止盈策略
    
    峰值回撤30%触发止盈
    """
    priority = 3
    
    def __init__(self, drawback_pct: float = 0.30):
        self.drawback_pct = drawback_pct
    
    def check(self, ctx: ExitContext) -> ExitSignal:
        current_pnl = self._calc_pnl(ctx)
        
        # 需要先有盈利
        if ctx.peak_pnl <= 0:
            return ExitSignal(should_exit=False)
        
        # 检查是否跌破移动止损线
        if current_pnl < ctx.trailing_stop:
            return ExitSignal(
                should_exit=True,
                exit_type=ExitType.TRAILING_STOP,
                reason=f"移动止盈触发(峰值{ctx.peak_pnl*100:.2f}%, 当前{current_pnl*100:.2f}%)",
                params={
                    'peak_pnl': ctx.peak_pnl,
                    'trailing_stop': ctx.trailing_stop,
                    'current_pnl': current_pnl,
                    'drawback_pct': self.drawback_pct,
                }
            )
        return ExitSignal(should_exit=False)


class EVTExtremeStrategy(ExitStrategy):
    """
    EVT极端值止盈策略
    
    基于极值理论的动态止盈
    """
    priority = 4
    
    def check(self, ctx: ExitContext) -> ExitSignal:
        # TODO: 集成 EVT 计算
        # 目前返回不触发，后续实现
        return ExitSignal(should_exit=False)


class ATRFixedStrategy(ExitStrategy):
    """
    ATR固定倍数止盈
    
    震荡4倍ATR，趋势8倍ATR
    """
    priority = 5
    
    def check(self, ctx: ExitContext) -> ExitSignal:
        current_pnl = self._calc_pnl(ctx)
        
        # 根据市场状态选择倍数
        if 'SIDEWAYS' in ctx.regime:
            atr_mult = 4.0
            target_pct = atr_mult * ctx.atr / ctx.entry_price
        else:
            atr_mult = 8.0
            target_pct = atr_mult * ctx.atr / ctx.entry_price
        
        if current_pnl >= target_pct:
            return ExitSignal(
                should_exit=True,
                exit_type=ExitType.ATR_FIXED,
                reason=f"ATR固定止盈触发({current_pnl*100:.2f}%, 目标{target_pct*100:.2f}%)",
                params={
                    'atr_mult': atr_mult,
                    'target_pct': target_pct,
                    'current_pnl': current_pnl,
                    'regime': ctx.regime,
                }
            )
        return ExitSignal(should_exit=False)


class MLReversalStrategy(ExitStrategy):
    """
    ML趋势反转出场
    
    ML预测反转且置信度>0.75
    """
    priority = 6
    
    def __init__(self, threshold: float = 0.75):
        self.threshold = threshold
    
    def check(self, ctx: ExitContext) -> ExitSignal:
        if not ctx.ml_prediction:
            return ExitSignal(should_exit=False)
        
        ml_conf = ctx.ml_prediction.get('confidence', 0)
        ml_dir = ctx.ml_prediction.get('direction', 0)
        
        # 检查是否反转
        position_dir = 1 if ctx.side == 'LONG' else -1
        if ml_dir * position_dir < 0 and ml_conf >= self.threshold:
            return ExitSignal(
                should_exit=True,
                exit_type=ExitType.ML_REVERSAL,
                reason=f"ML趋势反转(置信度{ml_conf:.2f})",
                params={
                    'ml_confidence': ml_conf,
                    'ml_direction': ml_dir,
                    'threshold': self.threshold,
                }
            )
        return ExitSignal(should_exit=False)


class FundingExtremeStrategy(ExitStrategy):
    """
    资金费率极端值出场
    
    资金费率>1%对持仓不利
    """
    priority = 7
    
    def __init__(self, threshold: float = 0.01):
        self.threshold = threshold
    
    def check(self, ctx: ExitContext) -> ExitSignal:
        # 做空时资金费率过高（负值）不利
        if ctx.side == 'SHORT' and ctx.funding_rate < -self.threshold:
            return ExitSignal(
                should_exit=True,
                exit_type=ExitType.FUNDING_HIGH,
                reason=f"资金费率极端(做空不利: {ctx.funding_rate*100:.3f}%)",
                params={'funding_rate': ctx.funding_rate}
            )
        
        # 做多时资金费率过高不利
        if ctx.side == 'LONG' and ctx.funding_rate > self.threshold:
            return ExitSignal(
                should_exit=True,
                exit_type=ExitType.FUNDING_HIGH,
                reason=f"资金费率极端(做多不利: {ctx.funding_rate*100:.3f}%)",
                params={'funding_rate': ctx.funding_rate}
            )
        
        return ExitSignal(should_exit=False)


class TimeExitStrategy(ExitStrategy):
    """
    超时平仓
    
    持仓时间过长强制出场
    """
    priority = 8
    
    def __init__(self, max_periods: int = 180):  # 默认3小时(1分钟K线)
        self.max_periods = max_periods
    
    def check(self, ctx: ExitContext) -> ExitSignal:
        if ctx.holding_periods >= self.max_periods:
            return ExitSignal(
                should_exit=True,
                exit_type=ExitType.TIMEOUT,
                reason=f"持仓超时({ctx.holding_periods}周期)",
                params={
                    'holding_periods': ctx.holding_periods,
                    'max_periods': self.max_periods,
                }
            )
        return ExitSignal(should_exit=False)


class ExitSignalGenerator:
    """
    出场信号生成器
    
    使用责任链模式，按优先级检查各出场策略
    
    Example:
        >>> generator = ExitSignalGenerator()
        >>> ctx = ExitContext(symbol="ETHUSDT", side="SHORT", ...)
        >>> signal = generator.check_exit(ctx)
        >>> if signal.should_exit:
        ...     print(f"出场: {signal.reason}")
    """
    
    def __init__(self, config: Optional[Dict] = None):
        """
        初始化出场信号生成器
        
        Args:
            config: 配置参数，可选
        """
        self.config = config or {}
        
        # 初始化策略链
        self.strategies: List[ExitStrategy] = [
            StopLossStrategy(
                atr_mult=self.config.get('STOP_LOSS_ATR_MULT', 2.0)  # 优化后：1.5->2.0
            ),
            ProfitProtectionStrategy(
                enable_pct=self.config.get('PROFIT_PROTECTION_ENABLE_PCT', 0.005),
                drawback_pct=self.config.get('PROFIT_PROTECTION_DRAWBACK_PCT', 0.50)
            ),
            TrailingStopStrategy(
                drawback_pct=self.config.get('TRAILING_STOP_DRAWBACK_PCT', 0.30)
            ),
            EVTExtremeStrategy(),
            ATRFixedStrategy(),
            MLReversalStrategy(
                threshold=self.config.get('ML_REVERSAL_THRESHOLD', 0.75)
            ),
            FundingExtremeStrategy(
                threshold=self.config.get('FUNDING_THRESHOLD', 0.01)
            ),
            TimeExitStrategy(
                max_periods=self.config.get('MAX_HOLDING_PERIODS', 180)
            ),
        ]
        
        # 按优先级排序
        self.strategies.sort(key=lambda s: s.priority)
        
        logger.info(f"[ExitSignalGenerator] 初始化完成，加载{len(self.strategies)}个出场策略")
    
    def check_exit(self, ctx: ExitContext) -> ExitSignal:
        """
        检查出场信号
        
        按优先级遍历策略链，触发即返回
        
        Args:
            ctx: 出场决策上下文
        
        Returns:
            ExitSignal: 出场信号
        """
        for strategy in self.strategies:
            signal = strategy.check(ctx)
            if signal.should_exit:
                logger.debug(
                    f"[ExitSignalGenerator] 策略触发: {signal.exit_type.value} | "
                    f"{signal.reason}"
                )
                return signal
        
        return ExitSignal(should_exit=False)
    
    def get_strategy_info(self) -> List[Dict]:
        """获取策略信息"""
        return [
            {'name': s.__class__.__name__, 'priority': s.priority}
            for s in self.strategies
        ]


# ==================== 单元测试 ====================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s | %(levelname)s | %(message)s'
    )
    
    print("="*60)
    print("ExitSignalGenerator 单元测试")
    print("="*60)
    
    # 测试1: 止损触发
    print("\n[Test 1] 动态止损")
    gen = ExitSignalGenerator()
    ctx = ExitContext(
        symbol="ETHUSDT",
        side="SHORT",
        entry_price=2149.20,
        current_price=2180.0,  # 价格上涨，做空亏损
        qty=0.018,
        current_pnl_pct=-0.014,  # -1.4%
        peak_pnl=0.0,
        trailing_stop=0.0,
        holding_periods=10,
        atr=10.5,
        regime="TRENDING_DOWN",
        funding_rate=0.0001,
    )
    signal = gen.check_exit(ctx)
    assert signal.should_exit == True
    assert signal.exit_type == ExitType.STOP_LOSS_DYNAMIC
    print(f"[OK] 止损触发: {signal.reason}")
    
    # 测试2: 移动止盈
    print("\n[Test 2] 移动止盈")
    ctx2 = ExitContext(
        symbol="ETHUSDT",
        side="SHORT",
        entry_price=2149.20,
        current_price=2130.0,  # 下跌后反弹
        qty=0.018,
        current_pnl_pct=0.008,  # 0.89% (从峰值1.5%回撤)
        peak_pnl=0.015,  # 峰值1.5%
        trailing_stop=0.0105,  # 1.5% * 0.7 = 1.05%
        holding_periods=20,
        atr=10.5,
        regime="TRENDING_DOWN",
        funding_rate=0.0001,
    )
    signal2 = gen.check_exit(ctx2)
    print(f"[OK] 移动止盈检查: should_exit={signal2.should_exit}")
    
    # 测试3: 利润保护
    print("\n[Test 3] 利润保护")
    ctx3 = ExitContext(
        symbol="ETHUSDT",
        side="LONG",
        entry_price=2000.0,
        current_price=2025.0,  # 1.25%盈利，从5%回撤到1.25% (回撤75% > 50%)
        qty=0.01,
        current_pnl_pct=0.0125,
        peak_pnl=0.05,  # 峰值5%
        trailing_stop=0.035,
        holding_periods=30,
        atr=15.0,
        regime="TRENDING_UP",
        funding_rate=0.0001,
    )
    pp_strategy = ProfitProtectionStrategy(enable_pct=0.005, drawback_pct=0.50)
    signal3 = pp_strategy.check(ctx3)
    # peak 5%, stop_level = 5% * 0.5 = 2.5%, current 1.25% < 2.5%, 应该触发
    assert signal3.should_exit == True
    print(f"[OK] 利润保护触发: {signal3.reason}")
    
    print("\n" + "="*60)
    print("[PASS] All tests passed!")
    print("="*60)
