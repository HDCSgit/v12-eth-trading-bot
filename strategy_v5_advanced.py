#!/usr/bin/env python3
"""
V5-Advanced: 多策略ML集成交易系统
核心：LightGBM + XGBoost + RandomForest + LSTM + 规则引擎
目标：爆仓=0，胜率>65%，交易次数>300/2年
"""

import pandas as pd
import numpy as np
import logging
from datetime import datetime
from typing import Dict, List, Tuple, Optional
import json
import warnings
warnings.filterwarnings('ignore')

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# 尝试导入ML库
try:
    import xgboost as xgb
    from sklearn.ensemble import RandomForestClassifier, VotingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import train_test_split, TimeSeriesSplit
    from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False

try:
    import lightgbm as lgb
    LIGHTGBM_AVAILABLE = True
except ImportError:
    LIGHTGBM_AVAILABLE = False
    logger.warning("LightGBM未安装，使用XGBoost替代")


class AdvancedFeatureEngineer:
    """高级特征工程 - 多时间框架特征"""
    
    def __init__(self):
        self.feature_cols = []
        
    def create_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """创建全面的特征集"""
        df = df.copy()
        
        # 1. 基础特征
        df['returns'] = df['close'].pct_change()
        df['log_returns'] = np.log(df['close'] / df['close'].shift(1))
        
        # 2. 多时间框架价格特征
        for period in [5, 10, 20, 50]:
            df[f'price_change_{period}'] = df['close'].pct_change(period)
            df[f'price_std_{period}'] = df['close'].rolling(period).std() / df['close']
            df[f'price_momentum_{period}'] = df['close'] / df['close'].shift(period) - 1
        
        # 3. 技术指标
        # RSI多周期
        for period in [6, 12, 24]:
            delta = df['close'].diff()
            gain = delta.clip(lower=0).rolling(period).mean()
            loss = (-delta.clip(upper=0)).rolling(period).mean()
            df[f'rsi_{period}'] = 100 - 100 / (1 + gain / (loss + 1e-10))
        
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
        
        # ATR和波动率
        for period in [14, 28]:
            tr = pd.concat([
                df['high'] - df['low'],
                np.abs(df['high'] - df['close'].shift()),
                np.abs(df['low'] - df['close'].shift())
            ], axis=1).max(axis=1)
            df[f'atr_{period}'] = tr.rolling(period).mean()
            df[f'atr_pct_{period}'] = df[f'atr_{period}'] / df['close']
        
        # 4. 趋势特征
        for fast, slow in [(10, 30), (20, 60)]:
            df[f'ma_{fast}'] = df['close'].rolling(fast).mean()
            df[f'ma_{slow}'] = df['close'].rolling(slow).mean()
            df[f'trend_{fast}_{slow}'] = np.where(df[f'ma_{fast}'] > df[f'ma_{slow}'], 1, -1)
        
        # 5. 量能特征
        for period in [5, 10, 20]:
            df[f'volume_ma_{period}'] = df['volume'].rolling(period).mean()
            df[f'volume_ratio_{period}'] = df['volume'] / df[f'volume_ma_{period}']
        
        # 量能趋势
        df['volume_trend'] = df['volume_ma_5'] / df['volume_ma_20']
        
        # OBV
        obv = [0]
        for i in range(1, len(df)):
            if df['close'].iloc[i] > df['close'].iloc[i-1]:
                obv.append(obv[-1] + df['volume'].iloc[i])
            elif df['close'].iloc[i] < df['close'].iloc[i-1]:
                obv.append(obv[-1] - df['volume'].iloc[i])
            else:
                obv.append(obv[-1])
        df['obv'] = obv
        df['obv_ma'] = df['obv'].rolling(20).mean()
        
        # 6. 价格形态特征
        df['higher_high'] = (df['high'] > df['high'].shift(1)).astype(int)
        df['lower_low'] = (df['low'] < df['low'].shift(1)).astype(int)
        df['higher_close'] = (df['close'] > df['close'].shift(1)).astype(int)
        
        # 7. 统计特征
        df['skewness'] = df['returns'].rolling(30).skew()
        df['kurtosis'] = df['returns'].rolling(30).kurt()
        
        # 8. 时间特征
        df['hour'] = pd.to_datetime(df['timestamp']).dt.hour
        df['day_of_week'] = pd.to_datetime(df['timestamp']).dt.dayofweek
        df['is_weekend'] = (df['day_of_week'] >= 5).astype(int)
        
        # 9. 目标变量（未来3周期涨跌1%）
        df['future_returns'] = df['close'].shift(-3) / df['close'] - 1
        df['target'] = np.where(df['future_returns'] > 0.01, 1,
                               np.where(df['future_returns'] < -0.01, -1, 0))
        
        # 记录特征列
        self.feature_cols = [col for col in df.columns if col not in 
                            ['timestamp', 'open', 'high', 'low', 'close', 'volume',
                             'open_time', 'close_time', 'quote_volume', 'trades',
                             'future_returns', 'target']]
        
        return df.dropna()


