#!/usr/bin/env python3
"""
ML市场环境检测器 - 模块化设计
================================
职责：基于ML模型输出判断市场环境
耦合度：低（仅依赖配置，不依赖主程序）

Author: AI Assistant
Version: 1.0.0
"""

from enum import Enum, auto
from typing import Dict, Tuple, Optional, List
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


class MLRegimeType(Enum):
    """ML判断的市场环境类型"""
    STRONG_UP = auto()      # 强趋势上涨
    STRONG_DOWN = auto()    # 强趋势下跌
    WEAK_UP = auto()        # 弱趋势上涨
    WEAK_DOWN = auto()      # 弱趋势下跌
    SIDEWAYS = auto()       # 震荡市
    REVERSAL_TOP = auto()   # 顶部反转
    REVERSAL_BOTTOM = auto() # 底部反转
    UNCERTAIN = auto()      # 不确定


@dataclass
class MLRegimeResult:
    """ML环境判断结果"""
    regime: MLRegimeType
    confidence: float           # 判断置信度 0-1
    trend_strength: float       # 趋势强度 0-1
    recommended_action: str     # 建议操作: LONG/SHORT/HOLD
    position_size_mult: float   # 仓位倍数建议
    urgency: str               # 紧急程度: HIGH/MEDIUM/LOW
    reason: str                # 判断理由


@dataclass
class MLInput:
    """ML模型输入数据"""
    direction: int             # 1=多, -1=空, 0=观望
    confidence: float          # ML置信度
    proba_long: float          # 做多概率
    proba_short: float         # 做空概率
    
    # 可选：历史上下文
    history: List[Dict] = None  # 最近N次预测历史


