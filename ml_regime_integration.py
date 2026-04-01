#!/usr/bin/env python3
"""
ML模型参与市场环境判断

思路：
1. ML高置信度 + 明确方向 → 趋势市强化
2. ML低置信度 + 概率接近 → 震荡市确认
3. ML预测与技术指标背离 → 反转预警
4. ML连续预测同一方向 → 趋势延续
"""

from enum import Enum
from typing import Tuple, Optional
import numpy as np

class MLRegimeSignal(Enum):
    """ML环境判断信号"""
    STRONG_TREND_UP = "ML强趋势上涨"
    STRONG_TREND_DOWN = "ML强趋势下跌"
    WEAK_TREND = "ML弱趋势"
    SIDEWAYS = "ML判断震荡"
    REVERSAL_WARNING = "ML反转预警"
    CONFIRMATION = "ML确认当前趋势"
    UNKNOWN = "ML不确定"


class MLRegimeAnalyzer:
    """ML市场环境分析器"""
    
    def __init__(self, history_size: int = 10):
        self.ml_history = []  # 存储最近N次ML预测
        self.history_size = history_size
        
    def update_history(self, ml_direction: int, ml_confidence: float, 
                       proba_short: float, proba_long: float):
        """更新ML预测历史"""
        self.ml_history.append({
            'direction': ml_direction,
            'confidence': ml_confidence,
            'proba_short': proba_short,
            'proba_long': proba_long
        })
        
        # 保持历史长度
        if len(self.ml_history) > self.history_size:
            self.ml_history.pop(0)
    
    def analyze_regime(self, ml_direction: int, ml_confidence: float,
                       proba_short: float, proba_long: float,
                       current_regime: str = "UNKNOWN") -> Tuple[MLRegimeSignal, float]:
        """
        分析ML判断的市场环境
        
        Returns:
            (ML信号, 信号强度0-1)
        """
        # 更新历史
        self.update_history(ml_direction, ml_confidence, proba_short, proba_long)
        
        # ========== 1. 强趋势判断（高置信度+明确方向）==========
        if ml_confidence >= 0.75:
            if ml_direction == 1 and proba_long > 0.7:
                return MLRegimeSignal.STRONG_TREND_UP, ml_confidence
            elif ml_direction == -1 and proba_short > 0.7:
                return MLRegimeSignal.STRONG_TREND_DOWN, ml_confidence
        
        # ========== 2. 震荡市判断（低置信度+概率接近）==========
        if ml_confidence < 0.6:
            prob_diff = abs(proba_long - proba_short)
            if prob_diff < 0.2:  # 概率接近50/50
                return MLRegimeSignal.SIDEWAYS, 1 - ml_confidence
        
        # ========== 3. 趋势延续性判断（历史一致性）==========
        if len(self.ml_history) >= 3:
            recent_directions = [h['direction'] for h in self.ml_history[-3:]]
            if all(d == 1 for d in recent_directions):
                # 连续3次看多
                avg_conf = np.mean([h['confidence'] for h in self.ml_history[-3:]])
                return MLRegimeSignal.STRONG_TREND_UP, avg_conf
            elif all(d == -1 for d in recent_directions):
                # 连续3次看空
                avg_conf = np.mean([h['confidence'] for h in self.ml_history[-3:]])
                return MLRegimeSignal.STRONG_TREND_DOWN, avg_conf
        
        # ========== 4. 反转预警（ML方向与当前趋势背离）==========
        if current_regime == "趋势上涨" and ml_direction == -1 and ml_confidence > 0.65:
            return MLRegimeSignal.REVERSAL_WARNING, ml_confidence
        elif current_regime == "趋势下跌" and ml_direction == 1 and ml_confidence > 0.65:
            return MLRegimeSignal.REVERSAL_WARNING, ml_confidence
        
        # ========== 5. 弱趋势（中等置信度）==========
        if 0.6 <= ml_confidence < 0.75:
            return MLRegimeSignal.WEAK_TREND, ml_confidence
        
        return MLRegimeSignal.UNKNOWN, 0.5
    
    def get_regime_adjustment(self, ml_signal: MLRegimeSignal, 
                             current_regime: str) -> dict:
        """
        根据ML信号调整市场环境判断
        
        Returns:
            调整建议字典
        """
        adjustment = {
            'regime_override': None,  # 是否覆盖原环境判断
            'confidence_boost': 0.0,  # 置信度调整
            'position_size_mult': 1.0,  # 仓位倍数调整
            'strategy_hint': None,  # 策略建议
        }
        
        # ML强趋势 vs 原震荡 → 可能趋势刚开始
        if ml_signal in [MLRegimeSignal.STRONG_TREND_UP, MLRegimeSignal.STRONG_TREND_DOWN]:
            if "震荡" in current_regime:
                adjustment['regime_override'] = "趋势上涨" if ml_signal == MLRegimeSignal.STRONG_TREND_UP else "趋势下跌"
                adjustment['confidence_boost'] = 0.1
                adjustment['position_size_mult'] = 1.2
                adjustment['strategy_hint'] = "ML发现趋势启动，加大仓位"
        
        # ML震荡 vs 原趋势 → 可能趋势结束
        elif ml_signal == MLRegimeSignal.SIDEWAYS:
            if "趋势" in current_regime:
                adjustment['confidence_boost'] = -0.1
                adjustment['position_size_mult'] = 0.8
                adjustment['strategy_hint'] = "ML判断进入震荡，降低仓位"
        
        # ML反转预警
        elif ml_signal == MLRegimeSignal.REVERSAL_WARNING:
            adjustment['confidence_boost'] = -0.15
            adjustment['position_size_mult'] = 0.7
            adjustment['strategy_hint'] = "ML预警反转，谨慎交易"
        
        return adjustment


