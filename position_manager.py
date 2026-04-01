#!/usr/bin/env python3
"""
PositionManager - 持仓状态管理器
========================================
重构提取日期: 2026-03-24
原位置: main_v12_live_optimized.py SignalGenerator.position_peak_pnl 等

职责:
    - 维护单个持仓的全部状态
    - 提供出场决策所需上下文
    - 与信号生成器解耦

设计原则:
    - 单一职责: 只管理持仓状态，不生成信号
    - 状态封装: 所有持仓相关状态集中管理
    - 便于测试: 纯状态管理，无外部依赖

Author: AI Assistant
Version: 1.0.0
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional, Literal
import logging

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class PositionState:
    """持仓状态快照"""
    has_position: bool = False
    side: Optional[str] = None  # 'LONG' or 'SHORT'
    entry_price: float = 0.0
    qty: float = 0.0
    entry_time: Optional[datetime] = None
    
    # 盈亏追踪
    current_pnl_pct: float = 0.0
    peak_pnl: float = 0.0
    trailing_stop: float = 0.0
    
    # 持仓时间
    holding_periods: int = 0
    
    def to_dict(self) -> Dict:
        """转为字典，便于序列化"""
        return {
            'has_position': self.has_position,
            'side': self.side,
            'entry_price': self.entry_price,
            'qty': self.qty,
            'entry_time': self.entry_time.isoformat() if self.entry_time else None,
            'current_pnl_pct': self.current_pnl_pct,
            'peak_pnl': self.peak_pnl,
            'trailing_stop': self.trailing_stop,
            'holding_periods': self.holding_periods,
        }


@dataclass
class ExitContext:
    """
    出场决策上下文
    
    包含出场信号生成所需的全部信息
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


class PositionManager:
    """
    持仓状态管理器
    
    维护单个交易对的持仓状态，提供出场决策上下文
    
    Example:
        >>> pm = PositionManager("ETHUSDT")
        >>> pm.open("SHORT", 2149.20, 0.018)
        >>> state = pm.update(2150.0)  # 价格下跌，做空盈利
        >>> print(f"PnL: {state.current_pnl_pct:.2%}")
        >>> context = pm.get_exit_context(2150.0, atr=10.0, 
        ...                               regime="TRENDING_DOWN", 
        ...                               funding_rate=0.0001)
        >>> record = pm.close(2155.0)  # 平仓
    """
    
    def __init__(self, symbol: str, config: Optional[Dict] = None):
        """
        初始化持仓管理器
        
        Args:
            symbol: 交易对，如 "ETHUSDT"
            config: 可选配置，覆盖默认参数
        """
        self.symbol = symbol
        self.config = config or {}
        
        # 默认配置
        self.trailing_drawback_pct = self.config.get(
            "TRAILING_STOP_DRAWBACK_PCT", 0.30
        )
        
        self.reset()
        logger.info(f"[PositionManager] 初始化完成: {symbol}")
    
    def reset(self):
        """重置所有状态（新开仓前调用）"""
        self.has_position = False
        self.side = None
        self.entry_price = 0.0
        self.qty = 0.0
        self.entry_time = None
        
        # 盈亏追踪
        self.current_pnl_pct = 0.0
        self.peak_pnl = 0.0
        self.trailing_stop = 0.0
        
        # 持仓时间
        self.holding_periods = 0
        
        logger.debug(f"[PositionManager] 状态已重置")
    
    def open(self, side: str, entry_price: float, qty: float) -> PositionState:
        """
        记录开仓
        
        Args:
            side: 方向，'LONG' 或 'SHORT'
            entry_price: 入场价格
            qty: 数量
        
        Returns:
            PositionState: 开仓后的状态
        
        Raises:
            ValueError: 已有持仓时抛出
        """
        if self.has_position:
            raise ValueError(f"已有持仓，无法开仓: {self.side} {self.qty}")
        
        self.has_position = True
        self.side = side.upper()
        self.entry_price = entry_price
        self.qty = qty
        self.entry_time = datetime.now()
        
        # 重置盈亏追踪
        self.current_pnl_pct = 0.0
        self.peak_pnl = 0.0
        self.trailing_stop = 0.0
        self.holding_periods = 0
        
        logger.info(
            f"[PositionManager] 开仓 {self.side} {self.qty} @ {self.entry_price}"
        )
        
        return self.get_state()
    
    def update(self, current_price: float) -> PositionState:
        """
        每周期更新持仓状态
        
        计算当前盈亏，更新峰值和移动止损
        
        Args:
            current_price: 当前价格
        
        Returns:
            PositionState: 更新后的状态
        """
        if not self.has_position:
            return self.get_state()
        
        self.holding_periods += 1
        
        # 计算当前盈亏百分比
        self.current_pnl_pct = self._calc_pnl_pct(current_price)
        
        # 更新峰值盈亏
        if self.current_pnl_pct > self.peak_pnl:
            self.peak_pnl = self.current_pnl_pct
            # 更新移动止损线（回撤30%）
            self.trailing_stop = self.peak_pnl * (1 - self.trailing_drawback_pct)
            logger.debug(
                f"[PositionManager] 峰值更新: {self.peak_pnl:.2%}, "
                f"移动止损: {self.trailing_stop:.2%}"
            )
        
        return self.get_state()
    
    def close(self, exit_price: float, exit_reason: str = "") -> Dict:
        """
        记录平仓
        
        Args:
            exit_price: 出场价格
            exit_reason: 平仓原因
        
        Returns:
            Dict: 完整交易记录
        """
        if not self.has_position:
            logger.warning("[PositionManager] 平仓时无持仓")
            return None
        
        # 计算最终盈亏
        final_pnl_pct = self._calc_pnl_pct(exit_price)
        
        record = {
            'symbol': self.symbol,
            'side': self.side,
            'entry_price': self.entry_price,
            'exit_price': exit_price,
            'qty': self.qty,
            'pnl_pct': final_pnl_pct,
            'pnl_usdt': final_pnl_pct * self.entry_price * self.qty,
            'entry_time': self.entry_time.isoformat() if self.entry_time else None,
            'exit_time': datetime.now().isoformat(),
            'holding_periods': self.holding_periods,
            'max_pnl': self.peak_pnl,
            'exit_reason': exit_reason,
        }
        
        logger.info(
            f"[PositionManager] 平仓 {self.side} @ {exit_price} | "
            f"PnL: {final_pnl_pct*100:.2f}%, 持仓: {self.holding_periods}周期"
        )
        
        self.reset()
        return record
    
    def get_state(self) -> PositionState:
        """获取当前状态快照"""
        return PositionState(
            has_position=self.has_position,
            side=self.side,
            entry_price=self.entry_price,
            qty=self.qty,
            entry_time=self.entry_time,
            current_pnl_pct=self.current_pnl_pct,
            peak_pnl=self.peak_pnl,
            trailing_stop=self.trailing_stop,
            holding_periods=self.holding_periods,
        )
    
    def get_exit_context(
        self,
        current_price: float,
        atr: float,
        regime: str,
        funding_rate: float,
        extra: Optional[Dict] = None
    ) -> ExitContext:
        """
        生成出场决策上下文
        
        Args:
            current_price: 当前价格
            atr: 真实波幅
            regime: 市场状态
            funding_rate: 资金费率
            extra: 额外信息
        
        Returns:
            ExitContext: 出场决策所需完整上下文
        """
        # 确保状态已更新
        if self.has_position and current_price != self.entry_price:
            self.update(current_price)
        
        return ExitContext(
            symbol=self.symbol,
            side=self.side if self.side else 'LONG',
            entry_price=self.entry_price,
            current_price=current_price,
            qty=self.qty,
            current_pnl_pct=self.current_pnl_pct,
            peak_pnl=self.peak_pnl,
            trailing_stop=self.trailing_stop,
            holding_periods=self.holding_periods,
            atr=atr,
            regime=regime,
            funding_rate=funding_rate,
            extra=extra or {}
        )
    
    def _calc_pnl_pct(self, current_price: float) -> float:
        """计算当前盈亏百分比（内部方法）"""
        if not self.has_position or self.entry_price == 0:
            return 0.0
        
        if self.side in ['SELL', 'SHORT']:
            # 做空：价格下跌盈利
            return (self.entry_price - current_price) / self.entry_price
        else:
            # 做多：价格上涨盈利
            return (current_price - self.entry_price) / self.entry_price
    
    def __repr__(self) -> str:
        """字符串表示"""
        if self.has_position:
            return (
                f"PositionManager({self.symbol}: {self.side} {self.qty} @ "
                f"{self.entry_price}, PnL: {self.current_pnl_pct:.2%}, "
                f"Peak: {self.peak_pnl:.2%})"
            )
        return f"PositionManager({self.symbol}: No Position)"


