#!/usr/bin/env python3
"""
统一止盈管理器 - 所有策略带完整留痕
整合：止损、保护、移动止盈、EVT、ATR、ML、资金费率
"""

import numpy as np
import pandas as pd
from typing import Tuple, Dict, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
import logging
import json

logger = logging.getLogger(__name__)


class TPSignalType(Enum):
    """止盈信号类型枚举"""
    # 止损类（必须最优先）
    STOP_LOSS_DYNAMIC = "动态止损_ATR"
    STOP_LOSS_FIXED = "固定止损"
    
    # 保护类
    PROFIT_PROTECTION = "盈利保护_回撤50"
    
    # 移动类
    TRAILING_STOP = "移动止盈_回撤30"
    
    # 目标类
    EVT_EXTREME = "EVT极值止盈"
    ATR_FIXED_SIDEWAYS = "ATR固定_震荡4倍"
    ATR_FIXED_TREND = "ATR固定_趋势8倍"
    
    # 智能类
    ML_REVERSAL = "ML趋势反转"
    
    # 成本类
    FUNDING_HIGH = "资金费率_过高"
    FUNDING_LOW = "资金费率_过低"
    
    # 其他
    MANUAL = "手动平仓"
    TIMEOUT = "超时平仓"
    UNKNOWN = "未知"


@dataclass
class TPSignalRecord:
    """
    止盈信号完整记录 - 用于后期分析评估
    """
    # ========== 必填字段（无默认值，必须放前面）==========
    # 基础信息
    timestamp: datetime
    position_id: str
    symbol: str
    side: str
    
    # 核心：信号来源
    signal_type: TPSignalType
    signal_description: str
    
    # 价格信息
    entry_price: float
    exit_price: float
    pnl_pct: float
    pnl_usdt: float
    
    # 触发时的市场状态
    market_regime: str
    current_price: float
    
    # ========== 可选字段（有默认值，放后面）==========
    # 杠杆（默认5倍）
    leverage: int = 5
    
    # 持仓周期数
    holding_periods: int = 0
    
    # 各策略参数（根据signal_type填充对应字段）
    # ========== 止损类参数 ==========
    sl_atr_value: Optional[float] = None
    sl_atr_multiplier: Optional[float] = None
    sl_distance_pct: Optional[float] = None
    
    # ========== 盈利保护参数 ==========
    pp_peak_pnl: Optional[float] = None
    pp_current_pnl: Optional[float] = None
    pp_drawback_pct: Optional[float] = None  # 通常50%
    
    # ========== 移动止盈参数 ==========
    ts_peak_pnl: Optional[float] = None
    ts_trailing_stop_level: Optional[float] = None
    ts_drawback_pct: Optional[float] = None  # 通常30%
    
    # ========== EVT参数 ==========
    evt_shape: Optional[float] = None
    evt_scale: Optional[float] = None
    evt_threshold: Optional[float] = None
    evt_confidence: Optional[float] = None
    evt_expected_return: Optional[float] = None
    evt_safety_factor: Optional[float] = None
    
    # ========== ATR固定参数 ==========
    atr_fixed_value: Optional[float] = None
    atr_fixed_multiplier: Optional[float] = None  # 4或8
    atr_target_pct: Optional[float] = None
    
    # ========== ML反转参数 ==========
    ml_confidence: Optional[float] = None
    ml_direction: Optional[int] = None
    ml_required_confidence: Optional[float] = None
    
    # ========== 资金费率参数 ==========
    funding_rate: Optional[float] = None
    funding_threshold: Optional[float] = None
    
    # 综合信息
    additional_info: Dict = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        """转为字典，便于数据库存储"""
        return {
            'timestamp': self.timestamp.isoformat(),
            'position_id': self.position_id,
            'symbol': self.symbol,
            'side': self.side,
            'entry_price': self.entry_price,
            'exit_price': self.exit_price,
            'pnl_pct': self.pnl_pct,
            'pnl_usdt': self.pnl_usdt,
            'leverage': self.leverage,
            'signal_type': self.signal_type.value,
            'signal_description': self.signal_description,
            'market_regime': self.market_regime,
            'current_price': self.current_price,
            'params': {
                'stop_loss': {
                    'atr_value': self.sl_atr_value,
                    'atr_multiplier': self.sl_atr_multiplier,
                    'distance_pct': self.sl_distance_pct
                },
                'profit_protection': {
                    'peak_pnl': self.pp_peak_pnl,
                    'current_pnl': self.pp_current_pnl,
                    'drawback_pct': self.pp_drawback_pct
                },
                'trailing_stop': {
                    'peak_pnl': self.ts_peak_pnl,
                    'trailing_level': self.ts_trailing_stop_level,
                    'drawback_pct': self.ts_drawback_pct
                },
                'evt': {
                    'shape': self.evt_shape,
                    'scale': self.evt_scale,
                    'threshold': self.evt_threshold,
                    'confidence': self.evt_confidence,
                    'expected_return': self.evt_expected_return,
                    'safety_factor': self.evt_safety_factor
                },
                'atr_fixed': {
                    'atr_value': self.atr_fixed_value,
                    'multiplier': self.atr_fixed_multiplier,
                    'target_pct': self.atr_target_pct
                },
                'ml_reversal': {
                    'confidence': self.ml_confidence,
                    'direction': self.ml_direction,
                    'required_confidence': self.ml_required_confidence
                },
                'funding': {
                    'rate': self.funding_rate,
                    'threshold': self.funding_threshold
                }
            },
            'holding_periods': self.holding_periods
        }
    
    def to_log_string(self) -> str:
        """转为日志字符串"""
        base = (
            f"[出场] {self.timestamp.strftime('%H:%M:%S')} | "
            f"{self.symbol} {self.side} | "
            f"PnL:{self.pnl_pct*100:+.2f}%(${self.pnl_usdt:+.2f}) | "
            f"来源:{self.signal_type.value} | "
            f"环境:{self.market_regime}"
        )
        
        # 根据类型添加详细信息
        if self.signal_type == TPSignalType.STOP_LOSS_DYNAMIC:
            base += f" | ATR:{self.sl_atr_multiplier:.1f}x"
        elif self.signal_type == TPSignalType.PROFIT_PROTECTION:
            base += f" | 峰值:{self.pp_peak_pnl*100:.2f}%→当前:{self.pp_current_pnl*100:.2f}%"
        elif self.signal_type == TPSignalType.TRAILING_STOP:
            base += f" | 回撤:{self.ts_drawback_pct*100:.0f}%"
        elif self.signal_type == TPSignalType.EVT_EXTREME:
            base += f" | EVT(ξ={self.evt_shape:.3f},目标{self.evt_expected_return*100:.2f}%)"
        elif self.signal_type == TPSignalType.ATR_FIXED_SIDEWAYS:
            base += f" | ATR震荡4x"
        elif self.signal_type == TPSignalType.ATR_FIXED_TREND:
            base += f" | ATR趋势8x"
        elif self.signal_type == TPSignalType.ML_REVERSAL:
            base += f" | ML({self.ml_confidence:.2f})"
        elif self.signal_type in [TPSignalType.FUNDING_HIGH, TPSignalType.FUNDING_LOW]:
            base += f" | 费率{self.funding_rate:.4%}"
        
        return base


