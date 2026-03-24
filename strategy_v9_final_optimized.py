#!/usr/bin/env python3
"""
V9-Final-Optimized: 终极优化版
核心：V2.5强规则 + 优化ML参数 + 在线学习 + 成本建模
目标：胜率60%+，收益转正
"""

import pandas as pd
import numpy as np
import logging
from datetime import datetime
from typing import Dict, List, Tuple
import warnings
warnings.filterwarnings('ignore')

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

try:
    import xgboost as xgb
    from sklearn.preprocessing import StandardScaler
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    logger.warning("ML库未安装，使用规则模式")


class EnhancedFeatureEngineer:
    """增强特征工程 - 包含V2.5核心特征"""
    
    def create_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """创建全面特征集"""
        df = df.copy()
        
        # 基础价格特征
        df['returns'] = df['close'].pct_change()
        
        # RSI多周期
        for period in [6, 12, 24]:
            delta = df['close'].diff()
            gain = delta.clip(lower=0).rolling(period).mean()
            loss = (-delta.clip(upper=0)).rolling(period).mean()
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
        
        # 均线
        for period in [5, 10, 20, 55, 200]:
            df[f'ma_{period}'] = df['close'].rolling(period).mean()
        
        # 趋势
        df['trend_short'] = np.where(df['ma_10'] > df['ma_20'], 1, -1)
        df['trend_long'] = np.where(df['ma_55'] > df['ma_200'], 1, -1)
        
        # 量能
        df['volume_ma'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma']
        
        # 动量
        for period in [3, 5, 10, 20]:
            df[f'momentum_{period}'] = df['close'].pct_change(period)
            df[f'volatility_{period}'] = df['returns'].rolling(period).std()
        
        # 价格位置
        df['high_20'] = df['high'].rolling(20).max()
        df['low_20'] = df['low'].rolling(20).min()
        df['price_position'] = (df['close'] - df['low_20']) / (df['high_20'] - df['low_20'] + 1e-10)
        
        # 目标变量
        df['future_return'] = df['close'].shift(-5) / df['close'] - 1
        df['target'] = np.where(df['future_return'] > 0.003, 1, 
                               np.where(df['future_return'] < -0.003, 0, -1))
        
        return df.dropna()


class MLTradingModel:
    """ML交易模型 - 优化参数"""
    
    def __init__(self):
        self.model = None
        self.scaler = StandardScaler()
        self.is_trained = False
        self.feature_eng = EnhancedFeatureEngineer()
        
    def train(self, df: pd.DataFrame):
        """训练模型 - 优化参数"""
        if not ML_AVAILABLE:
            return
        
        df_features = self.feature_eng.create_features(df)
        mask = df_features['target'] != -1
        
        feature_cols = ['rsi_12', 'rsi_24', 'macd', 'macd_hist', 'bb_position', 
                       'bb_width', 'volume_ratio', 'momentum_5', 'momentum_10',
                       'volatility_10', 'trend_short', 'price_position']
        
        X = df_features[feature_cols].loc[mask]
        y = df_features['target'].loc[mask]
        
        if len(X) < 100:
            return
        
        X_scaled = self.scaler.fit_transform(X)
        
        # 训练XGBoost - 已优化参数
        self.model = xgb.XGBClassifier(
            n_estimators=120,      # 原50 → 120
            max_depth=5,           # 原4 → 5
            learning_rate=0.08,    # 原0.1 → 0.08（更稳）
            subsample=0.85,
            random_state=42,
            eval_metric='logloss'
        )
        
        self.model.fit(X_scaled, y)
        self.is_trained = True
    
    def predict(self, df: pd.DataFrame) -> Dict:
        """预测"""
        if not self.is_trained or not ML_AVAILABLE:
            return {'direction': 0, 'confidence': 0.5}
        
        df_features = self.feature_eng.create_features(df)
        if len(df_features) == 0:
            return {'direction': 0, 'confidence': 0.5}
        
        feature_cols = ['rsi_12', 'rsi_24', 'macd', 'macd_hist', 'bb_position', 
                       'bb_width', 'volume_ratio', 'momentum_5', 'momentum_10',
                       'volatility_10', 'trend_short', 'price_position']
        
        X = df_features[feature_cols].iloc[-1:]
        X_scaled = self.scaler.transform(X)
        
        proba = self.model.predict_proba(X_scaled)[0]
        pred = self.model.predict(X_scaled)[0]
        
        return {
            'direction': 1 if pred == 1 else -1,
            'confidence': max(proba),
            'up_prob': proba[1],
            'down_prob': proba[0]
        }


class V9FinalTrader:
    """V9终极优化版"""
    
    def __init__(self, initial_balance: float = 1000.0):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        
        # 交易参数
        self.base_leverage = 3
        self.base_position_size = 0.08
        
        # 交易成本建模
        self.trading_fee = 0.0004      # 0.04% taker费
        self.funding_rate = 0.0001     # 0.01% 资金费率/天
        
        # 组件
        self.ml_model = MLTradingModel()
        
        # 统计
        self.stats = {
            'total_trades': 0,
            'wins': 0,
            'losses': 0,
            'liquidations': 0,
            'total_fees': 0
        }
        
        logger.info("\n" + "=" * 70)
        logger.info("🚀 V9-Final-Optimized 终极优化版")
        logger.info("V2.5规则 + 优化ML + 在线学习 + 成本建模")
        logger.info("=" * 70)
    
    def generate_enhanced_signals(self, df: pd.DataFrame) -> Dict:
        """生成增强信号 - 规则已融合"""
        current = df.iloc[-1]
        prev = df.iloc[-2]
        prev2 = df.iloc[-3]
        
        base_signals = []
        
        # 原3个蜡烛（保留）
        if current['close'] < prev['close'] and prev['close'] < prev2['close']:
            base_signals.append('Consecutive_Drop')
        if current['close'] < min(prev['low'], prev2['low']):
            base_signals.append('Below_Low')
        if current['close'] > current['open']:
            base_signals.append('Bullish_Candle')
        
        # 新增3个V2.5强规则（核心提升！）
        if current.get('rsi_12', 50) < 45:
            base_signals.append('RSI_Oversold')
        if current.get('macd_hist', 0) > 0 and prev.get('macd_hist', 0) < 0:
            base_signals.append('MACD_Cross')
        if current.get('bb_width', 0.1) < 0.05:
            base_signals.append('BB_Squeeze')
        
        # ML增强
        ml_pred = self.ml_model.predict(df)
        
        score = len(base_signals)
        if ml_pred['direction'] == 1 and ml_pred['confidence'] > 0.6:
            score += 2
        elif ml_pred['direction'] == -1 and ml_pred['confidence'] > 0.6:
            score -= 2
        
        position_size = self.base_position_size
        if ml_pred['confidence'] > 0.7:
            position_size *= 1.5
        elif ml_pred['confidence'] < 0.5:
            position_size *= 0.5
        
        return {
            'action': 'BUY' if score >= 2 else 'SELL' if score <= -2 else 'HOLD',
            'score': score,
            'position_size': position_size,
            'ml_confidence': ml_pred['confidence'],
            'base_signals': base_signals
        }
    
    def run_backtest(self, df: pd.DataFrame) -> Dict:
        """运行回测 - 含成本建模和在线学习"""
        # 初始训练
        train_size = int(len(df) * 0.3)  # 只用30%初始训练，更多留给在线学习
        train_df = df.iloc[:train_size]
        
        logger.info("初始训练ML模型...")
        self.ml_model.train(train_df)
        
        # 回测
        test_df = df.iloc[train_size:].reset_index(drop=True)
        
        position = None
        position_side = None
        entry_price = None
        position_bars = 0
        
        for i in range(55, len(test_df)):
            current_df = test_df.iloc[:i+1]
            current_price = test_df['close'].iloc[i]
            
            # 扣除资金费（每天约288个5分钟K线）
            if i % 288 == 0:
                self.balance *= (1 - self.funding_rate)
            
            # 持仓管理
            if position:
                position_bars += 1
                
                if position_side == 'LONG':
                    pnl_pct = (current_price - entry_price) / entry_price * self.base_leverage
                else:
                    pnl_pct = (entry_price - current_price) / entry_price * self.base_leverage
                
                # 止损止盈（优化后参数）
                if pnl_pct <= -3.6:  # 1.2% * 3x
                    loss = position['margin'] * 0.036
                    self.balance -= loss
                    self.stats['losses'] += 1
                    self.stats['total_fees'] += position['margin'] * self.trading_fee * 2
                    position = None
                    continue
                
                if pnl_pct >= 11.4:  # 3.8% * 3x
                    profit = position['margin'] * 0.114
                    self.balance += position['margin'] + profit
                    self.stats['wins'] += 1
                    self.stats['total_fees'] += position['margin'] * self.trading_fee * 2
                    position = None
                    continue
                
                # 强制平仓
                if position_bars >= 12:
                    self.stats['total_fees'] += position['margin'] * self.trading_fee * 2
                    if pnl_pct > 0:
                        profit = position['margin'] * pnl_pct / 100
                        self.balance += position['margin'] + profit
                        self.stats['wins'] += 1
                    else:
                        loss = position['margin'] * abs(pnl_pct) / 100
                        self.balance += position['margin'] - loss
                        self.stats['losses'] += 1
                    position = None
                    position_bars = 0
            
            # 新开仓
            else:
                signal = self.generate_enhanced_signals(current_df)
                
                if signal['action'] in ['BUY', 'SELL']:
                    # 扣除成本
                    cost = self.balance * signal['position_size'] * self.trading_fee * 2
                    self.balance -= cost
                    self.stats['total_fees'] += cost
                    
                    margin = self.balance * signal['position_size']
                    self.balance -= margin
                    
                    position = {'margin': margin, 'max_profit': 0}
                    position_side = 'LONG' if signal['action'] == 'BUY' else 'SHORT'
                    entry_price = current_price
                    position_bars = 0
                    self.stats['total_trades'] += 1
                    
                    # 在线学习：每500根K线重新训练
                    if i % 500 == 0 and i > 500:
                        logger.info(f"在线重训ML模型（第{i}根K线）")
                        self.ml_model.train(current_df)
        
        # 计算结果
        total_return = (self.balance - self.initial_balance) / self.initial_balance * 100
        win_rate = self.stats['wins'] / max(self.stats['total_trades'], 1) * 100
        
        return {
            'total_return': total_return,
            'total_trades': self.stats['total_trades'],
            'win_rate': win_rate,
            'wins': self.stats['wins'],
            'losses': self.stats['losses'],
            'total_fees': self.stats['total_fees'],
            'liquidations': self.stats['liquidations']
        }


def main():
    """主函数"""
    logger.info("加载5分钟ETH数据...")
    df = pd.read_csv('eth_usdt_5m_2024_2026.csv')
    logger.info(f"数据条数: {len(df):,}")
    
    trader = V9FinalTrader(initial_balance=1000.0)
    result = trader.run_backtest(df)
    
    print("\n" + "=" * 70)
    print("🚀 V9-Final-Optimized 回测报告")
    print("=" * 70)
    print(f"\n💰 总收益: {result['total_return']:+.2f}%")
    print(f"📊 交易: {result['total_trades']} 笔")
    print(f"  胜率: {result['win_rate']:.1f}% (目标>60%)")
    print(f"  盈利: {result['wins']} | 亏损: {result['losses']}")
    print(f"\n💸 总成本: ${result['total_fees']:.2f}")
    print(f"🛡️ 爆仓: {result['liquidations']} 次")
    
    # 评分
    score = 0
    if result['liquidations'] == 0: score += 30
    if result['win_rate'] > 60: score += 35
    elif result['win_rate'] > 55: score += 25
    if result['total_return'] > 0: score += 25
    if result['total_return'] > 20: score += 10
    
    print(f"\n⭐ 综合评分: {score}/100")
    if score >= 90: print("🟢 优秀 - 立即实盘")
    elif score >= 75: print("🟡 良好 - 可以实盘")
    elif score >= 60: print("🟠 一般 - 谨慎使用")
    else: print("🔴 较差 - 继续优化")
    print("=" * 70)


if __name__ == "__main__":
    main()