class MLRegimeDetector:
    """
    ML市场环境检测器
    
    使用方法：
        detector = MLRegimeDetector(config)
        result = detector.detect(ml_input)
    """
    
    def __init__(self, config: Optional[Dict] = None):
        """
        初始化检测器
        
        Args:
            config: 配置字典，可选
        """
        self.config = config or self._default_config()
        self.history_buffer = []
        self.max_history = self.config.get('ML_REGIME_HISTORY_SIZE', 10)
        
        logger.info("[MLRegimeDetector] 初始化完成")
    
    def _default_config(self) -> Dict:
        """默认配置"""
        return {
            # 强趋势阈值（与config.py保持一致）
            'ML_STRONG_TREND_CONFIDENCE': 0.75,
            'ML_STRONG_TREND_PROBA': 0.70,
            
            # 震荡市阈值
            'ML_SIDEWAYS_MAX_CONFIDENCE': 0.60,
            'sideways_proba_diff_max': 0.20,
            
            # 趋势延续判断
            'trend_continuity_min_count': 3,
            'ML_TREND_CONTINUITY_CONF': 0.65,
            
            # 反转预警
            'ML_REVERSAL_CONFIDENCE': 0.65,
            'reversal_proba_flip': 0.15,
            
            # 仓位调整
            'ML_POS_STRONG': 1.2,
            'position_size_normal': 1.0,
            'ML_POS_WEAK': 0.7,
            'ML_POS_REVERSAL': 0.5,
            
            # 历史记录
            'ML_REGIME_HISTORY_SIZE': 10,
        }
    
    def detect(self, ml_input: MLInput) -> MLRegimeResult:
        """
        检测市场环境
        
        Args:
            ml_input: ML模型输出数据
            
        Returns:
            MLRegimeResult: 环境判断结果
        """
        # 更新历史
        self._update_history(ml_input)
        
        # 执行检测规则（按优先级）
        checks = [
            self._check_strong_trend,
            self._check_reversal,
            self._check_trend_continuity,
            self._check_sideways,
            self._check_weak_trend,
        ]
        
        for check_func in checks:
            result = check_func(ml_input)
            if result:
                logger.debug(f"[MLRegimeDetector] {check_func.__name__} 命中: {result.regime}")
                return result
        
        # 默认不确定
        return MLRegimeResult(
            regime=MLRegimeType.UNCERTAIN,
            confidence=0.5,
            trend_strength=0.0,
            recommended_action='HOLD',
            position_size_mult=0.5,
            urgency='LOW',
            reason='ML信号不明确'
        )
    
    def _update_history(self, ml_input: MLInput):
        """更新预测历史"""
        self.history_buffer.append({
            'direction': ml_input.direction,
            'confidence': ml_input.confidence,
            'proba_long': ml_input.proba_long,
            'proba_short': ml_input.proba_short,
        })
        
        if len(self.history_buffer) > self.max_history:
            self.history_buffer.pop(0)
    
    def _check_strong_trend(self, ml_input: MLInput) -> Optional[MLRegimeResult]:
        """检查强趋势"""
        conf_threshold = self.config.get('ML_STRONG_TREND_CONFIDENCE', 0.75)
        proba_threshold = self.config.get('ML_STRONG_TREND_PROBA', 0.70)
        
        if ml_input.confidence < conf_threshold:
            return None
        
        if ml_input.direction == 1 and ml_input.proba_long > proba_threshold:
            return MLRegimeResult(
                regime=MLRegimeType.STRONG_UP,
                confidence=ml_input.confidence,
                trend_strength=ml_input.proba_long,
                recommended_action='LONG',
                position_size_mult=self.config.get('ML_POS_STRONG', 1.2),
                urgency='HIGH',
                reason=f'ML高置信度看多({ml_input.confidence:.2f})，趋势强劲'
            )
        
        if ml_input.direction == -1 and ml_input.proba_short > proba_threshold:
            return MLRegimeResult(
                regime=MLRegimeType.STRONG_DOWN,
                confidence=ml_input.confidence,
                trend_strength=ml_input.proba_short,
                recommended_action='SHORT',
                position_size_mult=self.config.get('ML_POS_STRONG', 1.2),
                urgency='HIGH',
                reason=f'ML高置信度看空({ml_input.confidence:.2f})，趋势强劲'
            )
        
        return None
    
    def _check_reversal(self, ml_input: MLInput) -> Optional[MLRegimeResult]:
        """检查反转信号"""
        if len(self.history_buffer) < 2:
            return None
        
        prev = self.history_buffer[-1]
        conf_threshold = self.config.get('ML_REVERSAL_CONFIDENCE', 0.65)
        
        # 顶背离：之前看多，现在看空
        if (prev['direction'] == 1 and ml_input.direction == -1 and
            ml_input.confidence > conf_threshold):
            return MLRegimeResult(
                regime=MLRegimeType.REVERSAL_TOP,
                confidence=ml_input.confidence,
                trend_strength=ml_input.proba_short,
                recommended_action='SHORT',
                position_size_mult=self.config.get('ML_POS_REVERSAL', 0.5),
                urgency='HIGH',
                reason='ML由多转空，顶部反转信号'
            )
        
        # 底背离：之前看空，现在看多
        if (prev['direction'] == -1 and ml_input.direction == 1 and
            ml_input.confidence > conf_threshold):
            return MLRegimeResult(
                regime=MLRegimeType.REVERSAL_BOTTOM,
                confidence=ml_input.confidence,
                trend_strength=ml_input.proba_long,
                recommended_action='LONG',
                position_size_mult=self.config.get('ML_POS_REVERSAL', 0.5),
                urgency='HIGH',
                reason='ML由空转多，底部反转信号'
            )
        
        return None
    
    def _check_trend_continuity(self, ml_input: MLInput) -> Optional[MLRegimeResult]:
        """检查趋势延续"""
        min_count = self.config.get('trend_continuity_min_count', 3)
        min_conf = self.config.get('ML_TREND_CONTINUITY_CONF', 0.65)
        
        if len(self.history_buffer) < min_count:
            return None
        
        recent = self.history_buffer[-min_count:]
        directions = [r['direction'] for r in recent]
        
        # 连续同方向
        if all(d == 1 for d in directions):
            avg_conf = sum(r['confidence'] for r in recent) / min_count
            if avg_conf > min_conf:
                return MLRegimeResult(
                    regime=MLRegimeType.STRONG_UP,
                    confidence=avg_conf,
                    trend_strength=recent[-1]['proba_long'],
                    recommended_action='LONG',
                    position_size_mult=self.config.get('position_size_normal', 1.0),
                    urgency='MEDIUM',
                    reason=f'ML连续{min_count}次看多，趋势延续'
                )
        
        if all(d == -1 for d in directions):
            avg_conf = sum(r['confidence'] for r in recent) / min_count
            if avg_conf > min_conf:
                return MLRegimeResult(
                    regime=MLRegimeType.STRONG_DOWN,
                    confidence=avg_conf,
                    trend_strength=recent[-1]['proba_short'],
                    recommended_action='SHORT',
                    position_size_mult=self.config.get('position_size_normal', 1.0),
                    urgency='MEDIUM',
                    reason=f'ML连续{min_count}次看空，趋势延续'
                )
        
        return None
    
    def _check_sideways(self, ml_input: MLInput) -> Optional[MLRegimeResult]:
        """检查震荡市"""
        max_conf = self.config.get('ML_SIDEWAYS_MAX_CONFIDENCE', 0.60)
        max_diff = self.config.get('sideways_proba_diff_max', 0.20)
        
        if ml_input.confidence > max_conf:
            return None
        
        proba_diff = abs(ml_input.proba_long - ml_input.proba_short)
        
        if proba_diff < max_diff:
            return MLRegimeResult(
                regime=MLRegimeType.SIDEWAYS,
                confidence=1 - ml_input.confidence,
                trend_strength=0.0,
                recommended_action='HOLD',
                position_size_mult=self.config.get('ML_POS_WEAK', 0.7),
                urgency='LOW',
                reason=f'ML置信度低({ml_input.confidence:.2f})，多空概率接近({proba_diff:.2f})，震荡市'
            )
        
        return None
    
    def _check_weak_trend(self, ml_input: MLInput) -> Optional[MLRegimeResult]:
        """检查弱趋势"""
        if ml_input.confidence < 0.6 or ml_input.confidence > 0.75:
            return None
        
        if ml_input.direction == 1:
            return MLRegimeResult(
                regime=MLRegimeType.WEAK_UP,
                confidence=ml_input.confidence,
                trend_strength=ml_input.proba_long,
                recommended_action='LONG',
                position_size_mult=self.config.get('ML_POS_WEAK', 0.7),
                urgency='LOW',
                reason=f'ML中等置信度看多({ml_input.confidence:.2f})，弱趋势'
            )
        
        if ml_input.direction == -1:
            return MLRegimeResult(
                regime=MLRegimeType.WEAK_DOWN,
                confidence=ml_input.confidence,
                trend_strength=ml_input.proba_short,
                recommended_action='SHORT',
                position_size_mult=self.config.get('ML_POS_WEAK', 0.7),
                urgency='LOW',
                reason=f'ML中等置信度看空({ml_input.confidence:.2f})，弱趋势'
            )
        
        return None
    
    def get_regime_mapping(self, ml_regime: MLRegimeType, 
                          technical_regime: str) -> Tuple[str, Dict]:
        """
        将ML环境映射到交易系统环境
        
        完整映射矩阵：
        - STRONG_UP/STRONG_DOWN: 强趋势，高置信度顺势交易
        - WEAK_UP/WEAK_DOWN: 弱趋势，降低仓位，技术优先
        - SIDEWAYS: 震荡市，均值回归策略
        - REVERSAL_TOP/BOTTOM: 反转预警，大幅降低仓位
        - UNCERTAIN: 不确定，禁止新开仓
        
        Args:
            ml_regime: ML判断的环境
            technical_regime: 技术指标判断的环境（中文或英文）
            
        Returns:
            (最终环境, 调整参数)
            调整参数包含: confidence_boost, position_mult, use_limit_order, override_regime
        """
        adjustments = {
            'confidence_boost': 0.0,
            'position_mult': 1.0,
            'use_limit_order': True,
            'override_regime': None,
            'block_new_position': False,  # 是否禁止新开仓
        }
        
        # ========== 辅助判断函数 ==========
        # 判断是否为震荡市
        def is_sideways_env(regime: str) -> bool:
            return ('震荡' in regime or 'SIDEWAYS' in regime or
                    regime in ['SIDEWAYS', 'SIDEWAYS_UP', 'SIDEWAYS_DOWN', '震荡市', '震荡上行', '震荡下行'])
        
        # 判断是否为趋势市
        def is_trending_env(regime: str) -> bool:
            return ('趋势' in regime or 'TRENDING' in regime or
                    regime in ['TRENDING_UP', 'TRENDING_DOWN', '趋势上涨', '趋势下跌'])
        
        # 判断是否为高风险环境
        def is_high_risk_env(regime: str) -> bool:
            risk_keywords = ['BREAKOUT', 'BREAKDOWN', 'PUMP', 'DUMP', 'HIGH_VOL', 'REVERSAL',
                           '突破', '插针', '爆拉', '砸盘', '高波动', '反转']
            return any(kw in regime for kw in risk_keywords)
        
        # 判断是否为低流动性环境
        def is_low_liquidity_env(regime: str) -> bool:
            return 'LOW_VOL' in regime or '低波动' in regime or '流动性' in regime
        
        # ========== 1. 强趋势处理 ==========
        if ml_regime in [MLRegimeType.STRONG_UP, MLRegimeType.STRONG_DOWN]:
            target_regime = 'TRENDING_UP' if ml_regime == MLRegimeType.STRONG_UP else 'TRENDING_DOWN'
            
            if is_sideways_env(technical_regime):
                # ML强趋势 + 技术震荡 = 趋势启动，覆盖为趋势
                adjustments['override_regime'] = target_regime
                adjustments['confidence_boost'] = 0.1
                adjustments['position_mult'] = 1.2  # 强趋势增加仓位
                adjustments['use_limit_order'] = False  # 趋势市用Taker确保成交
                return adjustments['override_regime'], adjustments
            
            elif is_trending_env(technical_regime):
                # ML强趋势 + 技术趋势 = 趋势确认
                # 检查同向还是反向
                same_direction = (
                    (ml_regime == MLRegimeType.STRONG_UP and 'UP' in technical_regime) or
                    (ml_regime == MLRegimeType.STRONG_UP and '上涨' in technical_regime) or
                    (ml_regime == MLRegimeType.STRONG_DOWN and 'DOWN' in technical_regime) or
                    (ml_regime == MLRegimeType.STRONG_DOWN and '下跌' in technical_regime)
                )
                if same_direction:
                    # 同向强化
                    adjustments['confidence_boost'] = 0.15
                    adjustments['position_mult'] = 1.3
                    adjustments['use_limit_order'] = False
                else:
                    # 反向冲突，降低仓位观望
                    adjustments['confidence_boost'] = -0.1
                    adjustments['position_mult'] = 0.6
                    adjustments['use_limit_order'] = True
                return technical_regime, adjustments
            
            elif is_high_risk_env(technical_regime):
                # ML强趋势 + 高风险环境 = 谨慎跟随
                adjustments['confidence_boost'] = 0.05
                adjustments['position_mult'] = 0.8  # 降低仓位防风险
                adjustments['use_limit_order'] = False
                return technical_regime, adjustments
            
            else:
                # 其他环境，适度偏向ML判断
                adjustments['confidence_boost'] = 0.08
                adjustments['position_mult'] = 1.1
                return technical_regime, adjustments
        
        # ========== 2. 弱趋势处理 ==========
        if ml_regime in [MLRegimeType.WEAK_UP, MLRegimeType.WEAK_DOWN]:
            # 弱趋势始终降低仓位，以技术判断为主
            adjustments['confidence_boost'] = -0.05
            adjustments['position_mult'] = 0.8
            adjustments['use_limit_order'] = True
            
            # 如果技术与ML方向相反，进一步降低仓位
            ml_bullish = ml_regime == MLRegimeType.WEAK_UP
            tech_bearish = 'DOWN' in technical_regime or '下跌' in technical_regime or '下行' in technical_regime
            tech_bullish = 'UP' in technical_regime or '上涨' in technical_regime or '上行' in technical_regime
            
            if (ml_bullish and tech_bearish) or (not ml_bullish and tech_bullish):
                adjustments['position_mult'] = 0.5  # 方向冲突，大幅减仓
                adjustments['confidence_boost'] = -0.1
            
            return technical_regime, adjustments
        
        # ========== 3. 震荡市处理 ==========
        if ml_regime == MLRegimeType.SIDEWAYS:
            if is_trending_env(technical_regime):
                # ML震荡 + 技术趋势 = 趋势可能结束，降低仓位
                adjustments['confidence_boost'] = -0.1
                adjustments['position_mult'] = 0.7
                adjustments['use_limit_order'] = True
                return technical_regime, adjustments
            
            elif is_sideways_env(technical_regime):
                # ML震荡 + 技术震荡 = 震荡确认，均值回归策略
                adjustments['confidence_boost'] = 0.05
                adjustments['position_mult'] = 1.0
                adjustments['use_limit_order'] = True
                return technical_regime, adjustments
            
            else:
                # 其他环境，保守处理
                adjustments['confidence_boost'] = 0.0
                adjustments['position_mult'] = 0.9
                adjustments['use_limit_order'] = True
                return technical_regime, adjustments
        
        # ========== 4. 反转预警处理 ==========
        if ml_regime in [MLRegimeType.REVERSAL_TOP, MLRegimeType.REVERSAL_BOTTOM]:
            # 反转预警大幅降低仓位，禁止新开仓或极小仓位
            adjustments['confidence_boost'] = -0.2
            adjustments['position_mult'] = 0.5
            adjustments['use_limit_order'] = False
            # 如果是趋势市，建议减仓观望
            if is_trending_env(technical_regime):
                adjustments['block_new_position'] = True  # 建议禁止新开仓
            return technical_regime, adjustments
        
        # ========== 5. 不确定状态处理 ==========
        if ml_regime == MLRegimeType.UNCERTAIN:
            # ML不确定时，严格依赖技术判断，禁止ML驱动的新开仓
            adjustments['confidence_boost'] = -0.15
            adjustments['position_mult'] = 0.6
            adjustments['use_limit_order'] = True
            adjustments['block_new_position'] = True  # 禁止新开仓
            return technical_regime, adjustments
        
        # ========== 默认处理 ==========
        return technical_regime, adjustments


