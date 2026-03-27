"""
V2 市场环境检测集成模块
提供与主程序的低耦合集成接口
"""
import logging
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

# V1 兼容导入
try:
    from config import CONFIG
except ImportError:
    CONFIG = {}

from .detector import MarketRegimeDetectorV2, RegimeResultV2, MarketRegimeV2

logger = logging.getLogger(__name__)


@dataclass
class RegimeDecision:
    """统一的环境决策输出（V1/V2兼容格式）"""
    regime: str                      # 环境类型名称
    confidence: float                # 置信度
    
    # 调整参数（与V1格式一致）
    adjustments: Dict[str, any]
    
    # 扩展信息
    is_v2: bool = False
    v2_result: Optional[RegimeResultV2] = None


class RegimeDetectorFactory:
    """
    市场环境检测器工厂
    
    根据配置自动创建V1或V2检测器
    """
    
    @staticmethod
    def create(config: Optional[Dict] = None):
        """
        创建市场环境检测器
        
        Args:
            config: 配置字典，默认使用config.py中的CONFIG
            
        Returns:
            V1或V2检测器实例
        """
        if config is None:
            config = CONFIG
        
        version = config.get("ML_REGIME_VERSION", "v1")
        enabled = config.get("ML_REGIME_ENABLED", False)
        
        if not enabled:
            logger.info("ML Regime detection disabled")
            return None
        
        if version == "v2":
            logger.info("Initializing V2 XGBoost Regime Detector...")
            return RegimeDetectorV2Wrapper(config)
        else:
            logger.info("Initializing V1 Rule-based Regime Detector...")
            return RegimeDetectorV1Wrapper(config)


class RegimeDetectorV2Wrapper:
    """
    V2检测器包装器
    
    提供与V1兼容的接口，便于主程序统一调用
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.detector = None
        self._init_detector()
    
    def _init_detector(self):
        """初始化V2检测器"""
        try:
            model_path = self.config.get("ML_REGIME_V2_MODEL_PATH", 
                                        "models/regime_xgb_v1.pkl")
            
            self.detector = MarketRegimeDetectorV2(
                config={
                    'CONFIDENCE_THRESHOLD': self.config.get(
                        'ML_REGIME_V2_CONFIDENCE_THRESHOLD', 0.65),
                    'ENABLE_UNCERTAINTY': self.config.get(
                        'ML_REGIME_V2_ENABLE_UNCERTAINTY', True),
                },
                model_path=model_path
            )
            
            if not self.detector.is_ready():
                logger.warning("V2 model not loaded, will use fallback logic")
            else:
                logger.info("V2 detector ready")
                
        except Exception as e:
            logger.error(f"Failed to init V2 detector: {e}")
            self.detector = None
    
    def detect(self, df, current_price: float = None) -> RegimeDecision:
        """
        检测市场环境
        
        Args:
            df: OHLCV DataFrame
            current_price: 当前价格（可选）
            
        Returns:
            RegimeDecision 统一格式的决策结果
        """
        if self.detector is None or not self.detector.is_ready():
            # 回退到简单逻辑
            return self._fallback_decision()
        
        try:
            # V2预测
            result = self.detector.predict(df)
            
            # 转换为V1兼容格式
            regime_name, adjustments = result.to_v1_format()
            
            # 根据置信度调整
            if result.confidence < 0.5:
                adjustments['confidence_boost'] = -0.2
                adjustments['position_mult'] = 0.5
            elif result.confidence > 0.8:
                adjustments['confidence_boost'] = 0.1
                adjustments['position_mult'] = 1.2
            
            return RegimeDecision(
                regime=regime_name,
                confidence=result.confidence,
                adjustments=adjustments,
                is_v2=True,
                v2_result=result
            )
            
        except Exception as e:
            logger.error(f"V2 detection error: {e}")
            return self._fallback_decision()
    
    def _fallback_decision(self) -> RegimeDecision:
        """回退决策"""
        return RegimeDecision(
            regime="SIDEWAYS",
            confidence=0.5,
            adjustments={
                'confidence_boost': 0,
                'position_mult': 1.0,
                'use_limit_order': True,
                'override_regime': None,
                'block_new_position': False,
            },
            is_v2=True
        )
    
    def get_regime_stability(self) -> float:
        """获取环境稳定性"""
        if self.detector:
            return self.detector.get_regime_stability()
        return 1.0
    
    def is_ready(self) -> bool:
        """检测器是否就绪"""
        return self.detector is not None and self.detector.is_ready()


class RegimeDetectorV1Wrapper:
    """
    V1检测器包装器（原有逻辑）
    
    保持与原有代码的兼容性
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.detector = None
        self._init_detector()
    
    def _init_detector(self):
        """初始化V1检测器"""
        try:
            from ml_regime_detector import MLRegimeDetector
            self.detector = MLRegimeDetector(self.config)
            logger.info("V1 detector ready")
        except Exception as e:
            logger.error(f"Failed to init V1 detector: {e}")
            self.detector = None
    
    def detect(self, df, current_price: float = None) -> RegimeDecision:
        """
        V1检测
        
        保持与原有ml_regime_detector接口一致
        """
        if self.detector is None:
            return self._fallback_decision()
        
        try:
            # V1使用ml_input格式
            from ml_regime_detector import MLInput
            
            # 这里需要主程序传入ML预测结果
            # 暂时返回回退
            return self._fallback_decision()
            
        except Exception as e:
            logger.error(f"V1 detection error: {e}")
            return self._fallback_decision()
    
    def _fallback_decision(self) -> RegimeDecision:
        """回退决策"""
        return RegimeDecision(
            regime="SIDEWAYS",
            confidence=0.5,
            adjustments={
                'confidence_boost': 0,
                'position_mult': 1.0,
                'use_limit_order': True,
                'override_regime': None,
                'block_new_position': False,
            },
            is_v2=False
        )
    
    def is_ready(self) -> bool:
        """检测器是否就绪"""
        return self.detector is not None


def get_regime_detector(config: Optional[Dict] = None):
    """
    获取市场环境检测器的便捷函数
    
    使用示例:
        detector = get_regime_detector()
        if detector:
            decision = detector.detect(df)
            print(f"当前环境: {decision.regime}")
            print(f"建议仓位倍数: {decision.adjustments['position_mult']}")
    """
    return RegimeDetectorFactory.create(config)


# 向后兼容
class MLRegimeDetectorAdapter:
    """
    适配器：使V2兼容旧版MLRegimeDetector接口
    
    用于无缝替换原有代码中的检测器
    """
    
    def __init__(self, config: Dict = None):
        self._detector = get_regime_detector(config)
    
    def detect(self, ml_input) -> 'MLRegimeResult':
        """
        兼容旧版detect接口
        
        注意：ml_input会被忽略，V2直接从价格数据检测
        """
        # 这里需要主程序传入df
        # 暂时返回模拟结果
        pass
