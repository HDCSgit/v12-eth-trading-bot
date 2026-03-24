#!/usr/bin/env python3
"""
V12-LIVE-OPTIMIZED: 优化版实盘交易系统

核心优化：
1. ML信号融合 - 集成XGBoost机器学习预测
2. 动态ATR止盈止损 - 根据波动率自适应调整
3. 趋势/震荡双模式 - 自动识别市场环境
4. 智能仓位管理 - Kelly+ATR+置信度动态调整
5. 资金费率过滤 - 避免高资金费率时段开不利仓位
6. API重试机制 - 网络抖动自动重连
7. 信号质量追踪 - 持续优化模型表现

 author: AI Assistant
 version: 12.1.0
"""

import pandas as pd
import numpy as np
import logging
import time
import sqlite3
import json
import random
import math
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass, asdict
from enum import Enum
import warnings
warnings.filterwarnings('ignore')

from binance_api import BinanceExpertAPI
from config import CONFIG, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
import requests

# ==================== 配置日志 ====================
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler(f'logs/v12_live_opt_{datetime.now().strftime("%Y%m%d")}.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# 交易专用日志
trade_logger = logging.getLogger("trade")
trade_logger.setLevel(logging.INFO)
trade_handler = logging.FileHandler(f'logs/v12_trades_{datetime.now().strftime("%Y%m%d")}.log', encoding='utf-8')
trade_handler.setFormatter(logging.Formatter('%(asctime)s | %(message)s'))
trade_logger.addHandler(trade_handler)


# ==================== 枚举和配置 ====================
class MarketRegime(Enum):
    # 核心4种
    TRENDING_UP = "趋势上涨"      # 顺势做多
    TRENDING_DOWN = "趋势下跌"    # 顺势做空
    SIDEWAYS_UP = "震荡上行"      # 套利：高抛低吸
    SIDEWAYS_DOWN = "震荡下行"    # 套利：高抛低吸
    SIDEWAYS = "震荡市"           # 普通震荡
    # ETH合约特色市场环境
    BREAKOUT = "突破追势"         # 价格突破关键位，追涨杀跌
    BREAKDOWN = "插针暴跌"        # ETH典型插针行情，快速暴跌
    PUMP = "爆拉行情"             # ETH典型FOMO爆拉
    HIGH_VOL = "高波动无序"       # 高波动无明显方向，减少交易
    LOW_VOL = "低波动休整"        # 流动性枯竭，禁止交易
    REVERSAL = "趋势反转"         # 顶底背离，趋势可能反转
    CONSOLIDATION = "盘整待破"    # 横盘整理末期，等待突破
    UNKNOWN = "未知"


class SignalSource(Enum):
    ML = "机器学习"
    TECHNICAL = "技术指标"
    GRID = "网格策略"
    FUNDING = "资金费率"


@dataclass
class TradingSignal:
    """交易信号数据类"""
    action: str  # BUY, SELL, HOLD, CLOSE
    confidence: float
    source: SignalSource
    reason: str
    atr: float = 0.0
    sl_price: float = 0.0
    tp_price: float = 0.0
    regime: MarketRegime = MarketRegime.UNKNOWN
    funding_rate: float = 0.0
    features: Dict = None
    
    def to_dict(self) -> dict:
        return {
            'action': self.action,
            'confidence': self.confidence,
            'source': self.source.value,
            'reason': self.reason,
            'atr': self.atr,
            'sl_price': self.sl_price,
            'tp_price': self.tp_price,
            'regime': self.regime.value,
            'funding_rate': self.funding_rate
        }


# ==================== ML模型 ====================
try:
    import xgboost as xgb
    from sklearn.preprocessing import StandardScaler
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    logger.warning("XGBoost未安装，ML功能将使用备用方案")


class MLFeatureEngineer:
    """特征工程 - 生产级优化"""
    
    FEATURE_COLS = [
        'rsi_6', 'rsi_12', 'rsi_24',
        'macd_hist', 'bb_position', 'bb_width',
        'volume_ratio', 'momentum_5', 'momentum_10',
        'trend_short', 'atr_pct', 'price_position'
    ]
    
    def create_features(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        
        # 基础价格特征
        df['returns'] = df['close'].pct_change()
        df['log_returns'] = np.log(df['close'] / df['close'].shift(1))
        
        # RSI多周期
        for period in [6, 12, 24]:
            delta = df['close'].diff()
            gain = delta.clip(lower=0).rolling(window=period).mean()
            loss = (-delta.clip(upper=0)).rolling(window=period).mean()
            df[f'rsi_{period}'] = 100 - 100 / (1 + gain / (loss + 1e-10))
        
        # MACD
        ema12 = df['close'].ewm(span=12).mean()
        ema26 = df['close'].ewm(span=26).mean()
        df['macd'] = ema12 - ema26
        df['macd_signal'] = df['macd'].ewm(span=9).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']
        
        # 布林带
        df['bb_mid'] = df['close'].rolling(20).mean()
        df['bb_std'] = df['close'].rolling(20).std()
        df['bb_upper'] = df['bb_mid'] + 2 * df['bb_std']
        df['bb_lower'] = df['bb_mid'] - 2 * df['bb_std']
        df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_mid']
        df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'] + 1e-10)
        
        # 均线系统
        for period in [5, 10, 20, 55]:
            df[f'ma_{period}'] = df['close'].rolling(period).mean()
        df['trend_short'] = np.where(df['ma_10'] > df['ma_20'], 1, -1)
        df['trend_mid'] = np.where(df['ma_20'] > df['ma_55'], 1, -1)
        
        # 成交量
        df['volume_ma'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma']
        
        # 动量
        for period in [3, 5, 10]:
            df[f'momentum_{period}'] = df['close'].pct_change(period)
        
        # ATR (平均真实波幅)
        tr1 = df['high'] - df['low']
        tr2 = abs(df['high'] - df['close'].shift())
        tr3 = abs(df['low'] - df['close'].shift())
        df['atr'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).rolling(14).mean()
        df['atr_pct'] = df['atr'] / df['close']
        
        # 价格位置
        df['high_20'] = df['high'].rolling(20).max()
        df['low_20'] = df['low'].rolling(20).min()
        df['price_position'] = (df['close'] - df['low_20']) / (df['high_20'] - df['low_20'] + 1e-10)
        
        return df.dropna()


class V12MLModel:
    """V12机器学习模型 - 在线学习支持"""
    
    def __init__(self):
        self.model = None
        self.scaler = StandardScaler()
        self.is_trained = False
        self.feature_eng = MLFeatureEngineer()
        self.training_count = 0
        self.min_training_samples = CONFIG.get("ML_MIN_TRAINING_SAMPLES", 30)
        
    def train(self, df: pd.DataFrame) -> bool:
        """训练模型"""
        if not ML_AVAILABLE:
            return False
        
        # 数据量检查
        if len(df) < 300:
            logger.debug(f"数据量不足: {len(df)} < 300，跳过训练")
            return False
            
        try:
            df_feat = self.feature_eng.create_features(df)
            
            # 生成标签：未来3根K线收益 > 0.15%为1，< -0.15%为0，其他为-1(忽略)
            # 注：1分钟K线波动较小，使用更低阈值
            df_feat['future_return'] = df_feat['close'].shift(-3) / df_feat['close'] - 1
            df_feat['target'] = np.where(
                df_feat['future_return'] > 0.0015, 1,
                np.where(df_feat['future_return'] < -0.0015, 0, -1)
            )
            
            mask = df_feat['target'] != -1
            X = df_feat[self.feature_eng.FEATURE_COLS].loc[mask]
            y = df_feat['target'].loc[mask]
            
            if len(X) < self.min_training_samples:
                logger.warning(f"训练样本不足: {len(X)} < {self.min_training_samples}")
                return False
            
            X_scaled = self.scaler.fit_transform(X)
            
            self.model = xgb.XGBClassifier(
                n_estimators=CONFIG.get("ML_N_ESTIMATORS", 150),
                max_depth=CONFIG.get("ML_MAX_DEPTH", 4),
                learning_rate=CONFIG.get("ML_LEARNING_RATE", 0.08),
                subsample=CONFIG.get("ML_SUBSAMPLE", 0.8),
                colsample_bytree=CONFIG.get("ML_COLSAMPLE_BYTREE", 0.8),
                random_state=42,
                eval_metric='logloss'
            )
            self.model.fit(X_scaled, y)
            self.is_trained = True
            self.training_count += 1
            
            # 特征重要性
            importance = dict(zip(
                self.feature_eng.FEATURE_COLS,
                self.model.feature_importances_
            ))
            top_features = sorted(importance.items(), key=lambda x: x[1], reverse=True)[:3]
            logger.info(f"✅ ML模型训练完成 | 样本数: {len(X)} | 重要特征: {top_features}")
            
            return True
            
        except Exception as e:
            logger.error(f"ML训练失败: {e}")
            return False
    
    def predict(self, df: pd.DataFrame) -> Dict:
        """预测信号"""
        if not self.is_trained or not ML_AVAILABLE:
            return {'direction': 0, 'confidence': 0.5, 'proba': [0.5, 0.5]}
        
        try:
            df_feat = self.feature_eng.create_features(df)
            if len(df_feat) == 0:
                return {'direction': 0, 'confidence': 0.5, 'proba': [0.5, 0.5]}
            
            X = df_feat[self.feature_eng.FEATURE_COLS].iloc[-1:]
            
            # 检查并处理NaN
            if X.isnull().any().any():
                logger.warning("ML预测数据包含NaN，使用前向填充")
                X = X.fillna(method='ffill').fillna(0)
            
            X_scaled = self.scaler.transform(X)
            
            proba = self.model.predict_proba(X_scaled)[0]
            direction = 1 if proba[1] > proba[0] else -1
            confidence = max(proba)
            
            return {
                'direction': direction,
                'confidence': confidence,
                'proba': proba.tolist()
            }
        except Exception as e:
            logger.error(f"ML预测失败: {e}")
            return {'direction': 0, 'confidence': 0.5, 'proba': [0.5, 0.5]}


# ==================== 市场分析器 ====================
class MarketAnalyzer:
    """市场环境分析器 - 针对ETHUSDT合约优化"""
    
    def analyze_regime(self, df: pd.DataFrame) -> MarketRegime:
        """分析市场状态 - ETHUSDT合约特色识别"""
        if len(df) < 55:
            return MarketRegime.UNKNOWN
        
        current = df.iloc[-1]
        prev_3 = df.iloc[-3] if len(df) >= 3 else df.iloc[-1]
        prev_5 = df.iloc[-5] if len(df) >= 5 else df.iloc[-1]
        
        # ========== 基础指标 ==========
        adx = self._calculate_adx(df)
        adx_threshold = CONFIG.get("TECH_ADX_TREND_THRESHOLD", 25)
        adx_strong = 35  # 强趋势阈值
        
        bb_width = current.get('bb_width', 0.1)
        bb_threshold = CONFIG.get("TECH_BB_WIDTH_THRESHOLD", 0.05)
        bb_position = current.get('bb_position', 0.5)
        
        ma10 = current.get('ma_10', current['close'])
        ma20 = current.get('ma_20', current['close'])
        ma55 = current.get('ma_55', current['close'])
        
        ma_bullish = ma10 > ma20 > ma55
        ma_bearish = ma10 < ma20 < ma55
        
        # 价格变动（ETH波动大，用3根和5根K线）
        price_change_3 = (current['close'] - prev_3['close']) / prev_3['close']
        price_change_5 = (current['close'] - prev_5['close']) / prev_5['close']
        
        # 波动率
        atr_pct = current.get('atr_pct', 0.01)
        high_vol_threshold = 0.012  # ETH 1分钟1.2%算高波动
        low_vol_threshold = 0.002   # ETH 1分钟0.2%算低波动
        
        volume_ratio = current.get('volume_ratio', 1.0)
        rsi = current.get('rsi_12', 50)
        
        # 前高前低（20根K线=20分钟）
        high_20 = df['high'].tail(20).max()
        low_20 = df['low'].tail(20).min()
        
        # ========== 1. ETH插针/爆拉检测（优先，因为风险最高）==========
        
        # 插针暴跌：收紧条件（3分钟跌1.5%），减少假信号
        if (price_change_3 < -0.015 and 
            current['close'] < low_20 * 1.002 and 
            volume_ratio > 1.5):
            return MarketRegime.BREAKDOWN
        
        # 爆拉行情：3分钟内快速上涨 > 1.0% + 价格接近20分钟高点 + 放量
        # ETH常见爆拉：FOMO情绪快速拉升
        if (price_change_3 > 0.010 and 
            current['close'] > high_20 * 0.995 and 
            volume_ratio > 1.3):
            return MarketRegime.PUMP
        
        # ========== 2. 突破检测（次于插针）==========
        # 突破20分钟高点 + ADX强趋势 + 放量
        if (current['close'] > high_20 * 1.002 and 
            adx > adx_strong and 
            volume_ratio > 1.2 and
            ma_bullish):
            return MarketRegime.BREAKOUT
        
        # ========== 3. 高波动/低波动检测（无明显方向）==========
        # 高波动但无明显趋势（ADX低）- ETH常见震荡洗盘
        if atr_pct > high_vol_threshold and adx < adx_threshold:
            return MarketRegime.HIGH_VOL
        
        # 低波动 - 流动性枯竭，避免交易
        if atr_pct < low_vol_threshold and volume_ratio < 0.6 and bb_width < 0.015:
            return MarketRegime.LOW_VOL
        
        # ========== 4. 趋势反转检测 ==========
        # 顶背离：价格新高但RSI未新高 + 缩量
        price_high_new = current['close'] >= high_20 * 0.998
        rsi_not_high = rsi < 65
        volume_shrink = volume_ratio < 0.8
        
        if price_high_new and rsi_not_high and volume_shrink and ma_bullish:
            return MarketRegime.REVERSAL
        
        # 底背离：价格新低但RSI未新低 + 缩量
        price_low_new = current['close'] <= low_20 * 1.002
        rsi_not_low = rsi > 35
        
        if price_low_new and rsi_not_low and volume_shrink and ma_bearish:
            return MarketRegime.REVERSAL
        
        # ========== 5. 盘整检测（布林带收窄持续）==========
        bb_width_avg = df['bb_width'].tail(15).mean()
        if bb_width < bb_threshold * 0.8 and bb_width < bb_width_avg * 0.7:
            return MarketRegime.CONSOLIDATION
        
        # ========== 6. 标准趋势市检测 ==========
        if adx > adx_threshold:
            if ma_bullish:
                return MarketRegime.TRENDING_UP
            elif ma_bearish:
                return MarketRegime.TRENDING_DOWN
        
        # ========== 7. 震荡市细分 ==========
        if bb_width < bb_threshold:
            ma20_slope = (ma20 - df['ma_20'].iloc[-5]) / ma20 if len(df) >= 5 else 0
            if ma20_slope > 0.0002:
                return MarketRegime.SIDEWAYS_UP
            elif ma20_slope < -0.0002:
                return MarketRegime.SIDEWAYS_DOWN
            else:
                return MarketRegime.SIDEWAYS
        
        return MarketRegime.UNKNOWN
    
    def _calculate_adx(self, df: pd.DataFrame, period: int = 14) -> float:
        """计算ADX趋势强度"""
        try:
            high = df['high']
            low = df['low']
            close = df['close']
            
            plus_dm = high.diff()
            minus_dm = -low.diff()
            
            plus_dm[plus_dm < 0] = 0
            minus_dm[minus_dm < 0] = 0
            
            tr1 = high - low
            tr2 = abs(high - close.shift())
            tr3 = abs(low - close.shift())
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            
            atr = tr.rolling(period).mean()
            plus_di = 100 * plus_dm.rolling(period).mean() / atr
            minus_di = 100 * minus_dm.rolling(period).mean() / atr
            
            dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
            adx = dx.rolling(period).mean()
            
            return adx.iloc[-1] if not pd.isna(adx.iloc[-1]) else 0
        except:
            return 0


# ==================== 信号生成器 ====================
class SignalGenerator:
    """信号生成器 - 融合多策略（含市场辅助数据）"""
    
    def __init__(self):
        self.ml_model = V12MLModel()
        self.market_analyzer = MarketAnalyzer()
        self.last_training_time = None
        self.training_interval = timedelta(hours=CONFIG.get("ML_TRAINING_INTERVAL_HOURS", 4))
        
        # 持仓追踪（用于移动止盈）
        self.position_peak_pnl = 0.0  # 峰值盈亏
        self.position_trailing_stop = 0.0  # 移动止损线
        
        # 插针熔断机制
        self.spike_circuit_breaker_until = None  # 熔断结束时间
        self.last_prices = []  # 最近价格记录 [(timestamp, price), ...]
        
        # 市场辅助数据（非主导，仅参考）
        try:
            from binance_data_feed import BinanceMarketData
            self.market_data_feed = BinanceMarketData()
            logger.info("✅ 市场辅助数据模块加载成功（多空比、爆仓数据，仅供参考）")
        except ImportError:
            self.market_data_feed = None
            logger.warning("⚠️ 市场辅助数据模块未加载")
        
    def reset_position_tracking(self):
        """重置持仓追踪数据（新开仓时调用）"""
        self.position_peak_pnl = 0.0
        self.position_trailing_stop = 0.0
    
    def check_spike_circuit_breaker(self, current_price: float) -> Tuple[bool, str]:
        """插针熔断检测 - 价格剧烈波动保护
        
        Returns:
            (是否熔断, 原因)
        """
        now = datetime.now()
        window_seconds = CONFIG.get("SPIKE_DETECTION_WINDOW_SECONDS", 60)
        
        # 清理超过检测窗口的历史价格
        self.last_prices = [(t, p) for t, p in self.last_prices if (now - t).seconds < window_seconds]
        
        # 检查是否处于熔断期
        if self.spike_circuit_breaker_until and now < self.spike_circuit_breaker_until:
            remaining = (self.spike_circuit_breaker_until - now).seconds
            return True, f"插针熔断中({remaining}秒)"
        
        # 检查1分钟内价格波动
        if len(self.last_prices) >= 2:
            min_price = min(p for t, p in self.last_prices)
            max_price = max(p for t, p in self.last_prices)
            price_range = (max_price - min_price) / min_price
            
            spike_threshold = CONFIG.get("SPIKE_PRICE_CHANGE_THRESHOLD", 0.02)
            if price_range > spike_threshold:
                # 触发熔断
                breaker_minutes = CONFIG.get("SPIKE_CIRCUIT_BREAKER_MINUTES", 5)
                self.spike_circuit_breaker_until = now + timedelta(minutes=breaker_minutes)
                # 保留最近5条用于熔断结束后快速恢复
                self.last_prices = self.last_prices[-5:] if len(self.last_prices) >= 5 else []
                return True, f"检测到插针({price_range*100:.1f}%)，熔断{breaker_minutes}分钟"
        
        # 记录当前价格
        self.last_prices.append((now, current_price))
        
        return False, ""
        
    def generate_signal(
        self,
        df: pd.DataFrame,
        current_price: float,
        funding_rate: float = 0.0,
        has_position: bool = False,
        position_side: str = None,
        entry_price: float = 0.0
    ) -> TradingSignal:
        """生成交易信号"""
        
        # 确保ML模型已训练
        self._ensure_model_trained(df)
        
        # 特征工程
        df_feat = MLFeatureEngineer().create_features(df)
        if len(df_feat) == 0:
            return TradingSignal('HOLD', 0.5, SignalSource.TECHNICAL, '数据不足')
        
        current = df_feat.iloc[-1]
        default_atr_pct = 0.02  # 默认2% ATR
        atr = current.get('atr', current_price * default_atr_pct)
        regime = self.market_analyzer.analyze_regime(df_feat)
        
        # ========== 趋势确认机制（防止连续反向开仓）==========
        # 记录最近的环境判断
        if not hasattr(self, '_recent_regimes'):
            self._recent_regimes = []
        self._recent_regimes.append(regime)
        if len(self._recent_regimes) > 3:
            self._recent_regimes.pop(0)
        
        # 无持仓时需要趋势确认（放宽条件：3个周期中有2个一致即可）
        if not has_position and len(self._recent_regimes) >= 3:
            from collections import Counter
            regime_counts = Counter(self._recent_regimes)
            most_common_regime, count = regime_counts.most_common(1)[0]
            
            # 至少2个周期一致，且当前环境与多数一致
            if count < 2 or regime != most_common_regime:
                if regime not in [MarketRegime.SIDEWAYS, MarketRegime.SIDEWAYS_UP, MarketRegime.SIDEWAYS_DOWN]:
                    # 非震荡市且趋势不一致，观望
                    return TradingSignal(
                        'HOLD', 0.5, SignalSource.TECHNICAL,
                        f'趋势确认中（{count}/3一致）',
                        atr, regime=regime, funding_rate=funding_rate
                    )
        
        # 如果有持仓，检查止盈止损
        if has_position and position_side:
            return self._check_exit_signal(
                current_price, entry_price, position_side,
                atr, regime, funding_rate, df_feat
            )
        
        # 无持仓时检查插针熔断（防止插针时乱开仓）
        is_spike, spike_reason = self.check_spike_circuit_breaker(current_price)
        if is_spike:
            return TradingSignal(
                'HOLD', 0.5, SignalSource.TECHNICAL, 
                spike_reason, atr, regime=regime, funding_rate=funding_rate
            )
        
        # ML信号（可能未训练）
        ml_pred = self.ml_model.predict(df)
        ml_confidence = ml_pred['confidence']
        ml_direction = ml_pred['direction']
        ml_available = self.ml_model.is_trained
        
        # 技术指标信号
        tech_signal = self._technical_signal(df_feat, current)
        
        # ========== 时段过滤：凌晨2-5点降低交易频率 ==========
        current_hour = datetime.now().hour
        if 2 <= current_hour <= 5 and not has_position:
            # 凌晨时段提高置信度门槛
            if ml_confidence < 0.75:
                return TradingSignal(
                    'HOLD', ml_confidence, SignalSource.TECHNICAL,
                    f'凌晨{current_hour}点时段，提高门槛观望',
                    atr, regime=regime, funding_rate=funding_rate
                )
        
        # ========== ETHUSDT合约市场环境策略路由 ==========
        
        # 1. ETH插针/爆拉行情（优先处理，风险最高）
        if regime == MarketRegime.BREAKDOWN:
            return self._breakdown_strategy(
                df_feat, current, atr, ml_confidence, funding_rate,
                ml_available, ml_direction, current_price
            )
        
        if regime == MarketRegime.PUMP:
            return self._pump_strategy(
                df_feat, current, atr, ml_confidence, funding_rate,
                ml_available, ml_direction, current_price
            )
        
        # 2. 突破行情
        if regime == MarketRegime.BREAKOUT:
            return self._breakout_strategy(
                df_feat, current, atr, ml_confidence, funding_rate,
                ml_available, ml_direction, current_price
            )
        
        # 3. 高波动/低波动/反转/盘整
        if regime == MarketRegime.HIGH_VOL:
            return self._high_vol_strategy(
                df_feat, current, atr, ml_confidence, funding_rate,
                ml_available, ml_direction
            )
        
        if regime == MarketRegime.LOW_VOL:
            return self._low_vol_strategy(
                df_feat, current, atr, funding_rate
            )
        
        if regime == MarketRegime.REVERSAL:
            return self._reversal_strategy(
                df_feat, current, atr, ml_confidence, funding_rate,
                ml_available, ml_direction
            )
        
        if regime == MarketRegime.CONSOLIDATION:
            # 临时禁用：盘整策略表现差（0胜率），观望
            return TradingSignal(
                'HOLD', 0.5, SignalSource.TECHNICAL, 
                '盘整待破-策略优化中，暂停交易',
                atr, regime=MarketRegime.CONSOLIDATION, funding_rate=funding_rate
            )
        
        # 4. 震荡市细分策略
        if regime == MarketRegime.SIDEWAYS:
            return self._sideways_strategy(
                df_feat, current, atr, ml_confidence, funding_rate,
                ml_available, direction_bias='neutral'
            )
        
        if regime == MarketRegime.SIDEWAYS_UP:
            return self._sideways_strategy(
                df_feat, current, atr, ml_confidence, funding_rate,
                ml_available, direction_bias='long'
            )
        
        if regime == MarketRegime.SIDEWAYS_DOWN:
            return self._sideways_strategy(
                df_feat, current, atr, ml_confidence, funding_rate,
                ml_available, direction_bias='short'
            )
        
        # 5. 趋势市：ML为主，必须顺势（核心修复）
        ml_threshold = CONFIG.get("ML_CONFIDENCE_THRESHOLD", 0.56)
        if ml_available and ml_confidence >= ml_threshold:
            action = 'BUY' if ml_direction == 1 else 'SELL'
            
            # ========== 新增：趋势市顺势过滤（核心修复）==========
            is_counter_trend = (
                (regime == MarketRegime.TRENDING_UP and action == 'SELL') or
                (regime == MarketRegime.TRENDING_DOWN and action == 'BUY')
            )
            
            if is_counter_trend:
                # 逆势交易需要极高的置信度（抓回调/反弹）
                counter_trend_threshold = CONFIG.get("COUNTER_TREND_ML_THRESHOLD", 0.85)  # 从0.82提高到0.85
                if ml_confidence < counter_trend_threshold:
                    return TradingSignal(
                        'HOLD', ml_confidence, SignalSource.ML,
                        f'{regime.value}-ML逆势信号置信度不足({ml_confidence:.2f}<{counter_trend_threshold})，观望',
                        atr, regime=regime, funding_rate=funding_rate
                    )
                # 高置信度逆势信号，允许但标记为高风险
                logger.warning(f"⚠️ 允许高置信度逆势交易: {regime.value} + {action} (置信度:{ml_confidence:.2f})")
            
            # 顺势交易，正常执行
            is_with_trend = (
                (regime == MarketRegime.TRENDING_UP and action == 'BUY') or
                (regime == MarketRegime.TRENDING_DOWN and action == 'SELL')
            )
            
            # 资金费率过滤
            if self._funding_filter(action, funding_rate):
                return TradingSignal(
                    'HOLD', ml_confidence, SignalSource.FUNDING,
                    f'资金费率过滤(费率:{funding_rate:.4%})',
                    atr, regime=regime, funding_rate=funding_rate
                )
            
            sl_price, tp_price = self._calculate_sl_tp(
                action, current_price, atr, regime
            )
            
            # 构建信号描述（明确显示方向和趋势）
            direction_desc = '做多' if action == 'BUY' else '做空'
            trend_desc = "顺势" if is_with_trend else "逆势(高置信度)"
            signal_desc = f'ML{direction_desc}信号({regime.value},{trend_desc})'
            
            # 创建信号并应用市场辅助数据微调
            signal = TradingSignal(
                action, ml_confidence, SignalSource.ML,
                signal_desc,
                atr, sl_price, tp_price, regime, funding_rate,
                {'ml_proba': ml_pred.get('proba'), 'is_counter_trend': is_counter_trend}
            )
            
            # 应用市场辅助数据微调（非主导，仅轻微调整）
            market_context = self._get_market_context()
            return self._apply_market_context_adjustment(signal, market_context)
        
        # 技术信号作为主要/补充信号
        tech_threshold = CONFIG.get("CONFIDENCE_MULT_MID", 1.2)  # 使用类似阈值
        if tech_signal['action'] != 'HOLD' and tech_signal['confidence'] > 0.6:
            action = tech_signal['action']
            
            # 资金费率过滤
            if self._funding_filter(action, funding_rate):
                return TradingSignal(
                    'HOLD', tech_signal['confidence'], SignalSource.FUNDING,
                    f'资金费率过滤(费率:{funding_rate:.4%})',
                    atr, regime=regime, funding_rate=funding_rate
                )
            
            return TradingSignal(
                tech_signal['action'], tech_signal['confidence'], SignalSource.TECHNICAL,
                tech_signal['reason'], atr,
                *self._calculate_sl_tp(tech_signal['action'], current_price, atr, regime),
                regime, funding_rate
            )
        
        # ========== 获取市场辅助数据（非主导，仅参考）==========
        market_context = self._get_market_context()
        
        # 如果有辅助信息，可以微调信号（权重很低）
        if market_context and market_context.get('info'):
            # 只在日志中记录，不直接影响信号
            logger.debug(f"📊 市场辅助信息: {market_context['info']}")
        
        return TradingSignal(
            'HOLD', 0.5, SignalSource.TECHNICAL, '无明确信号',
            atr, regime=regime, funding_rate=funding_rate
        )
    
    def _get_market_context(self) -> Optional[Dict]:
        """
        获取市场辅助数据 - 轻量级参考，不主导决策
        
        这些数据仅用于：
        1. 日志记录，增加市场理解
        2. 极端情况下的轻微置信度调整（±5%以内）
        3. 风险提示，不作为交易信号
        """
        if not self.market_data_feed:
            return None
        
        try:
            return self.market_data_feed.get_market_sentiment("ETHUSDT")
        except Exception as e:
            logger.debug(f"获取市场辅助数据失败: {e}")
            return None
    
    def _apply_market_context_adjustment(self, signal: TradingSignal, market_context: Dict) -> TradingSignal:
        """
        应用市场辅助数据的微调 - 非常轻量，不主导
        
        调整规则（都很保守）：
        - 多空比极端时，降低对应方向的置信度最多5%
        - 爆仓数据极端时，增加反向置信度最多3%
        """
        if not market_context:
            return signal
        
        if signal.action == 'HOLD':
            return signal
        
        original_conf = signal.confidence
        adjustment = 0.0
        reason = signal.reason
        
        # 1. 多空比调整（权重0.05）
        ls_signal = market_context.get('long_short_signal', 'neutral')
        if ls_signal == 'extreme_long' and signal.action == 'BUY':
            adjustment -= 0.05  # 多头极端拥挤，降低做多置信度
            reason += "[多空比极端多头，-5%]"
        elif ls_signal == 'extreme_short' and signal.action == 'SELL':
            adjustment -= 0.05  # 空头极端拥挤，降低做空置信度
            reason += "[多空比极端空头，-5%]"
        
        # 2. 爆仓数据调整（权重0.03）
        liq_signal = market_context.get('liquidation_signal', 'neutral')
        if liq_signal == 'long_squeeze' and signal.action == 'SELL':
            adjustment -= 0.03  # 多头已爆仓很多，不再追空
            reason += "[多头爆仓多，-3%]"
        elif liq_signal == 'short_squeeze' and signal.action == 'BUY':
            adjustment -= 0.03  # 空头已爆仓很多，不再追多
            reason += "[空头爆仓多，-3%]"
        
        # 应用调整（限制范围）
        new_confidence = max(0.5, min(1.0, original_conf + adjustment))
        
        if abs(adjustment) > 0.01:
            logger.info(f"🎛️ 市场数据微调: {original_conf:.2f} -> {new_confidence:.2f} ({adjustment:+.0%})")
        
        return TradingSignal(
            signal.action, new_confidence, signal.source, reason,
            signal.atr, signal.sl_price, signal.tp_price,
            signal.regime, signal.funding_rate, signal.features
        )
    
    def _ensure_model_trained(self, df: pd.DataFrame):
        """确保模型已训练"""
        now = datetime.now()
        if (self.last_training_time is None or 
            now - self.last_training_time > self.training_interval):
            logger.info(f"🔄 尝试训练ML模型，当前数据量: {len(df)}")
            if self.ml_model.train(df):
                self.last_training_time = now
            else:
                logger.debug("ML模型训练跳过（数据不足或训练失败）")
    
    def _technical_signal(self, df: pd.DataFrame, current) -> Dict:
        """纯技术指标信号"""
        rsi = current.get('rsi_12', 50)
        macd_hist = current.get('macd_hist', 0)
        bb_position = current.get('bb_position', 0.5)
        
        rsi_oversold = CONFIG.get("TECH_RSI_OVERSOLD", 30)
        if rsi < rsi_oversold and macd_hist > 0:
            return {'action': 'BUY', 'confidence': 0.65, 'reason': 'RSI超卖+MACD转正'}
        
        rsi_overbought = CONFIG.get("TECH_RSI_OVERBOUGHT", 70)
        if rsi > rsi_overbought and macd_hist < 0:
            return {'action': 'SELL', 'confidence': 0.65, 'reason': 'RSI超买+MACD转负'}
        
        # 布林带极端位置
        bb_lower_threshold = CONFIG.get("TECH_BB_WIDTH_THRESHOLD", 0.05)
        if bb_position < bb_lower_threshold:
            return {'action': 'BUY', 'confidence': 0.6, 'reason': '布林带下轨'}
        bb_upper_threshold = 1 - CONFIG.get("TECH_BB_WIDTH_THRESHOLD", 0.05)
        if bb_position > bb_upper_threshold:
            return {'action': 'SELL', 'confidence': 0.6, 'reason': '布林带上轨'}
        
        return {'action': 'HOLD', 'confidence': 0.5, 'reason': ''}
    
    def _sideways_strategy(
        self, df: pd.DataFrame, current, atr: float,
        ml_confidence: float, funding_rate: float,
        ml_available: bool = False, direction_bias: str = 'neutral'
    ) -> TradingSignal:
        """震荡市套利策略 - 核心策略（简化版）
        
        Args:
            direction_bias: 'neutral'普通震荡, 'long'震荡上行(做多为主), 'short'震荡下行(做空为主)
        """
        close = current['close']
        bb_upper = current.get('bb_upper', close * 1.02)
        bb_lower = current.get('bb_lower', close * 0.98)
        bb_mid = current.get('bb_mid', close)
        rsi = current.get('rsi_12', 50)
        rsi_6 = current.get('rsi_6', 50)
        volume_ratio = current.get('volume_ratio', 1.0)
        
        funding_threshold = CONFIG.get("FUNDING_RATE_THRESHOLD", 0.001)
        min_confidence = CONFIG.get("SIDEWAYS_MIN_CONFIDENCE", 0.65)
        
        # 根据方向偏好调整参数
        if direction_bias == 'long':
            # 震荡上行：放宽做多条件，收紧做空条件
            long_rsi_threshold = 45  # 放宽
            short_rsi_threshold = 65  # 收紧
            long_conf_mult = 0.9
            short_conf_mult = 1.1
            regime_label = "震荡上行"
        elif direction_bias == 'short':
            # 震荡下行：放宽做空条件，收紧做多条件
            long_rsi_threshold = 35  # 收紧
            short_rsi_threshold = 55  # 放宽
            long_conf_mult = 1.1
            short_conf_mult = 0.9
            regime_label = "震荡下行"
        else:
            # 普通震荡
            long_rsi_threshold = 40
            short_rsi_threshold = 60
            long_conf_mult = 1.0
            short_conf_mult = 1.0
            regime_label = "震荡市"
        
        # 靠近下轨做多
        if (close < bb_lower * 1.01 and 
            rsi < long_rsi_threshold and 
            (rsi_6 < 30 or volume_ratio > 1.2)):
            
            if funding_rate < funding_threshold:
                conf = max(min_confidence * long_conf_mult, ml_confidence if ml_available else 0)
                sl_price = close - atr * 1.5
                tp_price = bb_mid
                
                return TradingSignal(
                    'BUY', conf, SignalSource.GRID,
                    f'{regime_label}-下轨做多(RSI:{rsi:.0f})',
                    atr, sl_price, tp_price,
                    MarketRegime.SIDEWAYS_UP if direction_bias == 'long' else MarketRegime.SIDEWAYS,
                    funding_rate
                )
        
        # 靠近上轨做空
        if (close > bb_upper * 0.99 and 
            rsi > short_rsi_threshold and 
            (rsi_6 > 70 or volume_ratio > 1.2)):
            
            if funding_rate > -funding_threshold:
                conf = max(min_confidence * short_conf_mult, ml_confidence if ml_available else 0)
                sl_price = close + atr * 1.5
                tp_price = bb_mid
                
                return TradingSignal(
                    'SELL', conf, SignalSource.GRID,
                    f'{regime_label}-上轨做空(RSI:{rsi:.0f})',
                    atr, sl_price, tp_price,
                    MarketRegime.SIDEWAYS_DOWN if direction_bias == 'short' else MarketRegime.SIDEWAYS,
                    funding_rate
                )
        
        return TradingSignal(
            'HOLD', 0.5, SignalSource.TECHNICAL, f'{regime_label}-观望',
            atr, regime=MarketRegime.SIDEWAYS, funding_rate=funding_rate
        )
    
    def _breakout_strategy(
        self, df: pd.DataFrame, current, atr: float,
        ml_confidence: float, funding_rate: float,
        ml_available: bool = False, ml_direction: int = 0,
        current_price: float = 0
    ) -> TradingSignal:
        """ETH突破市策略 - 追涨杀跌（针对ETH高波动优化）"""
        close = current_price if current_price > 0 else current['close']
        volume_ratio = current.get('volume_ratio', 1.0)
        rsi = current.get('rsi_12', 50)
        
        # ETH突破必须放量确认（防止假突破）
        min_volume = CONFIG.get("BREAKOUT_MIN_VOLUME", 1.3)
        if volume_ratio < min_volume:
            return TradingSignal(
                'HOLD', 0.5, SignalSource.TECHNICAL, 
                f'突破-成交量不足({volume_ratio:.1f}<{min_volume})',
                atr, regime=MarketRegime.BREAKOUT, funding_rate=funding_rate
            )
        
        # ETH突破策略：RSI不过高（<75）才追，防止追在短期山顶
        if ml_available and ml_direction == 1 and ml_confidence >= 0.68 and rsi < 75:
            # ETH波动大，止损要收紧，止盈要放大
            sl_price = close - atr * 1.2  # 更紧止损
            tp_price = close + atr * 12   # ETH趋势延续性强，放大止盈
            
            # 资金费率检查（做多时费率不能太高）
            if funding_rate > 0.001:
                return TradingSignal(
                    'HOLD', ml_confidence, SignalSource.FUNDING,
                    f'突破-资金费率过高({funding_rate:.4%})',
                    atr, regime=MarketRegime.BREAKOUT, funding_rate=funding_rate
                )
            
            return TradingSignal(
                'BUY', ml_confidence, SignalSource.ML,
                f'ETH突破追涨(量:{volume_ratio:.1f},RSI:{rsi:.0f})',
                atr, sl_price, tp_price,
                MarketRegime.BREAKOUT, funding_rate
            )
        
        # ETH偶尔也有向下突破（趋势反转）
        if ml_available and ml_direction == -1 and ml_confidence >= 0.70 and rsi > 30:
            sl_price = close + atr * 1.2
            tp_price = close - atr * 10
            
            if funding_rate < -0.001:
                return TradingSignal(
                    'HOLD', ml_confidence, SignalSource.FUNDING,
                    f'突破做空-资金费率过低({funding_rate:.4%})',
                    atr, regime=MarketRegime.BREAKOUT, funding_rate=funding_rate
                )
            
            return TradingSignal(
                'SELL', ml_confidence, SignalSource.ML,
                f'ETH突破追空(量:{volume_ratio:.1f},RSI:{rsi:.0f})',
                atr, sl_price, tp_price,
                MarketRegime.BREAKOUT, funding_rate
            )
        
        return TradingSignal(
            'HOLD', 0.5, SignalSource.TECHNICAL, '突破市-等待确认',
            atr, regime=MarketRegime.BREAKOUT, funding_rate=funding_rate
        )
    
    def _breakdown_strategy(
        self, df: pd.DataFrame, current, atr: float,
        ml_confidence: float, funding_rate: float,
        ml_available: bool = False, ml_direction: int = 0,
        current_price: float = 0
    ) -> TradingSignal:
        """ETH插针暴跌策略 - ETH典型插针行情（3分钟内急跌1%+）
        
        ETH插针特点：快速暴跌后往往快速反弹，适合抄底或观望
        合约风险：高杠杆下插针容易爆仓，必须严格止损
        """
        close = current_price if current_price > 0 else current['close']
        rsi = current.get('rsi_12', 50)
        rsi_6 = current.get('rsi_6', rsi)  # 短周期RSI更敏感
        volume_ratio = current.get('volume_ratio', 1.0)
        
        # ETH插针抄底策略（核心）
        # 条件：RSI极度超卖(<25) + 短周期RSI<20 + 放量（恐慌盘涌出）
        extreme_oversold = CONFIG.get("BREAKDOWN_RSI_THRESHOLD", 25)
        
        if rsi < extreme_oversold and rsi_6 < 20 and volume_ratio > 1.2:
            # ETH插针抄底机会 - 但风险极高，必须满足：
            # 1. ML确认反弹信号 或 2. 价格远离均线（超卖）
            price_vs_ma20 = (close - current.get('ma_20', close)) / close
            
            if ml_available and ml_direction == 1 and ml_confidence >= 0.72:
                # 轻仓试多，极紧止损（ETH插针可能继续下跌）
                sl_price = close - atr * 0.8  # 极紧止损！
                tp_price = close + atr * 4    # 抓反弹，不贪心
                
                return TradingSignal(
                    'BUY', ml_confidence * 0.85, SignalSource.TECHNICAL,
                    f'ETH插针抄底(RSI:{rsi:.0f},距MA20:{price_vs_ma20*100:.1f}%)',
                    atr, sl_price, tp_price,
                    MarketRegime.BREAKDOWN, funding_rate
                )
        
        # 插针后继续下跌（追空）- 较少见，但可能
        if ml_available and ml_direction == -1 and ml_confidence >= 0.75:
            # 确认是趋势下跌而非插针反弹
            if rsi > 30:  # 不是极度超卖
                sl_price = close + atr * 1.5
                tp_price = close - atr * 5
                
                return TradingSignal(
                    'SELL', ml_confidence, SignalSource.ML,
                    f'ETH插针后追空(RSI:{rsi:.0f})',
                    atr, sl_price, tp_price,
                    MarketRegime.BREAKDOWN, funding_rate
                )
        
        # 默认：ETH插针时观望（最安全）
        return TradingSignal(
            'HOLD', 0.5, SignalSource.TECHNICAL, 
            f'ETH插针-观望(RSI:{rsi:.0f})',
            atr, regime=MarketRegime.BREAKDOWN, funding_rate=funding_rate
        )
    
    def _pump_strategy(
        self, df: pd.DataFrame, current, atr: float,
        ml_confidence: float, funding_rate: float,
        ml_available: bool = False, ml_direction: int = 0,
        current_price: float = 0
    ) -> TradingSignal:
        """ETH爆拉策略 - FOMO快速上涨（3分钟内急涨1%+）
        
        ETH爆拉特点：FOMO情绪下快速拉升，但回调也快
        合约风险：追高容易被套，或开空被继续拉升爆仓
        """
        close = current_price if current_price > 0 else current['close']
        rsi = current.get('rsi_12', 50)
        rsi_6 = current.get('rsi_6', rsi)
        volume_ratio = current.get('volume_ratio', 1.0)
        
        # ETH爆拉回调做空策略（摸顶，高风险）
        # 条件：RSI极度超买(>80) + 短周期RSI>85 + 缩量（上涨乏力）
        extreme_overbought = CONFIG.get("PUMP_RSI_THRESHOLD", 80)
        
        if rsi > extreme_overbought and rsi_6 > 85 and volume_ratio < 0.9:
            # 上涨乏力信号，轻仓试空
            if ml_available and ml_direction == -1 and ml_confidence >= 0.75:
                sl_price = close + atr * 1.0  # 极紧止损，防止继续爆拉
                tp_price = close - atr * 3    # 抓回调，不贪心
                
                return TradingSignal(
                    'SELL', ml_confidence * 0.85, SignalSource.TECHNICAL,
                    f'ETH爆拉摸顶(RSI:{rsi:.0f},缩量)',
                    atr, sl_price, tp_price,
                    MarketRegime.PUMP, funding_rate
                )
        
        # 爆拉顺势追多（较少用，因为风险高）
        # 只在：ML高置信度 + RSI不太高(<75) + 放量确认
        if ml_available and ml_direction == 1 and ml_confidence >= 0.72:
            if rsi < 75 and volume_ratio > 1.2:
                sl_price = close - atr * 1.0  # 极紧止损
                tp_price = close + atr * 5
                
                # 检查资金费率（爆拉时做空的人多，费率可能负）
                if funding_rate < -0.0005:
                    return TradingSignal(
                        'BUY', ml_confidence * 0.9, SignalSource.ML,
                        f'ETH爆拉追多(费率优惠{funding_rate:.4%})',
                        atr, sl_price, tp_price,
                        MarketRegime.PUMP, funding_rate
                    )
        
        # 默认：ETH爆拉时观望（避免FOMO）
        return TradingSignal(
            'HOLD', 0.5, SignalSource.TECHNICAL, 
            f'ETH爆拉-观望(RSI:{rsi:.0f})',
            atr, regime=MarketRegime.PUMP, funding_rate=funding_rate
        )
    
    def _high_vol_strategy(
        self, df: pd.DataFrame, current, atr: float,
        ml_confidence: float, funding_rate: float,
        ml_available: bool = False, ml_direction: int = 0
    ) -> TradingSignal:
        """ETH高波动无序策略 - 高波动但无明显方向（ETH洗盘行情）
        
        ETH特点：经常出现大上下影线，多空双杀
        策略：极高置信度才交易，且收紧止盈止损
        """
        close = current['close']
        rsi = current.get('rsi_12', 50)
        bb_position = current.get('bb_position', 0.5)
        
        # 高波动市门槛极高（防止被洗盘）
        high_vol_threshold = CONFIG.get("HIGH_VOL_CONFIDENCE", 0.78)
        
        if not ml_available or ml_confidence < high_vol_threshold:
            return TradingSignal(
                'HOLD', 0.5, SignalSource.TECHNICAL, 
                f'ETH高波动洗盘-观望(需>{high_vol_threshold})',
                atr, regime=MarketRegime.HIGH_VOL, funding_rate=funding_rate
            )
        
        # 只在布林带极端位置交易（降低风险）
        action = 'BUY' if ml_direction == 1 else 'SELL'
        
        if action == 'BUY' and bb_position > 0.4:  # 不在上半部分做多
            return TradingSignal(
                'HOLD', ml_confidence, SignalSource.TECHNICAL,
                'ETH高波动-位置不适合做多',
                atr, regime=MarketRegime.HIGH_VOL, funding_rate=funding_rate
            )
        
        if action == 'SELL' and bb_position < 0.6:  # 不在下半部分做空
            return TradingSignal(
                'HOLD', ml_confidence, SignalSource.TECHNICAL,
                'ETH高波动-位置不适合做空',
                atr, regime=MarketRegime.HIGH_VOL, funding_rate=funding_rate
            )
        
        # 极紧止盈止损，快进快出
        sl_price = close - atr * 0.8 if action == 'BUY' else close + atr * 0.8
        tp_price = close + atr * 2.5 if action == 'BUY' else close - atr * 2.5
        
        return TradingSignal(
            action, ml_confidence * 0.85, SignalSource.ML,
            f'ETH高波动-{action}(减仓,极紧止损)',
            atr, sl_price, tp_price,
            MarketRegime.HIGH_VOL, funding_rate
        )
    
    def _low_vol_strategy(
        self, df: pd.DataFrame, current, atr: float,
        funding_rate: float
    ) -> TradingSignal:
        """ETH低波动休整策略 - 流动性枯竭，禁止交易
        
        ETH特点：凌晨或节假日可能出现极低波动
        合约风险：点差大，滑点严重，难盈利
        """
        close = current['close']
        volume_ratio = current.get('volume_ratio', 1.0)
        
        # 记录低波动持续时间（考虑加入冷却期）
        if not hasattr(self, '_low_vol_count'):
            self._low_vol_count = 0
        self._low_vol_count += 1
        
        # 如果低波动持续很久，可能是暴风雨前的宁静，提高警觉
        if self._low_vol_count > 30:  # 30分钟
            msg = f'ETH低波动持续{self._low_vol_count}分钟，警惕即将变盘'
        else:
            msg = f'ETH低波动休整-禁止交易(量:{volume_ratio:.1f})'
        
        return TradingSignal(
            'HOLD', 0.5, SignalSource.TECHNICAL, 
            msg,
            atr, regime=MarketRegime.LOW_VOL, funding_rate=funding_rate
        )
    
    def _reversal_strategy(
        self, df: pd.DataFrame, current, atr: float,
        ml_confidence: float, funding_rate: float,
        ml_available: bool = False, ml_direction: int = 0
    ) -> TradingSignal:
        """ETH趋势反转策略 - 顶底背离，趋势可能反转
        
        ETH特点：顶底背离后反转往往比较剧烈
        但假背离也多，必须高置信度确认
        """
        close = current['close']
        rsi = current.get('rsi_12', 50)
        bb_position = current.get('bb_position', 0.5)
        volume_ratio = current.get('volume_ratio', 1.0)
        
        # 反转交易门槛极高（防止假信号）
        reversal_threshold = 0.82
        
        if not ml_available or ml_confidence < reversal_threshold:
            return TradingSignal(
                'HOLD', 0.5, SignalSource.TECHNICAL, 
                f'ETH反转-等待确认(需>{reversal_threshold})',
                atr, regime=MarketRegime.REVERSAL, funding_rate=funding_rate
            )
        
        action = 'BUY' if ml_direction == 1 else 'SELL'
        
        # 顶部反转做空：必须在布林带上轨附近
        if action == 'SELL' and bb_position < 0.7:
            return TradingSignal(
                'HOLD', ml_confidence, SignalSource.TECHNICAL,
                'ETH反转-不在高位，不摸顶',
                atr, regime=MarketRegime.REVERSAL, funding_rate=funding_rate
            )
        
        # 底部反转做多：必须在布林带下轨附近
        if action == 'BUY' and bb_position > 0.3:
            return TradingSignal(
                'HOLD', ml_confidence, SignalSource.TECHNICAL,
                'ETH反转-不在低位，不抄底',
                atr, regime=MarketRegime.REVERSAL, funding_rate=funding_rate
            )
        
        # 小仓位试探，收紧止损
        sl_price = close - atr * 1.0 if action == 'BUY' else close + atr * 1.0
        tp_price = close + atr * 6 if action == 'BUY' else close - atr * 6
        
        return TradingSignal(
            action, ml_confidence * 0.75, SignalSource.ML,
            f'ETH反转-{action}(极小仓位,RSI:{rsi:.0f})',
            atr, sl_price, tp_price,
            MarketRegime.REVERSAL, funding_rate
        )
    
    def _consolidation_strategy(
        self, df: pd.DataFrame, current, atr: float,
        ml_confidence: float, funding_rate: float,
        ml_available: bool = False
    ) -> TradingSignal:
        """ETH盘整待破策略 - 横盘整理末期，等待突破
        
        ETH特点：盘整后往往有大行情，提前布局收益高
        风险：假突破多，必须等确认或控制仓位
        """
        close = current['close']
        bb_position = current.get('bb_position', 0.5)
        bb_width = current.get('bb_width', 0.05)
        volume_ratio = current.get('volume_ratio', 1.0)
        rsi = current.get('rsi_12', 50)
        
        # 计算盘整时间（简化：用布林带收窄程度）
        bb_width_avg = df['bb_width'].tail(20).mean()
        consolidation_strength = 1 - (bb_width / bb_width_avg) if bb_width_avg > 0 else 0
        
        # 只在极端位置埋伏，预期突破
        # 下轨埋伏做多
        if bb_position < 0.10:
            # 检查是否有放量迹象（资金流入）
            if volume_ratio > 1.1 or ml_confidence >= 0.70:
                sl_price = close - atr * 1.0
                tp_price = close + atr * 8  # 盘整突破后空间大
                
                return TradingSignal(
                    'BUY', max(0.70, ml_confidence) if ml_available else 0.70,
                    SignalSource.GRID,
                    f'ETH盘整埋伏多(收窄{consolidation_strength*100:.0f}%,RSI:{rsi:.0f})',
                    atr, sl_price, tp_price,
                    MarketRegime.CONSOLIDATION, funding_rate
                )
        
        # 上轨埋伏做空
        if bb_position > 0.90:
            if volume_ratio > 1.1 or ml_confidence >= 0.70:
                sl_price = close + atr * 1.0
                tp_price = close - atr * 8
                
                return TradingSignal(
                    'SELL', max(0.70, ml_confidence) if ml_available else 0.70,
                    SignalSource.GRID,
                    f'ETH盘整埋伏空(收窄{consolidation_strength*100:.0f}%,RSI:{rsi:.0f})',
                    atr, sl_price, tp_price,
                    MarketRegime.CONSOLIDATION, funding_rate
                )
        
        # 记录盘整时间
        if not hasattr(self, '_consolidation_info'):
            self._consolidation_info = {'start_price': close, 'count': 0}
        self._consolidation_info['count'] += 1
        consol_count = self._consolidation_info['count']
        
        return TradingSignal(
            'HOLD', 0.5, SignalSource.TECHNICAL, 
            f'ETH盘整待破-观望({consol_count}分钟)',
            atr, regime=MarketRegime.CONSOLIDATION, funding_rate=funding_rate
        )
    
    def _check_exit_signal(
        self, current_price: float, entry_price: float,
        position_side: str, atr: float, regime: MarketRegime,
        funding_rate: float, df: pd.DataFrame
    ) -> TradingSignal:
        """
        智能平仓检查 - 完整版（所有策略带留痕）
        检查顺序：止损 > 保护 > 移动 > EVT > ATR固定 > ML > 资金费率
        """
        from take_profit_manager import TPSignalType, TPSignalRecord, get_tp_manager
        
        # 计算当前盈亏（未加杠杆）
        is_short = position_side in ['SELL', 'SHORT']
        pnl_pct = (entry_price - current_price) / entry_price if is_short else (current_price - entry_price) / entry_price
        
        # 更新峰值盈亏（用于移动止盈）
        if pnl_pct > self.position_peak_pnl:
            self.position_peak_pnl = pnl_pct
            trailing_drawback = CONFIG.get("TRAILING_STOP_DRAWBACK_PCT", 0.30)
            self.position_trailing_stop = self.position_peak_pnl * (1 - trailing_drawback)
        
        # 获取止盈管理器
        tp_manager = get_tp_manager()
        
        # ========== 1. 动态止损（严格）- 最高优先级 ==========
        sl_mult = CONFIG.get("STOP_LOSS_ATR_MULT", 2.0)
        sl_pct = -sl_mult * atr / entry_price
        
        if pnl_pct <= sl_pct:
            record = TPSignalRecord(
                timestamp=datetime.now(),
                position_id=f"{self.symbol}_{datetime.now().timestamp()}",
                symbol=self.symbol,
                side=position_side,
                entry_price=entry_price,
                exit_price=current_price,
                pnl_pct=pnl_pct,
                pnl_usdt=0,  # 会在平仓时更新
                signal_type=TPSignalType.STOP_LOSS_DYNAMIC,
                signal_description=f'动态止损触发，亏损{pnl_pct*100:.2f}%',
                market_regime=regime.value,
                current_price=current_price,
                sl_atr_value=atr,
                sl_atr_multiplier=sl_mult,
                sl_distance_pct=sl_pct
            )
            tp_manager.record_signal(record)
            
            return TradingSignal(
                'CLOSE', 1.0, SignalSource.TECHNICAL,
                f'动态止损({pnl_pct*100:.2f}%)',
                atr, regime=regime, funding_rate=funding_rate
            )
        
        # ========== 2. 盈利保护（浮盈回撤50%强制平仓）==========
        profit_prot_pct = CONFIG.get("PROFIT_PROTECTION_ENABLE_PCT", 0.005)
        profit_drawback = CONFIG.get("PROFIT_PROTECTION_DRAWBACK_PCT", 0.50)
        
        if self.position_peak_pnl > profit_prot_pct and pnl_pct < self.position_peak_pnl * (1 - profit_drawback):
            record = TPSignalRecord(
                timestamp=datetime.now(),
                position_id=f"{self.symbol}_{datetime.now().timestamp()}",
                symbol=self.symbol,
                side=position_side,
                entry_price=entry_price,
                exit_price=current_price,
                pnl_pct=pnl_pct,
                pnl_usdt=0,
                signal_type=TPSignalType.PROFIT_PROTECTION,
                signal_description=f'盈利保护：峰值{self.position_peak_pnl*100:.2f}%回撤50%至{pnl_pct*100:.2f}%',
                market_regime=regime.value,
                current_price=current_price,
                pp_peak_pnl=self.position_peak_pnl,
                pp_current_pnl=pnl_pct,
                pp_drawback_pct=profit_drawback
            )
            tp_manager.record_signal(record)
            
            return TradingSignal(
                'CLOSE', 1.0, SignalSource.TECHNICAL,
                f'盈利保护(峰值{self.position_peak_pnl*100:.2f}%, 回撤过半至{pnl_pct*100:.2f}%)',
                atr, regime=regime, funding_rate=funding_rate
            )
        
        # ========== 3. 移动止盈（让利润奔跑，回撤30%）==========
        trailing_enable = CONFIG.get("TRAILING_STOP_ENABLE_PCT", 0.008)
        
        if self.position_peak_pnl > trailing_enable and pnl_pct <= self.position_trailing_stop:
            record = TPSignalRecord(
                timestamp=datetime.now(),
                position_id=f"{self.symbol}_{datetime.now().timestamp()}",
                symbol=self.symbol,
                side=position_side,
                entry_price=entry_price,
                exit_price=current_price,
                pnl_pct=pnl_pct,
                pnl_usdt=0,
                signal_type=TPSignalType.TRAILING_STOP,
                signal_description=f'移动止盈：峰值{self.position_peak_pnl*100:.2f}%回撤30%至{pnl_pct*100:.2f}%',
                market_regime=regime.value,
                current_price=current_price,
                ts_peak_pnl=self.position_peak_pnl,
                ts_trailing_stop_level=self.position_trailing_stop,
                ts_drawback_pct=0.30
            )
            tp_manager.record_signal(record)
            
            return TradingSignal(
                'CLOSE', 1.0, SignalSource.TECHNICAL,
                f'移动止盈(峰值{self.position_peak_pnl*100:.2f}%, 回撤至{pnl_pct*100:.2f}%)',
                atr, regime=regime, funding_rate=funding_rate
            )
        
        # ========== 4. EVT极值止盈（新增）==========
        try:
            from evt_take_profit import get_evt_engine
            evt_engine = get_evt_engine()
            
            # 更新参数
            evt_engine.update_parameters(df['close'])
            
            # 计算EVT止盈位
            tp_return, evt_info = evt_engine.calculate_tp_level(
                side='SHORT' if is_short else 'LONG',
                regime=regime.value
            )
            
            if evt_info.get('method') == 'EVT_GPD':
                if pnl_pct >= tp_return:
                    record = TPSignalRecord(
                        timestamp=datetime.now(),
                        position_id=f"{self.symbol}_{datetime.now().timestamp()}",
                        symbol=self.symbol,
                        side=position_side,
                        entry_price=entry_price,
                        exit_price=current_price,
                        pnl_pct=pnl_pct,
                        pnl_usdt=0,
                        signal_type=TPSignalType.EVT_EXTREME,
                        signal_description=f'EVT极值止盈触发(目标{tp_return*100:.2f}%)',
                        market_regime=regime.value,
                        current_price=current_price,
                        evt_shape=evt_info.get('shape'),
                        evt_scale=evt_info.get('scale'),
                        evt_threshold=evt_info.get('threshold'),
                        evt_confidence=evt_info.get('confidence'),
                        evt_expected_return=evt_info.get('final_return'),
                        evt_safety_factor=evt_info.get('safety_factor')
                    )
                    tp_manager.record_signal(record)
                    
                    return TradingSignal(
                        'CLOSE', 1.0, SignalSource.TECHNICAL,
                        f'EVT极值止盈({pnl_pct*100:.2f}%, ξ={evt_info.get("shape", 0):.2f})',
                        atr, regime=regime, funding_rate=funding_rate
                    )
        except Exception as e:
            logger.debug(f"EVT计算跳过: {e}")
        
        # ========== 5. 分级ATR止盈（后备）==========
        if regime == MarketRegime.SIDEWAYS:
            tp_sideways_mult = CONFIG.get("TP_SIDEWAYS_ATR_MULT", 4.0)
            tp_pct = tp_sideways_mult * atr / entry_price
            
            if pnl_pct >= tp_pct:
                record = TPSignalRecord(
                    timestamp=datetime.now(),
                    position_id=f"{self.symbol}_{datetime.now().timestamp()}",
                    symbol=self.symbol,
                    side=position_side,
                    entry_price=entry_price,
                    exit_price=current_price,
                    pnl_pct=pnl_pct,
                    pnl_usdt=0,
                    signal_type=TPSignalType.ATR_FIXED_SIDEWAYS,
                    signal_description=f'震荡市ATR止盈({tp_sideways_mult}x ATR)',
                    market_regime=regime.value,
                    current_price=current_price,
                    atr_fixed_value=atr,
                    atr_fixed_multiplier=tp_sideways_mult,
                    atr_target_pct=tp_pct
                )
                tp_manager.record_signal(record)
                
                return TradingSignal(
                    'CLOSE', 1.0, SignalSource.TECHNICAL,
                    f'震荡市ATR止盈({pnl_pct*100:.2f}%)',
                    atr, regime=regime, funding_rate=funding_rate
                )
        else:
            tp_trend_mult = CONFIG.get("TP_TRENDING_ATR_MULT", 8.0)
            tp_pct = tp_trend_mult * atr / entry_price
            
            if pnl_pct >= tp_pct:
                record = TPSignalRecord(
                    timestamp=datetime.now(),
                    position_id=f"{self.symbol}_{datetime.now().timestamp()}",
                    symbol=self.symbol,
                    side=position_side,
                    entry_price=entry_price,
                    exit_price=current_price,
                    pnl_pct=pnl_pct,
                    pnl_usdt=0,
                    signal_type=TPSignalType.ATR_FIXED_TREND,
                    signal_description=f'趋势市ATR大止盈({tp_trend_mult}x ATR)',
                    market_regime=regime.value,
                    current_price=current_price,
                    atr_fixed_value=atr,
                    atr_fixed_multiplier=tp_trend_mult,
                    atr_target_pct=tp_pct
                )
                tp_manager.record_signal(record)
                
                return TradingSignal(
                    'CLOSE', 1.0, SignalSource.TECHNICAL,
                    f'趋势市ATR止盈({pnl_pct*100:.2f}%)',
                    atr, regime=regime, funding_rate=funding_rate
                )
        
        # ========== 6. ML趋势反转 ==========
        if self.ml_model.is_trained:
            ml_pred = self.ml_model.predict(df)
            
            ml_reverse_pnl = CONFIG.get("PROFIT_PROTECTION_ENABLE_PCT", 0.015) * 3
            ml_reverse_conf = CONFIG.get("ML_CONFIDENCE_THRESHOLD", 0.56) + 0.19
            
            if pnl_pct > ml_reverse_pnl and ml_pred['confidence'] > ml_reverse_conf:
                if (is_short and ml_pred['direction'] == 1) or (not is_short and ml_pred['direction'] == -1):
                    record = TPSignalRecord(
                        timestamp=datetime.now(),
                        position_id=f"{self.symbol}_{datetime.now().timestamp()}",
                        symbol=self.symbol,
                        side=position_side,
                        entry_price=entry_price,
                        exit_price=current_price,
                        pnl_pct=pnl_pct,
                        pnl_usdt=0,
                        signal_type=TPSignalType.ML_REVERSAL,
                        signal_description=f'ML趋势反转信号(置信度{ml_pred["confidence"]:.2f})',
                        market_regime=regime.value,
                        current_price=current_price,
                        ml_confidence=ml_pred['confidence'],
                        ml_direction=ml_pred['direction'],
                        ml_required_confidence=ml_reverse_conf
                    )
                    tp_manager.record_signal(record)
                    
                    return TradingSignal(
                        'CLOSE', ml_pred['confidence'], SignalSource.ML,
                        f'ML止盈反转(盈利{pnl_pct*100:.2f}%)',
                        atr, regime=regime, funding_rate=funding_rate
                    )
        
        # ========== 7. 资金费率极端 ==========
        funding_extreme = CONFIG.get("FUNDING_RATE_EXTREME", 0.01)
        
        if not is_short and funding_rate > funding_extreme:
            record = TPSignalRecord(
                timestamp=datetime.now(),
                position_id=f"{self.symbol}_{datetime.now().timestamp()}",
                symbol=self.symbol,
                side=position_side,
                entry_price=entry_price,
                exit_price=current_price,
                pnl_pct=pnl_pct,
                pnl_usdt=0,
                signal_type=TPSignalType.FUNDING_HIGH,
                signal_description=f'资金费率过高({funding_rate:.4%}>{funding_extreme:.4%})',
                market_regime=regime.value,
                current_price=current_price,
                funding_rate=funding_rate,
                funding_threshold=funding_extreme
            )
            tp_manager.record_signal(record)
            
            return TradingSignal(
                'CLOSE', 0.8, SignalSource.FUNDING,
                f'资金费率过高({funding_rate:.4%})',
                atr, regime=regime, funding_rate=funding_rate
            )
        
        if is_short and funding_rate < -funding_extreme:
            record = TPSignalRecord(
                timestamp=datetime.now(),
                position_id=f"{self.symbol}_{datetime.now().timestamp()}",
                symbol=self.symbol,
                side=position_side,
                entry_price=entry_price,
                exit_price=current_price,
                pnl_pct=pnl_pct,
                pnl_usdt=0,
                signal_type=TPSignalType.FUNDING_LOW,
                signal_description=f'资金费率过低({funding_rate:.4%}<{-funding_extreme:.4%})',
                market_regime=regime.value,
                current_price=current_price,
                funding_rate=funding_rate,
                funding_threshold=-funding_extreme
            )
            tp_manager.record_signal(record)
            
            return TradingSignal(
                'CLOSE', 0.8, SignalSource.FUNDING,
                f'资金费率过低({funding_rate:.4%})',
                atr, regime=regime, funding_rate=funding_rate
            )
        
        # 无信号，继续持仓
        return TradingSignal(
            'HOLD', 0.5, SignalSource.TECHNICAL,
            f'持仓(峰值{self.position_peak_pnl*100:.2f}%, 当前{pnl_pct*100:.2f}%)',
            atr, regime=regime, funding_rate=funding_rate
        )
    
    def _calculate_sl_tp(
        self, action: str, price: float, atr: float, regime: MarketRegime
    ) -> Tuple[float, float]:
        """计算动态止盈止损价格（修复版）
        
        修复：直接使用配置参数，避免额外的乘法导致参数不一致
        """
        # 从配置直接读取，不使用默认值避免与config.py不一致
        base_sl_mult = CONFIG.get("STOP_LOSS_ATR_MULT")
        if base_sl_mult is None:
            base_sl_mult = 1.5  # 与config.py默认值一致
        
        # 根据市场环境调整倍数
        if regime == MarketRegime.SIDEWAYS:
            # 震荡市：使用专用参数或基础值的固定比例
            sl_mult = CONFIG.get("SIDEWAYS_STOP_LOSS_ATR_MULT", base_sl_mult * 0.9)
            tp_mult = CONFIG.get("TP_SIDEWAYS_ATR_MULT", 4.0)
        else:  # 趋势市
            sl_mult = base_sl_mult
            tp_mult = CONFIG.get("TP_TRENDING_ATR_MULT", 8.0)
        
        # 确保最小止损距离（避免过紧）
        min_sl_pct = CONFIG.get("STOP_LOSS_MIN_PCT", 0.008)
        actual_sl_pct = sl_mult * atr / price
        if actual_sl_pct < min_sl_pct:
            sl_mult = min_sl_pct * price / atr
            logger.debug(f"止损距离过紧，调整倍数: {sl_mult:.2f}")
        
        if action == 'BUY':
            sl_price = price - atr * sl_mult
            tp_price = price + atr * tp_mult
        else:
            sl_price = price + atr * sl_mult
            tp_price = price - atr * tp_mult
        
        return sl_price, tp_price
    
    def _funding_filter(self, action: str, funding_rate: float) -> bool:
        """资金费率过滤器"""
        threshold = CONFIG.get("FUNDING_RATE_THRESHOLD", 0.001)
        
        if action == 'BUY' and funding_rate > threshold:
            return True  # 过滤
        if action == 'SELL' and funding_rate < -threshold:
            return True
        
        return False


# ==================== 风控引擎 ====================
class RiskManager:
    """生产级风险管理器"""
    
    def __init__(self):
        self.start_balance = None
        self.peak_balance = None
        self.daily_pnl = 0
        self.daily_trades = 0
        self.last_reset_day = datetime.now().day
        
        # 风控参数
        self.max_daily_loss_pct = CONFIG.get("MAX_DAILY_LOSS_PCT", 0.05)
        self.max_daily_trades = CONFIG.get("MAX_DAILY_TRADES", 50)
        self.max_position_pct = CONFIG.get("POSITION_SIZE_PCT_MAX", 0.60)
        self.max_leverage = 5
        
        # 冷却期控制
        self.last_trade_time = None
        self.last_trade_result = None
        self.cooldown_seconds = 0  # 动态冷却时间
        
    def reset_daily_stats(self):
        """重置日统计"""
        current_day = datetime.now().day
        if current_day != self.last_reset_day:
            self.daily_pnl = 0
            self.daily_trades = 0
            self.last_reset_day = current_day
            logger.info("📅 新的一天，重置日统计数据")
    
    def update_balance(self, balance: float):
        """更新余额统计"""
        if self.start_balance is None:
            self.start_balance = balance
            self.peak_balance = balance
        
        if balance > self.peak_balance:
            self.peak_balance = balance
    
    def check_drawdown(self, balance: float) -> Tuple[bool, float]:
        """检查回撤"""
        if self.peak_balance is None or self.peak_balance <= 0:
            return False, 0
        
        drawdown = (self.peak_balance - balance) / self.peak_balance
        max_dd_limit = CONFIG.get("MAX_DD_LIMIT", 0.15)
        
        if drawdown > max_dd_limit:
            return True, drawdown
        return False, drawdown
    
    def check_risk_limits(self, balance: float) -> Tuple[bool, str]:
        """检查风险限制"""
        self.reset_daily_stats()
        
        # 日亏损限制
        if self.daily_pnl < -self.max_daily_loss_pct:
            return False, f"日亏损超限({self.daily_pnl*100:.2f}%)"
        
        # 交易次数限制
        if self.daily_trades >= self.max_daily_trades:
            return False, f"日交易次数超限({self.daily_trades})"
        
        # 最大回撤限制
        should_stop, dd = self.check_drawdown(balance)
        if should_stop:
            return False, f"最大回撤超限({dd*100:.2f}%)"
        
        # 冷却期检查（避免连续交易）
        if self.last_trade_time:
            elapsed = (datetime.now() - self.last_trade_time).total_seconds()
            if elapsed < self.cooldown_seconds:
                return False, f"冷却期中({self.cooldown_seconds - elapsed:.0f}秒)"
        
        return True, "OK"
    
    def calculate_position_size(
        self, balance: float, price: float,
        atr: float, confidence: float,
        regime: MarketRegime = None
    ) -> float:
        """智能动态仓位 - 分级置信度+市场环境"""
        
        # 基础风险金额（从配置读取，默认0.8%）
        base_risk = balance * CONFIG.get("MAX_RISK_PCT", 0.008)
        
        # ========== 1. 置信度分级（从配置读取）==========
        if confidence >= 0.80:
            confidence_mult = CONFIG.get("CONFIDENCE_MULT_EXTREME", 3.0)
            confidence_level = "极高"
        elif confidence >= 0.70:
            confidence_mult = CONFIG.get("CONFIDENCE_MULT_HIGH", 2.0)
            confidence_level = "高"
        elif confidence >= 0.60:
            confidence_mult = CONFIG.get("CONFIDENCE_MULT_MID", 1.2)
            confidence_level = "中"
        elif confidence >= 0.55:
            confidence_mult = CONFIG.get("CONFIDENCE_MULT_LOW", 0.6)
            confidence_level = "低"
        else:
            logger.warning(f"置信度{confidence:.2f}过低，建议观望")
            confidence_mult = CONFIG.get("CONFIDENCE_MULT_VERY_LOW", 0.3)
            confidence_level = "极低"
        
        # ========== 2. 市场环境因子（从配置读取）==========
        if regime in [MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN]:
            if confidence >= 0.65:
                regime_mult = CONFIG.get("REGIME_TREND_HIGH_CONF_MULT", 1.3)
            else:
                regime_mult = CONFIG.get("REGIME_TREND_LOW_CONF_MULT", 0.9)
            regime_desc = "趋势市"
        elif regime == MarketRegime.SIDEWAYS:
            if confidence < 0.70:
                regime_mult = CONFIG.get("REGIME_SIDEWAYS_LOW_CONF_MULT", 0.7)
            else:
                regime_mult = CONFIG.get("REGIME_SIDEWAYS_HIGH_CONF_MULT", 1.0)
            regime_desc = "震荡市"
        else:
            regime_mult = 1.0
            regime_desc = "未知"
        
        # 综合乘数
        total_mult = confidence_mult * regime_mult
        
        # ========== 3. ATR止损距离（根据置信度调整）==========
        base_sl_mult = CONFIG.get("STOP_LOSS_ATR_MULT", 2.0)
        if confidence >= 0.75:
            atr_mult = base_sl_mult * 1.25  # 高置信度：宽止损
        elif confidence >= 0.60:
            atr_mult = base_sl_mult  # 中置信度：标准
        else:
            atr_mult = base_sl_mult * 0.75  # 低置信度：紧止损
        
        min_sl_pct = CONFIG.get("STOP_LOSS_MIN_PCT", 0.008)
        stop_loss_pct = max(atr_mult * atr / price, min_sl_pct)
        
        # ========== 4. 计算基础数量 ==========
        base_qty = (base_risk * total_mult) / (stop_loss_pct * price)
        base_notional = base_qty * price  # 基础名义价值
        base_pct = base_notional / balance  # 占余额百分比
        
        # ========== 5. 应用仓位占比范围限制 ==========
        # 读取用户设置的仓位占比范围
        pos_pct_min = CONFIG.get("POSITION_SIZE_PCT_MIN", 0.30)  # 默认30%
        pos_pct_max = CONFIG.get("POSITION_SIZE_PCT_MAX", 0.70)  # 默认70%
        
        # 将计算值限制在 [MIN, MAX] 范围内
        limited_pct = max(pos_pct_min, min(pos_pct_max, base_pct))
        limited_notional = balance * limited_pct
        qty = limited_notional / price
        
        # 记录调整信息
        if limited_pct != base_pct:
            logger.info(
                f"仓位调整 | 计算占比:{base_pct*100:.1f}% → "
                f"限制后:{limited_pct*100:.1f}% (范围:[{pos_pct_min*100:.0f}%-{pos_pct_max*100:.0f}%])"
            )
        
        # 币安最小名义价值（从配置读取，默认$21）
        min_notional = CONFIG.get("MIN_NOTIONAL", 21.0)
        min_qty = math.ceil(min_notional / price * 1000) / 1000
        
        # 记录计算过程
        final_pct = qty * price / balance
        logger.info(
            f"仓位计算 | 基础风险:{CONFIG.get('MAX_RISK_PCT', 0.03)*100:.1f}%×${balance:.0f}=${base_risk:.2f} | "
            f"置信度:{confidence:.2f}({confidence_level})×{total_mult:.2f} | "
            f"止损:{stop_loss_pct*100:.2f}% | "
            f"理论:{base_pct*100:.1f}%→限制:{final_pct*100:.1f}% | "
            f"仓位:{qty:.4f}ETH(${qty*price:.0f})"
        )
        
        # 如果计算值低于最小要求，说明风险设置或余额不足
        if qty < min_qty:
            logger.warning(
                f"计算仓位{qty:.4f}ETH(${qty*price:.2f})低于最小名义价值，"
                f"使用最小仓位{min_qty:.4f}ETH。建议：增加余额或调整MAX_RISK_PCT"
            )
            qty = min_qty
        
        return round(qty, 3)
    
    def set_cooldown_by_signal(self, signal_confidence: float, signal_source: str, 
                                 regime: MarketRegime = None):
        """根据信号质量设置智能冷却期（增强版）
        
        原则：
        - 高置信度(>0.7) + 趋势信号：0-10秒
        - 中置信度(0.6-0.7) + 技术/网格：10-20秒  
        - 低置信度(<0.6)：20-30秒
        - 震荡市额外增加冷却期（更难预测）
        - 最高不超过120秒（防止插针后乱开仓）
        """
        # 基础冷却时间根据置信度（从配置读取）
        if signal_confidence >= 0.75:
            base_cooldown = CONFIG.get("COOLDOWN_HIGH_CONFIDENCE", 10)
        elif signal_confidence >= 0.65:
            base_cooldown = CONFIG.get("COOLDOWN_MID_CONFIDENCE", 30)
        else:
            base_cooldown = CONFIG.get("COOLDOWN_LOW_CONFIDENCE", 45)
        
        # 信号来源调整
        if signal_source == '机器学习':
            base_cooldown *= CONFIG.get("COOLDOWN_ML_FACTOR", 0.8)
        elif signal_source == '网格策略':
            base_cooldown *= CONFIG.get("COOLDOWN_GRID_FACTOR", 1.2)
        
        # 市场环境调整（新增）：震荡市更谨慎
        if regime == MarketRegime.SIDEWAYS:
            sideways_mult = CONFIG.get("SIDEWAYS_COOLDOWN_MULT", 1.5)
            base_cooldown *= sideways_mult
            regime_note = f"[震荡市×{sideways_mult}]"
        else:
            regime_note = ""
        
        max_cooldown = CONFIG.get("COOLDOWN_MAX_SECONDS", 120)
        self.cooldown_seconds = min(int(base_cooldown), max_cooldown)
        
        if self.cooldown_seconds > 0:
            logger.info(f"⏱️ 信号冷却期: {self.cooldown_seconds}秒 {regime_note}(置信度:{signal_confidence:.2f})")
    
    def record_trade(self, pnl_pct: float):
        """记录交易结果"""
        self.daily_pnl += pnl_pct
        self.daily_trades += 1
        self.last_trade_time = datetime.now()
        self.last_trade_result = 'WIN' if pnl_pct > 0 else 'LOSS'
        
        # 盈利后不设置冷却期（让信号质量决定）
        if pnl_pct < 0:
            # 亏损后额外冷静期
            loss_cooldown = CONFIG.get("COOLDOWN_AFTER_LOSS", 15)
            self.cooldown_seconds = max(self.cooldown_seconds, loss_cooldown)
            logger.info(f"⏱️ 亏损冷静: {self.cooldown_seconds}秒")


# ==================== 数据库管理 ====================
class TradeDatabase:
    """交易数据库管理"""
    
    def __init__(self, db_path: str = 'v12_optimized.db'):
        self.db_path = db_path
        self.init_tables()
    
    def get_connection(self):
        return sqlite3.connect(self.db_path, check_same_thread=False)
    
    def init_tables(self):
        """初始化表结构"""
        conn = self.get_connection()
        
        # 交易记录表
        conn.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                symbol TEXT,
                side TEXT,
                entry_price REAL,
                exit_price REAL,
                qty REAL,
                pnl_pct REAL,
                pnl_usdt REAL,
                result TEXT,
                reason TEXT,
                signal_source TEXT,
                confidence REAL,
                regime TEXT,
                funding_rate REAL
            )
        ''')
        
        # 信号记录表
        conn.execute('''
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                symbol TEXT,
                action TEXT,
                confidence REAL,
                source TEXT,
                reason TEXT,
                price REAL,
                atr REAL,
                regime TEXT,
                executed BOOLEAN,
                result TEXT
            )
        ''')
        
        # 持仓记录表
        conn.execute('''
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                symbol TEXT,
                side TEXT,
                qty REAL,
                entry_price REAL,
                current_price REAL,
                unrealized_pnl_pct REAL,
                unrealized_pnl_usdt REAL,
                sl_price REAL,
                tp_price REAL
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def log_trade(self, symbol: str, side: str, entry_price: float,
                  exit_price: float, qty: float, pnl_pct: float,
                  pnl_usdt: float, result: str, reason: str,
                  signal_source: str, confidence: float,
                  regime: str, funding_rate: float):
        """记录交易"""
        conn = self.get_connection()
        conn.execute('''
            INSERT INTO trades (timestamp, symbol, side, entry_price, exit_price,
                              qty, pnl_pct, pnl_usdt, result, reason,
                              signal_source, confidence, regime, funding_rate)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            datetime.now().isoformat(), symbol, side, entry_price, exit_price,
            qty, pnl_pct, pnl_usdt, result, reason,
            signal_source, confidence, regime, funding_rate
        ))
        conn.commit()
        conn.close()
        
        trade_logger.info(
            f"TRADE | {symbol} | {side} | {result} | "
            f"PnL:{pnl_pct*100:+.2f}% | ${pnl_usdt:+.2f} | {reason}"
        )
    
    def log_signal(self, symbol: str, signal: TradingSignal,
                   price: float, executed: bool = False):
        """记录信号"""
        conn = self.get_connection()
        conn.execute('''
            INSERT INTO signals (timestamp, symbol, action, confidence, source,
                               reason, price, atr, regime, executed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            datetime.now().isoformat(), symbol, signal.action,
            signal.confidence, signal.source.value, signal.reason,
            price, signal.atr, signal.regime.value, executed
        ))
        conn.commit()
        conn.close()
    
    def log_position(self, symbol: str, side: str, qty: float,
                     entry_price: float, current_price: float,
                     unrealized_pnl_pct: float, unrealized_pnl_usdt: float,
                     sl_price: float, tp_price: float):
        """记录持仓"""
        conn = self.get_connection()
        conn.execute('''
            INSERT INTO positions (timestamp, symbol, side, qty, entry_price,
                                 current_price, unrealized_pnl_pct, unrealized_pnl_usdt,
                                 sl_price, tp_price)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            datetime.now().isoformat(), symbol, side, qty, entry_price,
            current_price, unrealized_pnl_pct, unrealized_pnl_usdt,
            sl_price, tp_price
        ))
        conn.commit()
        conn.close()
    
    def get_recent_performance(self, hours: int = 24) -> Dict:
        """获取近期表现"""
        conn = self.get_connection()
        since = (datetime.now() - timedelta(hours=hours)).isoformat()
        
        cursor = conn.execute('''
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) as losses,
                SUM(pnl_usdt) as total_pnl
            FROM trades
            WHERE timestamp > ?
        ''', (since,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row and row[0] > 0:
            return {
                'total_trades': row[0],
                'wins': row[1],
                'losses': row[2],
                'win_rate': row[1] / row[0] * 100 if row[0] > 0 else 0,
                'total_pnl': row[3] or 0
            }
        return {'total_trades': 0, 'wins': 0, 'losses': 0, 'win_rate': 0, 'total_pnl': 0}


# ==================== 主交易类 ====================
class V12OptimizedTrader:
    """V12优化版实盘交易器"""
    
    def __init__(self):
        self.api = BinanceExpertAPI()
        self.symbol = CONFIG["SYMBOLS"][0]
        self.leverage = CONFIG.get("LEVERAGE", 5)
        
        # 组件
        self.signal_gen = SignalGenerator()
        self.risk_mgr = RiskManager()
        self.db = TradeDatabase()
        
        # 状态
        self.position = None  # 当前持仓
        self.last_signal_time = None
        self.cycle_count = 0
        
        # 初始化
        self._init_exchange()
        
        logger.info("=" * 70)
        logger.info("🚀 V12-OPTIMIZED 优化版实盘交易器")
        logger.info(f"   交易对: {self.symbol}")
        logger.info(f"   杠杆: {self.leverage}x")
        logger.info(f"   ML可用: {ML_AVAILABLE}")
        logger.info("=" * 70)
    
    def _init_exchange(self):
        """初始化交易所设置"""
        try:
            # 设置杠杆
            self.api.set_leverage(self.symbol, self.leverage)
            logger.info(f"✅ 杠杆设置为 {self.leverage}x")
            
            # 同步当前持仓
            self._sync_position()
            
        except Exception as e:
            logger.error(f"初始化交易所设置失败: {e}")
    
    def _print_tp_performance_report(self):
        """打印止盈策略绩效报告"""
        try:
            from take_profit_manager import get_tp_manager
            tp_manager = get_tp_manager()
            
            df = tp_manager.get_strategy_performance()
            if df.empty:
                return
            
            print("\n" + "="*80)
            print("止盈策略绩效报告")
            print("="*80)
            print(df.to_string(index=False))
            print("="*80 + "\n")
            
            # 记录到日志
            logger.info("止盈策略绩效报告已生成")
            
        except Exception as e:
            logger.debug(f"生成绩效报告失败: {e}")
    
    def _sync_position(self):
        """同步交易所持仓"""
        try:
            pos = self.api.get_position(self.symbol)
            if pos and pos.get('qty', 0) > 0.0001:
                self.position = {
                    'side': pos['side'],
                    'qty': pos['qty'],
                    'entry_price': pos['entryPrice'],
                    'leverage': pos['leverage']
                }
                logger.info(
                    f"📊 同步持仓: {pos['side']} {pos['qty']} @ ${pos['entryPrice']:.2f} "
                    f"| 未实现PnL: ${pos.get('unrealizedProfit', 0):.2f}"
                )
            else:
                self.position = None
                logger.info("📊 当前无持仓")
        except Exception as e:
            logger.error(f"同步持仓失败: {e}")
    
    def send_notification(self, message: str):
        """发送通知"""
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
            return
        
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML"
            }
            requests.post(url, json=payload, timeout=5)
        except Exception as e:
            logger.error(f"Telegram通知失败: {e}")
    
    def _retry_api_call(self, func, max_retries: int = 3, *args, **kwargs):
        """带重试的API调用"""
        for i in range(max_retries):
            try:
                result = func(*args, **kwargs)
                if result is not None:
                    return result
            except Exception as e:
                logger.warning(f"API调用失败({i+1}/{max_retries}): {e}")
                if i < max_retries - 1:
                    time.sleep(2 ** i)  # 指数退避
        return None
    
    def execute_open(self, signal: TradingSignal, price: float):
        """执行开仓"""
        try:
            side = signal.action  # BUY or SELL
            
            # 智能冷却期：根据信号质量调整（传入市场环境）
            self.risk_mgr.set_cooldown_by_signal(
                signal.confidence, 
                signal.source.value,
                signal.regime
            )
            
            # 获取账户信息
            balance = self._retry_api_call(self.api.get_balance)
            if balance is None:
                logger.error("获取余额失败，取消开仓")
                return False
            
            self.risk_mgr.update_balance(balance)
            
            # 检查风险限制（包含冷却期检查）
            can_trade, reason = self.risk_mgr.check_risk_limits(balance)
            if not can_trade:
                logger.warning(f"⚠️ 风控拦截: {reason}")
                return False
            
            # 计算仓位大小（传入市场环境）
            qty = self.risk_mgr.calculate_position_size(
                balance, price, signal.atr, signal.confidence,
                signal.regime
            )
            
            if qty < 0.001:
                logger.warning(f"仓位计算结果过小: {qty}")
                return False
            
            # 执行下单
            order = self._retry_api_call(
                self.api.place_order, 3,
                self.symbol, side, qty
            )
            
            if order and order.get('orderId'):
                self.position = {
                    'side': side,
                    'qty': qty,
                    'entry_price': price,
                    'sl_price': signal.sl_price,
                    'tp_price': signal.tp_price,
                    'entry_time': datetime.now()
                }
                
                # 重置止盈止损追踪
                self.signal_gen.reset_position_tracking()
                
                # 记录到数据库
                self.db.log_signal(self.symbol, signal, price, executed=True)
                
                msg = (
                    f"🟢 <b>开仓成功</b>\n"
                    f"方向: {side}\n"
                    f"价格: ${price:.2f}\n"
                    f"数量: {qty:.4f}\n"
                    f"止损: ${signal.sl_price:.2f}\n"
                    f"止盈: ${signal.tp_price:.2f}\n"
                    f"置信度: {signal.confidence:.2f}\n"
                    f"原因: {signal.reason}"
                )
                
                logger.info(f"✅ 开仓: {side} {qty} @ ${price:.2f} | {signal.reason}")
                self.send_notification(msg)
                return True
            else:
                logger.error("下单失败")
                return False
                
        except Exception as e:
            logger.error(f"开仓异常: {e}")
            return False
    
    def execute_close(self, signal: TradingSignal, price: float, reason: str = ""):
        """执行平仓"""
        try:
            if not self.position:
                return False
            
            side = self.position['side']
            qty = self.position['qty']
            entry_price = self.position['entry_price']
            
            # 计算盈亏 (支持 LONG/SHORT 和 BUY/SELL 两种表示)
            is_short = side in ['SELL', 'SHORT']
            pnl_pct = (entry_price - price) / entry_price * self.leverage if is_short else (price - entry_price) / entry_price * self.leverage
            
            pnl_usdt = qty * entry_price * pnl_pct
            result = 'WIN' if pnl_pct > 0 else 'LOSS'
            
            # 执行平仓 (LONG->SELL, SHORT->BUY)
            close_side = 'SELL' if not is_short else 'BUY'
            order = self._retry_api_call(
                self.api.place_order, 3,
                self.symbol, close_side, qty, reduce_only=True
            )
            
            if order and order.get('orderId'):
                # 记录到数据库
                self.db.log_trade(
                    self.symbol, side, entry_price, price, qty,
                    pnl_pct, pnl_usdt, result,
                    reason or signal.reason,
                    signal.source.value, signal.confidence,
                    signal.regime.value, signal.funding_rate
                )
                
                # 更新风控统计
                self.risk_mgr.record_trade(pnl_pct)
                
                # 更新止盈记录中的盈亏（用于后期分析）
                try:
                    from take_profit_manager import get_tp_manager
                    tp_manager = get_tp_manager()
                    # 更新最后一条记录的盈亏
                    if tp_manager.records:
                        last_record = tp_manager.records[-1]
                        last_record.pnl_usdt = pnl_usdt
                        last_record.pnl_pct = pnl_pct
                except Exception:
                    pass
                
                # 每5笔平仓打印一次绩效报告
                self.cycle_count += 1
                if self.cycle_count % 5 == 0:
                    self._print_tp_performance_report()
                
                emoji = "🟢" if pnl_pct > 0 else "🔴"
                msg = (
                    f"{emoji} <b>平仓成功</b>\n"
                    f"方向: {side}\n"
                    f"入场: ${entry_price:.2f}\n"
                    f"出场: ${price:.2f}\n"
                    f"盈亏: {pnl_pct*100:+.2f}%\n"
                    f"金额: ${pnl_usdt:+.2f}\n"
                    f"原因: {reason or signal.reason}"
                )
                
                logger.info(f"✅ 平仓: {side} | PnL: {pnl_pct*100:+.2f}% | {reason or signal.reason}")
                self.send_notification(msg)
                
                self.position = None
                return True
            else:
                logger.error("平仓失败")
                return False
                
        except Exception as e:
            logger.error(f"平仓异常: {e}")
            return False
    
    def run_cycle(self):
        """运行一个交易周期"""
        try:
            self.cycle_count += 1
            
            # 获取数据 - 需要足够数据用于特征工程(RSI24+MA55+缓冲)
            df = self._retry_api_call(self.api.get_klines, 3, self.symbol, limit=1000)
            if df is None or len(df) < 200:
                logger.warning("获取K线数据失败或数据不足")
                return
            
            current_price = float(df['close'].iloc[-1])
            
            # 获取资金费率
            funding_rate = self.api.get_funding_rate(self.symbol)
            
            # 生成信号
            signal = self.signal_gen.generate_signal(
                df, current_price, funding_rate,
                has_position=self.position is not None,
                position_side=self.position['side'] if self.position else None,
                entry_price=self.position['entry_price'] if self.position else 0
            )
            
            # 记录信号 - 交易信号立即记录，HOLD信号每15秒记录一次
            if signal.action != 'HOLD' or self.cycle_count % 19 == 0:
                self.db.log_signal(self.symbol, signal, current_price)
            
            # 执行交易
            if signal.action == 'CLOSE' and self.position:
                self.execute_close(signal, current_price)
            
            elif signal.action in ['BUY', 'SELL'] and not self.position:
                self.execute_open(signal, current_price)
            
            # 定期同步持仓 (每30个周期)
            if self.cycle_count % 30 == 0:
                self._sync_position()
            
            # 交易逻辑（保持全速运行，不受日志影响）
            # 记录持仓状态 - 数据库写入每5周期一次（异步不影响交易）
            if self.position:
                entry = self.position['entry_price']
                side = self.position['side']
                is_short = side in ['SELL', 'SHORT']
                pnl_pct = (entry - current_price) / entry * self.leverage if is_short else (current_price - entry) / entry * self.leverage
                
                # 数据库记录每5周期（不影响交易速度）
                if self.cycle_count % 5 == 0:
                    self.db.log_position(
                        self.symbol, side, self.position['qty'],
                        entry, current_price, pnl_pct,
                        self.position['qty'] * entry * pnl_pct,
                        self.position.get('sl_price', 0),
                        self.position.get('tp_price', 0)
                    )
                
                # 日志打印每15秒一次（0.8s * 19 ≈ 15s）
                if self.cycle_count % 19 == 0:
                    logger.info(
                        f"📊 持仓: {side} | 入场: ${entry:.2f} | "
                        f"当前: ${current_price:.2f} | 盈亏: {pnl_pct*100:+.2f}% | "
                        f"环境: {signal.regime.value}"
                    )
            else:
                # 观望状态日志每15秒一次
                if self.cycle_count % 19 == 0:
                    ml_status = "ML" if self.signal_gen.ml_model.is_trained else "NO_ML"
                    logger.info(
                        f"📊 观望 | 价格: ${current_price:.2f} | "
                        f"信号: {signal.action} | 置信度: {signal.confidence:.2f} | "
                        f"来源: {signal.source.value} | 环境: {signal.regime.value} | {ml_status}"
                    )
            
        except Exception as e:
            logger.error(f"交易周期异常: {e}")
    
    def run(self):
        """主循环"""
        logger.info("🚀 V12优化版实盘交易启动...")
        self.send_notification("🚀 <b>V12优化版实盘交易启动</b>")
        
        poll_interval = CONFIG.get("POLL_INTERVAL", 10)
        
        while True:
            try:
                self.run_cycle()
                time.sleep(poll_interval)
                
            except KeyboardInterrupt:
                logger.info("🛑 收到停止信号")
                if self.position:
                    price = self.api.get_price(self.symbol)
                    self.execute_close(
                        TradingSignal('CLOSE', 1.0, SignalSource.TECHNICAL, '程序退出'),
                        price, "程序退出"
                    )
                break
            
            except Exception as e:
                logger.error(f"主循环异常: {e}")
                time.sleep(5)


def main():
    """入口"""
    # 确认模式
    if CONFIG["MODE"] != "LIVE":
        logger.warning(f"⚠️ 当前模式为 {CONFIG['MODE']}，要切换到LIVE模式请输入 'LIVE':")
        confirm = input().strip()
        if confirm != "LIVE":
            logger.info("取消启动")
            return
        CONFIG["MODE"] = "LIVE"
    
    trader = V12OptimizedTrader()
    trader.run()


if __name__ == "__main__":
    main()