# ========== 便捷使用函数 ==========

def detect_ml_regime(ml_direction: int, ml_confidence: float,
                     proba_long: float, proba_short: float,
                     config: Optional[Dict] = None) -> MLRegimeResult:
    """
    便捷函数：快速检测ML环境
    
    使用示例：
        result = detect_ml_regime(
            ml_direction=1,
            ml_confidence=0.82,
            proba_long=0.85,
            proba_short=0.15
        )
        print(result.regime)  # MLRegimeType.STRONG_UP
    """
    detector = MLRegimeDetector(config)
    ml_input = MLInput(
        direction=ml_direction,
        confidence=ml_confidence,
        proba_long=proba_long,
        proba_short=proba_short
    )
    return detector.detect(ml_input)


if __name__ == "__main__":
    # 测试
    logging.basicConfig(level=logging.INFO)
    
    test_cases = [
        # (direction, confidence, proba_long, proba_short, description)
        (1, 0.82, 0.85, 0.15, "强趋势上涨"),
        (-1, 0.78, 0.20, 0.80, "强趋势下跌"),
        (1, 0.55, 0.55, 0.45, "震荡市"),
        (1, 0.68, 0.70, 0.30, "弱趋势上涨"),
    ]
    
    detector = MLRegimeDetector()
    
    print("=" * 70)
    print("MLRegimeDetector 测试")
    print("=" * 70)
    
    for direction, conf, pl, ps, desc in test_cases:
        ml_input = MLInput(direction=direction, confidence=conf, 
                          proba_long=pl, proba_short=ps)
        result = detector.detect(ml_input)
        
        print(f"\n{desc}:")
        print(f"  ML输出: 方向={direction}, 置信度={conf}")
        print(f"  检测结果: {result.regime.name}")
        print(f"  建议操作: {result.recommended_action}")
        print(f"  仓位倍数: {result.position_size_mult}")
        print(f"  紧急程度: {result.urgency}")
