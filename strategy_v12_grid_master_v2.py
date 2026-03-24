#!/usr/bin/env python3
"""
V12-Grid-Master-V2: 优化版（增加交易频率）
"""

import pandas as pd
import numpy as np
import logging
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
        for period in [6, 12, 24]:
            delta = df['close'].diff()
            gain = delta.clip(lower=0).rolling(period).mean()
            loss = (-delta.clip(upper=0)).rolling(period).mean()
            df[f'rsi_{period}'] = 100 - 100 / (1 + gain / (loss + 1e-10))
        ema12 = df['close'].ewm(span=12).mean()
        ema26 = df['close'].ewm(span=26).mean()
        df['macd'] = ema12 - ema26
        df['macd_signal'] = df['macd'].ewm(span=9).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']
        df['bb_mid'] = df['close'].rolling(20).mean()
        df['bb_std'] = df['close'].rolling(20).std()
        df['bb_upper'] = df['bb_mid'] + 2 * df['bb_std']
        df['bb_lower'] = df['bb_mid'] - 2 * df['bb_std']
        df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_mid']
        df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'] + 1e-10)
        for period in [5, 10, 20, 55, 200]:
            df[f'ma_{period}'] = df['close'].rolling(period).mean()
        df['trend_short'] = np.where(df['ma_10'] > df['ma_20'], 1, -1)
        df['volume_ma'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma']
        for period in [3, 5, 10, 20]:
            df[f'momentum_{period}'] = df['close'].pct_change(period)
        tr1 = df['high'] - df['low']
        tr2 = abs(df['high'] - df['close'].shift())
        tr3 = abs(df['low'] - df['close'].shift())
        df['atr'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).rolling(14).mean()
        df['high_20'] = df['high'].rolling(20).max()
        df['low_20'] = df['low'].rolling(20).min()
        df['price_position'] = (df['close'] - df['low_20']) / (df['high_20'] - df['low_20'] + 1e-10)
        df['future_return'] = df['close'].shift(-2) / df['close'] - 1
        df['target'] = np.where(df['future_return'] > 0.004, 1, np.where(df['future_return'] < -0.004, 0, -1))
        return df.dropna()

class MLTradingModel:
    def __init__(self):
        self.model = None
        self.scaler = StandardScaler()
        self.is_trained = False
        self.feature_eng = EnhancedFeatureEngineer()
        
    def train(self, df: pd.DataFrame):
        if not ML_AVAILABLE: return
        df_feat = self.feature_eng.create_features(df)
        feature_cols = ['rsi_12', 'rsi_24', 'macd_hist', 'bb_position', 'bb_width', 'volume_ratio', 'momentum_5', 'trend_short', 'price_position']
        mask = df_feat['target'] != -1
        X = df_feat[feature_cols].loc[mask]
        y = df_feat['target'].loc[mask]
        if len(X) < 200: return
        X_scaled = self.scaler.fit_transform(X)
        self.model = xgb.XGBClassifier(n_estimators=150, max_depth=5, learning_rate=0.06, subsample=0.85, random_state=42)
        self.model.fit(X_scaled, y)
        self.is_trained = True

    def predict(self, df: pd.DataFrame) -> dict:
        if not self.is_trained: return {'direction': 0, 'confidence': 0.5}
        df_feat = self.feature_eng.create_features(df)
        if len(df_feat) == 0: return {'direction': 0, 'confidence': 0.5}
        X = df_feat[['rsi_12', 'rsi_24', 'macd_hist', 'bb_position', 'bb_width', 'volume_ratio', 'momentum_5', 'trend_short', 'price_position']].iloc[-1:]
        X_scaled = self.scaler.transform(X)
        proba = self.model.predict_proba(X_scaled)[0]
        return {'direction': 1 if proba[1] > proba[0] else -1, 'confidence': max(proba)}

class V12GridMasterTrader:
    def __init__(self, initial_balance: float = 1000.0):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.ml_model = MLTradingModel()
        self.stats = {'total_trades': 0, 'wins': 0, 'losses': 0}
        self.base_leverage = 3
        self.trading_fee = 0.0004
        self.grid = []
        self.position_side = None
        self.entry_price = 0.0
        self.margin = 0.0

    def resample_to_1h(self, df: pd.DataFrame) -> pd.DataFrame:
        if 'open_time' in df.columns:
            df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
            df.set_index('open_time', inplace=True)
        elif 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df.set_index('timestamp', inplace=True)
        df_1h = df.resample('1H').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'}).dropna()
        logger.info(f"✅ 5m→1h重采样完成（{len(df_1h)}条）")
        return df_1h.reset_index()

    def is_sideways(self, df: pd.DataFrame) -> bool:
        """大幅放宽震荡市检测"""
        current = df.iloc[-1]
        bb_width = current.get('bb_width', 0.15)
        rsi = current.get('rsi_12', 50)
        return bb_width < 0.15 and 30 < rsi < 70

    def open_grid(self, side: str, entry_price: float, qty: float, atr: float):
        self.grid = []
        for i, mult in enumerate([1.0, 2.0, 3.0]):
            if side == 'BUY':
                tp_price = entry_price + (atr * mult * 1.2)
            else:
                tp_price = entry_price - (atr * mult * 1.2)
            level_qty = qty * (0.5 if i == 0 else 0.25)
            self.grid.append({'price': tp_price, 'qty': level_qty, 'filled': False})

    def check_grid_take_profit(self, price: float):
        if not self.grid:
            return
        for level in self.grid:
            if not level['filled']:
                if (self.position_side == 'BUY' and price >= level['price']) or \
                   (self.position_side == 'SELL' and price <= level['price']):
                    pnl_pct = abs(level['price'] - self.entry_price) / self.entry_price * self.base_leverage
                    profit = level['qty'] * pnl_pct
                    self.balance += profit
                    level['filled'] = True
                    if all(l['filled'] for l in self.grid):
                        self.stats['wins'] += 1
                        self.balance += self.margin * 0.25
                        self.position_side = None
                        self.grid = []

    def run_backtest(self, df: pd.DataFrame) -> dict:
        df = self.resample_to_1h(df)
        self.ml_model.train(df.iloc[:int(len(df)*0.4)])
        test_df = df.iloc[int(len(df)*0.4):].reset_index(drop=True)
        atr_series = test_df['close'].rolling(14).std()

        for i in range(30, len(test_df)):
            price = test_df['close'].iloc[i]
            current_df = test_df.iloc[:i+1]
            atr = atr_series.iloc[i]

            if self.position_side:
                self.check_grid_take_profit(price)

            if not self.position_side:
                action = 'HOLD'
                ml = self.ml_model.predict(current_df)
                
                # 降低ML门槛到0.52
                if ml['confidence'] >= 0.52:
                    action = 'BUY' if ml['direction'] == 1 else 'SELL'
                
                # 震荡市网格
                elif self.is_sideways(current_df):
                    close = current_df.iloc[-1]['close']
                    bb_mid = current_df.iloc[-1]['bb_mid']
                    bb_upper = current_df.iloc[-1]['bb_upper']
                    bb_lower = current_df.iloc[-1]['bb_lower']
                    
                    if close > bb_mid + (bb_upper - bb_mid) * 0.2:
                        action = 'SELL'
                    elif close < bb_mid - (bb_mid - bb_lower) * 0.2:
                        action = 'BUY'

                if action != 'HOLD':
                    self.stats['total_trades'] += 1
                    self.margin = self.balance * 0.06
                    self.balance -= self.margin
                    self.entry_price = price
                    self.position_side = action
                    self.open_grid(action, price, self.margin / price, atr)

        if self.position_side:
            self.stats['losses'] += 1
        
        total_return = (self.balance - self.initial_balance) / self.initial_balance * 100
        win_rate = self.stats['wins'] / max(self.stats['total_trades'], 1) * 100
        return {'total_return': total_return, 'win_rate': win_rate, 'total_trades': self.stats['total_trades']}

def main():
    logger.info("加载5分钟ETH数据...")
    df = pd.read_csv('eth_usdt_5m_2024_2026.csv')
    logger.info(f"数据条数: {len(df):,}")
    trader = V12GridMasterTrader()
    result = trader.run_backtest(df)
    print("\n" + "=" * 70)
    print("🚀 V12-Grid-Master-V2 回测报告")
    print("=" * 70)
    print(f"💰 总收益: {result['total_return']:+.2f}%")
    print(f"📊 交易: {result['total_trades']} 笔")
    print(f"  胜率: {result['win_rate']:.1f}%")
    print("=" * 70)

if __name__ == "__main__":
    main()