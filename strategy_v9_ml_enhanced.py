#!/usr/bin/env python3
"""
V9-ML-Enhanced: 机器学习增强版高频交易系统
核心：V9极简框架 + XGBoost动态学习 + 自适应风控 + 智能参数优化
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


class MLFeatureEngineer:
    """ML特征工程 - 为动态学习准备特征"""
    
    def __init__(self):
        self.feature_cols = []
        
    def create_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """创建ML特征"""
        df = df.copy()
        
        # 价格特征
        df['returns'] = df['close'].pct_change()
        
        # 多周期动量
        for period in [3, 5, 10, 20]:
            df[f'momentum_{period}'] = df['close'].pct_change(period)
            df[f'volatility_{period}'] = df['returns'].rolling(period).std()
        
        # 价格位置
        df['high_20'] = df['high'].rolling(20).max()
        df['low_20'] = df['low'].rolling(20).min()
        df['price_position'] = (df['close'] - df['low_20']) / (df['high_20'] - df['low_20'] + 1e-10)
        
        # 量能特征
        df['volume_ma'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma']
        
        # 趋势强度
        df['trend_5'] = np.where(df['close'] > df['close'].shift(5), 1, -1)
        df['trend_10'] = np.where(df['close'] > df['close'].shift(10), 1, -1)
        
        # 目标变量（未来3周期收益）
        df['future_return'] = df['close'].shift(-3) / df['close'] - 1
        df['target'] = np.where(df['future_return'] > 0.002, 1, 
                               np.where(df['future_return'] < -0.002, 0, -1))
        
        return df.dropna()


class DynamicRiskManager:
    """动态风险管理器 - 自适应止盈止损"""
    
    def __init__(self):
        self.volatility_history = []
        self.win_streak = 0
        self.loss_streak = 0
        
    def calculate_dynamic_levels(self, df: pd.DataFrame, current_price: float, 
                                 position_side: str, entry_price: float) -> Dict:
        """计算动态止盈止损水平"""
        # 基于波动率调整 - 计算returns
        returns = df['close'].pct_change()
        recent_vol = returns.tail(20).std()
        atr = self._calculate_atr(df)
        
        # 基于连赢/连输调整
        if self.win_streak >= 3:
            # 连赢时收紧止盈，让利润奔跑
            take_profit = 0.038  # 止盈稍微放宽
            stop_loss = 0.012    # 止损收紧（连输时更狠）
        elif self.loss_streak >= 2:
            # 连输时收紧止损，保护本金
            take_profit = 0.038
            stop_loss = 0.012
        else:
            # 正常情况
            take_profit = 0.038
            stop_loss = 0.012
        
        # 根据市场波动率微调
        if recent_vol > 0.02:  # 高波动
            take_profit *= 1.2
            stop_loss *= 1.2
        elif recent_vol < 0.01:  # 低波动
            take_profit *= 0.8
            stop_loss *= 0.8
        
        return {
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'trailing_stop': take_profit * 0.5  # 移动止损
        }
    
    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """计算ATR"""
        high = df['high'].iloc[-period:]
        low = df['low'].iloc[-period:]
        close = df['close'].iloc[-period:]
        
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.mean()
    
    def update_streak(self, result: str):
        """更新连胜/连输记录"""
        if result == 'WIN':
            self.win_streak += 1
            self.loss_streak = 0
        else:
            self.loss_streak += 1
            self.win_streak = 0


class MLTradingModel:
    """ML交易模型 - 动态学习市场行情"""
    
    def __init__(self):
        self.model = None
        self.scaler = StandardScaler()
        self.is_trained = False
        self.feature_eng = MLFeatureEngineer()
        self.prediction_history = []
        
    def train(self, df: pd.DataFrame):
        """训练模型"""
        if not ML_AVAILABLE:
            return
        
        df_features = self.feature_eng.create_features(df)
        
        # 只使用明确的涨跌信号
        mask = df_features['target'] != -1
        X = df_features[self._get_feature_cols()].loc[mask]
        y = df_features['target'].loc[mask]
        
        if len(X) < 100:
            return
        
        # 标准化
        X_scaled = self.scaler.fit_transform(X)
        
        # 训练XGBoost
        self.model = xgb.XGBClassifier(
            n_estimators=50,
            max_depth=4,
            learning_rate=0.1,
            subsample=0.8,
            random_state=42,
            eval_metric='logloss'
        )
        
        self.model.fit(X_scaled, y)
        self.is_trained = True
        
        logger.info(f"ML模型训练完成，样本数: {len(X)}")
    
    def predict(self, df: pd.DataFrame) -> Dict:
        """预测信号强度"""
        if not self.is_trained or not ML_AVAILABLE:
            return {'direction': 0, 'confidence': 0.5}
        
        df_features = self.feature_eng.create_features(df)
        
        if len(df_features) == 0:
            return {'direction': 0, 'confidence': 0.5}
        
        X = df_features[self._get_feature_cols()].iloc[-1:]
        X_scaled = self.scaler.transform(X)
        
        proba = self.model.predict_proba(X_scaled)[0]
        pred = self.model.predict(X_scaled)[0]
        
        # 记录预测历史用于回测
        self.prediction_history.append({
            'time': datetime.now(),
            'prediction': pred,
            'confidence': max(proba),
            'up_prob': proba[1],
            'down_prob': proba[0]
        })
        
        return {
            'direction': 1 if pred == 1 else -1,
            'confidence': max(proba),
            'up_prob': proba[1],
            'down_prob': proba[0]
        }
    
    def _get_feature_cols(self) -> List[str]:
        """获取特征列"""
        return ['returns', 'momentum_3', 'momentum_5', 'momentum_10',
                'volatility_5', 'volatility_10', 'price_position', 
                'volume_ratio', 'trend_5', 'trend_10']


class V9MLEnhancedTrader:
    """V9-ML-Enhanced 机器学习增强版"""
    
    def __init__(self, initial_balance: float = 1000.0):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        
        # 交易参数（动态调整）
        self.base_leverage = 3          # 回到你喜欢的杠杆
        self.base_position_size = 0.08  # 仓位再小一点
        
        # 组件
        self.ml_model = MLTradingModel()
        self.risk_manager = DynamicRiskManager()
        
        # 统计
        self.stats = {
            'total_trades': 0,
            'wins': 0,
            'losses': 0,
            'liquidations': 0,
            'ml_correct': 0,
            'ml_total': 0
        }
        
        self.trade_log = []
        
        logger.info("\n" + "=" * 70)
        logger.info("🚀 V9-ML-Enhanced 机器学习增强版")
        logger.info("核心: XGBoost动态学习 + 自适应风控")
        logger.info("=" * 70)
    
    def generate_enhanced_signals(self, df: pd.DataFrame) -> Dict:
        """生成增强信号 - 结合规则和ML"""
        # 基础信号（V9极简）
        current = df.iloc[-1]
        prev = df.iloc[-2]
        prev2 = df.iloc[-3]
        
        base_signals = []
        
        # 多头基础信号
        if current['close'] < prev['close'] and prev['close'] < prev2['close']:
            base_signals.append('Consecutive_Drop')
        if current['close'] < min(prev['low'], prev2['low']):
            base_signals.append('Below_Low')
        if current['close'] > current['open']:
            base_signals.append('Bullish_Candle')
        
        # ML增强
        ml_pred = self.ml_model.predict(df)
        
        # 信号融合
        score = len(base_signals)
        if ml_pred['direction'] == 1 and ml_pred['confidence'] > 0.68:  # 过滤更严格
            score += 2  # ML确认做多
        elif ml_pred['direction'] == -1 and ml_pred['confidence'] > 0.68:  # 过滤更严格
            score -= 2  # ML确认做空
        
        # 动态仓位
        position_size = self.base_position_size
        if ml_pred['confidence'] > 0.68:      # 降低加仓门槛
            position_size *= 1.4
        elif ml_pred['confidence'] < 0.55:
            position_size *= 0.6
        
        return {
            'action': 'BUY' if score >= 2 else 'SELL' if score <= -2 else 'HOLD',
            'score': score,
            'position_size': position_size,
            'ml_confidence': ml_pred['confidence'],
            'base_signals': base_signals
        }
    
    def run_backtest(self, df: pd.DataFrame) -> Dict:
        """运行ML增强回测"""
        # 训练ML模型（前80%数据）
        train_size = int(len(df) * 0.8)
        train_df = df.iloc[:train_size]
        
        logger.info("训练ML模型...")
        self.ml_model.train(train_df)
        
        # 回测（后20%数据）
        test_df = df.iloc[train_size:].reset_index(drop=True)
        
        position = None
        position_side = None
        entry_price = None
        position_bars = 0
        
        for i in range(3, len(test_df)):
            current_df = test_df.iloc[:i+1]
            current_price = test_df['close'].iloc[i]
            
            # 动态风控
            if position:
                position_bars += 1
                
                if position_side == 'LONG':
                    pnl_pct = (current_price - entry_price) / entry_price * self.base_leverage
                else:
                    pnl_pct = (entry_price - current_price) / entry_price * self.base_leverage
                
                # 获取动态止盈止损
                risk_levels = self.risk_manager.calculate_dynamic_levels(
                    current_df, current_price, position_side, entry_price
                )
                
                # 爆仓检查
                if pnl_pct <= -48:
                    self.stats['liquidations'] += 1
                    self.balance *= 0.04
                    position = None
                    self.risk_manager.update_streak('LOSE')
                    continue
                
                # 止损
                if pnl_pct <= -risk_levels['stop_loss'] * 100:
                    loss = position['margin'] * risk_levels['stop_loss'] * self.base_leverage
                    self.balance -= loss
                    self.stats['losses'] += 1
                    position = None
                    self.risk_manager.update_streak('LOSE')
                    continue
                
                # 止盈
                if pnl_pct >= risk_levels['take_profit'] * 100:
                    profit = position['margin'] * risk_levels['take_profit'] * self.base_leverage
                    self.balance += position['margin'] + profit
                    self.stats['wins'] += 1
                    position = None
                    self.risk_manager.update_streak('WIN')
                    continue
                
                # 移动止损（保护利润）
                if pnl_pct > risk_levels['trailing_stop'] * 100:
                    # 如果回调超过利润的50%，平仓
                    if pnl_pct < position.get('max_profit', 0) * 0.5:
                        profit = position['margin'] * pnl_pct / 100
                        self.balance += position['margin'] + profit
                        self.stats['wins'] += 1
                        position = None
                        self.risk_manager.update_streak('WIN')
                        continue
                
                # 记录最高利润
                if pnl_pct > position.get('max_profit', 0):
                    position['max_profit'] = pnl_pct
                
                # 强制平仓（持仓过久）
                if position_bars >= 15:
                    if pnl_pct > 0:
                        profit = position['margin'] * pnl_pct / 100
                        self.balance += position['margin'] + profit
                        self.stats['wins'] += 1
                        self.risk_manager.update_streak('WIN')
                    else:
                        loss = position['margin'] * abs(pnl_pct) / 100
                        self.balance += position['margin'] - loss
                        self.stats['losses'] += 1
                        self.risk_manager.update_streak('LOSE')
                    
                    position = None
                    position_bars = 0
            
            # 新开仓
            else:
                signal = self.generate_enhanced_signals(current_df)
                
                if signal['action'] in ['BUY', 'SELL']:
                    margin = self.balance * signal['position_size']
                    self.balance -= margin
                    
                    position = {
                        'margin': margin,
                        'max_profit': 0
                    }
                    position_side = 'LONG' if signal['action'] == 'BUY' else 'SHORT'
                    entry_price = current_price
                    position_bars = 0
                    self.stats['total_trades'] += 1
        
        # 计算结果
        total_return = (self.balance - self.initial_balance) / self.initial_balance * 100
        
        win_rate = self.stats['wins'] / max(self.stats['total_trades'], 1) * 100
        
        return {
            'total_return': total_return,
            'total_trades': self.stats['total_trades'],
            'win_rate': win_rate,
            'wins': self.stats['wins'],
            'losses': self.stats['losses'],
            'liquidations': self.stats['liquidations']
        }


def main():
    """主函数"""
    logger.info("加载5分钟ETH数据...")
    df = pd.read_csv('eth_usdt_5m_2024_2026.csv')
    logger.info(f"数据条数: {len(df):,}")
    
    # 运行回测
    trader = V9MLEnhancedTrader(initial_balance=1000.0)
    result = trader.run_backtest(df)
    
    # 打印报告
    print("\n" + "=" * 70)
    print("🚀 V9-ML-Enhanced 回测报告")
    print("=" * 70)
    print(f"\n💰 收益: {result['total_return']:+.2f}%")
    print(f"\n📊 交易: {result['total_trades']} 笔")
    print(f"  胜率: {result['win_rate']:.1f}%")
    print(f"  盈利: {result['wins']} | 亏损: {result['losses']}")
    print(f"\n🛡️ 爆仓: {result['liquidations']} 次")
    print("=" * 70)


if __name__ == "__main__":
    main()