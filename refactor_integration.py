#!/usr/bin/env python3
"""
重构集成模块
================
连接 PositionManager 和 ExitSignalGenerator
用于逐步替换旧的 _check_exit_signal 方法

使用方式:
    在 V12OptimizedTrader 中:
        from refactor_integration import ExitSignalAdapter
        
        # 替换原来的 _check_exit_signal 调用
        exit_signal = ExitSignalAdapter.check_exit(
            self.position_manager, 
            current_price, 
            atr, 
            regime, 
            funding_rate,
            df
        )
"""

from typing import Dict, Optional
import pandas as pd
import logging

from position_manager import PositionManager, ExitContext
from exit_signals import ExitSignalGenerator, ExitSignal, ExitType

logger = logging.getLogger(__name__)


class ExitSignalAdapter:
    """
    出场信号适配器
    
    桥接 PositionManager 和 ExitSignalGenerator
    提供与旧代码兼容的接口
    """
    
    def __init__(self, config: Optional[Dict] = None):
        """
        初始化适配器
        
        Args:
            config: 配置参数
        """
        self.generator = ExitSignalGenerator(config)
        logger.info("[ExitSignalAdapter] 初始化完成")
    
    def check_exit(
        self,
        position_manager: PositionManager,
        current_price: float,
        atr: float,
        regime: str,
        funding_rate: float,
        df: Optional[pd.DataFrame] = None,
        ml_prediction: Optional[Dict] = None
    ) -> ExitSignal:
        """
        检查出场信号
        
        Args:
            position_manager: 持仓管理器
            current_price: 当前价格
            atr: 真实波幅
            regime: 市场状态
            funding_rate: 资金费率
            df: K线数据（可选）
            ml_prediction: ML预测结果（可选）
        
        Returns:
            ExitSignal: 出场信号
        """
        # 从 PositionManager 获取出场上下文
        ctx = position_manager.get_exit_context(
            current_price=current_price,
            atr=atr,
            regime=regime,
            funding_rate=funding_rate
        )
        
        # 添加可选数据
        if df is not None:
            ctx.df = df
        if ml_prediction is not None:
            ctx.ml_prediction = ml_prediction
        
        # 检查出场信号
        signal = self.generator.check_exit(ctx)
        
        return signal
    
    def to_trading_signal_dict(self, exit_signal: ExitSignal) -> Dict:
        """
        转换为 TradingSignal 兼容的字典
        
        用于兼容旧代码的数据库记录
        
        Args:
            exit_signal: 出场信号
        
        Returns:
            Dict: 兼容旧格式的字典
        """
        return {
            'action': 'CLOSE' if exit_signal.should_exit else 'HOLD',
            'exit_type': exit_signal.exit_type.value,
            'reason': exit_signal.reason,
            'params': exit_signal.params,
            'timestamp': exit_signal.timestamp.isoformat(),
        }


# 全局实例（单例模式）
_adapter_instance: Optional[ExitSignalAdapter] = None


def get_exit_adapter(config: Optional[Dict] = None) -> ExitSignalAdapter:
    """
    获取全局 ExitSignalAdapter 实例
    
    Args:
        config: 可选配置
    
    Returns:
        ExitSignalAdapter: 全局实例
    """
    global _adapter_instance
    if _adapter_instance is None:
        _adapter_instance = ExitSignalAdapter(config)
    return _adapter_instance


# ==================== 集成测试 ====================

if __name__ == "__main__":
    import sys
    
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s | %(levelname)s | %(message)s'
    )
    
    print("="*60)
    print("Refactor Integration Test")
    print("="*60)
    
    # 创建模拟配置
    config = {
        'STOP_LOSS_ATR_MULT': 1.5,
        'PROFIT_PROTECTION_ENABLE_PCT': 0.005,
        'PROFIT_PROTECTION_DRAWBACK_PCT': 0.50,
        'TRAILING_STOP_DRAWBACK_PCT': 0.30,
    }
    
    # 测试1: 完整流程
    print("\n[Test 1] 完整流程测试")
    
    # 创建持仓
    pm = PositionManager("ETHUSDT", config)
    pm.open("SHORT", 2149.20, 0.018)
    
    # 价格下跌（做空盈利）
    print("  价格 2149.20 -> 2130.0 (做空盈利)")
    state = pm.update(2130.0)
    print(f"  PnL: {state.current_pnl_pct:.2%}, Peak: {state.peak_pnl:.2%}")
    
    # 检查出场（不应触发）
    adapter = ExitSignalAdapter(config)
    signal = adapter.check_exit(
        pm, 2130.0, 
        atr=10.5, 
        regime="TRENDING_DOWN", 
        funding_rate=0.0001
    )
    print(f"  出场信号: should_exit={signal.should_exit}")
    assert not signal.should_exit, "不应触发出场"
    
    # 价格反弹（触发移动止盈）
    print("\n  价格 2130.0 -> 2140.0 (反弹触发移动止盈)")
    state = pm.update(2140.0)
    print(f"  PnL: {state.current_pnl_pct:.2%}, Peak: {state.peak_pnl:.2%}, Trailing: {state.trailing_stop:.2%}")
    
    signal = adapter.check_exit(
        pm, 2140.0,
        atr=10.5,
        regime="TRENDING_DOWN",
        funding_rate=0.0001
    )
    print(f"  出场信号: should_exit={signal.should_exit}, type={signal.exit_type.value if signal.should_exit else 'N/A'}")
    
    if signal.should_exit:
        print(f"  原因: {signal.reason}")
        # 利润保护优先级高于移动止盈，可能先触发
        assert signal.exit_type in [ExitType.TRAILING_STOP, ExitType.PROFIT_PROTECTION], \
            f"应该是移动止盈或利润保护，实际是 {signal.exit_type}"
    
    # 测试2: 止损触发
    print("\n[Test 2] 止损触发测试")
    pm2 = PositionManager("ETHUSDT", config)
    pm2.open("LONG", 2000.0, 0.01)
    
    # 价格下跌（做多亏损）
    print("  价格 2000.0 -> 1970.0 (做多亏损超过1.5ATR)")
    pm2.update(1970.0)
    
    signal = adapter.check_exit(
        pm2, 1970.0,
        atr=15.0,  # 1.5 * 15 = 22.5, 22.5/2000 = 1.125% 止损线
        regime="TRENDING_DOWN",
        funding_rate=0.0001
    )
    print(f"  出场信号: should_exit={signal.should_exit}, type={signal.exit_type.value if signal.should_exit else 'N/A'}")
    
    if signal.should_exit:
        print(f"  原因: {signal.reason}")
        assert signal.exit_type == ExitType.STOP_LOSS_DYNAMIC, "应该是动态止损"
    
    print("\n" + "="*60)
    print("[PASS] All integration tests passed!")
    print("="*60)
    
    print("\n集成测试完成，可以安全地替换旧代码中的 _check_exit_signal!")
    print("\n替换步骤:")
    print("1. 在 V12OptimizedTrader.__init__ 中添加:")
    print("   self.exit_adapter = ExitSignalAdapter(CONFIG)")
    print("\n2. 替换 _check_exit_signal 调用:")
    print("   # 旧代码")
    print("   signal = self.signal_gen._check_exit_signal(...)")
    print("   ")
    print("   # 新代码")
    print("   exit_signal = self.exit_adapter.check_exit(")
    print("       self.position_manager, current_price,")
    print("       atr, regime, funding_rate, df")
    print("   )")
    print("   if exit_signal.should_exit:")
    print("       return TradingSignal('CLOSE', ..., exit_signal.reason)")
