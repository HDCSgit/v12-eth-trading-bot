#!/usr/bin/env python3
"""
V8-ML-Optimized: ML驱动的高频交易系统
核心：V6信号框架 + V7单信号逻辑 + XGBoost信号评分
数据：5分钟K线（2年）
"""

import pandas as pd
import numpy as np
import logging
from datetime import datetime
from typing import Dict, List, Tuple
import warnings
warnings.filterwarnings('ignore')

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

try:
    import xgboost as xgb
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import accuracy_score, precision_score, recall_score
    from sklearn import set_config
    # 关闭特征名检查（方法3：无名氏模式）
    set_config(transform_output="default")
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    logger.warning("ML库未安装，使用规则模式")


class MLFeatureEngineer:
    """ML特征工程 - 为XGBoost准备特征"""
    
    def __init__(self):
        self.feature_cols = []
        self.scaler = StandardScaler()
        
    def create_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """创建ML特征"""
        df = df.copy()
        
        # 价格特征
        df['returns'] = df['close'].pct_change()
        df['log_returns'] = np.log(df['close'] / df['close'].shift(1))
        
        # 滞后特征（多周期）
        for lag in [1, 2, 3, 5, 10]:
            df[f'return_lag_{lag}'] = df['returns'].shift(lag)
            df[f'close_lag_{lag}'] = df['close'].shift(lag)
        
        # 多周期均线
        for period in [5, 10, 20, 55, 200]:
            df[f'ma_{period}'] = df['close'].rolling(period).mean()
            df[f'ma_ratio_{period}'] = df['close'] / df[f'ma_{period}']
        
        # 趋势
        df['trend_long'] = np.where(df['ma_55'] > df['ma_200'], 1, -1)
        df['trend_short'] = np.where(df['ma_10'] > df['ma_20'], 1, -1)
        
        # RSI多周期
        for period in [6, 12, 24]:
            delta = df['close'].diff()
            gain = delta.clip(lower=0).rolling(period).mean()
            loss = (-delta.clip(upper=0)).rolling(period).mean()
            df[f'rsi_{period}'] = 100 - 100 / (1 + gain / (loss + 1e-10))
        
        df['rsi_slope'] = df['rsi_12'].diff(3)
        df['rsi_ma_diff'] = df['rsi_12'] - df['rsi_12'].rolling(10).mean()
        
        # MACD
        for fast, slow, signal in [(12, 26, 9), (5, 35, 5)]:
            ema_fast = df['close'].ewm(span=fast).mean()
            ema_slow = df['close'].ewm(span=slow).mean()
            df[f'macd_{fast}_{slow}'] = ema_fast - ema_slow
            df[f'macd_signal_{fast}_{slow}'] = df[f'macd_{fast}_{slow}'].ewm(span=signal).mean()
            df[f'macd_hist_{fast}_{slow}'] = df[f'macd_{fast}_{slow}'] - df[f'macd_signal_{fast}_{slow}']
        
        # 布林带
        for period in [20, 50]:
            df[f'bb_mid_{period}'] = df['close'].rolling(period).mean()
            df[f'bb_std_{period}'] = df['close'].rolling(period).std()
            df[f'bb_upper_{period}'] = df[f'bb_mid_{period}'] + 2 * df[f'bb_std_{period}']
            df[f'bb_lower_{period}'] = df[f'bb_mid_{period}'] - 2 * df[f'bb_std_{period}']
            df[f'bb_position_{period}'] = (df['close'] - df[f'bb_lower_{period}']) / (df[f'bb_upper_{period}'] - df[f'bb_lower_{period}'] + 1e-10)
            df[f'bb_width_{period}'] = (df[f'bb_upper_{period}'] - df[f'bb_lower_{period}']) / df[f'bb_mid_{period}']
        
        # ATR
        tr = pd.concat([
            df['high'] - df['low'],
            np.abs(df['high'] - df['close'].shift()),
            np.abs(df['low'] - df['close'].shift())
        ], axis=1).max(axis=1)
        df['atr'] = tr.rolling(14).mean()
        df['atr_pct'] = df['atr'] / df['close']
        
        # 量能
        for period in [5, 10, 20]:
            df[f'volume_ma_{period}'] = df['volume'].rolling(period).mean()
            df[f'volume_ratio_{period}'] = df['volume'] / df[f'volume_ma_{period}']
        
        df['volume_trend'] = df['volume_ma_5'] / df['volume_ma_20']
        
        # 价格变化多周期
        for period in [3, 5, 10, 20]:
            df[f'price_change_{period}m'] = df['close'].pct_change(period) * 100
        
        # 统计特征
        df['volatility'] = df['returns'].rolling(20).std()
        df['skewness'] = df['returns'].rolling(30).skew()
        
        # 动量
        df['momentum_10'] = df['close'] / df['close'].shift(10) - 1
        
        # 时间特征
        df['hour'] = pd.to_datetime(df['timestamp']).dt.hour
        df['day_of_week'] = pd.to_datetime(df['timestamp']).dt.dayofweek
        
        # 目标变量（未来5周期收益，约25分钟）
        df['future_return'] = df['close'].shift(-5) / df['close'] - 1
        df['target'] = np.where(df['future_return'] > 0.002, 1,  # 0.2%
                               np.where(df['future_return'] < -0.002, -1, 0))
        
        # 记录特征列
        self.feature_cols = [col for col in df.columns if col not in 
                            ['timestamp', 'open', 'high', 'low', 'close', 'volume',
                             'close_time', 'quote_volume', 'trades', 'taker_buy_base', 'taker_buy_quote',
                             'future_return', 'target', 'ignore']]
        
        return df.dropna()