class MultiModelStrategy:
    """多模型集成策略"""
    
    def __init__(self):
        self.models = {}
        self.scaler = StandardScaler()
        self.feature_engineer = AdvancedFeatureEngineer()
        self.is_trained = False
        
    def train(self, df: pd.DataFrame) -> Dict:
        """训练多个模型"""
        logger.info("开始训练多模型集成...")
        
        # 特征工程
        df_features = self.feature_engineer.create_features(df)
        X = df_features[self.feature_engineer.feature_cols]
        y = df_features['target']
        
        # 只使用明确方向的样本
        mask = y != 0
        X = X[mask]
        y = y[mask]
        y = np.where(y == -1, 0, 1)  # 转换为0,1
        
        # 时间序列分割
        split_idx = int(len(X) * 0.8)
        X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
        y_train, y_test = y[:split_idx], y[split_idx:]
        
        # 标准化
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_test_scaled = self.scaler.transform(X_test)
        
        results = {}
        
        # 1. LightGBM (如果可用)
        if LIGHTGBM_AVAILABLE:
            logger.info("训练LightGBM...")
            lgb_model = lgb.LGBMClassifier(
                n_estimators=200,
                max_depth=7,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                random_state=42,
                verbose=-1
            )
            lgb_model.fit(X_train_scaled, y_train)
            self.models['lightgbm'] = lgb_model
            lgb_pred = lgb_model.predict(X_test_scaled)
            results['lightgbm'] = accuracy_score(y_test, lgb_pred)
        
        # 2. XGBoost
        logger.info("训练XGBoost...")
        xgb_model = xgb.XGBClassifier(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            eval_metric='logloss',
            use_label_encoder=False
        )
        xgb_model.fit(X_train_scaled, y_train)
        self.models['xgboost'] = xgb_model
        xgb_pred = xgb_model.predict(X_test_scaled)
        results['xgboost'] = accuracy_score(y_test, xgb_pred)
        
        # 3. Random Forest
        logger.info("训练Random Forest...")
        rf_model = RandomForestClassifier(
            n_estimators=150,
            max_depth=10,
            min_samples_split=5,
            random_state=42,
            n_jobs=-1
        )
        rf_model.fit(X_train_scaled, y_train)
        self.models['random_forest'] = rf_model
        rf_pred = rf_model.predict(X_test_scaled)
        results['random_forest'] = accuracy_score(y_test, rf_pred)
        
        # 4. 软投票集成
        logger.info("创建投票集成...")
        estimators = []
        if 'lightgbm' in self.models:
            estimators.append(('lgb', self.models['lightgbm']))
        estimators.append(('xgb', self.models['xgboost']))
        estimators.append(('rf', self.models['random_forest']))
        
        voting_clf = VotingClassifier(
            estimators=estimators,
            voting='soft',
            weights=[2, 1.5, 1] if 'lightgbm' in self.models else [1.5, 1]
        )
        voting_clf.fit(X_train_scaled, y_train)
        self.models['voting'] = voting_clf
        voting_pred = voting_clf.predict(X_test_scaled)
        results['voting'] = accuracy_score(y_test, voting_pred)
        
        self.is_trained = True
        
        logger.info(f"模型训练完成！各模型准确率: {results}")
        return results
    
    def predict(self, df: pd.DataFrame) -> Dict:
        """多模型预测"""
        if not self.is_trained:
            return {'direction': 0, 'confidence': 0, 'agreement': 0}
        
        # 特征工程
        df_features = self.feature_engineer.create_features(df)
        X = df_features[self.feature_engineer.feature_cols].iloc[-1:]
        X_scaled = self.scaler.transform(X)
        
        predictions = {}
        probabilities = {}
        
        # 各模型预测
        for name, model in self.models.items():
            if name == 'voting':
                continue
            pred = model.predict(X_scaled)[0]
            proba = model.predict_proba(X_scaled)[0]
            predictions[name] = pred
            probabilities[name] = proba
        
        # 计算共识
        pred_list = list(predictions.values())
        majority = max(set(pred_list), key=pred_list.count)
        agreement = pred_list.count(majority) / len(pred_list)
        
        # 使用投票集成作为主预测
        voting_proba = self.models['voting'].predict_proba(X_scaled)[0]
        voting_pred = self.models['voting'].predict(X_scaled)[0]
        
        # 转换标签：0 -> -1 (跌), 1 -> 1 (涨)
        direction = 1 if voting_pred == 1 else -1
        confidence = max(voting_proba)
        
        return {
            'direction': direction,
            'confidence': confidence,
            'agreement': agreement,  # 模型一致性
            'individual_preds': predictions,
            'individual_proba': probabilities
        }


