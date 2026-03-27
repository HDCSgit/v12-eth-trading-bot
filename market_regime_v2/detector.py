"""
市场环境检测器 V2 主接口
基于XGBoost的实时市场环境分类
"""
import pandas as pd
import numpy as np
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import logging

from .features import RegimeFeatureExtractor

logger = logging.getLogger(__name__)


class MarketRegimeV2(Enum):
    """市场环境枚举（优化版5分类）"""
    SIDEWAYS = "SIDEWAYS"           # 震荡市
    TREND_UP = "TREND_UP"           # 上涨趋势（强+弱合并）
    TREND_DOWN = "TREND_DOWN"       # 下跌趋势（强+弱合并）
    BREAKOUT = "BREAKOUT"           # 突破行情
    EXTREME = "EXTREME"             # 极端行情（PUMP+DUMP）
    UNKNOWN = "UNKNOWN"


@dataclass
class RegimeResultV2:
    """市场环境检测结果"""
    regime: MarketRegimeV2          # 主要环境类型
    confidence: float               # 置信度 (0-1)
    probabilities: Dict[str, float] # 所有类别的概率
    
    # V2特有：不确定性量化
    uncertainty: float              # 不确定性度量 (熵)
    top_2_gap: float               # Top2类别概率差
    
    # 特征重要性（可解释性）
    feature_importance: Optional[Dict[str, float]] = None
    
    # 建议
    recommended_action: str = "HOLD"
    position_size_mult: float = 1.0
    use_limit_order: bool = True
    
    def to_v1_format(self) -> Tuple[str, Dict]:
        """
        转换为V1格式，保持兼容性
        
        Returns:
            (regime_name, adjustments_dict)
        """
        regime_map = {
            MarketRegimeV2.TREND_UP: "TRENDING_UP",      # 映射到V1的枚举
            MarketRegimeV2.TREND_DOWN: "TRENDING_DOWN",
            MarketRegimeV2.SIDEWAYS: "SIDEWAYS",
            MarketRegimeV2.BREAKOUT: "BREAKOUT",
            MarketRegimeV2.EXTREME: "PUMP",               # 极端映射到PUMP（高风险）
        }
        
        regime_name = regime_map.get(self.regime, "SIDEWAYS")
        
        adjustments = {
            'confidence_boost': self.confidence - 0.5,
            'position_mult': self.position_size_mult,
            'use_limit_order': self.use_limit_order,
            'override_regime': regime_name if self.confidence > 0.7 else None,
            'block_new_position': self.uncertainty > 0.5,
        }
        
        return regime_name, adjustments


