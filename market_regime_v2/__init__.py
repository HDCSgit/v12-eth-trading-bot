"""
Market Regime Detector V2 - XGBoost Based
基于XGBoost的市场环境检测模块 V2

使用方式:
    from market_regime_v2 import MarketRegimeDetectorV2
    
    detector = MarketRegimeDetectorV2(model_path='models/regime_xgb_v1.pkl')
    result = detector.predict(df)
    
    print(result.regime)        # 'TRENDING_UP'
    print(result.confidence)    # 0.85
    print(result.probabilities) # {'TRENDING_UP': 0.85, 'SIDEWAYS': 0.10, ...}
"""

from .detector import MarketRegimeDetectorV2, RegimeResultV2
from .trainer import MarketRegimeTrainer
from .features import RegimeFeatureExtractor

__version__ = '2.0.0'
__all__ = ['MarketRegimeDetectorV2', 'RegimeResultV2', 'MarketRegimeTrainer', 'RegimeFeatureExtractor']