class HybridSignalGenerator:
    """混合信号生成器 - ML + 规则 + 市场微观结构"""
    
    def __init__(self):
        self.ml_strategy = MultiModelStrategy()
        self.weights = {
            'ml': 0.5,      # ML信号权重
            'trend': 0.25,   # 趋势规则权重
            'momentum': 0.15, # 动量规则权重
            'volume': 0.1    # 量能规则权重
        }
        
    def generate_signal(self, df: pd.DataFrame) -> Dict:
        """生成混合信号"""
        # ML信号
        ml_signal = self.ml_strategy.predict(df)
        
        # 获取最新数据
        row = df.iloc[-1]
        
        # 趋势规则
        trend_score = 0
        if row.get('ma_10', 0) > row.get('ma_30', 0):
            trend_score += 0.5
        if row.get('rsi_12', 50) < 40:
            trend_score += 0.3
        if row.get('macd_12_26', 0) > row.get('macd_signal_12_26', 0):
            trend_score += 0.2
        
        # 动量规则
        momentum_score = 0
        if row.get('price_momentum_5', 0) > 0.005:
            momentum_score += 0.4
        if row.get('rsi_slope', 0) > 0:
            momentum_score += 0.3
        if row.get('price_change_10', 0) > 0:
            momentum_score += 0.3
        
        # 量能规则
        volume_score = 0
        if row.get('volume_ratio_5', 1) > 1.5:
            volume_score += 0.6
        if row.get('volume_trend', 1) > 1.2:
            volume_score += 0.4
        
        # 综合评分
        if ml_signal['direction'] == 1:
            combined_score = (
                self.weights['ml'] * ml_signal['confidence'] +
                self.weights['trend'] * trend_score +
                self.weights['momentum'] * momentum_score +
                self.weights['volume'] * volume_score
            )
        else:
            combined_score = -(
                self.weights['ml'] * ml_signal['confidence'] +
                self.weights['trend'] * (1 - trend_score) +
                self.weights['momentum'] * (1 - momentum_score) +
                self.weights['volume'] * (1 - volume_score)
            )
        
        # 阈值判断（大幅放宽以提升交易频率）
        if combined_score > 0.15:
            action = 'BUY'
            strength = min(abs(combined_score), 1.0)
        elif combined_score < -0.15:
            action = 'SELL'
            strength = min(abs(combined_score), 1.0)
        else:
            action = 'HOLD'
            strength = 0.0
        
        return {
            'action': action,
            'strength': strength,
            'combined_score': combined_score,
            'ml_signal': ml_signal,
            'rule_scores': {
                'trend': trend_score,
                'momentum': momentum_score,
                'volume': volume_score
            }
        }