class MLTradingModel:
    """ML交易模型 - XGBoost预测信号质量"""
    
    def __init__(self):
        self.model_long = None
        self.scaler = StandardScaler()
        self.is_trained = False
        self.feature_eng = MLFeatureEngineer()  # 共享特征工程实例
        
    def train(self, df: pd.DataFrame) -> Dict:
        """训练XGBoost模型"""
        logger.info("训练ML模型...")
        
        df_features = self.feature_eng.create_features(df)
        X = df_features[self.feature_eng.feature_cols]
        
        # 多头模型
        y_long = (df_features['target'] == 1).astype(int)
        mask_long = df_features['target'] != 0
        
        X_long = X[mask_long]
        y_long = y_long[mask_long]
        
        # 分割训练集
        split_idx = int(len(X_long) * 0.8)
        X_train_long, X_test_long = X_long.iloc[:split_idx], X_long.iloc[split_idx:]
        y_train_long, y_test_long = y_long.iloc[:split_idx], y_long.iloc[split_idx:]
        
        # 标准化 - 使用numpy数组避免特征名检查
        X_train_long_scaled = self.scaler.fit_transform(X_train_long.values)
        X_test_long_scaled = self.scaler.transform(X_test_long.values)
        
        # 训练XGBoost
        self.model_long = xgb.XGBClassifier(
            n_estimators=100,
            max_depth=5,
            learning_rate=0.1,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            eval_metric='logloss',
            use_label_encoder=False
        )
        
        self.model_long.fit(X_train_long_scaled, y_train_long)
        
        # 评估
        y_pred_long = self.model_long.predict(X_test_long_scaled)
        acc_long = accuracy_score(y_test_long, y_pred_long)
        
        self.is_trained = True
        
        logger.info(f"多头模型训练完成！准确率: {acc_long:.2%}")
        
        return {
            'accuracy_long': acc_long,
            'feature_count': len(self.feature_eng.feature_cols)
        }
    
    def predict_signal_quality(self, df: pd.DataFrame, direction: str) -> float:
        """预测信号质量（0-1）"""
        if not self.is_trained or not ML_AVAILABLE:
            return 0.5
        
        # 使用相同的feature_eng保持特征一致性
        df_features = self.feature_eng.create_features(df)
        
        # 检查是否有足够的数据
        if len(df_features) == 0:
            return 0.5
        
        # 只使用训练时的特征列
        X = df_features[self.feature_eng.feature_cols].iloc[-1:]
        
        # 再次检查
        if len(X) == 0:
            return 0.5
        
        X_scaled = self.scaler.transform(X.values)
        
        if direction == 'LONG':
            proba = self.model_long.predict_proba(X_scaled)[0]
            return proba[1]  # 上涨概率
        else:
            return 0.5  # 简化处理


