#!/usr/bin/env python3
"""
EVT极值理论止盈模块 - 专业版（带完整留痕）
与V12系统深度融合，记录每个止盈决策的详细信息
"""

import numpy as np
import pandas as pd
from scipy import stats
from typing import Tuple, Optional, Dict, List
from dataclasses import dataclass, field
from enum import Enum, auto
from datetime import datetime
import logging
import json

logger = logging.getLogger(__name__)


class TPSignalSource(Enum):
    """止盈信号来源 - 用于留痕"""
    DYNAMIC_STOP_LOSS = "动态止损"           # ATR止损
    PROFIT_PROTECTION = "盈利保护"           # 回撤50%
    TRAILING_STOP = "移动止盈"               # 回撤30%
    EVT_EXTREME = "EVT极值止盈"              # 新增EVT
    ATR_FIXED = "ATR固定止盈"                # 4倍/8倍ATR
    ML_REVERSAL = "ML反转信号"               # ML判断
    FUNDING_EXTREME = "资金费率极端"         # 费率高/低
    MANUAL_CLOSE = "手动平仓"                # 人工干预
    UNKNOWN = "未知"


@dataclass
class TPTakeProfitRecord:
    """止盈记录 - 完整留痕"""
    timestamp: datetime
    position_id: str
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    pnl_pct: float
    pnl_usdt: float
    
    # 关键：记录哪个止盈策略生效
    tp_source: TPSignalSource
    tp_source_detail: str  # 详细说明
    
    # EVT专用信息（如果适用）
    evt_shape: Optional[float] = None
    evt_scale: Optional[float] = None
    evt_threshold: Optional[float] = None
    evt_confidence: Optional[float] = None
    evt_expected_return: Optional[float] = None
    
    # ATR信息
    atr_value: Optional[float] = None
    atr_multiplier: Optional[float] = None
    
    # ML信息
    ml_confidence: Optional[float] = None
    ml_direction: Optional[int] = None
    
    # 资金费率
    funding_rate: Optional[float] = None
    
    # 市场环境
    market_regime: Optional[str] = None
    
    # 其他信息
    additional_info: Dict = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        """转为字典，用于数据库存储"""
        return {
            'timestamp': self.timestamp.isoformat(),
            'position_id': self.position_id,
            'symbol': self.symbol,
            'side': self.side,
            'entry_price': self.entry_price,
            'exit_price': self.exit_price,
            'pnl_pct': self.pnl_pct,
            'pnl_usdt': self.pnl_usdt,
            'tp_source': self.tp_source.value,
            'tp_source_detail': self.tp_source_detail,
            'evt_params': {
                'shape': self.evt_shape,
                'scale': self.evt_scale,
                'threshold': self.evt_threshold,
                'confidence': self.evt_confidence,
                'expected_return': self.evt_expected_return
            } if self.evt_shape else None,
            'atr_params': {
                'value': self.atr_value,
                'multiplier': self.atr_multiplier
            } if self.atr_value else None,
            'ml_params': {
                'confidence': self.ml_confidence,
                'direction': self.ml_direction
            } if self.ml_confidence else None,
            'funding_rate': self.funding_rate,
            'market_regime': self.market_regime,
            'additional_info': self.additional_info
        }
    
    def to_log_string(self) -> str:
        """转为日志字符串"""
        base = (
            f"[止盈记录] {self.timestamp.strftime('%H:%M:%S')} | "
            f"{self.symbol} {self.side} | "
            f"PnL:{self.pnl_pct*100:+.2f}% | "
            f"来源:{self.tp_source.value}"
        )
        
        if self.tp_source == TPSignalSource.EVT_EXTREME:
            base += f" | EVT(ξ={self.evt_shape:.3f}, 预期{self.evt_expected_return*100:.2f}%)"
        elif self.tp_source == TPSignalSource.ATR_FIXED:
            base += f" | ATR({self.atr_multiplier:.1f}x)"
        elif self.tp_source == TPSignalSource.ML_REVERSAL:
            base += f" | ML(置信度{self.ml_confidence:.2f})"
        
        return base