class V5AdvancedTrader:
    """V5高级交易系统"""
    
    def __init__(self, initial_balance: float = 1000.0):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        
        # 严格风控
        self.leverage = 2  # 降低到2x
        self.stop_loss = 0.025  # 2.5%止损
        self.take_profit_1 = 0.05  # 5%第一目标
        self.take_profit_2 = 0.10  # 10%第二目标
        self.position_size = 0.04  # 4%仓位
        
        # 风控参数
        self.max_daily_loss = 0.08  # 日最大亏损8%
        self.max_drawdown = 0.15   # 最大回撤15%
        self.daily_loss = 0
        
        # 策略
        self.signal_generator = HybridSignalGenerator()
        
        # 统计
        self.stats = {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'liquidations': 0,
            'max_consecutive_losses': 0
        }
        
        logger.info("=" * 60)
        logger.info("V5-Advanced 高级交易系统")
        logger.info(f"杠杆: {self.leverage}x | 止损: {self.stop_loss*100}%")
        logger.info(f"仓位: {self.position_size*100}% | 爆仓线: {-50/self.leverage:.1f}%")
        logger.info("=" * 60)
    
    def train(self, df: pd.DataFrame):
        """训练模型"""
        return self.signal_generator.ml_strategy.train(df)
    
    def run_backtest(self, df: pd.DataFrame) -> Dict:
        """运行回测"""
        logger.info("开始V5-Advanced回测...")
        
        # 特征工程
        df = self.signal_generator.ml_strategy.feature_engineer.create_features(df)
        
        # 划分训练/测试
        train_size = int(len(df) * 0.7)
        train_df = df.iloc[:train_size]
        test_df = df.iloc[train_size:].reset_index(drop=True)
        
        # 训练模型
        self.train(train_df)
        
        # 回测
        position = None
        equity_curve = []
        consecutive_losses = 0
        max_consecutive = 0
        
        for i in range(100, len(test_df)):
            current_df = test_df.iloc[:i+1]
            current_price = test_df['close'].iloc[i]
            
            # 组合风控检查
            if position is None:
                total_equity = self.balance
                if len(equity_curve) > 0:
                    total_equity = equity_curve[-1]
                drawdown = (self.initial_balance - total_equity) / self.initial_balance
                if drawdown > self.max_drawdown:
                    logger.warning(f"组合回撤 {drawdown*100:.1f}% > 限制，停止交易")
                    break
            
            # 持仓管理
            if position:
                entry = position['entry_price']
                
                if position['side'] == 'LONG':
                    pnl_pct = (current_price - entry) / entry * self.leverage
                else:
                    pnl_pct = (entry - current_price) / entry * self.leverage
                
                # 爆仓检查（2x杠杆，-50%线，实际上不可能达到）
                if pnl_pct <= -45:
                    self.stats['liquidations'] += 1
                    self.balance *= 0.5  # 剩余50%
                    position = None
                    consecutive_losses += 1
                    continue
                
                # 止损
                if pnl_pct <= -self.stop_loss * self.leverage * 100:
                    loss = position['margin'] * self.stop_loss * self.leverage
                    self.balance -= loss
                    self.stats['losing_trades'] += 1
                    position = None
                    consecutive_losses += 1
                    max_consecutive = max(max_consecutive, consecutive_losses)
                    continue
                
                # 分级止盈
                if pnl_pct >= self.take_profit_1 * self.leverage * 100 and not position.get('tp1_hit'):
                    # 平50%
                    profit = position['margin'] * 0.5 * self.take_profit_1 * self.leverage
                    self.balance += profit
                    position['margin'] *= 0.5
                    position['tp1_hit'] = True
                    position['entry_price'] = current_price
                    self.stats['winning_trades'] += 0.5
                
                if pnl_pct >= self.take_profit_2 * self.leverage * 100:
                    # 平剩余
                    profit = position['margin'] * self.take_profit_2 * self.leverage
                    self.balance += position['margin'] + profit
                    self.stats['winning_trades'] += 0.5
                    position = None
                    consecutive_losses = 0
                    continue
            
            # 新开仓
            else:
                signal = self.signal_generator.generate_signal(current_df)
                
                if signal['action'] != 'HOLD' and signal['strength'] > 0.2:
                    margin = self.balance * self.position_size
                    self.balance -= margin
                    
                    position = {
                        'side': signal['action'],
                        'entry_price': current_price,
                        'margin': margin,
                        'signal_strength': signal['strength'],
                        'tp1_hit': False
                    }
                    self.stats['total_trades'] += 1
            
            # 记录权益
            equity = self.balance
            if position:
                if position['side'] == 'LONG':
                    unrealized = position['margin'] * (current_price - position['entry_price']) / position['entry_price'] * self.leverage
                else:
                    unrealized = position['margin'] * (position['entry_price'] - current_price) / position['entry_price'] * self.leverage
                equity += position['margin'] + unrealized
            
            equity_curve.append(equity)
        
        # 平仓
        if position:
            if position['side'] == 'LONG':
                pnl_pct = (current_price - position['entry_price']) / position['entry_price'] * self.leverage
            else:
                pnl_pct = (position['entry_price'] - current_price) / position['entry_price'] * self.leverage
            
            if pnl_pct > 0:
                self.stats['winning_trades'] += 1
            else:
                self.stats['losing_trades'] += 1
        
        self.stats['max_consecutive_losses'] = max_consecutive
        
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
        
        return {
            'total_return': total_return,
            'max_drawdown': max_dd * 100,
            'total_trades': int(self.stats['total_trades']),
            'winning_trades': int(self.stats['winning_trades']),
            'losing_trades': int(self.stats['losing_trades']),
            'win_rate': self.stats['winning_trades'] / max(self.stats['total_trades'], 1) * 100,
            'liquidations': self.stats['liquidations'],
            'max_consecutive_losses': max_consecutive
        }


def main():
    """主函数"""
    df = pd.read_csv('eth_usdt_1h_binance.csv')
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    trader = V5AdvancedTrader(initial_balance=1000.0)
    results = trader.run_backtest(df)
    
    print("\n" + "=" * 60)
    print("V5-Advanced 回测结果")
    print("=" * 60)
    print(f"总收益: {results['total_return']:+.2f}%")
    print(f"最大回撤: {results['max_drawdown']:.2f}%")
    print(f"交易次数: {results['total_trades']}")
    print(f"胜: {results['winning_trades']} | 负: {results['losing_trades']}")
    print(f"胜率: {results['win_rate']:.1f}%")
    print(f"爆仓: {results['liquidations']}")
    print(f"最大连续亏损: {results['max_consecutive_losses']}")
    print("=" * 60)


if __name__ == "__main__":
    main()