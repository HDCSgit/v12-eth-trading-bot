#!/usr/bin/env python3
"""
V12-Professional: 专业级回测报告版
包含：详细统计、风险指标、交易记录、可视化数据导出
"""

import pandas as pd
import numpy as np
import logging
import json
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
        for period in [5, 10, 20]:
            df[f'ma_{period}'] = df['close'].rolling(period).mean()
        df['trend_short'] = np.where(df['ma_10'] > df['ma_20'], 1, -1)
        df['volume_ma'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma']
        for period in [3, 5, 10]:
            df[f'momentum_{period}'] = df['close'].pct_change(period)
        df['high_20'] = df['high'].rolling(20).max()
        df['low_20'] = df['low'].rolling(20).min()
        df['future_return'] = df['close'].shift(-3) / df['close'] - 1
        df['target'] = np.where(df['future_return'] > 0.005, 1, np.where(df['future_return'] < -0.005, 0, -1))
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
        feature_cols = ['rsi_12', 'macd_hist', 'bb_position', 'bb_width', 'momentum_5', 'trend_short']
        mask = df_feat['target'] != -1
        X = df_feat[feature_cols].loc[mask]
        y = df_feat['target'].loc[mask]
        if len(X) < 200: 
            return
        X_scaled = self.scaler.fit_transform(X)
        self.model = xgb.XGBClassifier(
            n_estimators=100, 
            max_depth=4, 
            learning_rate=0.08, 
            subsample=0.8, 
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
        X = df_feat[['rsi_12', 'macd_hist', 'bb_position', 'bb_width', 'momentum_5', 'trend_short']].iloc[-1:]
        X_scaled = self.scaler.transform(X)
        proba = self.model.predict_proba(X_scaled)[0]
        return {'direction': 1 if proba[1] > proba[0] else -1, 'confidence': max(proba)}


class V12ProfessionalTrader:
    """V12专业版 - 带详细统计"""
    
    def __init__(self, initial_balance: float = 1000.0):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.peak_balance = initial_balance
        self.ml_model = MLTradingModel()
        
        # 统计
        self.stats = {
            'total_trades': 0,
            'wins': 0,
            'losses': 0,
            'total_pnl': 0,
            'max_win': 0,
            'max_loss': 0,
            'win_streak': 0,
            'loss_streak': 0,
            'max_win_streak': 0,
            'max_loss_streak': 0
        }
        
        # 风险
        self.max_drawdown = 0
        self.drawdown_start = None
        self.trade_log = []
        self.equity_curve = []
        
        self.base_leverage = 2  # 降低杠杆
        self.trading_fee = 0.0004

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

    def update_drawdown(self):
        """更新最大回撤"""
        if self.balance > self.peak_balance:
            self.peak_balance = self.balance
            self.drawdown_start = None
        else:
            drawdown = (self.peak_balance - self.balance) / self.peak_balance
            if drawdown > self.max_drawdown:
                self.max_drawdown = drawdown

    def generate_signal(self, df: pd.DataFrame) -> str:
        """简化信号生成 - 降低门槛增加交易"""
        ml = self.ml_model.predict(df)
        
        # 大幅降低门槛到0.52
        if ml['confidence'] < 0.52:
            return 'HOLD'
        
        current = df.iloc[-1]
        
        # 简化：只要有ML信号就交易（不检查技术指标）
        if ml['direction'] == 1:
            return 'BUY'
        else:
            return 'SELL'

    def run_backtest(self, df: pd.DataFrame) -> dict:
        """运行专业回测"""
        df = self.resample_to_1h(df)
        train_size = int(len(df) * 0.4)
        self.ml_model.train(df.iloc[:train_size])
        
        test_df = df.iloc[train_size:].reset_index(drop=True)
        
        position = None
        entry_price = 0.0
        margin = 0.0
        entry_time = None
        
        for i in range(20, len(test_df)):
            current_time = test_df.iloc[i].get('open_time', test_df.index[i])
            price = test_df['close'].iloc[i]
            current_df = test_df.iloc[:i+1]
            
            # 记录权益曲线
            self.equity_curve.append({
                'time': current_time,
                'balance': self.balance
            })
            self.update_drawdown()
            
            # 持仓管理
            if position:
                pnl_pct = (price - entry_price) / entry_price * self.base_leverage
                if position == 'SELL':
                    pnl_pct = -pnl_pct
                
                # 止损止盈
                if pnl_pct <= -0.025 or pnl_pct >= 0.05:
                    # 平仓
                    pnl_amount = margin * pnl_pct
                    self.balance += margin + pnl_amount
                    
                    # 更新统计
                    if pnl_pct > 0:
                        self.stats['wins'] += 1
                        self.stats['total_pnl'] += pnl_amount
                        self.stats['max_win'] = max(self.stats['max_win'], pnl_amount)
                        self.stats['win_streak'] += 1
                        self.stats['loss_streak'] = 0
                        self.stats['max_win_streak'] = max(self.stats['max_win_streak'], self.stats['win_streak'])
                    else:
                        self.stats['losses'] += 1
                        self.stats['total_pnl'] += pnl_amount
                        self.stats['max_loss'] = min(self.stats['max_loss'], pnl_amount)
                        self.stats['loss_streak'] += 1
                        self.stats['win_streak'] = 0
                        self.stats['max_loss_streak'] = max(self.stats['max_loss_streak'], self.stats['loss_streak'])
                    
                    # 记录交易
                    self.trade_log.append({
                        'entry_time': entry_time,
                        'exit_time': current_time,
                        'side': position,
                        'entry_price': entry_price,
                        'exit_price': price,
                        'pnl_pct': pnl_pct * 100,
                        'pnl_amount': pnl_amount,
                        'result': 'WIN' if pnl_pct > 0 else 'LOSS'
                    })
                    
                    position = None
                    self.stats['total_trades'] += 1
                    continue
            
            # 开仓
            if not position:
                action = self.generate_signal(current_df)
                if action != 'HOLD':
                    margin = self.balance * 0.08
                    self.balance -= margin
                    entry_price = price
                    position = action
                    entry_time = current_time

        # 强制平仓最后一笔
        if position:
            self.stats['losses'] += 1
            self.stats['total_trades'] += 1
        
        # 计算指标
        total_return = (self.balance - self.initial_balance) / self.initial_balance * 100
        win_rate = self.stats['wins'] / max(self.stats['total_trades'], 1) * 100
        profit_factor = abs(self.stats['max_win'] / self.stats['max_loss']) if self.stats['max_loss'] != 0 else 0
        
        return {
            'total_return': total_return,
            'win_rate': win_rate,
            'total_trades': self.stats['total_trades'],
            'wins': self.stats['wins'],
            'losses': self.stats['losses'],
            'profit_factor': profit_factor,
            'max_drawdown': self.max_drawdown * 100,
            'max_win_streak': self.stats['max_win_streak'],
            'max_loss_streak': self.stats['max_loss_streak'],
            'avg_win': self.stats['total_pnl'] / self.stats['wins'] if self.stats['wins'] > 0 else 0,
            'trade_log': self.trade_log,
            'equity_curve': self.equity_curve
        }

    def print_professional_report(self, result: dict):
        """打印专业回测报告"""
        print("\n" + "=" * 80)
        print(" " * 20 + "📊 V12-PROFESSIONAL 回测报告")
        print("=" * 80)
        
        # 基本信息
        print("\n【基本指标】")
        print(f"  初始资金: ${self.initial_balance:,.2f}")
        print(f"  最终资金: ${self.balance:,.2f}")
        print(f"  总收益率: {result['total_return']:+7.2f}%")
        print(f"  总交易数: {result['total_trades']:4d} 笔")
        print(f"  盈利次数: {result['wins']:4d} 次")
        print(f"  亏损次数: {result['losses']:4d} 次")
        
        # 胜率与盈亏
        print("\n【胜率分析】")
        print(f"  胜率:       {result['win_rate']:6.2f}%")
        print(f"  盈亏比:     {result['profit_factor']:6.2f}")
        print(f"  最大连胜:   {result['max_win_streak']:3d} 次")
        print(f"  最大连亏:   {result['max_loss_streak']:3d} 次")
        
        # 风险指标
        print("\n【风险指标】")
        print(f"  最大回撤:   {result['max_drawdown']:6.2f}%")
        print(f"  杠杆倍数:   {self.base_leverage:.1f}x")
        print(f"  单笔仓位:   8.0%")
        
        # 交易记录（最近5笔）
        if result['trade_log']:
            print("\n【最近交易记录】")
            for trade in result['trade_log'][-5:]:
                print(f"  {trade['result']:4s} | {trade['pnl_pct']:+6.2f}% | "
                      f"${trade['pnl_amount']:+8.2f} | {str(trade['exit_time'])[:16]}")
        
        # 评分
        print("\n【综合评分】")
        score = 0
        if result['max_drawdown'] < 20: score += 25
        if result['win_rate'] > 55: score += 30
        elif result['win_rate'] > 50: score += 20
        if result['total_return'] > 0: score += 25
        if result['profit_factor'] > 1.5: score += 20
        
        print(f"  评分: {score}/100")
        if score >= 90:
            print("  🟢 优秀 - 立即实盘")
        elif score >= 75:
            print("  🟡 良好 - 可以实盘")
        elif score >= 60:
            print("  🟠 一般 - 谨慎使用")
        else:
            print("  🔴 较差 - 继续优化")
        
        print("=" * 80)


def main():
    logger.info("加载5分钟ETH数据...")
    df = pd.read_csv('eth_usdt_5m_2024_2026.csv')
    logger.info(f"数据条数: {len(df):,}")
    
    trader = V12ProfessionalTrader(initial_balance=1000.0)
    result = trader.run_backtest(df)
    trader.print_professional_report(result)
    
    # 导出数据
    with open('v12_backtest_report.json', 'w') as f:
        json.dump({
            'summary': {
                'total_return': result['total_return'],
                'win_rate': result['win_rate'],
                'total_trades': result['total_trades'],
                'max_drawdown': result['max_drawdown']
            },
            'trade_log': result['trade_log']
        }, f, indent=2, default=str)
    
    print("\n💾 详细报告已保存到 v12_backtest_report.json")


if __name__ == "__main__":
    main()