# ========== 集成到主程序 ==========

def integrate_ml_to_regime(signal, current_regime: str, ml_analyzer: MLRegimeAnalyzer) -> dict:
    """
    将ML判断整合到交易信号中
    
    Args:
        signal: TradingSignal对象
        current_regime: 当前市场环境
        ml_analyzer: ML环境分析器
    
    Returns:
        增强后的信号信息
    """
    # 获取ML环境判断
    ml_signal, ml_strength = ml_analyzer.analyze_regime(
        signal.ml_direction,
        signal.ml_confidence,
        signal.ml_proba_short,
        signal.ml_proba_long,
        current_regime
    )
    
    # 获取调整建议
    adjustment = ml_analyzer.get_regime_adjustment(ml_signal, current_regime)
    
    return {
        'ml_regime_signal': ml_signal,
        'ml_regime_strength': ml_strength,
        'adjustment': adjustment,
        'combined_confidence': min(1.0, signal.confidence + adjustment['confidence_boost']),
        'recommended_position_size': adjustment['position_size_mult'],
        'strategy_hint': adjustment['strategy_hint']
    }


# ========== 使用示例 ==========

if __name__ == "__main__":
    analyzer = MLRegimeAnalyzer(history_size=10)
    
    # 模拟连续预测
    predictions = [
        (1, 0.65, 0.35, 0.65),  # 看多，置信0.65
        (1, 0.72, 0.28, 0.72),  # 看多，置信0.72
        (1, 0.81, 0.19, 0.81),  # 看多，置信0.81（趋势增强）
    ]
    
    current_regime = "震荡市"
    
    for pred in predictions:
        direction, conf, ps, pl = pred
        signal, strength = analyzer.analyze_regime(direction, conf, ps, pl, current_regime)
        adj = analyzer.get_regime_adjustment(signal, current_regime)
        
        print(f"\nML预测: 方向={direction}, 置信度={conf}")
        print(f"ML环境判断: {signal.value}, 强度={strength:.2f}")
        print(f"调整建议: {adj['strategy_hint']}")
        print(f"建议仓位倍数: {adj['position_size_mult']}")