class UnifiedTakeProfitManager:
    """
    统一止盈管理器
    
    整合所有止盈策略，按优先级检查，完整记录每个决策
    """
    
    def __init__(self):
        self.records: List[TPSignalRecord] = []
        self.stats = {
            'by_type': {},
            'by_regime': {},
            'total_pnl': 0,
            'total_count': 0
        }
        
        # 各策略统计
        self._type_stats = {t: {'count': 0, 'wins': 0, 'total_pnl': 0} for t in TPSignalType}
    
    def record_signal(self, record: TPSignalRecord):
        """记录止盈信号"""
        self.records.append(record)
        
        # 更新统计
        t = record.signal_type
        self._type_stats[t]['count'] += 1
        self._type_stats[t]['total_pnl'] += record.pnl_pct
        if record.pnl_pct > 0:
            self._type_stats[t]['wins'] += 1
        
        # 输出日志
        logger.info(record.to_log_string())
    
    def get_strategy_performance(self) -> pd.DataFrame:
        """
        获取各策略绩效对比（用于后期评估）
        """
        data = []
        for t in TPSignalType:
            stats = self._type_stats[t]
            if stats['count'] > 0:
                data.append({
                    '策略': t.value,
                    '触发次数': stats['count'],
                    '胜场': stats['wins'],
                    '胜率': f"{stats['wins']/stats['count']*100:.1f}%",
                    '总盈亏': f"{stats['total_pnl']*100:+.2f}%",
                    '平均盈亏': f"{stats['total_pnl']/stats['count']*100:+.2f}%"
                })
        
        return pd.DataFrame(data)
    
    def print_performance_report(self):
        """打印绩效报告"""
        print("\n" + "="*80)
        print("止盈策略绩效报告")
        print("="*80)
        
        df = self.get_strategy_performance()
        if not df.empty:
            print(df.to_string(index=False))
        else:
            print("暂无数据")
        
        print("="*80)
    
    def export_to_database(self, db_connection):
        """导出到数据库（用于长期分析）"""
        # 可以定期将记录导出到SQLite/PostgreSQL
        pass


# 全局实例
_tp_manager = None

def get_tp_manager() -> UnifiedTakeProfitManager:
    """获取统一止盈管理器"""
    global _tp_manager
    if _tp_manager is None:
        _tp_manager = UnifiedTakeProfitManager()
    return _tp_manager