class MarketRegimeDetectorV2:
    """
    市场环境检测器 V2
    
    基于XGBoost的多分类模型，相比V1规则版本：
    1. 更高的准确性（数据驱动特征组合）
    2. 概率输出（不仅仅是硬分类）
    3. 不确定性量化（知道"不知道"）
    4. SHAP可解释性（为什么是这个判断）
    """
    
    def __init__(self, config: Optional[Dict] = None, model_path: Optional[str] = None):
        self.config = config or {}
        self.feature_extractor = RegimeFeatureExtractor()
        self.model = None
        self.label_decoder = None
        
        # 配置参数
        self.confidence_threshold = self.config.get('CONFIDENCE_THRESHOLD', 0.65)
        self.uncertainty_threshold = self.config.get('UNCERTAINTY_THRESHOLD', 0.5)
        self.enable_shap = self.config.get('ENABLE_SHAP', False)
        
        # 历史记录（用于趋势分析）
        self.history: list = []
        self.max_history = 100
        
        # 加载模型
        if model_path:
            self.load(model_path)
    
    def load(self, path: str) -> bool:
        """加载预训练模型"""
        try:
            import pickle
            with open(path, 'rb') as f:
                data = pickle.load(f)
            
            self.model = data['model']
            self.label_decoder = data.get('label_decoder', {})
            
            logger.info(f"V2 Model loaded from {path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load V2 model: {e}")
            return False
    
    def predict(self, df: pd.DataFrame) -> RegimeResultV2:
        """
        预测当前市场环境
        
        Args:
            df: 包含最近N个周期的OHLCV数据
            
        Returns:
            RegimeResultV2 检测结果
        """
        if self.model is None:
            logger.warning("V2 model not loaded, returning UNKNOWN")
            return self._make_unknown_result()
        
        # 提取特征
        features_df = self.feature_extractor.extract(df)
        
        if len(features_df) == 0:
            return self._make_unknown_result()
        
        # 取最后一行作为当前状态
        current_features = features_df.iloc[[-1]]
        
        # 预测概率
        proba = self.model.predict_proba(current_features)[0]
        
        # 构建结果
        result = self._build_result(proba, current_features)
        
        # 更新历史
        self._update_history(result)
        
        return result
    
    def predict_batch(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        批量预测（用于回测）
        
        Returns:
            DataFrame with regime predictions
        """
        if self.model is None:
            raise ValueError("Model not loaded")
        
        features_df = self.feature_extractor.extract(df)
        proba_matrix = self.model.predict_proba(features_df)
        
        # 解码标签
        predictions = []
        confidences = []
        
        for proba in proba_matrix:
            pred_idx = np.argmax(proba)
            pred_label = self.label_decoder.get(pred_idx, 'UNKNOWN')
            predictions.append(pred_label)
            confidences.append(proba[pred_idx])
        
        result_df = df.copy()
        result_df['regime_pred'] = pd.Series(predictions, index=features_df.index)
        result_df['regime_confidence'] = pd.Series(confidences, index=features_df.index)
        
        return result_df
    
    def _build_result(self, proba: np.ndarray, features: pd.DataFrame) -> RegimeResultV2:
        """构建检测结果"""
        # 获取Top1和Top2
        top_indices = np.argsort(proba)[-2:][::-1]
        top1_idx, top2_idx = top_indices[0], top_indices[1]
        
        top1_label = self.label_decoder.get(top1_idx, 'UNKNOWN')
        top1_proba = proba[top1_idx]
        top2_proba = proba[top2_idx]
        
        # 不确定性计算（熵）
        entropy = -np.sum(proba * np.log(proba + 1e-10))
        max_entropy = np.log(len(proba))
        normalized_entropy = entropy / max_entropy
        
        # 映射到枚举
        regime = self._label_to_enum(top1_label)
        
        # 生成建议
        action, pos_mult, use_limit = self._generate_recommendation(
            regime, top1_proba, normalized_entropy
        )
        
        # SHAP解释（可选）
        feature_importance = None
        if self.enable_shap and hasattr(self.model, 'feature_importances_'):
            feature_importance = dict(zip(
                self.feature_extractor.FEATURE_COLS,
                self.model.feature_importances_
            ))
        
        return RegimeResultV2(
            regime=regime,
            confidence=top1_proba,
            probabilities={
                self.label_decoder.get(i, f'class_{i}'): p 
                for i, p in enumerate(proba)
            },
            uncertainty=normalized_entropy,
            top_2_gap=top1_proba - top2_proba,
            feature_importance=feature_importance,
            recommended_action=action,
            position_size_mult=pos_mult,
            use_limit_order=use_limit,
        )
    
    def _label_to_enum(self, label: str) -> MarketRegimeV2:
        """字符串标签转枚举（优化版5分类）"""
        mapping = {
            'SIDEWAYS': MarketRegimeV2.SIDEWAYS,
            'TREND_UP': MarketRegimeV2.TREND_UP,
            'TREND_DOWN': MarketRegimeV2.TREND_DOWN,
            'BREAKOUT': MarketRegimeV2.BREAKOUT,
            'EXTREME': MarketRegimeV2.EXTREME,
        }
        return mapping.get(label, MarketRegimeV2.UNKNOWN)
    
    def _generate_recommendation(self, regime: MarketRegimeV2, 
                                  confidence: float,
                                  uncertainty: float) -> Tuple[str, float, bool]:
        """
        生成交易建议
        
        Returns:
            (action, position_mult, use_limit)
        """
        # 高不确定性 -> 观望
        if uncertainty > self.uncertainty_threshold:
            return "HOLD", 0.5, True
        
        # 低置信度 -> 观望
        if confidence < self.confidence_threshold:
            return "HOLD", 0.7, True
        
        # 根据环境类型生成建议（优化版5分类）
        regime_configs = {
            MarketRegimeV2.TREND_UP: ("LONG", 1.2, False),      # 趋势上涨：做多，1.2倍仓位
            MarketRegimeV2.TREND_DOWN: ("SHORT", 1.2, False),   # 趋势下跌：做空，1.2倍仓位
            MarketRegimeV2.SIDEWAYS: ("MEAN_REVERSION", 1.0, True),  # 震荡：均值回归，限价单
            MarketRegimeV2.BREAKOUT: ("MOMENTUM", 1.0, False),   # 突破：追势，市价单
            MarketRegimeV2.EXTREME: ("CAUTION", 0.6, False),     # 极端：减仓，谨慎
        }
        
        return regime_configs.get(regime, ("HOLD", 1.0, True))
    
    def _update_history(self, result: RegimeResultV2):
        """更新历史记录"""
        self.history.append({
            'timestamp': pd.Timestamp.now(),
            'regime': result.regime.value,
            'confidence': result.confidence,
            'uncertainty': result.uncertainty,
        })
        
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history:]
    
    def get_regime_stability(self, window: int = 10) -> float:
        """
        计算市场环境稳定性
        
        Returns:
            稳定性评分 (0-1)，越高表示环境越稳定
        """
        if len(self.history) < window:
            return 1.0
        
        recent = self.history[-window:]
        regimes = [h['regime'] for h in recent]
        
        # 计算环境转换次数
        changes = sum(1 for i in range(1, len(regimes)) if regimes[i] != regimes[i-1])
        
        return 1.0 - (changes / (window - 1))
    
    def _make_unknown_result(self) -> RegimeResultV2:
        """创建未知结果"""
        return RegimeResultV2(
            regime=MarketRegimeV2.UNKNOWN,
            confidence=0.0,
            probabilities={},
            uncertainty=1.0,
            top_2_gap=0.0,
        )
    
    def is_ready(self) -> bool:
        """检查模型是否就绪"""
        return self.model is not None
