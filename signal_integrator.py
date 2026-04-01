#!/usr/bin/env python3
"""
信号生成与入场评估集成模块
将原有的趋势确认替换为综合评分机制
"""

import pandas as pd
from typing import Optional, Dict
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class SignalIntegrator:
    """
    信号集成器 - 将generate_signal与入场评估结合
    
    主要职责:
    1. 生成原始信号
    2. 评估入场质量
    3. 调整仓位或过滤信号
    4. 完整留痕
    """
    
    def __init__(self, signal_gen, entry_checker):
        self.signal_gen = signal_gen
        self.entry_checker = entry_checker
    
    def generate_and_evaluate(
        self,
        df: pd.DataFrame,
        current_price: float,
        funding_rate: float = 0.0,
        has_position: bool = False,
        position_side: str = None,
        entry_price: float = 0.0,
        symbol: str = 'ETHUSDT'
    ):
        """
        生成信号并评估入场质量
        
        Returns:
            (signal, evaluation_result)
            - signal: 调整后的交易信号
            - evaluation_result: 评估详情（用于留痕和调试）
        """
        # 1. 先生成原始信号
        signal = self.signal_gen.generate_signal(
            df, current_price, funding_rate,
            has_position, position_side, entry_price
        )
        
        # 2. 如果有持仓或HOLD信号，直接返回（无需评估入场）
        if has_position or signal.action == 'HOLD':
            return signal, None
        
        # 3. 获取评估所需数据
        try:
            # 从df中获取RSI
            current_rsi = df['rsi_12'].iloc[-1] if 'rsi_12' in df.columns else 50
            
            # 获取近期价格
            recent_prices = df['close'].tail(20).tolist()
            
            # 获取ML信息（如果信号中有）
            ml_confidence = getattr(signal, 'ml_confidence', 0)
            ml_direction = getattr(signal, 'ml_direction', 0)
            
            # 更新趋势信息
            self.entry_checker.update_trend_info(
                signal.action, 
                datetime.now()
            )
            
            # 4. 进行综合评分检查
            should_enter, msg, score, details = self.entry_checker.comprehensive_check(
                signal_action=signal.action,
                current_price=current_price,
                recent_prices=recent_prices,
                current_rsi=current_rsi,
                weights={'position': 0.4, 'rsi': 0.3, 'duration': 0.3}
            )
            
            # 5. 构建记录
            from entry_quality_checker import EntryCheckRecord, EntryDecision
            
            record = EntryCheckRecord(
                timestamp=datetime.now(),
                symbol=symbol,
                action=signal.action,
                current_price=current_price,
                decision=EntryDecision.REJECTED if not should_enter else (
                    EntryDecision.REDUCED if score < 0.7 else EntryDecision.APPROVED
                ),
                final_score=score,
                position_size_pct=details['position_size_pct'],
                reason=msg,
                position_score=details['checks'].get('position', {}).get('score'),
                position_msg=details['checks'].get('position', {}).get('message', ''),
                rsi_score=details['checks'].get('rsi', {}).get('score'),
                rsi_msg=details['checks'].get('rsi', {}).get('message', ''),
                duration_score=details['checks'].get('duration', {}).get('score'),
                duration_msg=details['checks'].get('duration', {}).get('message', ''),
                market_regime=signal.regime.value if signal.regime else '',
                rsi_value=current_rsi,
                trend_duration_minutes=details['checks'].get('duration', {}).get('score', 0) * 90,  # 估算
                price_position_pct=None,  # 可以从details中解析
                ml_confidence=ml_confidence,
                ml_direction=ml_direction
            )
            
            # 6. 保存记录
            self.entry_checker.save_record(record)
            
            # 7. 根据评分调整信号
            if not should_enter:
                # 禁止入场，改为HOLD
                logger.warning(f"[入场评估] 评分{score:.2f}<0.2，禁止入场: {msg}")
                from main_v12_live_optimized import TradingSignal, SignalSource
                adjusted_signal = TradingSignal(
                    'HOLD', 0.5, SignalSource.TECHNICAL,
                    f'入场评估拒绝({score:.2f}): {msg}',
                    signal.atr, regime=signal.regime, funding_rate=funding_rate
                )
                return adjusted_signal, details
            
            elif score < 0.7:
                # 降低仓位入场，修改信号中的信息
                logger.info(f"[入场评估] 评分{score:.2f}，降低仓位至{details['position_size_pct']*100:.0f}%")
                # 将仓位建议附加到信号中（供后续使用）
                signal._position_size_pct = details['position_size_pct']
                signal.reason += f" [评分{score:.2f},仓位{details['position_size_pct']*100:.0f}%]"
                return signal, details
            
            else:
                # 正常入场
                logger.info(f"[入场评估] 评分{score:.2f}，正常入场")
                signal.reason += f" [评分{score:.2f}]"
                return signal, details
                
        except Exception as e:
            logger.error(f"[入场评估] 评估过程出错: {e}")
            # 出错时允许入场（保守策略）
            return signal, None


# 快速集成函数
def integrate_entry_check(signal_gen, entry_checker):
    """
    快速集成：将入场检查集成到信号生成器中
    
    用法:
        signal_gen = EnhancedSignalGenerator(...)
        entry_checker = EntryQualityChecker()
        integrate_entry_check(signal_gen, entry_checker)
        
        # 之后调用generate_signal时会自动进行评估
    """
    integrator = SignalIntegrator(signal_gen, entry_checker)
    
    # 保存原始方法
    original_generate = signal_gen.generate_signal
    
    def new_generate_signal(df, current_price, funding_rate=0.0, 
                           has_position=False, position_side=None, entry_price=0.0):
        """包装后的generate_signal，自动进行入场评估"""
        
        # 先调用原始方法生成信号
        signal = original_generate(df, current_price, funding_rate,
                                   has_position, position_side, entry_price)
        
        # 如果有持仓或HOLD，直接返回
        if has_position or signal.action == 'HOLD':
            return signal
        
        # 进行综合评估
        adjusted_signal, details = integrator.generate_and_evaluate(
            df, current_price, funding_rate,
            has_position, position_side, entry_price
        )
        
        return adjusted_signal
    
    # 替换方法
    signal_gen.generate_signal = new_generate_signal
    
    logger.info("[集成] 入场评估机制已集成到信号生成器")
    
    return integrator


if __name__ == '__main__':
    print("信号集成模块加载成功")
    print("使用方式: integrate_entry_check(signal_gen, entry_checker)")
