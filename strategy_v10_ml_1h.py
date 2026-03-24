#!/usr/bin/env python3
"""
V10-ML-1H-Proper: 1小时K线专家版（真正学到东西）
- 自动5m→1h重采样（噪声最小）
- ML为主决策（规则只辅助）
- 合理retrain + 严格target
"""

import pandas as pd
import numpy as np
import logging
from datetime import datetime
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
    logger.error("请安装: pip install xgboost scikit-learn")


class EnhancedFeatureEngineer:
    def create_features(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
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
        
        df['trend_short'] = np.where(df['ma_10'] > df['ma_20'], 1, -1)
        df['trend_long'] = np.where(df['ma_55'] > df['ma_200'], 1, -1)
        
        # 量能
        df['volume_ma'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma']
        
        # 动量
        for period in [3, 5, 10, 20]:
            df[f'momentum_{period}'] = df['close'].pct_change(period)
            df[f'volatility_{period}'] = df['returns'].rolling(period).std()
        
        df['high_20'] = df['high'].rolling(20).max()
        df['low_20'] = df['low'].rolling(20).min()
        df['price_position'] = (df['close'] - df['low_20']) / (df['high_20'] - df['low_20'] + 1e-10)
        
        # 1h专用target（预测未来2小时）
        df['future_return'] = df['close'].shift(-2) / df['close'] - 1
        df['target'] = np.where(df['future_return'] > 0.004, 1, 
                               np.where(df['future_return'] < -0.006, 0, -1))
        
        return df.dropna()


class MLTradingModel:
    def __init__(self):
        self.model = None
        self.scaler = StandardScaler()
        self.is_trained = False
        self.feature_eng = EnhancedFeatureEngineer()
        
    def train(self, df: pd.DataFrame):
        if not ML_AVAILABLE: 
            return
        df_feat = self.feature_eng.create_features(df)
        feature_cols = ['rsi_12', 'rsi_24', 'macd_hist', 'bb_position', 'bb_width', 
                       'volume_ratio', 'momentum_5', 'trend_short', 'price_position']
        mask = df_feat['target'] != -1
        X = df_feat[feature_cols].loc[mask]
        y = df_feat['target'].loc[mask]
        if len(X) < 200: 
            return
        
        X_scaled = self.scaler.fit_transform(X)
        self.model = xgb.XGBClassifier(
            n_estimators=100, 
            max_depth=5, 
            learning_rate=0.08, 
            subsample=0.85, 
            random_state=42
        )
        self.model.fit(X_scaled, y)
        self.is_trained = True

    def predict(self, df: pd.DataFrame) -> dict:
        if not self.is_trained: 
            return {'direction': 0, 'confidence': 0.5}
        df_feat = self.feature_eng.create_features(df)
        if len(df_feat) == 0: 
            return {'direction': 0, 'confidence': 0.5}
        
        X = df_feat[['rsi_12', 'rsi_24', 'macd_hist', 'bb_position', 'bb_width', 
                     'volume_ratio', 'momentum_5', 'trend_short', 'price_position']].iloc[-1:]
        X_scaled = self.scaler.transform(X)
        proba = self.model.predict_proba(X_scaled)[0]
        return {
            'direction': 1 if proba[1] > proba[0] else -1, 
            'confidence': max(proba)
        }


class V10ML1HTrader:
    def __init__(self, initial_balance: float = 1000.0):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.ml_model = MLTradingModel()
        self.stats = {'total_trades': 0, 'wins': 0, 'losses': 0, 'total_fees': 0}
        self.base_leverage = 3
        self.trading_fee = 0.0004

    def resample_to_1h(self, df: pd.DataFrame) -> pd.DataFrame:
        """自动5m转1h（核心优化）"""
        if 'open_time' in df.columns:
            df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
            df.set_index('open_time', inplace=True)
        elif 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df.set_index('timestamp', inplace=True)
        
        df_1h = df.resample('1H').agg({
            'open': 'first', 
            'high': 'max', 
            'low': 'min', 
            'close': 'last', 
            'volume': 'sum'
        }).dropna()
        
        logger.info(f"✅ 5m数据已自动重采样为1hK线（{len(df_1h)}条）")
        return df_1h.reset_index()

    def generate_signal(self, df: pd.DataFrame) -> str:
        """ML为主决策"""
        ml = self.ml_model.predict(df)
        if ml['confidence'] < 0.55:  # 降低门槛，增加交易
            return 'HOLD'
        
        current = df.iloc[-1]
        rule_score = 0
        if current.get('rsi_12', 50) < 45:  # RSI放宽到45
            rule_score += 1
        if current.get('macd_hist', 0) > 0: 
            rule_score += 1
        if current.get('bb_width', 0.1) < 0.08:  # BB放宽到0.08
            rule_score += 1
        
        # 降低规则门槛，只要有ML信号就交易
        if ml['direction'] == 1 and rule_score >= 0:
            return 'BUY'
        elif ml['direction'] == -1 and rule_score >= 0:
            return 'SELL'
        return 'HOLD'

    def run_backtest(self, df: pd.DataFrame) -> dict:
        df = self.resample_to_1h(df)
        self.ml_model.train(df.iloc[:int(len(df)*0.4)])
        
        test_df = df.iloc[int(len(df)*0.4):].reset_index(drop=True)
        position = None
        entry_price = 0.0
        margin = 0.0  # 记录保证金
        
        for i in range(20, len(test_df)):
            current_df = test_df.iloc[:i+1]
            price = test_df['close'].iloc[i]
            
            if position:
                pnl_pct = (price - entry_price) / entry_price * self.base_leverage
                # 修复：平仓时返还保证金+盈亏
                if pnl_pct <= -0.025 or pnl_pct >= 0.09:
                    profit_loss = margin * (pnl_pct / 100)
                    self.balance += margin + profit_loss  # 返还保证金+盈亏
                    self.stats['wins' if pnl_pct > 0 else 'losses'] += 1
                    position = None
                continue
            
            action = self.generate_signal(current_df)
            if action in ['BUY', 'SELL']:
                self.stats['total_trades'] += 1
                # 修复：开仓时扣除保证金
                margin = self.balance * 0.08  # 8%仓位
                self.balance -= margin  # 扣除保证金
                entry_price = price
                position = True
                
                # 在线重训（1h专用：每300根，只用最近8000根）
                if i % 300 == 0 and i > 1000:
                    recent_data = current_df.iloc[-8000:] if len(current_df) > 8000 else current_df
                    logger.info(f"在线重训（第{i}根1hK线）")
                    self.ml_model.train(recent_data)
        
        total_return = (self.balance - self.initial_balance) / self.initial_balance * 100
        win_rate = self.stats['wins'] / max(self.stats['total_trades'], 1) * 100
        
        return {
            'total_return': total_return, 
            'win_rate': win_rate, 
            'total_trades': self.stats['total_trades']
        }


def main():
    logger.info("加载5分钟ETH数据...")
    df = pd.read_csv('eth_usdt_5m_2024_2026.csv')
    logger.info(f"数据条数: {len(df):,}")
    
    trader = V10ML1HTrader(initial_balance=1000.0)
    result = trader.run_backtest(df)
    
    print("\n" + "=" * 70)
    print("🚀 V10-ML-1H（1小时K线专家版）回测报告")
    print("=" * 70)
    print(f"\n💰 总收益: {result['total_return']:+.2f}%")
    print(f"📊 交易: {result['total_trades']} 笔")
    print(f"  胜率: {result['win_rate']:.1f}%")
    print("=" * 70)


if __name__ == "__main__":
    main()