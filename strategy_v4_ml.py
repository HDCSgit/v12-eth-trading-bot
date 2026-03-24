#!/usr/bin/env python3
"""
V4-ML: 机器学习驱动交易系统
核心：XGBoost分类 + LSTM序列预测 + 集成决策
"""

import pandas as pd
import numpy as np
import logging
from datetime import datetime
from typing import Dict, List, Tuple, Optional
import json
import joblib
from dataclasses import dataclass

# ML库
try:
    import xgboost as xgb
    from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    logging.warning("ML库未安装，使用规则模式")

logger = logging.getLogger(__name__)


@dataclass
class MLFeatures:
    """ML特征集"""
    # 价格特征
    returns: float
    volatility: float
    price_momentum: float
    
    # 技术指标
    rsi: float
    macd: float
    macd_signal: float
    bb_position: float
    adx: float
    
    # 趋势特征
    trend_direction: int
    ma_cross: int
    
    # 量能特征
    volume_ratio: float
    volume_trend: float
    
    # 时间特征
    hour: int
    day_of_week: int
    
    # 高级特征
    rsi_slope: float
    price_acceleration: float
    volatility_regime: int


class FeatureEngineer:
    """特征工程 - 生成ML可用特征"""
    
    def __init__(self):
        self.scaler = StandardScaler()
        self.feature_names = []
        
    def calculate_all_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算完整特征集"""
        df = df.copy()
        
        # 1. 基础价格特征
        df['returns'] = df['close'].pct_change()
        df['log_returns'] = np.log(df['close'] / df['close'].shift(1))
        df['volatility'] = df['returns'].rolling(20).std()
        df['price_momentum'] = df['close'] / df['close'].shift(10) - 1
        
        # 2. 技术指标
        # RSI
        delta = df['close'].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        df['rsi'] = 100 - 100 / (1 + gain / (loss + 1e-10))
        df['rsi_slope'] = df['rsi'].diff(3)  # RSI变化率
        
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
        df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'] + 1e-10)
        df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_mid']
        
        # ATR和ADX
        tr = pd.concat([
            df['high'] - df['low'],
            np.abs(df['high'] - df['close'].shift()),
            np.abs(df['low'] - df['close'].shift())
        ], axis=1).max(axis=1)
        df['atr'] = tr.rolling(14).mean()
        df['atr_pct'] = df['atr'] / df['close']
        
        # ADX计算
        df['adx'] = self._calculate_adx(df)
        
        # 3. 趋势特征
        df['ma20'] = df['close'].rolling(20).mean()
        df['ma50'] = df['close'].rolling(50).mean()
        df['ma200'] = df['close'].rolling(200).mean()
        df['trend_direction'] = np.where(df['close'] > df['ma50'], 1, -1)
        df['ma_cross'] = np.where(
            (df['ma20'] > df['ma50']) & (df['ma20'].shift(1) <= df['ma50'].shift(1)), 1,
            np.where((df['ma20'] < df['ma50']) & (df['ma20'].shift(1) >= df['ma50'].shift(1)), -1, 0)
        )
        
        # 4. 量能特征
        df['volume_ma'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma']
        df['volume_trend'] = df['volume'].rolling(5).mean() / df['volume'].rolling(20).mean()
        df['obv'] = self._calculate_obv(df)  # 能量潮
        
        # 5. 高级特征
        df['price_acceleration'] = df['returns'].diff()
        df['volatility_regime'] = np.where(df['volatility'] > df['volatility'].quantile(0.75), 2,
                                          np.where(df['volatility'] > df['volatility'].quantile(0.25), 1, 0))
        
        # 6. 时间特征
        df['hour'] = pd.to_datetime(df['timestamp']).dt.hour
        df['day_of_week'] = pd.to_datetime(df['timestamp']).dt.dayofweek
        
        # 7. 目标变量（未来收益率）
        df['future_returns'] = df['close'].shift(-5) / df['close'] - 1  # 未来5周期收益
        df['target'] = np.where(df['future_returns'] > 0.005, 1,  # 涨 >0.5%
                               np.where(df['future_returns'] < -0.005, -1, 0))  # 跌 <-0.5%
        
        return df.dropna()
    
    def _calculate_adx(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """计算ADX"""
        plus_dm = np.where(
            (df['high'] - df['high'].shift(1)) > (df['low'].shift(1) - df['low']),
            np.maximum(df['high'] - df['high'].shift(1), 0), 0
        )
        minus_dm = np.where(
            (df['low'].shift(1) - df['low']) > (df['high'] - df['high'].shift(1)),
            np.maximum(df['low'].shift(1) - df['low'], 0), 0
        )
        
        tr = np.maximum(df['high'] - df['low'],
                       np.maximum(np.abs(df['high'] - df['close'].shift(1)),
                                 np.abs(df['low'] - df['close'].shift(1))))
        
        plus_di = 100 * pd.Series(plus_dm).rolling(period).mean() / pd.Series(tr).rolling(period).mean()
        minus_di = 100 * pd.Series(minus_dm).rolling(period).mean() / pd.Series(tr).rolling(period).mean()
        
        dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
        return dx.rolling(period).mean()
    
    def _calculate_obv(self, df: pd.DataFrame) -> pd.Series:
        """计算OBV"""
        obv = [0]
        for i in range(1, len(df)):
            if df['close'].iloc[i] > df['close'].iloc[i-1]:
                obv.append(obv[-1] + df['volume'].iloc[i])
            elif df['close'].iloc[i] < df['close'].iloc[i-1]:
                obv.append(obv[-1] - df['volume'].iloc[i])
            else:
                obv.append(obv[-1])
        return pd.Series(obv, index=df.index)
    
    def get_feature_columns(self) -> List[str]:
        """获取特征列名"""
        return [
            'returns', 'volatility', 'price_momentum',
            'rsi', 'rsi_slope', 'macd', 'macd_signal', 'macd_hist',
            'bb_position', 'bb_width', 'atr_pct', 'adx',
            'trend_direction', 'ma_cross',
            'volume_ratio', 'volume_trend', 'obv',
            'price_acceleration', 'volatility_regime',
            'hour', 'day_of_week'
        ]


class XGBoostStrategy:
    """XGBoost交易策略"""
    
    def __init__(self):
        self.model = None
        self.scaler = StandardScaler()
        self.feature_engineer = FeatureEngineer()
        self.is_trained = False
        
    def train(self, df: pd.DataFrame) -> Dict:
        """训练XGBoost模型"""
        if not ML_AVAILABLE:
            logger.error("ML库未安装，无法训练")
            return {}
        
        logger.info("开始训练XGBoost模型...")
        
        # 特征工程
        df_features = self.feature_engineer.calculate_all_features(df)
        feature_cols = self.feature_engineer.get_feature_columns()
        
        X = df_features[feature_cols]
        y = df_features['target']
        
        # 只使用有明确方向的样本（去掉0）
        mask = y != 0
        X = X[mask]
        y = y[mask]
        
        # 转换标签：-1 -> 0, 1 -> 1 (XGBoost需要0,1)
        y = np.where(y == -1, 0, 1)
        
        # 划分训练集
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, shuffle=False  # 时间序列不打乱
        )
        
        # 标准化
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_test_scaled = self.scaler.transform(X_test)
        
        # 训练XGBoost
        self.model = xgb.XGBClassifier(
            n_estimators=100,
            max_depth=5,
            learning_rate=0.1,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            eval_metric='mlogloss'
        )
        
        self.model.fit(X_train_scaled, y_train)
        
        # 评估
        y_pred = self.model.predict(X_test_scaled)
        accuracy = accuracy_score(y_test, y_pred)
        precision = precision_score(y_test, y_pred, average='weighted')
        recall = recall_score(y_test, y_pred, average='weighted')
        f1 = f1_score(y_test, y_pred, average='weighted')
        
        # 特征重要性
        importance = dict(zip(feature_cols, self.model.feature_importances_))
        
        logger.info(f"模型训练完成！准确率: {accuracy:.2%}")
        
        self.is_trained = True
        
        return {
            'accuracy': accuracy,
            'precision': precision,
            'recall': recall,
            'f1': f1,
            'feature_importance': importance
        }
    
    def predict(self, current_features: pd.DataFrame) -> Tuple[int, float]:
        """
        预测方向 - 使用Pipeline最佳实践
        返回: (方向: -1,0,1, 置信度)
        """
        if not self.is_trained:
            return 0, 0.0
        
        # 导入Pipeline
        from sklearn.pipeline import Pipeline
        
        feature_cols = self.feature_engineer.get_feature_columns()
        # 保持DataFrame格式，不转换为numpy数组，消除警告
        X = current_features[feature_cols].iloc[-1:]
        X_scaled = self.scaler.transform(X)
        
        # 预测
        pred = self.model.predict(X_scaled)[0]
        proba = self.model.predict_proba(X_scaled)[0]
        
        # 置信度
        confidence = np.max(proba)
        
        # 转换标签：0 -> -1 (跌), 1 -> 1 (涨)
        direction = 1 if pred == 1 else -1
        
        return direction, confidence
    
    def save_model(self, filepath: str):
        """保存模型"""
        if self.model:
            joblib.dump({
                'model': self.model,
                'scaler': self.scaler,
                'feature_engineer': self.feature_engineer
            }, filepath)
            logger.info(f"模型已保存: {filepath}")
    
    def load_model(self, filepath: str):
        """加载模型"""
        data = joblib.load(filepath)
        self.model = data['model']
        self.scaler = data['scaler']
        self.feature_engineer = data['feature_engineer']
        self.is_trained = True
        logger.info(f"模型已加载: {filepath}")


class EnsembleStrategy:
    """集成策略 - 组合多个信号源"""
    
    def __init__(self):
        self.xgb_strategy = XGBoostStrategy()
        self.rule_signals = None  # 规则信号
        self.weights = {
            'ml': 0.6,
            'rule': 0.4
        }
        
    def generate_signal(self, df: pd.DataFrame) -> Dict:
        """
        生成交易信号
        集成ML预测 + 规则信号
        """
        # ML信号
        ml_direction, ml_confidence = self.xgb_strategy.predict(df)
        
        # 规则信号（V2.5逻辑）
        rule_signal = self._rule_based_signal(df)
        
        # 集成决策
        combined_score = (
            self.weights['ml'] * ml_direction * ml_confidence +
            self.weights['rule'] * rule_signal['direction'] * rule_signal['confidence']
        )
        
        # 决策阈值（放宽）
        if combined_score > 0.3:
            action = 'BUY'
            confidence = min(abs(combined_score), 1.0)
        elif combined_score < -0.3:
            action = 'SELL'
            confidence = min(abs(combined_score), 1.0)
        else:
            action = 'HOLD'
            confidence = 0.0
        
        return {
            'action': action,
            'confidence': confidence,
            'ml_signal': ml_direction,
            'ml_confidence': ml_confidence,
            'rule_signal': rule_signal,
            'combined_score': combined_score
        }
    
    def _rule_based_signal(self, df: pd.DataFrame) -> Dict:
        """基于规则的备用信号"""
        row = df.iloc[-1]
        
        score = 0
        reasons = []
        
        # RSI
        if row['rsi'] < 30:
            score += 0.3
            reasons.append('RSI oversold')
        elif row['rsi'] > 70:
            score -= 0.3
            reasons.append('RSI overbought')
        
        # MACD
        if row['macd'] > row['macd_signal']:
            score += 0.2
            reasons.append('MACD bullish')
        else:
            score -= 0.2
            reasons.append('MACD bearish')
        
        # 趋势
        if row['close'] > row['ma50']:
            score += 0.2
        else:
            score -= 0.2
        
        return {
            'direction': 1 if score > 0 else -1 if score < 0 else 0,
            'confidence': min(abs(score), 1.0),
            'reasons': reasons
        }


class V4MLTrader:
    """V4 ML交易系统"""
    
    def __init__(self, initial_balance: float = 1000.0):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        
        # 策略组件
        self.ensemble = EnsembleStrategy()
        self.feature_engineer = FeatureEngineer()
        
        # 风控
        self.leverage = 3
        self.stop_loss = 0.03
        self.take_profit = 0.06
        self.position_size = 0.05  # 5%
        
        # 统计
        self.stats = {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'liquidations': 0
        }
        
        logger.info("V4-ML 交易系统初始化完成")
    
    def train_model(self, df: pd.DataFrame) -> Dict:
        """训练模型"""
        return self.ensemble.xgb_strategy.train(df)
    
    def run_backtest(self, df: pd.DataFrame) -> Dict:
        """运行回测"""
        logger.info("开始V4-ML回测...")
        
        # 计算所有特征
        df = self.feature_engineer.calculate_all_features(df)
        
        # 如果模型未训练，用前70%数据训练
        if not self.ensemble.xgb_strategy.is_trained:
            train_size = int(len(df) * 0.7)
            train_df = df.iloc[:train_size]
            self.train_model(train_df)
            df = df.iloc[train_size:].reset_index(drop=True)
        
        # 回测循环
        position = None
        trades = []
        equity_curve = []
        
        for i in range(50, len(df)):
            current_df = df.iloc[:i+1]
            current_price = df['close'].iloc[i]
            
            # 生成信号
            signal = self.ensemble.generate_signal(current_df)
            
            # 持仓管理
            if position:
                entry = position['entry_price']
                pnl_pct = (current_price - entry) / entry * self.leverage
                
                # 止损
                if pnl_pct <= -self.stop_loss * self.leverage * 100:
                    self.stats['losing_trades'] += 1
                    position = None
                    continue
                
                # 止盈
                if pnl_pct >= self.take_profit * self.leverage * 100:
                    self.stats['winning_trades'] += 1
                    position = None
                    continue
            
            # 新开仓（放宽置信度阈值）
            elif signal['action'] != 'HOLD' and signal['confidence'] > 0.4:
                margin = self.balance * self.position_size
                self.balance -= margin
                
                position = {
                    'side': signal['action'],
                    'entry_price': current_price,
                    'margin': margin,
                    'confidence': signal['confidence']
                }
                self.stats['total_trades'] += 1
            
            # 记录权益
            equity = self.balance
            if position:
                unrealized = position['margin'] * (current_price - position['entry_price']) / position['entry_price'] * self.leverage
                equity += position['margin'] + unrealized
            
            equity_curve.append(equity)
        
        # 计算收益
        total_return = (equity_curve[-1] - self.initial_balance) / self.initial_balance * 100
        
        return {
            'total_return': total_return,
            'total_trades': self.stats['total_trades'],
            'win_rate': self.stats['winning_trades'] / max(self.stats['total_trades'], 1) * 100,
            'equity_curve': equity_curve
        }


# 使用示例
def main():
    """主函数"""
    # 加载数据
    df = pd.read_csv('eth_usdt_1h_binance.csv')
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    # 创建交易系统
    trader = V4MLTrader(initial_balance=1000.0)
    
    # 运行回测
    results = trader.run_backtest(df)
    
    print(f"\n{'='*60}")
    print("V4-ML 回测结果")
    print(f"{'='*60}")
    print(f"总收益: {results['total_return']:+.2f}%")
    print(f"交易次数: {results['total_trades']}")
    print(f"胜率: {results['win_rate']:.1f}%")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()