class V8SignalGenerator:
    """V8信号生成器 - V6信号 + ML评分"""
    
    def __init__(self):
        self.ml_model = MLTradingModel()
        self.is_trained = False
        
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算基础指标 - 使用与ML模型相同的特征名称"""
        # 直接使用ML特征工程的方法，但不做dropna以保留更多数据
        df = self.ml_model.feature_eng.create_features(df)
        return df
    
    def train_ml_model(self, df: pd.DataFrame):
        """训练ML模型"""
        self.ml_model.train(df)
        self.is_trained = True
    
    def generate_signals(self, df: pd.DataFrame) -> Dict:
        """生成交易信号（V6信号 + ML评分）"""
        df = self.calculate_indicators(df)
        
        if len(df) < 20:
            return {'action': 'HOLD', 'signals': [], 'ml_score': 0}
        
        row = df.iloc[-1]
        prev = df.iloc[-2]
        
        signals = []
        
        # ========== 高频信号（使用ML特征工程生成的正确列名）==========
        
        # 信号1: RSI超卖（阈值45）
        if row['rsi_12'] < 45:
            signals.append(('RSI_Oversold', 0.60))
        
        # 信号2: MACD金叉
        if row['macd_12_26'] > row['macd_signal_12_26'] and prev['macd_12_26'] <= prev['macd_signal_12_26']:
            signals.append(('MACD_Cross', 0.65))
        
        # 信号3: 价格触及布林带下轨（阈值1.03）
        if row['close'] < row['bb_lower_20'] * 1.03:
            signals.append(('BB_Lower', 0.55))
        
        # 信号4: 均线金叉
        if row['ma_5'] > row['ma_10'] and prev['ma_5'] <= prev['ma_10']:
            signals.append(('MA_Cross', 0.60))
        
        # 信号5: 趋势跟随
        if row['trend_long'] == 1 and row['rsi_12'] < 50:
            signals.append(('Trend_Follow', 0.50))
        
        # 信号6: 成交量突破
        if row['volume_ratio_5'] > 1.5 and row['close'] > row['open']:
            signals.append(('Volume_Break', 0.55))
        
        # 信号7: 价格反弹
        if row['price_change_3m'] < -1:
            signals.append(('Price_Bounce', 0.50))
        
        # 计算基础分数
        base_score = sum([conf for _, conf in signals])
        
        # ML评分（如果已训练）
        ml_score = 0.5
        if self.is_trained and ML_AVAILABLE:
            ml_score = self.ml_model.predict_signal_quality(df, 'LONG')
        
        # 综合评分（降低ML权重）
        final_score = base_score * 0.8 + ml_score * 0.2
        
        # 触发条件：只要有信号且综合评分>0.3（大幅降低）
        if len(signals) > 0 and final_score > 0.3:
            return {
                'action': 'BUY',
                'signals': signals,
                'base_score': base_score,
                'ml_score': ml_score,
                'final_score': final_score
            }
        else:
            return {
                'action': 'HOLD',
                'signals': signals,
                'base_score': base_score,
                'ml_score': ml_score,
                'final_score': final_score
            }


class V8MLOptimizedTrader:
    """V8 ML优化高频交易系统"""
    
    def __init__(self, initial_balance: float = 1000.0):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        
        # 高频参数（5分钟周期）
        self.leverage = 2
        self.stop_loss = 0.015  # 1.5%（更紧）
        self.take_profit = 0.03  # 3%（快速止盈）
        self.position_size = 0.08  # 8%仓位
        
        # 风控
        self.max_drawdown = 0.25
        
        # 策略
        self.signal_generator = V8SignalGenerator()
        
        # 统计
        self.stats = {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'liquidations': 0
        }
        
        logger.info("=" * 70)
        logger.info("V8-ML-Optimized ML驱动高频交易系统")
        logger.info(f"周期: 5分钟 | 杠杆: {self.leverage}x")
        logger.info(f"止损: {self.stop_loss*100}% | 止盈: {self.take_profit*100}%")
        logger.info("=" * 70)
    
    def train_model(self, df: pd.DataFrame):
        """训练模型"""
        self.signal_generator.train_ml_model(df)
    
    def run_backtest(self, df: pd.DataFrame) -> Dict:
        """运行回测"""
        logger.info("开始V8-ML回测...")
        
        # 训练模型（前80%数据）
        train_size = int(len(df) * 0.8)
        train_df = df.iloc[:train_size]
        test_df = df.iloc[train_size:].reset_index(drop=True)
        
        if ML_AVAILABLE:
            self.train_model(train_df)
        
        # 回测
        position = None
        equity_curve = []
        
        for i in range(100, len(test_df)):
            current_df = test_df.iloc[:i+1]
            current_price = test_df['close'].iloc[i]
            
            # 持仓管理
            if position:
                entry = position['entry_price']
                pnl_pct = (current_price - entry) / entry * self.leverage
                
                # 快速止损
                if pnl_pct <= -self.stop_loss * self.leverage * 100:
                    self.balance -= position['margin'] * self.stop_loss * self.leverage
                    self.stats['losing_trades'] += 1
                    position = None
                    continue
                
                # 快速止盈
                if pnl_pct >= self.take_profit * self.leverage * 100:
                    profit = position['margin'] * self.take_profit * self.leverage
                    self.balance += position['margin'] + profit
                    self.stats['winning_trades'] += 1
                    position = None
                    continue
            
            # 新开仓
            else:
                signal = self.signal_generator.generate_signals(current_df)
                
                if signal['action'] == 'BUY':
                    margin = self.balance * self.position_size
                    self.balance -= margin
                    
                    position = {
                        'side': 'LONG',
                        'entry_price': current_price,
                        'margin': margin
                    }
                    self.stats['total_trades'] += 1
            
            # 记录权益
            equity = self.balance
            if position:
                unrealized = position['margin'] * (current_price - position['entry_price']) / position['entry_price'] * self.leverage
                equity += position['margin'] + unrealized
            
            equity_curve.append(equity)
        
        # 平仓
        if position:
            pnl_pct = (current_price - position['entry_price']) / position['entry_price'] * self.leverage
            if pnl_pct > 0:
                self.stats['winning_trades'] += 1
            else:
                self.stats['losing_trades'] += 1
        
        # 计算结果
        total_return = (equity_curve[-1] - self.initial_balance) / self.initial_balance * 100
        
        max_dd = 0
        peak = self.initial_balance
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak
            if dd > max_dd:
                max_dd = dd
        
        years = 0.44  # 约5.3个月测试期
        annual_trades = self.stats['total_trades'] / years
        
        return {
            'total_return': total_return,
            'max_drawdown': max_dd * 100,
            'total_trades': self.stats['total_trades'],
            'annual_trades': annual_trades,
            'winning_trades': self.stats['winning_trades'],
            'losing_trades': self.stats['losing_trades'],
            'win_rate': self.stats['winning_trades'] / max(self.stats['total_trades'], 1) * 100,
            'liquidations': self.stats['liquidations']
        }


def main():
    """主函数"""
    # 加载5分钟数据
    df = pd.read_csv('eth_usdt_5m_2024_2026.csv')
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    trader = V8MLOptimizedTrader(initial_balance=1000.0)
    results = trader.run_backtest(df)
    
    print("\n" + "=" * 70)
    print("🚀 V8-ML-Optimized 回测报告")
    print("=" * 70)
    print(f"\n💰 资金表现:")
    print(f"  初始: $1000.00 → 最终: ${1000 * (1 + results['total_return']/100):.2f}")
    print(f"  总收益: {results['total_return']:+.2f}%")
    
    print(f"\n📊 交易统计:")
    print(f"  总交易: {results['total_trades']}")
    print(f"  年化交易: {results['annual_trades']:.0f} 笔")
    print(f"  盈利: {results['winning_trades']} | 亏损: {results['losing_trades']}")
    print(f"  胜率: {results['win_rate']:.1f}%")
    
    print(f"\n🛡️ 风险控制:")
    print(f"  最大回撤: {results['max_drawdown']:.2f}%")
    print(f"  爆仓: {results['liquidations']} 次")
    
    # 评分
    score = 0
    if results['liquidations'] == 0: score += 30
    if results['win_rate'] > 55: score += 25
    if results['win_rate'] > 50: score += 10
    if results['total_return'] > 0: score += 15
    if results['annual_trades'] > 400: score += 10
    if results['annual_trades'] > 800: score += 10
    
    print(f"\n⭐ 综合评分: {score}/100")
    print("=" * 70)


if __name__ == "__main__":
    main()