class EVTTakeProfitEngine:
    """
    EVT止盈引擎 - 基于GPD(广义帕累托分布)的极值止盈
    
    核心特性：
    1. POT(Peaks Over Threshold)方法，数据利用率高
    2. 滚动窗口自适应，跟随市场变化
    3. 多时间框架验证，减少假信号
    4. 完整留痕，每个决策可追溯
    """
    
    def __init__(
        self,
        window_size: int = 500,
        threshold_quantile: float = 0.90,
        update_interval: int = 50,
        safety_factor: float = 0.85,
        min_samples: int = 100
    ):
        self.window_size = window_size
        self.threshold_quantile = threshold_quantile
        self.update_interval = update_interval
        self.safety_factor = safety_factor
        self.min_samples = min_samples
        
        # 状态
        self._params = None
        self._last_update = 0
        self._history_records: List[TPTakeProfitRecord] = []
        
        # 统计
        self._evt_triggered_count = 0
        self._atr_triggered_count = 0
        
    def _fit_gpd(self, excesses: np.ndarray) -> Tuple[float, float, float]:
        """
        拟合广义帕累托分布(GPD)
        
        GPD分布函数：
        G(y) = 1 - (1 + ξy/β)^(-1/ξ)  当 ξ ≠ 0
        G(y) = 1 - exp(-y/β)           当 ξ = 0
        
        参数：
        - ξ (shape): 形状参数，决定尾部厚度
        - β (scale): 尺度参数
        - u (threshold): 阈值
        
        Returns: (shape, scale, threshold)
        """
        try:
            from scipy.stats import genpareto
            
            # 使用最大似然估计拟合
            shape, loc, scale = genpareto.fit(excesses, floc=0)  # 固定loc=0
            
            # 限制参数范围（防止过拟合）
            shape = max(-0.5, min(shape, 0.8))  # ξ ∈ [-0.5, 0.8]
            scale = max(0.0001, scale)  # β > 0
            
            return shape, scale, 0.0  # threshold已包含在excesses中
            
        except Exception as e:
            logger.warning(f"GPD拟合失败: {e}，使用默认参数")
            return 0.3, 0.001, 0.0  # ETH典型值
    
    def _calculate_var(self, returns: np.ndarray, confidence: float = 0.95) -> float:
        """计算风险价值(VaR)作为阈值"""
        return np.percentile(returns, (1 - confidence) * 100)
    
    def _calculate_expected_shortfall(self, returns: np.ndarray, confidence: float = 0.95) -> float:
        """计算期望损失(ES)"""
        var = self._calculate_var(returns, confidence)
        return np.mean(returns[returns <= var])
    
    def update_parameters(self, returns: pd.Series, force: bool = False) -> bool:
        """
        更新GPD参数
        
        Args:
            returns: 收益率序列
            force: 强制更新
        """
        current_time = len(returns)
        
        if not force and current_time - self._last_update < self.update_interval:
            return False
        
        if len(returns) < self.min_samples:
            return False
        
        try:
            recent_returns = returns.tail(self.window_size).values
            
            # 分别拟合正负收益
            pos_returns = recent_returns[recent_returns > 0]
            neg_returns = np.abs(recent_returns[recent_returns < 0])
            
            # 正收益GPD
            if len(pos_returns) >= 20:
                pos_threshold = np.percentile(pos_returns, self.threshold_quantile * 100)
                pos_excesses = pos_returns[pos_returns > pos_threshold] - pos_threshold
                
                if len(pos_excesses) >= 10:
                    pos_shape, pos_scale, _ = self._fit_gpd(pos_excesses)
                else:
                    pos_shape, pos_scale, pos_threshold = 0.3, 0.001, pos_threshold
            else:
                pos_shape, pos_scale, pos_threshold = 0.3, 0.001, 0.005
            
            # 负收益GPD
            if len(neg_returns) >= 20:
                neg_threshold = np.percentile(neg_returns, self.threshold_quantile * 100)
                neg_excesses = neg_returns[neg_returns > neg_threshold] - neg_threshold
                
                if len(neg_excesses) >= 10:
                    neg_shape, neg_scale, _ = self._fit_gpd(neg_excesses)
                else:
                    neg_shape, neg_scale, neg_threshold = 0.3, 0.001, neg_threshold
            else:
                neg_shape, neg_scale, neg_threshold = 0.3, 0.001, 0.005
            
            self._params = {
                'positive': {
                    'shape': pos_shape,
                    'scale': pos_scale,
                    'threshold': pos_threshold,
                    'sample_size': len(pos_excesses) if len(pos_returns) >= 20 else 0
                },
                'negative': {
                    'shape': neg_shape,
                    'scale': neg_scale,
                    'threshold': neg_threshold,
                    'sample_size': len(neg_excesses) if len(neg_returns) >= 20 else 0
                },
                'timestamp': current_time
            }
            
            self._last_update = current_time
            
            logger.info(
                f"EVT参数更新 | 正收益:ξ={pos_shape:.3f},u={pos_threshold*100:.3f}% | "
                f"负收益:ξ={neg_shape:.3f},u={neg_threshold*100:.3f}%"
            )
            
            return True
            
        except Exception as e:
            logger.error(f"EVT参数更新失败: {e}")
            return False
    
    def calculate_tp_level(
        self,
        side: str,
        confidence: float = 0.90,
        regime: str = "unknown"
    ) -> Tuple[float, Dict]:
        """
        计算止盈水平（以收益率形式）
        
        Returns:
            tp_return: 目标收益率
            info: 详细信息
        """
        if self._params is None:
            return 0.02, {'method': 'default', 'return': 0.02}  # 默认2%
        
        try:
            from scipy.stats import genpareto
            
            # 选择对应方向的参数
            if side == 'LONG':
                params = self._params['positive']
                target_cdf = confidence
            else:
                params = self._params['negative']
                target_cdf = confidence
            
            shape = params['shape']
            scale = params['scale']
            threshold = params['threshold']
            
            # GPD分位数计算
            # Q(p) = u + β/ξ * [(1-p)^(-ξ) - 1]  (ξ ≠ 0)
            if abs(shape) > 0.001:
                extreme_excess = scale / shape * ((1 - target_cdf) ** (-shape) - 1)
            else:
                extreme_excess = -scale * np.log(1 - target_cdf)
            
            # 极值 = 阈值 + 极值超额
            extreme_return = threshold + extreme_excess
            
            # 应用安全折扣
            adjusted_return = extreme_return * self.safety_factor
            
            # 根据市场环境调整
            regime_multiplier = 1.0
            if regime in ['TRENDING_UP', 'TRENDING_DOWN', 'BREAKOUT']:
                regime_multiplier = 1.3  # 趋势市放大止盈
            elif regime in ['SIDEWAYS', 'CONSOLIDATION']:
                regime_multiplier = 0.7  # 震荡市缩小止盈
            
            final_return = adjusted_return * regime_multiplier
            
            # 限制范围
            final_return = max(0.003, min(final_return, 0.05))  # 0.3% ~ 5%
            
            info = {
                'method': 'EVT_GPD',
                'shape': shape,
                'scale': scale,
                'threshold': threshold,
                'extreme_excess': extreme_excess,
                'raw_return': extreme_return,
                'adjusted_return': adjusted_return,
                'final_return': final_return,
                'safety_factor': self.safety_factor,
                'regime_multiplier': regime_multiplier,
                'confidence': confidence
            }
            
            return final_return, info
            
        except Exception as e:
            logger.warning(f"EVT计算失败: {e}")
            return 0.02, {'method': 'fallback', 'return': 0.02, 'error': str(e)}
    
    def record_take_profit(self, record: TPTakeProfitRecord):
        """记录止盈事件"""
        self._history_records.append(record)
        
        # 更新统计
        if record.tp_source == TPSignalSource.EVT_EXTREME:
            self._evt_triggered_count += 1
        elif record.tp_source == TPSignalSource.ATR_FIXED:
            self._atr_triggered_count += 1
        
        # 日志输出
        logger.info(record.to_log_string())
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        total = len(self._history_records)
        if total == 0:
            return {'total': 0}
        
        evt_wins = sum(1 for r in self._history_records 
                      if r.tp_source == TPSignalSource.EVT_EXTREME and r.pnl_pct > 0)
        atr_wins = sum(1 for r in self._history_records
                      if r.tp_source == TPSignalSource.ATR_FIXED and r.pnl_pct > 0)
        
        return {
            'total_records': total,
            'evt_triggered': self._evt_triggered_count,
            'atr_triggered': self._atr_triggered_count,
            'evt_win_rate': evt_wins / self._evt_triggered_count if self._evt_triggered_count > 0 else 0,
            'atr_win_rate': atr_wins / self._atr_triggered_count if self._atr_triggered_count > 0 else 0,
            'avg_pnl': np.mean([r.pnl_pct for r in self._history_records])
        }


# 单例实例
_evt_engine = None

def get_evt_engine() -> EVTTakeProfitEngine:
    """获取EVT引擎实例"""
    global _evt_engine
    if _evt_engine is None:
        _evt_engine = EVTTakeProfitEngine()
    return _evt_engine
