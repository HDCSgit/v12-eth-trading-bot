#!/usr/bin/env python3
"""
V9-Optimized: 融合V2.5规则 + ML的优化版本
目标：胜率56%+，收益转正，交易次数4000-6000笔
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


class EnhancedFeatureEngineer:
    """增强特征工程 - 融合V2.5的强特征"""
    
    def create_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """创建全面特征集"""
        df = df.copy()
        
        # 基础价格特征
        df['returns'] = df['close'].pct_change()
        
        # ========== V2.5核心特征 ==========
        
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
        
        # 均线多周期
        for period in [5, 10, 20, 55, 200]:
            df[f'ma_{period}'] = df['close'].rolling(period).mean()
        
        # 趋势判断
        df['trend_short'] = np.where(df['ma_10'] > df['ma_20'], 1, -1)
        df['trend_long'] = np.where(df['ma_55'] > df['ma_200'], 1, -1)
        
        # 量能特征
        df['volume_ma'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma']
        df['volume_spike'] = (df['volume_ratio'] > 1.8).astype(int)
        
        # 动量和波动率
        for period in [3, 5, 10, 20]:
            df[f'momentum_{period}'] = df['close'].pct_change(period)
            df[f'volatility_{period}'] = df['returns'].rolling(period).std()
        
        # 价格位置
        df['high_20'] = df['high'].rolling(20).max()
        df['low_20'] = df['low'].rolling(20).min()
        df['price_position'] = (df['close'] - df['low_20']) / (df['high_20'] - df['low_20'] + 1e-10)
        
        # 目标变量（未来5周期收益，更宽松）
        df['future_return'] = df['close'].shift(-5) / df['close'] - 1
        df['target'] = np.where(df['future_return'] > 0.003, 1,  # 0.3%
                               np.where(df['future_return'] < -0.003, 0, -1))
        
        return df.dropna()


class V25StrategyRules:
    """V2.5规则策略 - 生成强规则信号"""
    
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算指标"""
        df = df.copy()
        
        # RSI
        delta = df['close'].diff()
        gain = delta.clip(lower=0).rolling(12).mean()
        loss = (-delta.clip(upper=0)).rolling(12).mean()
        df['rsi_12'] = 100 - 100 / (1 + gain / (loss + 1e-10))
        
        # MACD
        ema12 = df['close'].ewm(span=12).mean()
        ema26 = df['close'].ewm(span=26).mean()
        df['macd'] = ema12 - ema26
        df['macd_signal'] = df['macd'].ewm(span=9).mean()
        
        # 布林带
        df['bb_mid'] = df['close'].rolling(20).mean()
        df['bb_std'] = df['close'].rolling(20).std()
        df['bb_upper'] = df['bb_mid'] + 2 * df['bb_std']
        df['bb_lower'] = df['bb_mid'] - 2 * df['bb_std']
        
        # 均线
        df['ma_10'] = df['close'].rolling(10).mean()
        df['ma_20'] = df['close'].rolling(20).mean()
        
        # 量能
        df['volume_ma'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma']
        
        return df.dropna()
    
    def get_rule_signals(self, df: pd.DataFrame) -> Dict:
        """获取V2.5规则信号"""
        # 计算指标
        df = self.calculate_indicators(df)
        
        row = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else row
        
        long_signals = []
        short_signals = []
        confidence = 0.5
        
        # ========== 多头规则（V2.5核心）==========
        
        # 1. RSI超卖 (<40)
        if row['rsi_12'] < 40:
            long_signals.append('RSI_Oversold')
            confidence += 0.15
        
        # 2. 布林带下轨反弹
        if row['close'] < row['bb_lower'] * 1.01:
            long_signals.append('BB_Bounce')
            confidence += 0.15
        
        # 3. MACD金叉
        if row['macd'] > row['macd_signal'] and prev['macd'] <= prev['macd_signal']:
            long_signals.append('MACD_Cross')
            confidence += 0.2
        
        # 4. 均线金叉
        if row['ma_10'] > row['ma_20'] and prev['ma_10'] <= prev['ma_20']:
            long_signals.append('MA_Cross')
            confidence += 0.15
        
        # 5. 放量上涨
        if row['volume_ratio'] > 1.5 and row['close'] > row['open']:
            long_signals.append('Volume_Break')
            confidence += 0.1
        
        # 6. 趋势向上 + RSI合理
        if row['trend_long'] == 1 and row['rsi_12'] < 60:
            long_signals.append('Trend_Follow')
            confidence += 0.1
        
        # ========== 空头规则 ==========
        
        # 1. RSI超买 (>60)
        if row['rsi_12'] > 60:
            short_signals.append('RSI_Overbought')
            confidence += 0.15
        
        # 2. 布林带上轨回落
        if row['close'] > row['bb_upper'] * 0.99:
            short_signals.append('BB_Reject')
            confidence += 0.15
        
        # 3. MACD死叉
        if row['macd'] < row['macd_signal'] and prev['macd'] >= prev['macd_signal']:
            short_signals.append('MACD_Cross_Down')
            confidence += 0.2
        
        # 4. 均线死叉
        if row['ma_10'] < row['ma_20'] and prev['ma_10'] >= prev['ma_20']:
            short_signals.append('MA_Cross_Down')
            confidence += 0.15
        
        # 5. 放量下跌
        if row['volume_ratio'] > 1.5 and row['close'] < row['open']:
            short_signals.append('Volume_Drop')
            confidence += 0.1
        
        # 决策
        if len(long_signals) >= 2 and confidence >= 0.7:
            return {'action': 'BUY', 'confidence': min(confidence, 1.0), 'signals': long_signals}
        elif len(short_signals) >= 2 and confidence >= 0.7:
            return {'action': 'SELL', 'confidence': min(confidence, 1.0), 'signals': short_signals}
        else:
            return {'action': 'HOLD', 'confidence': confidence, 'signals': []}


class MLModel:
    """ML模型"""
    
    def __init__(self):
        self.model = None
        self.scaler = StandardScaler()
        self.is_trained = False
        self.feature_eng = EnhancedFeatureEngineer()
        
    def train(self, df: pd.DataFrame):
        """训练模型"""
        if not ML_AVAILABLE:
            return
        
        df_features = self.feature_eng.create_features(df)
        mask = df_features['target'] != -1
        
        feature_cols = ['rsi_12', 'rsi_24', 'macd', 'macd_hist', 'bb_position', 
                       'bb_width', 'volume_ratio', 'momentum_5', 'momentum_10',
                       'volatility_10', 'trend_short', 'price_position']
        
        X = df_features[feature_cols].loc[mask]
        y = df_features['target'].loc[mask]
        
        if len(X) < 1000:
            return
        
        X_scaled = self.scaler.fit_transform(X)
        
        self.model = xgb.XGBClassifier(
            n_estimators=100,
            max_depth=5,
            learning_rate=0.1,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42
        )
        
        self.model.fit(X_scaled, y)
        self.is_trained = True
        logger.info(f"ML模型训练完成: {len(X)}样本")
    
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


class V9OptimizedTrader:
    """V9优化版 - 融合V2.5规则 + ML"""
    
    def __init__(self, initial_balance: float = 1000.0):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        
        # 交易参数
        self.leverage = 3  # 提高到3x
        self.base_position_size = 0.12
        
        # 交易成本（币安永续合约）
        self.trading_fee = 0.0004  # 0.04% taker费
        self.total_cost_per_trade = self.trading_fee * 2  # 双向
        
        # 组件
        self.ml_model = MLModel()
        self.rule_strategy = V25StrategyRules()
        
        # 统计
        self.stats = {
            'total_trades': 0,
            'wins': 0,
            'losses': 0,
            'liquidations': 0,
            'total_fees': 0
        }
        
        logger.info("\n" + "=" * 70)
        logger.info("🚀 V9-Optimized 融合版")
        logger.info("V2.5规则 + ML加权 + 成本建模")
        logger.info(f"杠杆: {self.leverage}x | 成本: {self.total_cost_per_trade*100:.2f}%")
        logger.info("=" * 70)
    
    def generate_fusion_signal(self, df: pd.DataFrame) -> Dict:
        """生成融合信号"""
        # 规则信号（权重60%）
        rule_signal = self.rule_strategy.get_rule_signals(df)
        
        # ML信号（权重40%）
        ml_pred = self.ml_model.predict(df)
        
        # 融合计算
        rule_weight = 0.6
        ml_weight = 0.4
        
        # 规则置信度
        rule_conf = rule_signal['confidence'] if rule_signal['action'] != 'HOLD' else 0.5
        
        # ML置信度
        ml_conf = ml_pred['confidence'] if ml_pred['confidence'] > 0.5 else 0.5
        
        # 最终置信度
        final_conf = rule_conf * rule_weight + ml_conf * ml_weight
        
        # 方向确认（需要规则和ML一致）
        rule_dir = 1 if rule_signal['action'] == 'BUY' else -1 if rule_signal['action'] == 'SELL' else 0
        ml_dir = ml_pred['direction']
        
        # 动态仓位
        position_size = self.base_position_size
        if final_conf > 0.8:
            position_size *= 1.3  # 高置信度加仓
        elif final_conf < 0.65:
            position_size *= 0.7  # 低置信度减仓
        
        # 决策：需要规则和ML方向一致，且置信度>0.65
        if rule_dir == 1 and ml_dir == 1 and final_conf > 0.65:
            return {'action': 'BUY', 'confidence': final_conf, 'position_size': position_size}
        elif rule_dir == -1 and ml_dir == -1 and final_conf > 0.65:
            return {'action': 'SELL', 'confidence': final_conf, 'position_size': position_size}
        else:
            return {'action': 'HOLD', 'confidence': final_conf, 'position_size': 0}
    
    def run_backtest(self, df: pd.DataFrame) -> Dict:
        """运行回测（含成本建模）"""
        # 训练ML（前80%）
        train_size = int(len(df) * 0.8)
        train_df = df.iloc[:train_size]
        
        logger.info("训练ML模型...")
        self.ml_model.train(train_df)
        
        # 回测（后20%）
        test_df = df.iloc[train_size:].reset_index(drop=True)
        
        position = None
        position_side = None
        entry_price = None
        position_bars = 0
        
        for i in range(55, len(test_df)):  # 需要55周期指标
            current_df = test_df.iloc[:i+1]
            current_price = test_df['close'].iloc[i]
            
            # 持仓管理
            if position:
                position_bars += 1
                
                if position_side == 'LONG':
                    pnl_pct = (current_price - entry_price) / entry_price * self.leverage
                else:
                    pnl_pct = (entry_price - current_price) / entry_price * self.leverage
                
                # 扣除持仓资金费（简化：每天0.01%）
                self.balance *= (1 - 0.0001)
                
                # 止损2%
                if pnl_pct <= -6:  # 2% * 3x
                    loss = position['margin'] * 0.06  # 包含成本
                    self.balance -= loss
                    self.stats['losses'] += 1
                    self.stats['total_fees'] += position['margin'] * self.total_cost_per_trade
                    position = None
                    continue
                
                # 止盈4%
                if pnl_pct >= 12:  # 4% * 3x
                    profit = position['margin'] * 0.12
                    self.balance += position['margin'] + profit
                    self.stats['wins'] += 1
                    self.stats['total_fees'] += position['margin'] * self.total_cost_per_trade
                    position = None
                    continue
                
                # 强制平仓（12周期）
                if position_bars >= 12:
                    # 扣除平仓成本
                    self.stats['total_fees'] += position['margin'] * self.total_cost_per_trade
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
                signal = self.generate_fusion_signal(current_df)
                
                if signal['action'] in ['BUY', 'SELL']:
                    # 扣除开仓成本
                    cost = self.balance * signal['position_size'] * self.total_cost_per_trade
                    self.balance -= cost
                    self.stats['total_fees'] += cost
                    
                    margin = self.balance * signal['position_size']
                    self.balance -= margin
                    
                    position = {'margin': margin}
                    position_side = 'LONG' if signal['action'] == 'BUY' else 'SHORT'
                    entry_price = current_price
                    position_bars = 0
                    self.stats['total_trades'] += 1
        
        # 计算结果
        total_return = (self.balance - self.initial_balance) / self.initial_balance * 100
        win_rate = self.stats['wins'] / max(self.stats['total_trades'], 1) * 100
        profit_factor = self.stats['wins'] / max(self.stats['losses'], 1)
        
        return {
            'total_return': total_return,
            'total_trades': self.stats['total_trades'],
            'win_rate': win_rate,
            'profit_factor': profit_factor,
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
    
    trader = V9OptimizedTrader(initial_balance=1000.0)
    result = trader.run_backtest(df)
    
    print("\n" + "=" * 70)
    print("🚀 V9-Optimized 回测报告")
    print("=" * 70)
    print(f"\n💰 总收益: {result['total_return']:+.2f}%")
    print(f"📊 交易: {result['total_trades']} 笔")
    print(f"  胜率: {result['win_rate']:.1f}% (目标>56%)")
    print(f"  盈亏比: {result['profit_factor']:.2f}")
    print(f"  盈利: {result['wins']} | 亏损: {result['losses']}")
    print(f"\n💸 总成本: ${result['total_fees']:.2f}")
    print(f"🛡️ 爆仓: {result['liquidations']} 次")
    
    # 评分
    score = 0
    if result['liquidations'] == 0: score += 30
    if result['win_rate'] > 56: score += 30
    elif result['win_rate'] > 53: score += 20
    if result['total_return'] > 0: score += 25
    if result['profit_factor'] > 1.2: score += 15
    
    print(f"\n⭐ 综合评分: {score}/100")
    if score >= 85: print("🟢 优秀 - 建议实盘")
    elif score >= 70: print("🟡 良好 - 可优化")
    else: print("🟠 一般 - 需调整")
    print("=" * 70)


if __name__ == "__main__":
    main()