# ==================== 单元测试 ====================

if __name__ == "__main__":
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s'
    )
    
    print("="*60)
    print("PositionManager 单元测试")
    print("="*60)
    
    # 测试1: 基础功能
    print("\n[Test 1] 基础开仓平仓")
    pm = PositionManager("ETHUSDT")
    
    # 开仓做空
    state = pm.open("SHORT", 2149.20, 0.018)
    assert state.has_position == True
    assert state.side == "SHORT"
    print(f"[OK] 开仓成功: {state}")
    
    # 更新价格（下跌，做空盈利）
    state = pm.update(2140.0)
    assert state.current_pnl_pct > 0  # 做空，下跌盈利
    print(f"[OK] 价格更新: PnL = {state.current_pnl_pct:.2%}")
    
    # 平仓
    record = pm.close(2130.0, "止盈出场")
    assert record['pnl_pct'] > 0
    assert pm.has_position == False
    print(f"[OK] 平仓成功: PnL = {record['pnl_pct']:.2%}")
    
    # 测试2: 移动止损
    print("\n[Test 2] 移动止损计算")
    pm2 = PositionManager("ETHUSDT")
    pm2.open("LONG", 2000.0, 0.01)
    
    # 价格上涨到2100 (5%盈利)
    pm2.update(2100.0)
    assert pm2.peak_pnl == 0.05
    assert pm2.trailing_stop == 0.05 * 0.7  # 回撤30%
    print(f"[OK] 峰值: {pm2.peak_pnl:.2%}, 移动止损线: {pm2.trailing_stop:.2%}")
    
    # 价格回落到2080 (4%盈利，触发移动止损)
    pm2.update(2080.0)
    print(f"[OK] 回落后 PnL: {pm2.current_pnl_pct:.2%}")
    
    # 测试3: ExitContext
    print("\n[Test 3] ExitContext 生成")
    pm3 = PositionManager("ETHUSDT")
    pm3.open("SHORT", 2149.20, 0.018)
    pm3.update(2140.0)
    
    ctx = pm3.get_exit_context(
        current_price=2135.0,
        atr=10.5,
        regime="TRENDING_DOWN",
        funding_rate=0.0001
    )
    assert ctx.symbol == "ETHUSDT"
    assert ctx.side == "SHORT"
    assert ctx.peak_pnl > 0
    print(f"[OK] ExitContext: side={ctx.side}, peak={ctx.peak_pnl:.2%}")
    
    print("\n" + "="*60)
    print("[PASS] All tests passed!")
    print("="*60)
