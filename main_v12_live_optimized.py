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

# 重构新增：出场信号系统 (2026-03-24)
from refactor_integration import ExitSignalAdapter, get_exit_adapter

# 🆕 V2市场环境检测可视化
try:
    from market_regime_v2.console_visualizer import ConsoleVisualizer
    V2_VISUALIZER_AVAILABLE = True
except ImportError:
    V2_VISUALIZER_AVAILABLE = False

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
    # ML相关字段
    ml_direction: int = 0  # -1=看空, 0=观望, 1=看多
    ml_confidence: float = 0.0
    ml_proba_short: float = 0.0
    ml_proba_long: float = 0.0
    ml_threshold: float = 0.55
    is_counter_trend: bool = False  # 是否逆势交易
    trend_direction: str = ""  # 当前趋势方向
    
    # ⭐ ML环境检测相关字段（新增，用于留痕）
    ml_regime: str = None           # ML判断的环境类型
    ml_regime_conf: float = 0.0     # ML环境置信度
    tech_regime: str = None         # 技术指标判断的环境
    regime_override: bool = False   # 是否被ML覆盖
    pos_size_mult: float = 1.0      # ML建议的仓位倍数
    ml_urgency: str = 'LOW'         # ML紧急程度
    
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
            'funding_rate': self.funding_rate,
            'ml_direction': self.ml_direction,
            'ml_confidence': self.ml_confidence,
            'ml_proba_short': self.ml_proba_short,
            'ml_proba_long': self.ml_proba_long,
            'is_counter_trend': self.is_counter_trend,
            'trend_direction': self.trend_direction
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
    """特征工程 - 生产级优化
    
    注意：FEATURE_COLS 必须与训练模型时使用的特征完全一致！
    当前与 auto_ml_trainer.py / offline_training.py 保持一致
    """
    
    FEATURE_COLS = [
        'returns', 'log_returns', 'rsi_6', 'rsi_14', 'rsi_24',
        'macd', 'macd_signal', 'macd_hist', 'bb_width', 'bb_position',
        'trend_short', 'trend_mid', 'volume_ratio', 'taker_ratio',
        'momentum_5', 'momentum_10', 'momentum_20', 'atr_pct',
        'price_position', 'hour', 'day_of_week'
    ]
    
    def create_features(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        
        # 确保timestamp列存在用于时间特征
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
        elif 'open_time' in df.columns:
            df['timestamp'] = pd.to_datetime(df['open_time'], unit='ms')
        
        # 时间特征 (必须与训练时一致)
        if 'timestamp' in df.columns:
            df['hour'] = df['timestamp'].dt.hour
            df['day_of_week'] = df['timestamp'].dt.dayofweek
        else:
            # 如果没有时间戳，使用当前时间
            now = datetime.now()
            df['hour'] = now.hour
            df['day_of_week'] = now.weekday()
        
        # 基础价格特征
        df['returns'] = df['close'].pct_change()
        df['log_returns'] = np.log(df['close'] / df['close'].shift(1))
        
        # RSI多周期 (保留 rsi_12 给技术分析用，添加 rsi_14 给ML用)
        for period in [6, 12, 14, 24]:
            delta = df['close'].diff()
            gain = delta.clip(lower=0).rolling(window=period).mean()
            loss = (-delta.clip(upper=0)).rolling(window=period).mean()
            df[f'rsi_{period}'] = 100 - 100 / (1 + gain / (loss + 1e-10))
        
        # MACD (完整的macd指标)
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
        
        # Taker比率 (估算，如果没有taker数据)
        if 'taker_buy_base' in df.columns and 'volume' in df.columns:
            # 确保taker_buy_base是数值类型
            taker_base = pd.to_numeric(df['taker_buy_base'], errors='coerce')
            df['taker_ratio'] = taker_base / df['volume']
        else:
            df['taker_ratio'] = 0.5  # 默认值
        
        # 动量 (添加 momentum_20 与训练一致)
        for period in [3, 5, 10, 20]:
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
    
    def load(self, model_path: str = "ml_model_trained.pkl") -> bool:
        """加载预训练模型"""
        import os
        import pickle
        
        if not os.path.exists(model_path):
            logger.debug(f"模型文件不存在: {model_path}")
            return False
        
        try:
            with open(model_path, 'rb') as f:
                pkg = pickle.load(f)
                self.model = pkg.get('model')
                self.scaler = pkg.get('scaler', StandardScaler())
                self.is_trained = True
            logger.info(f"✅ ML模型加载成功: {model_path}")
            return True
        except Exception as e:
            logger.warning(f"加载模型失败: {e}")
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
            
            # ML预测日志（调试用）
            direction_str = "看多" if direction == 1 else "看空" if direction == -1 else "观望"
            logger.debug(f"[ML分析] 方向:{direction_str} 置信度:{confidence:.3f} 概率:[{proba[0]:.3f}, {proba[1]:.3f}]")
            
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
        
        # ========== 5. 盘整检测（布林带收窄 + 低ADX + 低波动）==========
        bb_width_avg = df['bb_width'].tail(15).mean()
        # 修复：盘整必须满足ADX低（无趋势）且ATR低，避免误判趋势中的缩量
        if (bb_width < bb_threshold * 0.8 and 
            bb_width < bb_width_avg * 0.7 and 
            adx < adx_threshold * 0.8 and  # ADX必须低（<20）
            atr_pct < high_vol_threshold):   # ATR不能太高
            return MarketRegime.CONSOLIDATION
        
        # ========== 6. 标准趋势市检测（放宽条件）==========
        # 趋势判断：ADX趋势强度 + 均线排列 + 价格动量
        adx_trending = adx > adx_threshold * 0.8  # ADX>20即可（原25）
        adx_strong_trend = adx > adx_threshold
        
        # 放宽均线条件：短期均线在中期均线上方即可（不要求中期在长期上方）
        ma_bullish_loose = ma10 > ma20  # 放宽条件
        ma_bearish_loose = ma10 < ma20  # 放宽条件
        
        # 价格动量辅助判断（5分钟价格变化）
        price_momentum_up = price_change_5 > 0.002  # 5分钟涨0.2%
        price_momentum_down = price_change_5 < -0.002  # 5分钟跌0.2%
        
        # 趋势上涨判断：ADX趋势 + (均线多头 或 (放宽均线+价格动量))
        if adx_trending and (ma_bullish or (ma_bullish_loose and price_momentum_up)):
            return MarketRegime.TRENDING_UP
        
        # 趋势下跌判断：ADX趋势 + (均线空头 或 (放宽均线+价格动量))
        if adx_trending and (ma_bearish or (ma_bearish_loose and price_momentum_down)):
            return MarketRegime.TRENDING_DOWN
        
        # ========== 7. 震荡市细分（放宽斜率阈值）==========
        if bb_width < bb_threshold:
            ma20_slope = (ma20 - df['ma_20'].iloc[-5]) / ma20 if len(df) >= 5 else 0
            # 放宽斜率阈值，更容易判断震荡上行/下行
            if ma20_slope > 0.0001:  # 从0.0002放宽到0.0001
                return MarketRegime.SIDEWAYS_UP
            elif ma20_slope < -0.0001:  # 从-0.0002放宽到-0.0001
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
        
        # 交易对
        self.symbol = CONFIG["SYMBOLS"][0] if CONFIG["SYMBOLS"] else "ETHUSDT"
        
        # 持仓追踪（用于移动止盈）
        self.position_peak_pnl = 0.0  # 峰值盈亏
        self.position_trailing_stop = 0.0  # 移动止损线
        
        # 出场信号适配器（由 V12LiveTrader 注入）
        self.exit_adapter = None
        
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
        
        # ⭐ 新增: ML环境检测模块（带一键关停开关）
        self.ml_regime_enabled = CONFIG.get("ML_REGIME_ENABLED", True)
        self.ml_regime_detector = None
        self.ml_regime_result = None
        self.ml_adjustments = None  # 存储ML环境调整参数
        
        # 🆕 V2可视化器
        self.v2_visualizer = None
        if (V2_VISUALIZER_AVAILABLE and 
            CONFIG.get("ML_REGIME_VERSION") == "v2" and
            CONFIG.get("ML_REGIME_V2_ENABLE_VISUALIZATION", True)):
            try:
                self.v2_visualizer = ConsoleVisualizer(use_color=True)
                logger.info("🎨 V2市场环境可视化已启用")
            except Exception as e:
                logger.debug(f"V2可视化初始化失败: {e}")
        
        if self.ml_regime_enabled:
            try:
                from ml_regime_detector import MLRegimeDetector
                self.ml_regime_detector = MLRegimeDetector(CONFIG)
                logger.info("✅ ML环境检测模块已启用（一键关停开关: ML_REGIME_ENABLED）")
            except Exception as e:
                logger.warning(f"⚠️ ML环境检测模块加载失败: {e}，回退到纯技术指标")
                self.ml_regime_enabled = False
        else:
            logger.info("⚠️ ML环境检测模块已停用（使用纯技术指标判断）")
        
    # ========== 新增：当日区间位置过滤 (2026-03-27) ==========
    
    def _get_daily_position_pct(self, current_price: float, df: pd.DataFrame) -> float:
        """计算当日价格位置百分比 (0-100%)"""
        try:
            # 获取今日数据（基于timestamp列）
            latest_ts = pd.to_datetime(df['timestamp'].iloc[-1])
            today_start = latest_ts.normalize()
            today_data = df[pd.to_datetime(df['timestamp']) >= today_start]
            
            if len(today_data) < 5:
                # 数据不足，使用最近24小时
                today_data = df.tail(96)  # 15m * 96 = 24h
            
            daily_high = today_data['high'].max()
            daily_low = today_data['low'].min()
            
            if daily_high == daily_low:
                return 50.0
            
            position_pct = (current_price - daily_low) / (daily_high - daily_low) * 100
            return position_pct
        except Exception as e:
            logger.debug(f"计算当日位置失败: {e}")
            return 50.0
    
    def _check_daily_position_filter(self, action: str, current_price: float, df: pd.DataFrame) -> Tuple[bool, str]:
        """当日区间位置过滤器"""
        if not CONFIG.get("ENABLE_DAILY_POSITION_FILTER", False):
            return True, "过滤器关闭"
        
        position_pct = self._get_daily_position_pct(current_price, df)
        
        if action == 'SELL':
            min_position = CONFIG.get("DAILY_POSITION_SHORT_MIN", 0.70) * 100
            if position_pct < min_position:
                return False, f"不在当日高位({position_pct:.1f}%<{min_position:.0f}%)"
        elif action == 'BUY':
            max_position = CONFIG.get("DAILY_POSITION_LONG_MAX", 0.30) * 100
            if position_pct > max_position:
                return False, f"不在当日低位({position_pct:.1f}%>{max_position:.0f}%)"
        
        return True, f"位置合格({position_pct:.1f}%)"
    
    def _calculate_fixed_sl_tp(self, entry: float, action: str, atr: float = None) -> Tuple[float, float]:
        """使用固定盈亏比计算SL/TP"""
        if not CONFIG.get("USE_FIXED_RR_WITH_EVT", False):
            # 使用传统ATR模式
            if atr is None:
                atr = entry * 0.01  # 默认1%
            sl_mult = CONFIG.get("STOP_LOSS_ATR_MULT", 2.0)
            tp_mult = CONFIG.get("TP_SIDEWAYS_ATR_MULT", 4.0)
            if action == 'BUY':
                sl = entry - atr * sl_mult
                tp = entry + atr * tp_mult
            else:
                sl = entry + atr * sl_mult
                tp = entry - atr * tp_mult
            return sl, tp
        
        # 固定百分比模式
        stop_pct = CONFIG.get("FIXED_STOP_PCT", 0.008)
        tp_pct = CONFIG.get("FIXED_TP_PCT", 0.016)
        
        if action == 'BUY':
            sl = entry * (1 - stop_pct)
            tp = entry * (1 + tp_pct)
        else:
            sl = entry * (1 + stop_pct)
            tp = entry * (1 - tp_pct)
        
        return sl, tp
    
    def _calculate_position_size(self, base_risk: float, confidence: float, regime: MarketRegime = None) -> float:
        """动态仓位计算 - 仅按置信度调整，不按环境简化"""
        if not CONFIG.get("USE_DYNAMIC_POSITION_SIZE", False):
            return base_risk
        
        mult = 1.0
        high_threshold = CONFIG.get("POSITION_SIZE_HIGH_THRESHOLD", 0.75)
        low_threshold = CONFIG.get("POSITION_SIZE_LOW_THRESHOLD", 0.60)
        
        # 仅按置信度调整（三档）
        if confidence >= high_threshold:
            # 高置信度：增加仓位
            mult = CONFIG.get("POSITION_SIZE_HIGH_CONF", 1.5)
        elif confidence >= low_threshold:
            # 中等置信度：标准仓位
            mult = CONFIG.get("POSITION_SIZE_MID_CONF", 1.0)
        else:
            # 低置信度：减少仓位
            mult = CONFIG.get("POSITION_SIZE_LOW_CONF", 0.5)
        
        return base_risk * mult
    
    def reset_position_tracking(self):
        """重置持仓追踪数据（新开仓时调用）"""
        self.position_peak_pnl = 0.0
        self.position_trailing_stop = 0.0
        # 重置EVT追踪状态
        self._evt_trailing_active = False
        self._evt_trailing_peak = 0
        self._last_evt_target = 0  # 重置EVT目标追踪
        self._evt_high_target = 0  # 重置EVT高目标
    
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
        
    def _create_hold_signal(self, reason: str, atr: float, regime: MarketRegime, 
                            funding_rate: float, ml_info: dict = None) -> TradingSignal:
        """创建带ML信息的观望信号"""
        signal = TradingSignal(
            'HOLD', 0.5, SignalSource.TECHNICAL, reason,
            atr, regime=regime, funding_rate=funding_rate
        )
        if ml_info:
            signal.ml_direction = ml_info.get('direction', 0)
            signal.ml_confidence = ml_info.get('confidence', 0)
            signal.ml_proba_short = ml_info.get('proba_short', 0.5)
            signal.ml_proba_long = ml_info.get('proba_long', 0.5)
        return signal
    
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
        
        # ML模型由外部定时服务训练，这里只加载不训练
        self._load_model_if_exists()
        
        # 特征工程
        df_feat = MLFeatureEngineer().create_features(df)
        if len(df_feat) == 0:
            return self._create_hold_signal('数据不足', 0, MarketRegime.UNKNOWN, funding_rate)
        
        current = df_feat.iloc[-1]
        default_atr_pct = 0.02  # 默认2% ATR
        atr = current.get('atr', current_price * default_atr_pct)
        regime = self.market_analyzer.analyze_regime(df_feat)
        
        # ========== 入场质量评估机制（替代原有的3周期确认）==========
        # 使用综合评分系统，更灵活地评估入场位置质量
        # 评分<0.2禁止入场，0.2-0.5降低仓位，>0.5正常入场
        
        # 如果有持仓，检查止盈止损（最高优先级）
        # 日志优化：只在有持仓时输出详细信息，无持仓时仅debug
        if has_position:
            logger.info(f"[出场检查] 持仓={position_side}, 入场={entry_price:.2f}, 当前={current_price:.2f}")
        else:
            logger.debug(f"[出场检查] 无持仓, 当前价格={current_price:.2f}")
        
        if has_position and position_side:
            # 计算当前盈亏用于日志
            is_short = position_side in ['SELL', 'SHORT']
            pnl_calc = (entry_price - current_price) / entry_price if is_short else (current_price - entry_price) / entry_price
            leverage = CONFIG.get('LEVERAGE', 5)
            pnl_leverage = pnl_calc * leverage
            # 只在盈亏变化超过0.1%时输出，减少日志频率
            pnl_key = round(pnl_leverage * 100, 1)  # 保留1位小数作为key
            if not hasattr(self, '_last_pnl_log') or self._last_pnl_log != pnl_key:
                logger.info(f"[出场检查] 盈亏: {pnl_leverage*100:+.2f}% (峰值:{getattr(self, 'position_peak_pnl', 0)*100:.2f}%)")
                self._last_pnl_log = pnl_key
            # 优先尝试新出场系统（如果可用且有position_manager）
            if self.exit_adapter and hasattr(self, 'position_manager') and self.position_manager:
                try:
                    exit_signal = self.exit_adapter.check_exit(
                        self.position_manager,
                        current_price=current_price,
                        atr=atr,
                        regime=regime.value,
                        funding_rate=funding_rate,
                        df=df_feat
                    )
                    
                    if exit_signal.should_exit:
                        return TradingSignal(
                            'CLOSE',
                            1.0,
                            SignalSource.TECHNICAL,
                            exit_signal.reason,
                            atr,
                            regime=regime,
                            funding_rate=funding_rate
                        )
                except Exception as e:
                    logger.warning(f"[出场检查] 新系统异常，回退到旧系统: {e}")
            
            # 使用旧系统检查出场（保底方案）
            old_signal = self._check_exit_signal(
                current_price, entry_price, position_side,
                atr, regime, funding_rate, df_feat
            )
            # 只在信号变化时输出
            if old_signal.action == 'CLOSE':
                logger.info(f"[出场信号] {old_signal.reason}")
            else:
                logger.debug(f"[出场检查] 继续持仓: {old_signal.reason[:40]}")
            return old_signal
        
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
        ml_proba = ml_pred.get('proba', [0.5, 0.5])
        
        # 保存当前ML信息供日志使用
        self._last_ml_info = {
            'direction': ml_direction,
            'confidence': ml_confidence,
            'proba_short': ml_proba[0],
            'proba_long': ml_proba[1],
            'available': ml_available
        }
        
        # ⭐ ML环境检测（带一键关停开关）
        self.ml_regime_result = None
        self.ml_adjustments = None
        ml_adjustments = {'position_mult': 1.0, 'use_limit_order': True, 'confidence_boost': 0.0, 'block_new_position': False}
        
        if self.ml_regime_enabled and self.ml_regime_detector and ml_available:
            try:
                from ml_regime_detector import MLInput
                
                ml_input = MLInput(
                    direction=ml_direction,
                    confidence=ml_confidence,
                    proba_long=ml_proba[1],
                    proba_short=ml_proba[0]
                )
                
                self.ml_regime_result = self.ml_regime_detector.detect(ml_input)
                
                # 子开关：是否允许覆盖技术环境
                if CONFIG.get("ML_REGIME_OVERRIDE_ENABLED", True):
                    final_regime, ml_adjustments = self.ml_regime_detector.get_regime_mapping(
                        self.ml_regime_result.regime,
                        regime.value
                    )
                    
                    # 如果ML覆盖，更新环境
                    if ml_adjustments.get('override_regime'):
                        old_regime = regime
                        regime = MarketRegime[ml_adjustments['override_regime']]
                        logger.info(f"[ML整合] {old_regime.value} → {regime.value} "
                                   f"(原因: {self.ml_regime_result.reason})")
                
                logger.debug(f"[ML环境] 检测={self.ml_regime_result.regime.name}, "
                           f"建议={self.ml_regime_result.recommended_action}, "
                           f"仓位倍数={ml_adjustments['position_mult']}")
                
                # 🆕 V2可视化输出（如果启用V2且配置允许）
                if (CONFIG.get("ML_REGIME_VERSION") == "v2" and 
                    self.v2_visualizer and
                    CONFIG.get("ML_REGIME_V2_ENABLE_VISUALIZATION", True)):
                    try:
                        viz_output = self.v2_visualizer.format_regime_bar(
                            regime=self.ml_regime_result.regime.name,
                            confidence=self.ml_regime_result.confidence,
                            probabilities=getattr(self.ml_regime_result, 'probabilities', None)
                        )
                        
                        # ========== 日志优化：只有变化时才输出 ==========
                        current_viz_key = f"{self.ml_regime_result.regime.name}_{int(self.ml_regime_result.confidence*10)}"
                        if not hasattr(self, '_last_viz_key') or self._last_viz_key != current_viz_key:
                            print(f"\n{viz_output}")
                            self._last_viz_key = current_viz_key
                        # else: 相同状态，跳过输出
                    except Exception as e:
                        logger.debug(f"V2可视化输出失败: {e}")
                
                # 存储ML调整参数供后续使用
                self.ml_adjustments = ml_adjustments
                
            except Exception as e:
                logger.error(f"[ML环境] 检测异常: {e}")
                # 故障保护：自动关停
                if CONFIG.get("ML_REGIME_AUTO_DISABLE_ON_ERROR", True):
                    self.ml_regime_enabled = False
                    logger.warning("⚠️ ML环境检测模块已自动关停（故障保护）")
        else:
            if not self.ml_regime_enabled:
                logger.debug("[ML环境] 模块已停用（一键关停开关），使用纯技术指标")
            elif not ml_available:
                logger.debug("[ML环境] ML模型未训练，跳过环境检测")
        
        # 技术指标信号
        tech_signal = self._technical_signal(df_feat, current, regime)
        
        # ========== 时段过滤：凌晨2-5点降低交易频率 ==========
        current_hour = datetime.now().hour
        if 2 <= current_hour <= 5 and not has_position:
            # 凌晨时段提高置信度门槛
            if ml_confidence < 0.98:
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
        
        # 4. 震荡市细分策略（传递ml_direction用于放宽条件）
        if regime == MarketRegime.SIDEWAYS:
            return self._sideways_strategy(
                df_feat, current, atr, ml_confidence, funding_rate,
                ml_available, direction_bias='neutral', ml_direction=ml_direction
            )
        
        if regime == MarketRegime.SIDEWAYS_UP:
            return self._sideways_strategy(
                df_feat, current, atr, ml_confidence, funding_rate,
                ml_available, direction_bias='long', ml_direction=ml_direction
            )
        
        if regime == MarketRegime.SIDEWAYS_DOWN:
            return self._sideways_strategy(
                df_feat, current, atr, ml_confidence, funding_rate,
                ml_available, direction_bias='short', ml_direction=ml_direction
            )
        
        # 5. 趋势市：ML为主，必须顺势（核心修复）
        ml_threshold = CONFIG.get("ML_CONFIDENCE_THRESHOLD", 0.70)  # ML顺势阈值0.70
        ml_signal_blocked = False  # 标志：ML信号是否被阻止
        
        if ml_available and ml_confidence >= ml_threshold:
            action = 'BUY' if ml_direction == 1 else 'SELL'
            
            # ========== 新增：趋势市顺势过滤（核心修复）==========
            is_counter_trend = (
                (regime == MarketRegime.TRENDING_UP and action == 'SELL') or
                (regime == MarketRegime.TRENDING_DOWN and action == 'BUY')
            )
            
            if is_counter_trend:
                # 逆势交易需要高置信度（趋势市0.90，震荡市0.85）
                counter_trend_threshold = CONFIG.get("COUNTER_TREND_ML_THRESHOLD_TREND", 0.90)
                if ml_confidence < counter_trend_threshold:
                    # ML方向转文字
                    ml_dir_str = "看多" if ml_direction == 1 else "看空" if ml_direction == -1 else "观望"
                    
                    # 日志优化：同一原因不重复输出，5分钟冷却期
                    block_reason = f"逆势_{regime.value}_{ml_direction}"
                    now = time.time()
                    cooldown_secs = 300  # 5分钟
                    
                    last_reason = getattr(self, '_last_ml_block_reason', None)
                    last_time = getattr(self, '_last_ml_block_time', 0)
                    
                    if last_reason != block_reason or (now - last_time) > cooldown_secs:
                        logger.info(f"[ML过滤] 逆势交易被阻止，尝试技术指标: {regime.value} + ML{ml_dir_str} "
                                   f"(置信度:{ml_confidence:.2f} < 阈值:{counter_trend_threshold})")
                        self._last_ml_block_reason = block_reason
                        self._last_ml_block_time = now
                    else:
                        logger.debug(f"[ML过滤] 逆势阻止中(同前): {regime.value} + ML{ml_dir_str}")
                    
                    # 关键修复：标记ML信号被阻止，跳过ML信号执行块
                    ml_signal_blocked = True
                else:
                    # 高置信度逆势信号，允许但标记为高风险
                    ml_dir_str = "看多" if ml_direction == 1 else "看空"
                    logger.warning(f"⚠️ 允许高置信度逆势交易: {regime.value} + ML{ml_dir_str} (置信度:{ml_confidence:.2f}, "
                                  f"做空:{ml_pred.get('proba',[0,0])[0]:.2f}, 做多:{ml_pred.get('proba',[0,0])[1]:.2f})")
            
            # 如果ML逆势信号被阻止，跳过ML信号执行块，让流程走到技术指标判断
            if not ml_signal_blocked:
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
                
                # 趋势方向描述
                trend_direction_map = {
                    MarketRegime.TRENDING_UP: "上涨趋势",
                    MarketRegime.TRENDING_DOWN: "下跌趋势",
                    MarketRegime.SIDEWAYS: "震荡",
                    MarketRegime.SIDEWAYS_UP: "震荡上行",
                    MarketRegime.SIDEWAYS_DOWN: "震荡下行",
                    MarketRegime.CONSOLIDATION: "盘整待破",
                    MarketRegime.BREAKOUT: "突破",
                    MarketRegime.BREAKDOWN: "插针暴跌",
                    MarketRegime.PUMP: "爆拉",
                    MarketRegime.HIGH_VOL: "高波动",
                    MarketRegime.LOW_VOL: "低波动",
                    MarketRegime.REVERSAL: "趋势反转"
                }
                trend_direction = trend_direction_map.get(regime, regime.value)
                
                # 创建信号并填充ML详细信息
                signal = TradingSignal(
                    action, ml_confidence, SignalSource.ML,
                    signal_desc,
                    atr, sl_price, tp_price, regime, funding_rate,
                    {'ml_proba': ml_pred.get('proba'), 'is_counter_trend': is_counter_trend},
                    ml_direction=ml_direction,
                    ml_confidence=ml_confidence,
                    ml_proba_short=ml_proba[0],
                    ml_proba_long=ml_proba[1],
                    ml_threshold=counter_trend_threshold if is_counter_trend else ml_threshold,
                    is_counter_trend=is_counter_trend,
                    trend_direction=trend_direction
                )
                
                # 确保ML信息正确设置（防止关键字参数未生效）
                signal.ml_direction = ml_direction
                signal.ml_confidence = ml_confidence
                signal.ml_proba_short = ml_proba[0]
                signal.ml_proba_long = ml_proba[1]
                
                # 应用市场辅助数据微调（非主导，仅轻微调整）
                market_context = self._get_market_context()
                return self._apply_market_context_adjustment(signal, market_context)
            # 如果ML被阻止，代码会继续执行到下面的技术指标判断部分
        
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
            
            # 技术指标信号也需要顺势检查（在趋势市中）
            action = tech_signal['action']
            tech_is_counter_trend = (
                (regime == MarketRegime.TRENDING_UP and action == 'SELL') or
                (regime == MarketRegime.TRENDING_DOWN and action == 'BUY')
            )
            tech_is_with_trend = (
                (regime == MarketRegime.TRENDING_UP and action == 'BUY') or
                (regime == MarketRegime.TRENDING_DOWN and action == 'SELL')
            )
            
            # 核心修复：趋势市中，技术指标只做顺势，不做逆势
            if tech_is_counter_trend:
                logger.info(f"[技术指标过滤] 趋势市中拒绝逆势交易: {regime.value} + {action} | "
                           f"原因: {tech_signal['reason']}")
                signal = TradingSignal(
                    'HOLD', 0.5, SignalSource.TECHNICAL,
                    f'技术指标逆势被阻止({regime.value}+{action})',
                    atr, sl_price=0, tp_price=0, regime=regime, funding_rate=funding_rate,
                    ml_direction=ml_direction if 'ml_direction' in locals() else 0,
                    ml_confidence=ml_confidence if 'ml_confidence' in locals() else 0,
                    ml_proba_short=ml_proba[0] if 'ml_proba' in locals() else 0.5,
                    ml_proba_long=ml_proba[1] if 'ml_proba' in locals() else 0.5,
                    is_counter_trend=True,
                    trend_direction=regime.value
                )
                # 确保ML信息设置
                signal.ml_direction = ml_direction if 'ml_direction' in locals() else 0
                signal.ml_confidence = ml_confidence if 'ml_confidence' in locals() else 0
                return signal
            
            # 构建详细日志
            trend_type = "顺势" if tech_is_with_trend else "震荡"
            logger.info(f"[技术指标] {action}信号 ({trend_type}) | 置信度:{tech_signal['confidence']:.2f} | "
                       f"{tech_signal['reason']} | 环境:{regime.value} | 持仓检查已跳过")
            
            sl_price, tp_price = self._calculate_sl_tp(action, current_price, atr, regime)
            
            # 如果有ML信息，一并记录（这是ML被阻止后的备选）
            signal = TradingSignal(
                action, tech_signal['confidence'], SignalSource.TECHNICAL,
                f"{tech_signal['reason']}({trend_type})",
                atr, sl_price, tp_price, regime, funding_rate,
                features={'ml_proba': [ml_proba[0], ml_proba[1]] if 'ml_proba' in locals() else [0.5, 0.5]},
                ml_direction=ml_direction if 'ml_direction' in locals() else 0,
                ml_confidence=ml_confidence if 'ml_confidence' in locals() else 0,
                ml_proba_short=ml_proba[0] if 'ml_proba' in locals() else 0.5,
                ml_proba_long=ml_proba[1] if 'ml_proba' in locals() else 0.5,
                is_counter_trend=False,
                trend_direction=regime.value
            )
            
            return signal
        
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
    
    def _load_model_if_exists(self):
        """加载外部训练的模型（由定时训练服务维护）"""
        if not self.ml_model.is_trained:
            self.ml_model.load("ml_model_trained.pkl")
    
    def _ensure_model_trained(self, df: pd.DataFrame):
        """确保模型已训练 - 由外部定时服务维护，这里只加载"""
        self._load_model_if_exists()
    
    def _technical_signal(self, df: pd.DataFrame, current, regime: MarketRegime = None) -> Dict:
        """纯技术指标信号（增强趋势市顺势交易）"""
        rsi = current.get('rsi_12', 50)
        macd_hist = current.get('macd_hist', 0)
        bb_position = current.get('bb_position', 0.5)
        
        # ========== 趋势市顺势交易信号 ==========
        if regime in [MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN]:
            ma10 = current.get('ma_10', current['close'])
            ma20 = current.get('ma_20', current['close'])
            ma55 = current.get('ma_55', current['close'])
            close = current['close']
            volume_ratio = current.get('volume_ratio', 1.0)
            
            # 趋势上涨：均线多头排列 + 价格健康回调后延续
            if regime == MarketRegime.TRENDING_UP:
                # 条件1: 均线多头排列 + 价格接近MA10/MA20支撑 + RSI健康(40-65)
                ma_bullish = ma10 > ma20 > ma55
                price_near_support = close < ma10 * 1.005 or close < ma20 * 1.01  # 接近短期均线
                rsi_healthy = 40 <= rsi <= 65  # RSI不超买
                
                if ma_bullish and price_near_support and rsi_healthy and macd_hist > -0.1:
                    return {
                        'action': 'BUY', 
                        'confidence': 0.62 + min(volume_ratio * 0.03, 0.05),  # 放量加分
                        'reason': f'趋势上涨顺势买入(均线多头,RSI:{rsi:.0f},回调支撑)'
                    }
                
                # 条件2: 强势延续，价格沿上轨运行
                if ma_bullish and bb_position > 0.6 and rsi < 70 and macd_hist > 0:
                    return {
                        'action': 'BUY',
                        'confidence': 0.58,
                        'reason': f'趋势上涨强势延续(RSI:{rsi:.0f},BB位置:{bb_position:.2f})'
                    }
            
            # 趋势下跌：均线空头排列 + 价格反弹遇阻
            if regime == MarketRegime.TRENDING_DOWN:
                # 条件1: 均线空头排列 + 价格接近MA10/MA20阻力 + RSI健康(35-60)
                ma_bearish = ma10 < ma20 < ma55
                price_near_resistance = close > ma10 * 0.995 or close > ma20 * 0.99
                rsi_healthy = 35 <= rsi <= 60
                
                if ma_bearish and price_near_resistance and rsi_healthy and macd_hist < 0.1:
                    return {
                        'action': 'SELL',
                        'confidence': 0.62 + min(volume_ratio * 0.03, 0.05),
                        'reason': f'趋势下跌顺势做空(均线空头,RSI:{rsi:.0f},反弹阻力)'
                    }
                
                # 条件2: 弱势延续，价格沿下轨运行
                if ma_bearish and bb_position < 0.4 and rsi > 30 and macd_hist < 0:
                    return {
                        'action': 'SELL',
                        'confidence': 0.58,
                        'reason': f'趋势下跌弱势延续(RSI:{rsi:.0f},BB位置:{bb_position:.2f})'
                    }
        
        # ========== 原有震荡市信号 ==========
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
        ml_available: bool = False, direction_bias: str = 'neutral', ml_direction: int = 0
    ) -> TradingSignal:
        """震荡市套利策略 - 智能版（逆势需ML高置信度支持）
        
        核心原则：
        - 顺势交易（震荡上行做多，震荡下行做空）：使用原设置条件
        - 逆势交易（震荡上行做空，震荡下行做多）：需ML高置信度(≥0.70)支持
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
        
        # 逆势交易ML置信度门槛（震荡市0.85，趋势市0.90）
        counter_trend_ml_threshold = CONFIG.get("COUNTER_TREND_ML_THRESHOLD_SIDEWAYS", 0.85)
        
        # 恢复原设置
        long_rsi_threshold = 40   # 原设置
        short_rsi_threshold = 60  # 原设置
        
        if direction_bias == 'long':
            long_conf_mult = 0.9
            short_conf_mult = 1.1
            regime_label = "震荡上行"
        elif direction_bias == 'short':
            long_conf_mult = 1.1
            short_conf_mult = 0.9
            regime_label = "震荡下行"
        else:
            long_conf_mult = 1.0
            short_conf_mult = 1.0
            regime_label = "震荡市"
        
        # ========== 下轨做多逻辑 ==========
        if (close < bb_lower * 1.01 and   # 恢复原设置
            rsi < long_rsi_threshold):      
            
            # 判断是否顺势：震荡上行(SIDEWAYS_UP)或普通震荡中做多都是顺势
            is_with_trend = (direction_bias in ['long', 'neutral'])
            is_counter_trend = (direction_bias == 'short')  # 震荡下行中做多是逆势
            
            # 顺势交易：原条件 + 区间过滤 + 固定盈亏比
            if is_with_trend:
                if (rsi_6 < 30 or volume_ratio > 1.2):
                    if funding_rate < funding_threshold:
                        # 区间位置过滤
                        pos_allowed, pos_reason = self._check_daily_position_filter('BUY', close, df)
                        if not pos_allowed:
                            # 日志优化：不重复输出相同原因
                            pos_block_key = f"BUY_{position_pct:.0f}"
                            if not hasattr(self, '_last_pos_block_key') or self._last_pos_block_key != pos_block_key:
                                logger.info(f"[位置过滤] 下轨做多被阻止: {pos_reason}")
                                self._last_pos_block_key = pos_block_key
                            return TradingSignal(
                                'HOLD', min_confidence, SignalSource.TECHNICAL,
                                f'{regime_label}-下轨做多被过滤({pos_reason})',
                                atr, regime=MarketRegime.SIDEWAYS, funding_rate=funding_rate
                            )
                        
                        conf = max(min_confidence * long_conf_mult, ml_confidence if ml_available else 0)
                        
                        # 使用固定盈亏比计算SL/TP
                        sl_price, tp_price = self._calculate_fixed_sl_tp(close, 'BUY', atr)
                        
                        # ========== 盈亏比检查（留痕）==========
                        if CONFIG.get("ENABLE_RR_FILTER", True):
                            risk = close - sl_price
                            reward = tp_price - close
                            rr_ratio = reward / risk if risk > 0 else 0
                            min_rr = CONFIG.get("MIN_RR_RATIO", 2.0)
                            rr_exemption = CONFIG.get("RR_FILTER_ML_EXEMPTION", 0.85)
                            
                            # 检查是否满足盈亏比或ML豁免
                            if rr_ratio < min_rr and ml_confidence < rr_exemption:
                                # 留痕：盈亏比不足且未豁免
                                rr_block_key = f"RR_BUY_{rr_ratio:.1f}_{ml_confidence:.2f}"
                                if not hasattr(self, '_last_rr_block_key') or self._last_rr_block_key != rr_block_key:
                                    logger.info(f"[盈亏比过滤] 下轨做多被阻止: R:R=1:{rr_ratio:.2f}<{min_rr}, ML={ml_confidence:.2f}")
                                    self._last_rr_block_key = rr_block_key
                                return TradingSignal(
                                    'HOLD', conf, SignalSource.TECHNICAL,
                                    f'{regime_label}-盈亏比不足',
                                    atr, regime=MarketRegime.SIDEWAYS, funding_rate=funding_rate
                                )
                            elif rr_ratio < min_rr and ml_confidence >= rr_exemption:
                                # 留痕：ML豁免（较少发生，记录）
                                logger.info(f"[盈亏比豁免] ML高置信度({ml_confidence:.2f})豁免R:R检查")
                        
                        return TradingSignal(
                            'BUY', conf, SignalSource.GRID,
                            f'{regime_label}-下轨做多(RSI:{rsi:.0f})',
                            atr, sl_price, tp_price,
                            MarketRegime.SIDEWAYS_UP if direction_bias == 'long' else MarketRegime.SIDEWAYS,
                            funding_rate
                        )
            
            # 逆势交易：需要ML高置信度支持（新增逻辑）
            elif is_counter_trend:
                if ml_available and ml_direction == 1 and ml_confidence >= counter_trend_ml_threshold:
                    conf = max(min_confidence * long_conf_mult, ml_confidence)
                    sl_price = close - atr * 1.5
                    tp_price = bb_mid
                    
                    logger.info(f"[震荡逆势] 震荡下行中做多（ML支持）: 置信度{ml_confidence:.2f} >= {counter_trend_ml_threshold}")
                    
                    return TradingSignal(
                        'BUY', conf, SignalSource.GRID,
                        f'{regime_label}-下轨做多-ML支持({ml_confidence:.2f})',
                        atr, sl_price, tp_price,
                        MarketRegime.SIDEWAYS,
                        funding_rate
                    )
                else:
                    logger.debug(f"[震荡过滤] 震荡下行中做多被阻止: ML置信度{ml_confidence:.2f} < {counter_trend_ml_threshold} 或 ML方向不对")
        
        # ========== 上轨做空逻辑 ==========
        if (close > bb_upper * 0.99 and   # 恢复原设置
            rsi > short_rsi_threshold):     
            
            # 判断是否顺势
            is_with_trend = (direction_bias in ['short', 'neutral'])
            is_counter_trend = (direction_bias == 'long')  # 震荡上行中做空是逆势
            
            # 顺势交易：原条件 + 区间过滤 + 固定盈亏比
            if is_with_trend:
                if (rsi_6 > 70 or volume_ratio > 1.2):
                    if funding_rate > -funding_threshold:
                        # 区间位置过滤
                        pos_allowed, pos_reason = self._check_daily_position_filter('SELL', close, df)
                        if not pos_allowed:
                            # 日志优化：不重复输出相同原因
                            pos_block_key = f"SELL_{position_pct:.0f}"
                            if not hasattr(self, '_last_pos_block_key') or self._last_pos_block_key != pos_block_key:
                                logger.info(f"[位置过滤] 上轨做空被阻止: {pos_reason}")
                                self._last_pos_block_key = pos_block_key
                            return TradingSignal(
                                'HOLD', min_confidence, SignalSource.TECHNICAL,
                                f'{regime_label}-上轨做空被过滤({pos_reason})',
                                atr, regime=MarketRegime.SIDEWAYS, funding_rate=funding_rate
                            )
                        
                        conf = max(min_confidence * short_conf_mult, ml_confidence if ml_available else 0)
                        
                        # 使用固定盈亏比计算SL/TP
                        sl_price, tp_price = self._calculate_fixed_sl_tp(close, 'SELL', atr)
                        
                        # ========== 盈亏比检查（留痕）==========
                        if CONFIG.get("ENABLE_RR_FILTER", True):
                            risk = sl_price - close
                            reward = close - tp_price
                            rr_ratio = reward / risk if risk > 0 else 0
                            min_rr = CONFIG.get("MIN_RR_RATIO", 2.0)
                            rr_exemption = CONFIG.get("RR_FILTER_ML_EXEMPTION", 0.85)
                            
                            # 检查是否满足盈亏比或ML豁免
                            if rr_ratio < min_rr and ml_confidence < rr_exemption:
                                # 留痕：盈亏比不足且未豁免
                                rr_block_key = f"RR_SELL_{rr_ratio:.1f}_{ml_confidence:.2f}"
                                if not hasattr(self, '_last_rr_block_key') or self._last_rr_block_key != rr_block_key:
                                    logger.info(f"[盈亏比过滤] 上轨做空被阻止: R:R=1:{rr_ratio:.2f}<{min_rr}, ML={ml_confidence:.2f}")
                                    self._last_rr_block_key = rr_block_key
                                return TradingSignal(
                                    'HOLD', conf, SignalSource.TECHNICAL,
                                    f'{regime_label}-盈亏比不足',
                                    atr, regime=MarketRegime.SIDEWAYS, funding_rate=funding_rate
                                )
                            elif rr_ratio < min_rr and ml_confidence >= rr_exemption:
                                # 留痕：ML豁免（较少发生，记录）
                                logger.info(f"[盈亏比豁免] ML高置信度({ml_confidence:.2f})豁免R:R检查")
                        
                        return TradingSignal(
                            'SELL', conf, SignalSource.GRID,
                            f'{regime_label}-上轨做空(RSI:{rsi:.0f})',
                            atr, sl_price, tp_price,
                            MarketRegime.SIDEWAYS_DOWN if direction_bias == 'short' else MarketRegime.SIDEWAYS,
                            funding_rate
                        )
            
            # 逆势交易：需要ML高置信度支持（新增逻辑）
            elif is_counter_trend:
                if ml_available and ml_direction == -1 and ml_confidence >= counter_trend_ml_threshold:
                    conf = max(min_confidence * short_conf_mult, ml_confidence)
                    sl_price = close + atr * 1.5
                    tp_price = bb_mid
                    
                    logger.info(f"[震荡逆势] 震荡上行中做空（ML支持）: 置信度{ml_confidence:.2f} >= {counter_trend_ml_threshold}")
                    
                    return TradingSignal(
                        'SELL', conf, SignalSource.GRID,
                        f'{regime_label}-上轨做空-ML支持({ml_confidence:.2f})',
                        atr, sl_price, tp_price,
                        MarketRegime.SIDEWAYS,
                        funding_rate
                    )
                else:
                    logger.debug(f"[震荡过滤] 震荡上行中做空被阻止: ML置信度{ml_confidence:.2f} < {counter_trend_ml_threshold} 或 ML方向不对")
        
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
        if ml_available and ml_direction == -1 and ml_confidence >= 0.98:
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
            if ml_available and ml_direction == -1 and ml_confidence >= 0.98:
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
        
        # 计算当前盈亏（包含杠杆，与实盘一致）
        leverage = CONFIG.get('LEVERAGE', 5)
        is_short = position_side in ['SELL', 'SHORT']
        pnl_pct_raw = (entry_price - current_price) / entry_price if is_short else (current_price - entry_price) / entry_price
        pnl_pct = pnl_pct_raw * leverage  # 加杠杆后的盈亏百分比
        
        # 更新峰值盈亏（用于移动止盈）
        if pnl_pct > self.position_peak_pnl:
            self.position_peak_pnl = pnl_pct
            trailing_drawback = CONFIG.get("TRAILING_STOP_DRAWBACK_PCT", 0.30)
            self.position_trailing_stop = self.position_peak_pnl * (1 - trailing_drawback)
        
        # 获取止盈管理器
        tp_manager = get_tp_manager()
        
        # ========== 1. 动态止损（严格）- 最高优先级 ==========
        sl_mult = CONFIG.get("STOP_LOSS_ATR_MULT", 2.0)
        sl_pct = -sl_mult * atr / entry_price * leverage  # 乘以杠杆，与pnl_pct一致
        
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
        
        # ========== 2. 盈利保护（峰值回撤50%强制平仓）==========
        profit_prot_pct = CONFIG.get("PROFIT_PROTECTION_ENABLE_PCT", 0.005) * leverage  # 乘以杠杆匹配pnl_pct
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
        
        # ========== 3. 移动止盈（峰值回撤30%）==========
        trailing_enable = CONFIG.get("TRAILING_STOP_ENABLE_PCT", 0.008) * leverage  # 乘以杠杆匹配pnl_pct
        
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
        
        # ========== 4. 纯固定止盈（最简单可靠）==========
        fixed_tp_pct = CONFIG.get("FIXED_TP_PCT", 0.016) * leverage  # 1.6%杠杆后
        
        if pnl_pct >= fixed_tp_pct:
            record = TPSignalRecord(
                timestamp=datetime.now(),
                position_id=f"{self.symbol}_{datetime.now().timestamp()}",
                symbol=self.symbol,
                side=position_side,
                entry_price=entry_price,
                exit_price=current_price,
                pnl_pct=pnl_pct,
                pnl_usdt=0,
                signal_type=TPSignalType.ATR_FIXED_TREND,  # 复用类型
                signal_description=f'固定止盈触发(目标{fixed_tp_pct*100:.2f}%)',
                market_regime=regime.value,
                current_price=current_price
            )
            tp_manager.record_signal(record)
            
            logger.info(f"🎯 [固定止盈] 目标={fixed_tp_pct*100:.2f}%, 当前={pnl_pct*100:.2f}%, 超过即平")
            return TradingSignal(
                'CLOSE', 1.0, SignalSource.TECHNICAL,
                f'固定止盈({pnl_pct*100:.2f}%)',
                atr, regime=regime, funding_rate=funding_rate
            )
        else:
            # 接近目标时输出日志
            if pnl_pct >= fixed_tp_pct * 0.8:
                logger.info(f"[固定止盈接近] 目标={fixed_tp_pct*100:.2f}%, 当前={pnl_pct*100:.2f}%, 还差{(fixed_tp_pct-pnl_pct)*100:.2f}%")
        
        # [保留代码但不使用] ========== 5. 分级ATR止盈（后备）==========
        # 当前策略：纯固定1.6%止盈，注释掉ATR后备
        """
        if regime == MarketRegime.SIDEWAYS:
            tp_sideways_mult = CONFIG.get("TP_SIDEWAYS_ATR_MULT", 4.0)
            tp_pct = tp_sideways_mult * atr / entry_price * leverage
            
            if pnl_pct >= tp_pct:
                record = TPSignalRecord(...)
                tp_manager.record_signal(record)
                return TradingSignal('CLOSE', ...)
        else:
            tp_trend_mult = CONFIG.get("TP_TRENDING_ATR_MULT", 8.0)
            tp_pct = tp_trend_mult * atr / entry_price * leverage
            
            if pnl_pct >= tp_pct:
                record = TPSignalRecord(...)
                tp_manager.record_signal(record)
                return TradingSignal('CLOSE', ...)
        """
        
        # ========== 6. ML趋势反转 ==========
        if self.ml_model.is_trained:
            ml_pred = self.ml_model.predict(df)
            
            ml_reverse_pnl = CONFIG.get("PROFIT_PROTECTION_ENABLE_PCT", 0.015) * 3 * leverage  # 乘以杠杆匹配pnl_pct
            ml_reverse_conf = CONFIG.get("ML_CONFIDENCE_THRESHOLD", 0.55) + 0.19
            
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
        base_risk = balance * CONFIG.get("MAX_RISK_PCT", 0.025)
        
        # ========== 1. 置信度分级（从配置读取）==========
        if confidence >= 0.80:
            confidence_mult = CONFIG.get("CONFIDENCE_MULT_EXTREME", 2.5)
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
        if confidence >= 0.98:
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
        
        # 冷却期策略：止盈后无冷却，止损后冷却
        if pnl_pct > 0:
            # 止盈后：完全清除冷却期，允许立即寻找新机会
            self.cooldown_seconds = 0
            logger.info(f"⏱️ 止盈平仓: 无冷却期，立即寻找新机会")
        else:
            # 止损后：设置冷却期防止连续亏损
            loss_cooldown = CONFIG.get("COOLDOWN_AFTER_LOSS", 60)
            self.cooldown_seconds = max(self.cooldown_seconds, loss_cooldown)
            logger.info(f"⏱️ 止损平仓: 冷却期{self.cooldown_seconds}秒")


# ==================== 数据库管理 ====================
class TradeDatabase:
    """交易数据库管理"""
    
    def __init__(self, db_path: str = 'v12_optimized.db'):
        self.db_path = db_path
        self.init_tables()
    
    def get_connection(self):
        return sqlite3.connect(self.db_path, check_same_thread=False)
    
    def init_tables(self):
        """初始化表结构（支持迁移）"""
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
        
        # 迁移：添加ML相关字段（如果不存在）
        self._migrate_add_ml_columns(conn)
        
        conn.close()
    
    def _migrate_add_ml_columns(self, conn):
        """迁移：添加ML分析字段到signals表"""
        try:
            # 检查现有列
            cursor = conn.execute("PRAGMA table_info(signals)")
            existing_cols = {row[1] for row in cursor.fetchall()}
            
            # 需要添加的新列
            new_columns = {
                'ml_direction': 'INTEGER',
                'ml_confidence': 'REAL',
                'ml_proba_short': 'REAL',
                'ml_proba_long': 'REAL',
                'ml_threshold': 'REAL',
                'is_counter_trend': 'BOOLEAN',
                'trend_direction': 'TEXT'
            }
            
            added = []
            for col_name, col_type in new_columns.items():
                if col_name not in existing_cols:
                    conn.execute(f"ALTER TABLE signals ADD COLUMN {col_name} {col_type}")
                    added.append(col_name)
            
            if added:
                logger.info(f"✅ 数据库迁移完成: 添加列 {added}")
            
            conn.commit()
        except Exception as e:
            logger.warning(f"数据库迁移失败（可能已是最新版本）: {e}")
    
    def log_trade(self, symbol: str, side: str, entry_price: float,
                  exit_price: float, qty: float, pnl_pct: float,
                  pnl_usdt: float, result: str, reason: str,
                  signal_source: str, confidence: float,
                  regime: str, funding_rate: float, order_type: str = 'TAKER'):
        """记录交易"""
        conn = self.get_connection()
        try:
            conn.execute('''
                INSERT INTO trades (timestamp, symbol, side, entry_price, exit_price,
                                  qty, pnl_pct, pnl_usdt, result, reason,
                                  signal_source, confidence, regime, funding_rate, order_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                datetime.now().isoformat(), symbol, side, entry_price, exit_price,
                qty, pnl_pct, pnl_usdt, result, reason,
                signal_source, confidence, regime, funding_rate, order_type
            ))
        except sqlite3.OperationalError:
            # 兼容旧数据库（缺少order_type字段）
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
            f"TRADE | {symbol} | {side} | {result} | {order_type} | "
            f"PnL:{pnl_pct*100:+.2f}% | ${pnl_usdt:+.2f} | {reason}"
        )
    
    def log_signal(self, symbol: str, signal: TradingSignal,
                   price: float, executed: bool = False):
        """记录信号（包含ML详细信息，兼容旧数据库）"""
        conn = self.get_connection()
        
        try:
            # 尝试使用完整字段（新数据库）
            conn.execute('''
                INSERT INTO signals (timestamp, symbol, action, confidence, source,
                                   reason, price, atr, regime, executed,
                                   ml_direction, ml_confidence, ml_proba_short, ml_proba_long,
                                   ml_threshold, is_counter_trend, trend_direction)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                datetime.now().isoformat(), symbol, signal.action,
                signal.confidence, signal.source.value, signal.reason,
                price, signal.atr, signal.regime.value, executed,
                signal.ml_direction, signal.ml_confidence, 
                signal.ml_proba_short, signal.ml_proba_long,
                signal.ml_threshold, signal.is_counter_trend, signal.trend_direction
            ))
        except sqlite3.OperationalError as e:
            # 兼容旧数据库（缺少ML字段）
            if 'no column named ml_direction' in str(e):
                logger.debug("使用兼容模式记录信号（旧数据库）")
                conn.execute('''
                    INSERT INTO signals (timestamp, symbol, action, confidence, source,
                                       reason, price, atr, regime, executed)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    datetime.now().isoformat(), symbol, signal.action,
                    signal.confidence, signal.source.value, signal.reason,
                    price, signal.atr, signal.regime.value, executed
                ))
                # 触发迁移
                self._migrate_add_ml_columns(conn)
            else:
                raise
        
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
        
        # 手续费配置 (基于币安实际费率：Taker 0.05%, Maker 0.02%)
        self.taker_fee_rate = CONFIG.get("TAKER_FEE_RATE", 0.0005)  # 0.05%
        self.maker_fee_rate = CONFIG.get("MAKER_FEE_RATE", 0.0002)  # 0.02%
        # 当前使用市价单，全部为Taker
        self.fee_rate = self.taker_fee_rate
        
        # 重构新增: 先初始化出场信号适配器 (2026-03-24)
        self.exit_adapter = ExitSignalAdapter(CONFIG)
        
        # 组件
        self.signal_gen = SignalGenerator()
        self.signal_gen.exit_adapter = self.exit_adapter  # 传递 exit_adapter
        self.risk_mgr = RiskManager()
        self.db = TradeDatabase()
        
        # 重构新增: PositionManager (2026-03-24)
        from position_manager import PositionManager
        self.position_manager = PositionManager(self.symbol, CONFIG)
        # 兼容旧代码访问
        self._pm = self.position_manager
        
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
            
        except Exception as e:
            logger.error(f"设置杠杆失败: {e}")
        
        # 同步当前持仓（独立try，确保执行）
        try:
            logger.info("🔄 正在同步交易所持仓...")
            self._sync_position()
        except Exception as e:
            logger.error(f"同步持仓失败: {e}")
            self.position = None
    
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
                # 统一格式：side 用 BUY/SELL（与 execute_open 一致）
                api_side = pos['side']
                unified_side = 'BUY' if api_side in ['LONG', 'BUY'] else 'SELL'
                
                self.position = {
                    'side': unified_side,  # 统一用 BUY/SELL
                    'qty': pos['qty'],
                    'entry_price': pos['entryPrice'],
                    'leverage': pos['leverage']
                }
                logger.info(
                    f"📊 同步持仓: {api_side} {pos['qty']} @ ${pos['entryPrice']:.2f} "
                    f"| 未实现PnL: ${pos.get('unrealizedProfit', 0):.2f}"
                )
            else:
                # 日志优化：只在状态变化时输出无持仓日志
                if self.position is not None:
                    logger.info("📊 当前无持仓")
                else:
                    logger.debug("📊 同步持仓: 无持仓")
                self.position = None
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
    
    def _place_limit_with_retry(self, side: str, qty: float, base_price: float, 
                                  reduce_only: bool = False, max_retries: int = 2) -> tuple:
        """
        限价单下单，失败时重试（价格逐步向市价靠拢），最后 fallback 到市价单
        
        策略:
        - 第1次: 挂价偏离 0.05% (最优Maker价格)
        - 第2次: 挂价偏离 0.02% (更接近市价，增加成交概率)
        - 失败: 转为市价单
        
        Returns:
            (order_dict, order_type, executed_price)
            order_type: 'MAKER' or 'TAKER' or 'HYBRID'
        """
        # 价格偏移: 贪心策略，先挂最优价，再向市价靠拢
        # 第1次: 0.05%偏离（最有利价格，成交概率中等）
        # 第2次: 0.02%偏离（接近市价，成交概率高）
        price_offsets = [0.0005, 0.0002]  # 0.05%, 0.02%
        wait_time = CONFIG.get("LIMIT_WAIT_TIME", 0.8)  # 每次等0.8秒，总共1.6秒
        
        for attempt in range(max_retries):
            limit_price_offset = price_offsets[attempt]
            
            # 计算限价价格
            if side == 'BUY':
                limit_price = base_price * (1 - limit_price_offset)
            else:  # SELL
                limit_price = base_price * (1 + limit_price_offset)
            
            logger.info(f"[限价单] 尝试{attempt+1}/{max_retries}: {side} {qty} @ ${limit_price:.2f} "
                       f"(偏离{limit_price_offset*100:.3f}%)")
            
            # 下限价单
            order = self._retry_api_call(
                self.api.place_limit_order, 3,
                self.symbol, side, qty, limit_price, 
                time_in_force="IOC", reduce_only=reduce_only
            )
            
            if order and order.get('orderId'):
                order_id = order.get('orderId')
                
                # 等待系统轮询周期
                time.sleep(wait_time)
                
                # 检查订单状态 - 循环检查多次确保准确性
                filled = False
                avg_price = 0
                executed_qty = 0
                
                for check in range(3):  # 检查3次
                    try:
                        order_info = self.api._request(
                            'GET', '/fapi/v1/order', 
                            {'symbol': self.symbol, 'orderId': order_id},
                            signed=True
                        )
                        
                        if order_info:
                            status = order_info.get('status')
                            executed_qty = float(order_info.get('executedQty', 0))
                            avg_price = float(order_info.get('avgPrice', 0))
                            is_maker = order_info.get('isMaker', False)
                            
                            if status == 'FILLED':
                                filled = True
                                if avg_price <= 0:
                                    avg_price = limit_price
                                if is_maker:
                                    logger.info(f"[限价单] 成交成功 (Maker): {side} {qty} @ ${avg_price:.2f}")
                                else:
                                    logger.info(f"[限价单] 成交 (Taker): {side} {qty} @ ${avg_price:.2f}")
                                break
                            elif executed_qty > 0:
                                # 部分成交
                                filled = True
                                logger.info(f"[限价单] 部分成交: {executed_qty}/{qty} @ ${avg_price:.2f} (Maker={is_maker})")
                                break
                            elif status in ['CANCELED', 'REJECTED', 'EXPIRED']:
                                # 订单已取消，无需再处理
                                logger.info(f"[限价单] 订单已{status}，无需取消")
                                break
                        
                        if not filled and check < 2:
                            time.sleep(0.3)  # 再等0.3秒重试检查
                            
                    except Exception as e:
                        logger.warning(f"检查订单状态失败({check+1}/3): {e}")
                        if check < 2:
                            time.sleep(0.3)
                
                if filled:
                    # 根据实际成交类型返回
                    final_order_type = 'MAKER' if is_maker else 'TAKER'
                    if executed_qty >= qty * 0.99:  # 基本完全成交
                        return order, final_order_type, avg_price
                    else:
                        # 部分成交，取消剩余
                        try:
                            self.api.cancel_order(self.symbol, order_id)
                        except:
                            pass
                        remaining_qty = round(qty - executed_qty, 3)
                        if remaining_qty >= 0.001:
                            market_order = self._retry_api_call(
                                self.api.place_order, 3,
                                self.symbol, side, remaining_qty, reduce_only=reduce_only
                            )
                            if market_order:
                                # 部分Maker + 部分Taker = HYBRID
                                return market_order, 'HYBRID', avg_price
                        return order, final_order_type, avg_price
                else:
                    # 尝试取消订单 - 如果取消失败（订单已成交），则认为成交
                    try:
                        cancel_result = self.api.cancel_order(self.symbol, order_id)
                        if cancel_result and cancel_result.get('code') == -2011:
                            # 订单不存在或已成交
                            logger.warning(f"[限价单] 取消订单失败，可能已成交")
                            # 重新查询订单确认状态
                            order_info = self.api._request(
                                'GET', '/fapi/v1/order', 
                                {'symbol': self.symbol, 'orderId': order_id},
                                signed=True
                            )
                            if order_info and float(order_info.get('executedQty', 0)) > 0:
                                avg_price = float(order_info.get('avgPrice', 0))
                                is_maker = order_info.get('isMaker', False)
                                if avg_price <= 0:
                                    avg_price = limit_price
                                order_type = 'MAKER' if is_maker else 'TAKER'
                                logger.info(f"[限价单] 确认已成交: {side} @ ${avg_price:.2f} ({order_type})")
                                return order, order_type, avg_price
                    except Exception as e:
                        logger.warning(f"[限价单] 取消订单异常: {e}")
                        # 尝试查询确认
                        try:
                            order_info = self.api._request(
                                'GET', '/fapi/v1/order', 
                                {'symbol': self.symbol, 'orderId': order_id},
                                signed=True
                            )
                            if order_info and float(order_info.get('executedQty', 0)) > 0:
                                avg_price = float(order_info.get('avgPrice', 0))
                                is_maker = order_info.get('isMaker', False)
                                if avg_price <= 0:
                                    avg_price = limit_price
                                order_type = 'MAKER' if is_maker else 'TAKER'
                                logger.info(f"[限价单] 确认已成交: {side} @ ${avg_price:.2f} ({order_type})")
                                return order, order_type, avg_price
                        except:
                            pass
            
            # 获取最新价格用于下一次尝试
            new_price = self.api.get_price(self.symbol)
            if new_price and new_price > 0:
                base_price = new_price
                logger.info(f"[限价单] 重试用最新价格: ${base_price:.2f}")
        
        # 所有重试失败，转为市价单
        logger.warning(f"[限价单] 两次均未成交，转为市价单")
        order = self._retry_api_call(
            self.api.place_order, 3,
            self.symbol, side, qty, reduce_only=reduce_only
        )
        
        if order and order.get('orderId'):
            return order, 'TAKER', base_price
        else:
            return None, 'FAILED', 0
    
    def _place_limit_quick_then_taker(self, side: str, qty: float, base_price: float, 
                                       reduce_only: bool = False) -> tuple:
        """
        趋势市专用：轻微偏离限价单(0.01%)，等待足够时间，不成交再转Taker
        
        策略:
        - 挂价偏离仅0.01%（非常接近市价，Maker概率高）
        - 等待3秒（给足Maker成交时间）
        - 成交了享受0.02%费率
        - 没成交取消转Taker
        
        注意：根据实测，Maker成交可能需要5-10秒，不能太急
        
        Returns:
            (order_dict, order_type, executed_price)
        """
        limit_offset = CONFIG.get("LIMIT_PRICE_OFFSET", 0.0001)  # 0.01%偏离
        wait_time = CONFIG.get("LIMIT_WAIT_TIME", 1.0)  # 从配置读取等待时间（默认1秒）
        
        # 计算限价价格
        if side == 'BUY':
            limit_price = base_price * (1 - limit_offset)
        else:  # SELL
            limit_price = base_price * (1 + limit_offset)
        
        logger.info(f"[趋势限价] 尝试: {side} {qty} @ ${limit_price:.2f} (偏离0.01%, 等0.5秒)")
        
        # 下限价单
        order = self._retry_api_call(
            self.api.place_limit_order, 3,
            self.symbol, side, qty, limit_price, 
            time_in_force="IOC", reduce_only=reduce_only
        )
        
        if not order or not order.get('orderId'):
            logger.warning("[趋势限价] 下单失败，转市价单")
            order = self._retry_api_call(
                self.api.place_order, 3,
                self.symbol, side, qty, reduce_only=reduce_only
            )
            return order, 'TAKER', base_price
        
        order_id = order.get('orderId')
        
        # 等待0.5秒
        time.sleep(wait_time)
        
        # 检查订单状态
        try:
            order_info = self.api._request(
                'GET', '/fapi/v1/order', 
                {'symbol': self.symbol, 'orderId': order_id},
                signed=True
            )
            
            if order_info:
                status = order_info.get('status')
                executed_qty = float(order_info.get('executedQty', 0))
                avg_price = float(order_info.get('avgPrice', 0))
                is_maker = order_info.get('isMaker', False)  # 关键：检查是否是Maker
                
                if status == 'FILLED':
                    # 完全成交
                    if avg_price <= 0:
                        avg_price = limit_price
                    
                    if is_maker:
                        logger.info(f"[趋势限价] ✅ Maker成交: {side} {qty} @ ${avg_price:.2f} (省0.03%手续费)")
                        return order, 'MAKER', avg_price
                    else:
                        # LIMIT单但作为Taker成交（价格立即匹配）
                        logger.info(f"[趋势限价] ⚠️ LIMIT单作为Taker成交: {side} {qty} @ ${avg_price:.2f}")
                        return order, 'TAKER', avg_price
                elif executed_qty > 0:
                    # 部分成交
                    logger.info(f"[趋势限价] 部分成交: {executed_qty}/{qty}，剩余转Taker")
                    self.api.cancel_order(self.symbol, order_id)
                    remaining_qty = round(qty - executed_qty, 3)
                    if remaining_qty >= 0.001:
                        market_order = self._retry_api_call(
                            self.api.place_order, 3,
                            self.symbol, side, remaining_qty, reduce_only=reduce_only
                        )
                        if market_order:
                            return market_order, 'HYBRID', avg_price if avg_price > 0 else base_price
                    return order, 'HYBRID', avg_price if avg_price > 0 else base_price
                else:
                    # 未成交，立即取消转Taker
                    logger.info("[趋势限价] 未成交，立即转市价单")
                    try:
                        self.api.cancel_order(self.symbol, order_id)
                    except:
                        pass  # 取消失败可能是已成交，下面会处理
                    
                    # 检查是否实际上已成交（取消时可能刚好成交）
                    try:
                        order_info = self.api._request(
                            'GET', '/fapi/v1/order', 
                            {'symbol': self.symbol, 'orderId': order_id},
                            signed=True
                        )
                        if order_info:
                            executed_qty = float(order_info.get('executedQty', 0))
                            avg_price = float(order_info.get('avgPrice', 0))
                            is_maker = order_info.get('isMaker', False)
                            
                            if executed_qty > 0:
                                if avg_price <= 0:
                                    avg_price = limit_price
                                if is_maker:
                                    logger.info(f"[趋势限价] ✅ 实际Maker成交: @ ${avg_price:.2f}")
                                    return order, 'MAKER', avg_price
                                else:
                                    logger.info(f"[趋势限价] ⚠️ 实际Taker成交: @ ${avg_price:.2f}")
                                    return order, 'TAKER', avg_price
                    except:
                        pass
                    
                    # 确实未成交，转市价单
                    # 🔧 修复: 添加参数校验和调试日志
                    logger.debug(f"[转市价单] 参数检查: side={side!r}, qty={qty}, symbol={self.symbol}, reduce_only={reduce_only}")
                    if side not in ['BUY', 'SELL']:
                        logger.error(f"[BUG] 转市价单时 side 参数异常: {side!r}")
                        return None, 'FAILED', 0
                    
                    # 直接调用，不经过 _retry_api_call 避免参数传递问题
                    try:
                        order = self.api.place_order(self.symbol, side, qty, reduce_only=reduce_only)
                    except Exception as e:
                        logger.error(f"[转市价单] 失败: {e}")
                        order = None
                    return order, 'TAKER', base_price
        except Exception as e:
            logger.warning(f"[趋势限价] 检查状态失败: {e}，转市价单")
            try:
                self.api.cancel_order(self.symbol, order_id)
            except:
                pass
            order = self._retry_api_call(
                self.api.place_order, 3,
                self.symbol, side, qty, reduce_only=reduce_only
            )
            return order, 'TAKER', base_price
    
    def execute_open(self, signal: TradingSignal, price: float):
        """执行开仓（带详细ML日志）"""
        try:
            # ========== 防止重复开仓检查 ==========
            # 1. 检查内存中的持仓
            if self.position is not None:
                logger.warning(f"[开仓拦截] 已有持仓: {self.position['side']} {self.position['qty']}ETH，跳过")
                return False
            
            # 2. 同步检查币安API的实际持仓（双重保险）
            try:
                api_position = self.api.get_position(self.symbol)
                if api_position and api_position.get('qty', 0) > 0.0001:
                    logger.warning(f"[开仓拦截] API显示有持仓: {api_position['side']} {api_position['qty']}ETH，同步中...")
                    # 同步持仓到内存
                    self.position = {
                        'side': 'SELL' if api_position['side'] == 'SHORT' else 'BUY',
                        'qty': api_position['qty'],
                        'entry_price': api_position['entryPrice'],
                        'sl_price': 0,
                        'tp_price': 0,
                        'entry_time': datetime.now()
                    }
                    return False
            except Exception as e:
                logger.warning(f"[开仓检查] API查询失败: {e}")
            
            side = signal.action  # BUY or SELL
            
            # 构建详细的交易日志
            trade_type = "顺势" if not signal.is_counter_trend else "⚠️逆势(高置信度)"
            ml_dir = "看多" if signal.ml_direction == 1 else "看空" if signal.ml_direction == -1 else "观望"
            
            # 获取技术指标判断（用于日志显示）
            tech_signal = None  # 初始化为None
            try:
                df_feat = MLFeatureEngineer().create_features(df)
                if len(df_feat) > 0:
                    current = df_feat.iloc[-1]
                    tech_signal = self._technical_signal(df_feat, current, signal.regime)
                    tech_info = f"{tech_signal['action']}({tech_signal['confidence']:.2f})"
                else:
                    tech_info = "N/A"
            except Exception as e:
                tech_info = f"获取失败:{str(e)[:20]}"
            
            # 获取技术指标原因
            tech_reason = tech_signal.get('reason', 'N/A')[:30] if tech_signal else 'N/A'
            
            logger.info("="*70)
            logger.info(f"🚀 开仓执行 | {side} | {trade_type}")
            logger.info(f"   价格: ${price:.2f}")
            logger.info(f"   市场环境: {signal.regime.value} | 趋势: {signal.trend_direction}")
            logger.info(f"   ML判断: {ml_dir} (置信度:{signal.ml_confidence:.3f})")
            logger.info(f"   ML概率: 做空={signal.ml_proba_short:.3f}, 做多={signal.ml_proba_long:.3f}")
            logger.info(f"   技术指标: {tech_info} | 原因: {tech_reason}")
            logger.info(f"   ML阈值: {signal.ml_threshold:.3f} (顺势:0.70,逆势:0.85/0.90)")
            logger.info(f"   信号来源: {signal.source.value} | 原因: {signal.reason}")
            logger.info(f"   止损: ${signal.sl_price:.2f} | 止盈: ${signal.tp_price:.2f}")
            logger.info("="*70)
            
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
            base_qty = self.risk_mgr.calculate_position_size(
                balance, price, signal.atr, signal.confidence,
                signal.regime
            )
            
            # ========== 动态仓位调整（按置信度，基于基础仓位）==========
            if CONFIG.get("USE_DYNAMIC_POSITION_SIZE", False):
                # 获取置信度倍数
                mult = self.signal_gen._calculate_position_size(
                    1.0,  # 传入1.0获取倍数
                    signal.confidence,
                    signal.regime
                )
                
                # 基于基础仓位调整
                adjusted_qty = base_qty * mult
                
                # 确保不超过风险限制
                max_position_pct = CONFIG.get("POSITION_SIZE_PCT_MAX", 0.80)
                max_qty = (balance * max_position_pct) / price
                adjusted_qty = min(adjusted_qty, max_qty)
                
                if abs(adjusted_qty - base_qty) > 0.0001:  # 有显著变化才记录
                    logger.info(f"[仓位调整] 基础:{base_qty:.4f} -> 调整后:{adjusted_qty:.4f} "
                               f"(置信度:{signal.confidence:.2f}, 倍数:{mult:.2f}x)")
                
                qty = adjusted_qty
            else:
                qty = base_qty
            
            if qty < 0.001:
                logger.warning(f"仓位计算结果过小: {qty}")
                return False
            
            # 根据市场环境选择下单方式
            limit_regimes = CONFIG.get("LIMIT_ORDER_REGIMES", ["SIDEWAYS"])
            is_limit_regime = signal.regime.value in limit_regimes
            use_limit = CONFIG.get("USE_LIMIT_ORDER", True)
            
            if is_limit_regime and use_limit:
                # 震荡市使用限价单（Maker），两次重试
                logger.info(f"[下单策略] 环境={signal.regime.value}, 使用限价单(震荡策略)")
                order, order_type, executed_price = self._place_limit_with_retry(
                    side, qty, price, reduce_only=False, max_retries=2
                )
            elif use_limit:
                # 趋势市使用"轻微限价+Taker"策略
                logger.info(f"[下单策略] 环境={signal.regime.value}, 使用轻量限价(趋势策略)")
                order, order_type, executed_price = self._place_limit_quick_then_taker(
                    side, qty, price, reduce_only=False
                )
            else:
                # 禁用限价单，直接使用市价单
                logger.info(f"[下单策略] 环境={signal.regime.value}, 使用市价单")
                order = self._retry_api_call(
                    self.api.place_order, 3,
                    self.symbol, side, qty
                )
                order_type = 'TAKER'
                # 获取市价单实际成交价格
                if order and 'avgPrice' in order:
                    executed_price = float(order.get('avgPrice', 0))
                else:
                    executed_price = price
            
            if order and order.get('orderId'):
                # 使用实际成交价格
                price = executed_price if executed_price > 0 else price
                
                # 根据订单类型计算手续费
                notional_value = qty * price
                if order_type == 'MAKER':
                    open_fee = notional_value * self.maker_fee_rate  # 0.02%
                else:  # TAKER or HYBRID
                    open_fee = notional_value * self.taker_fee_rate  # 0.05%
                
                self.position = {
                    'side': side,
                    'qty': qty,
                    'entry_price': price,
                    'sl_price': signal.sl_price,
                    'tp_price': signal.tp_price,
                    'entry_time': datetime.now(),
                    'open_fee': open_fee,  # 记录开仓手续费
                    'notional_value': notional_value  # 记录名义价值
                }
                
                # 重构新增: PositionManager 记录开仓 (2026-03-24)
                pm_side = 'LONG' if side == 'BUY' else 'SHORT'
                self.position_manager.open(pm_side, price, qty)
                
                # 重置止盈止损追踪 (兼容旧代码)
                self.signal_gen.reset_position_tracking()
                
                # 记录到数据库
                self.db.log_signal(self.symbol, signal, price, executed=True)
                
                # 构建ML信息文本
                ml_dir = "看多" if signal.ml_direction == 1 else "看空" if signal.ml_direction == -1 else "观望"
                trend_type = "顺势" if not signal.is_counter_trend else "⚠️逆势"
                
                fee_emoji = "💚" if order_type == 'MAKER' else "💛" if order_type == 'HYBRID' else "❤️"
                msg = (
                    f"🟢 <b>开仓成功</b> [{order_type}]\n"
                    f"方向: {side} ({trend_type})\n"
                    f"价格: ${price:.2f}\n"
                    f"数量: {qty:.4f}\n"
                    f"名义价值: ${notional_value:.2f}\n"
                    f"{fee_emoji} 开仓手续费: ${open_fee:.4f} ({order_type})\n"
                    f"止损: ${signal.sl_price:.2f}\n"
                    f"止盈: ${signal.tp_price:.2f}\n"
                    f"市场环境: {signal.regime.value}\n"
                    f"ML判断: {ml_dir} (置信度:{signal.ml_confidence:.2f})\n"
                    f"ML概率: 做空{signal.ml_proba_short:.2f}/做多{signal.ml_proba_long:.2f}\n"
                    f"信号来源: {signal.source.value}\n"
                    f"原因: {signal.reason}"
                )
                
                logger.info(f"✅ 开仓: {side} [{order_type}] {qty} @ ${price:.2f} | 名义价值: ${notional_value:.2f} | "
                           f"手续费: ${open_fee:.4f} | ML{ml_dir}({signal.ml_confidence:.2f}) | {trend_type} | {signal.reason}")
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
            pnl_pct_raw = (entry_price - price) / entry_price if is_short else (price - entry_price) / entry_price
            pnl_pct = pnl_pct_raw * self.leverage  # 包含杠杆的收益率（毛收益）
            
            # 计算名义价值
            notional_value = self.position.get('notional_value', qty * entry_price)
            
            # 执行平仓 (LONG->SELL, SHORT->BUY) - 根据市场环境选择
            close_side = 'SELL' if not is_short else 'BUY'
            limit_regimes = CONFIG.get("LIMIT_ORDER_REGIMES", ["SIDEWAYS"])
            is_limit_regime = signal.regime.value in limit_regimes
            use_limit = CONFIG.get("USE_LIMIT_ORDER", True)
            
            if is_limit_regime and use_limit:
                # 震荡市使用限价单，两次重试
                logger.info(f"[平仓策略] 环境={signal.regime.value}, 使用限价单(震荡策略)")
                order, order_type, executed_price = self._place_limit_with_retry(
                    close_side, qty, price, reduce_only=True, max_retries=2
                )
            elif use_limit:
                # 趋势市使用"轻微限价+Taker"策略
                logger.info(f"[平仓策略] 环境={signal.regime.value}, 使用轻量限价(趋势策略)")
                order, order_type, executed_price = self._place_limit_quick_then_taker(
                    close_side, qty, price, reduce_only=True
                )
            else:
                # 禁用限价单，直接使用市价单
                logger.info(f"[平仓策略] 环境={signal.regime.value}, 使用市价单")
                order = self._retry_api_call(
                    self.api.place_order, 3,
                    self.symbol, close_side, qty, reduce_only=True
                )
                order_type = 'TAKER'
                # 获取市价单实际成交价格
                if order and 'avgPrice' in order:
                    executed_price = float(order.get('avgPrice', 0))
                else:
                    executed_price = price
            
            if order and order.get('orderId'):
                # 使用实际成交价格
                price = executed_price if executed_price > 0 else price
                
                # 根据订单类型计算手续费
                if order_type == 'MAKER':
                    open_fee_rate = self.maker_fee_rate
                    close_fee_rate = self.maker_fee_rate
                elif order_type == 'HYBRID':
                    open_fee_rate = self.maker_fee_rate  # 假设开仓是Maker
                    close_fee_rate = self.taker_fee_rate
                else:  # TAKER
                    open_fee_rate = self.taker_fee_rate
                    close_fee_rate = self.taker_fee_rate
                
                open_fee = self.position.get('open_fee', notional_value * open_fee_rate)
                close_fee = qty * price * close_fee_rate
                total_fees = open_fee + close_fee
                
                # 重新计算盈亏 (使用实际成交价格)
                if is_short:
                    pnl_pct_raw = (entry_price - price) / entry_price
                else:
                    pnl_pct_raw = (price - entry_price) / entry_price
                
                gross_pnl_usdt = notional_value * pnl_pct_raw
                pnl_usdt = gross_pnl_usdt - total_fees
                actual_pnl_pct = pnl_usdt / notional_value * self.leverage
                result = 'WIN' if pnl_usdt > 0 else 'LOSS'
            
            if order and order.get('orderId'):
                # 记录到数据库
                self.db.log_trade(
                    self.symbol, side, entry_price, price, qty,
                    actual_pnl_pct, pnl_usdt, result,
                    reason or signal.reason,
                    signal.source.value, signal.confidence,
                    signal.regime.value, signal.funding_rate,
                    order_type  # 记录订单类型 (MAKER/TAKER/HYBRID)
                )
                
                # 更新风控统计 (使用扣除手续费的实际收益率)
                self.risk_mgr.record_trade(actual_pnl_pct)
                
                # 更新止盈记录中的盈亏（用于后期分析）
                try:
                    from take_profit_manager import get_tp_manager
                    tp_manager = get_tp_manager()
                    # 更新最后一条记录的盈亏
                    if tp_manager.records:
                        last_record = tp_manager.records[-1]
                        last_record.pnl_usdt = pnl_usdt
                        last_record.pnl_pct = actual_pnl_pct
                except Exception:
                    pass
                
                # 每5笔平仓打印一次绩效报告
                self.cycle_count += 1
                if self.cycle_count % 5 == 0:
                    self._print_tp_performance_report()
                
                emoji = "🟢" if pnl_usdt > 0 else "🔴"
                fee_emoji = "💚" if order_type == 'MAKER' else "💛" if order_type == 'HYBRID' else "❤️"
                msg = (
                    f"{emoji} <b>平仓成功</b> [{order_type}]\n"
                    f"方向: {side}\n"
                    f"入场: ${entry_price:.2f}\n"
                    f"出场: ${price:.2f}\n"
                    f"毛盈亏: {pnl_pct*100:+.2f}%\n"
                    f"{fee_emoji} 手续费: ${total_fees:.4f} ({order_type})\n"
                    f"净盈亏: {actual_pnl_pct*100:+.2f}% | ${pnl_usdt:+.4f}\n"
                    f"原因: {reason or signal.reason}"
                )
                
                logger.info(f"✅ 平仓: {side} [{order_type}] | 净PnL: {actual_pnl_pct*100:+.2f}% (${pnl_usdt:+.4f}) | "
                           f"手续费: ${total_fees:.4f} | {reason or signal.reason}")
                self.send_notification(msg)
                
                # 重构新增: PositionManager 记录平仓 (2026-03-24)
                exit_reason = reason or signal.reason
                pm_record = self.position_manager.close(price, exit_reason)
                if pm_record:
                    logger.debug(f"[PositionManager] 平仓记录: {pm_record}")
                
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
            
            # 🔴 关键修复：每次交易周期强制同步持仓（确保出场检查正常）
            if self.cycle_count % 5 == 0:  # 每5周期同步一次
                self._sync_position()
            
            # 生成信号
            has_pos = self.position is not None
            pos_side = self.position['side'] if self.position else None
            entry_px = self.position['entry_price'] if self.position else 0
            
            # 先生成信号
            signal = self.signal_gen.generate_signal(
                df, current_price, funding_rate,
                has_position=has_pos,
                position_side=pos_side,
                entry_price=entry_px
            )
            
            # 日志优化：交易周期信息只在状态变化或每60秒输出一次
            entry_px_int = int(entry_px) if entry_px else 0
            price_int = int(current_price)  # 价格整数部分用于比较
            current_cycle_state = f"{has_pos}_{pos_side}_{entry_px_int}_{signal.regime.value if signal else 'unknown'}"
            
            # 加强过滤：状态变化 或 每60周期（约60秒）才输出
            should_log_cycle = (
                not hasattr(self, '_last_cycle_state') or 
                self._last_cycle_state != current_cycle_state or 
                self.cycle_count % 60 == 0
            )
            
            if should_log_cycle:
                if has_pos:
                    logger.info(f"[交易周期] 持仓={pos_side}, 入场={entry_px:.2f}, 价格={current_price:.2f}")
                else:
                    # 无持仓时简化输出，只显示关键信息
                    regime_val = signal.regime.value if signal and hasattr(signal, 'regime') else 'unknown'
                    ml_dir = signal.ml_direction if signal and hasattr(signal, 'ml_direction') else 0
                    ml_conf = signal.ml_confidence if signal and hasattr(signal, 'ml_confidence') else 0
                    ml_str = f"ML{'多' if ml_dir==1 else '空' if ml_dir==-1 else '观'}({ml_conf:.2f})" if ml_dir != 0 else ""
                    logger.info(f"[交易周期] 无持仓, 价格={current_price:.2f}, 环境={regime_val} {ml_str}")
                self._last_cycle_state = current_cycle_state
            
            # 记录信号 - 交易信号立即记录，HOLD信号每15秒记录一次
            if signal.action != 'HOLD' or self.cycle_count % 19 == 0:
                self.db.log_signal(self.symbol, signal, current_price)
            
            # 执行交易
            if signal.action == 'CLOSE' and self.position:
                self.execute_close(signal, current_price)
            
            elif signal.action in ['BUY', 'SELL'] and not self.position:
                self.execute_open(signal, current_price)
            
            # 定期同步持仓 (每30个周期，或无持仓时每5周期尝试同步)
            if self.cycle_count % 30 == 0 or (not self.position and self.cycle_count % 5 == 0):
                self._sync_position()
            
            # 交易逻辑（保持全速运行，不受日志影响）
            # 记录持仓状态 - 数据库写入每5周期一次（异步不影响交易）
            if self.position:
                # 重构新增: PositionManager 更新状态 (2026-03-24)
                pm_state = self.position_manager.update(current_price)
                
                entry = self.position['entry_price']
                side = self.position['side']
                is_short = side in ['SELL', 'SHORT']
                pnl_pct = (entry - current_price) / entry * self.leverage if is_short else (current_price - entry) / entry * self.leverage
                
                # 兼容旧代码：同步 peak_pnl 和 trailing_stop
                if pm_state:
                    self.signal_gen.position_peak_pnl = pm_state.peak_pnl
                    self.signal_gen.position_trailing_stop = pm_state.trailing_stop
                
                # 数据库记录每5周期（不影响交易速度）
                if self.cycle_count % 5 == 0:
                    self.db.log_position(
                        self.symbol, side, self.position['qty'],
                        entry, current_price, pnl_pct,
                        self.position['qty'] * entry * pnl_pct,
                        self.position.get('sl_price', 0),
                        self.position.get('tp_price', 0)
                    )
                
                # 日志打印每30秒一次（减少日志频率）
                if self.cycle_count % 38 == 0:
                    logger.info(
                        f"📊 持仓 {side} | 入场:{entry:.2f} 当前:{current_price:.2f} | "
                        f"盈亏:{pnl_pct*100:+.2f}% | 环境:{signal.regime.value}"
                    )
            else:
                # 观望状态日志每30秒一次（减少日志频率）
                if self.cycle_count % 38 == 0:
                    ml_status = "ML" if self.signal_gen.ml_model.is_trained else "NO_ML"
                    
                    # 构建ML详细信息（优先使用信号中的ML信息，其次使用最后保存的ML信息）
                    ml_info = getattr(self.signal_gen, '_last_ml_info', {})
                    ml_dir = signal.ml_direction if signal.ml_direction != 0 else ml_info.get('direction', 0)
                    ml_conf = signal.ml_confidence if signal.ml_confidence > 0 else ml_info.get('confidence', 0)
                    ml_ps = signal.ml_proba_short if signal.ml_proba_short > 0 else ml_info.get('proba_short', 0.5)
                    ml_pl = signal.ml_proba_long if signal.ml_proba_long > 0 else ml_info.get('proba_long', 0.5)
                    
                    if ml_dir != 0:
                        ml_dir_str = "看多" if ml_dir == 1 else "看空"
                        ml_detail = (f"ML{ml_dir_str}({ml_conf:.2f})"
                                    f"[做空:{ml_ps:.2f}/做多:{ml_pl:.2f}]")
                        if signal.is_counter_trend:
                            ml_detail += f"|逆势|阈值:{signal.ml_threshold:.2f}"
                        else:
                            ml_detail += "|顺势"
                    else:
                        ml_detail = "ML未触发"
                    
                    # 简化观望日志，只保留关键信息
                    ml_simple = f"ML{'多' if ml_dir==1 else '空' if ml_dir==-1 else '无'}({ml_conf:.2f})" if ml_dir != 0 else "ML观望"
                    logger.info(
                        f"📊 观望 价格:{current_price:.2f} | "
                        f"环境:{signal.regime.value} | {ml_simple}"
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
                logger.info("🛑 收到停止信号 (Ctrl+C)")
                
                if self.position:
                    # 显示持仓信息
                    pos_side = self.position['side']
                    pos_qty = self.position['qty']
                    entry_price = self.position['entry_price']
                    current_price = self.api.get_price(self.symbol)
                    
                    # 计算盈亏
                    is_short = pos_side in ['SELL', 'SHORT']
                    if is_short:
                        pnl_pct = (entry_price - current_price) / entry_price
                    else:
                        pnl_pct = (current_price - entry_price) / entry_price
                    leverage = CONFIG.get('LEVERAGE', 5)
                    pnl_leverage = pnl_pct * leverage
                    
                    print("\n" + "="*60)
                    print("⚠️  程序退出确认")
                    print("="*60)
                    print(f"当前持仓: {pos_side} {pos_qty} ETH @ ${entry_price:.2f}")
                    print(f"当前价格: ${current_price:.2f}")
                    print(f"当前盈亏: {pnl_leverage*100:+.2f}%")
                    print("-"*60)
                    
                    # 询问用户是否平仓
                    try:
                        user_input = input("是否平仓后退出? [Y/n] (默认Y): ").strip().lower()
                        
                        if user_input in ['', 'y', 'yes']:
                            # 用户确认平仓
                            logger.info("用户确认: 平仓后退出")
                            self.execute_close(
                                TradingSignal('CLOSE', 1.0, SignalSource.TECHNICAL, '程序退出'),
                                current_price, "程序退出-用户确认"
                            )
                            print("✅ 已平仓，程序退出")
                        else:
                            # 用户选择不平仓
                            logger.info("用户选择: 不平仓直接退出")
                            print("⚠️ 持仓未平，程序直接退出")
                            print(f"   持仓保留: {pos_side} {pos_qty} ETH @ ${entry_price:.2f}")
                    except EOFError:
                        # 非交互式环境(如脚本)，默认平仓
                        logger.info("非交互式环境，自动平仓后退出")
                        self.execute_close(
                            TradingSignal('CLOSE', 1.0, SignalSource.TECHNICAL, '程序退出'),
                            current_price, "程序退出-自动平仓"
                        )
                        print("✅ 自动平仓，程序退出")
                else:
                    print("\n✅ 无持仓，程序退出")
                
                logger.info("程序正常退出")
                break
            
            except Exception as e:
                logger.error(f"主循环异常: {e}")
                time.sleep(5)


def main():
    """入口"""
    # 强制LIVE模式 - bat启动自动确认
    if CONFIG["MODE"] != "LIVE":
        logger.info(f"模式切换: {CONFIG['MODE']} -> LIVE")
        CONFIG["MODE"] = "LIVE"
    
    trader = V12OptimizedTrader()
    trader.run()


if __name__ == "__main__":
    main()
