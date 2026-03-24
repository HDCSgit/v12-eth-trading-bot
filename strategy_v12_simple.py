#!/usr/bin/env python3
"""
V12-Simple: 简化版确保有交易
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
    logger.warning("ML库未安装，使用备用策略")


class SimpleTrader:
    """简化交易器 - 确保有交易"""
    
    def __init__(self, initial_balance: float = 1000.0):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.stats = {
            'total_trades': 0,
            'wins': 0,
            'losses': 0,
            'long_trades': 0,
            'short_trades': 0
        }
        self.trade_log = []
        self.base_leverage = 5
        self.trading_fee = 0.0004

    def resample_to_1h(self, df: pd.DataFrame) -> pd.DataFrame:
        """5m转1h"""
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
        
        # 计算技术指标
        df_1h['rsi'] = self.calculate_rsi(df_1h['close'])
        df_1h['ma10'] = df_1h['close'].rolling(10).mean()
        df_1h['ma20'] = df_1h['close'].rolling(20).mean()
        
        logger.info(f"✅ 数据重采样完成（{len(df_1h)}条）")
        return df_1h.dropna().reset_index()

    def calculate_rsi(self, prices, period=14):
        """计算RSI"""
        delta = prices.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss
        return 100 - 100 / (1 + rs)

    def generate_signal(self, df: pd.DataFrame, idx: int) -> str:
        """生成交易信号 - 超简化"""
        if idx < 20:
            return 'HOLD'
        
        current = df.iloc[idx]
        prev = df.iloc[idx-1]
        
        # 超卖反弹做多
        if current['rsi'] < 35 and current['close'] > prev['close']:
            return 'BUY'
        
        # 超买回落做空
        if current['rsi'] > 65 and current['close'] < prev['close']:
            return 'SELL'
        
        # 均线金叉做多
        if current['ma10'] > current['ma20'] and prev['ma10'] <= prev['ma20']:
            return 'BUY'
        
        # 均线死叉做空
        if current['ma10'] < current['ma20'] and prev['ma10'] >= prev['ma20']:
            return 'SELL'
        
        return 'HOLD'

    def run_backtest(self, df: pd.DataFrame) -> dict:
        """运行回测"""
        df = self.resample_to_1h(df)
        test_df = df.iloc[int(len(df)*0.3):].reset_index(drop=True)  # 只用10%做训练，90%回测
        
        position = None
        entry_price = 0.0
        margin = 0.0
        
        for i in range(20, len(test_df)):
            price = test_df['close'].iloc[i]
            
            # 持仓管理
            if position:
                pnl_pct = (price - entry_price) / entry_price * self.base_leverage
                if position == 'SELL':
                    pnl_pct = -pnl_pct
                
                # 止损止盈
                if pnl_pct <= -0.1 or pnl_pct >= 0.17:
                    self.balance += margin + (margin * pnl_pct)
                    
                    if pnl_pct > 0:
                        self.stats['wins'] += 1
                    else:
                        self.stats['losses'] += 1
                    
                    self.trade_log.append({
                        'side': position,
                        'pnl_pct': pnl_pct * 100,
                        'result': 'WIN' if pnl_pct > 0 else 'LOSS'
                    })
                    
                    position = None
                    self.stats['total_trades'] += 1
                    continue
            
            # 开仓
            if not position:
                action = self.generate_signal(test_df, i)
                
                if action == 'BUY':
                    self.stats['long_trades'] += 1
                elif action == 'SELL':
                    self.stats['short_trades'] += 1
                
                if action != 'HOLD':
                    margin = self.balance * 0.10  # 10%仓位
                    self.balance -= margin
                    entry_price = price
                    position = action

        # 强制平仓
        if position:
            self.stats['losses'] += 1
            self.stats['total_trades'] += 1
        
        # 计算结果
        total_return = (self.balance - self.initial_balance) / self.initial_balance * 100
        win_rate = self.stats['wins'] / max(self.stats['total_trades'], 1) * 100
        
        return {
            'total_return': total_return,
            'win_rate': win_rate,
            'total_trades': self.stats['total_trades'],
            'wins': self.stats['wins'],
            'losses': self.stats['losses'],
            'long_trades': self.stats['long_trades'],
            'short_trades': self.stats['short_trades'],
            'trade_log': self.trade_log
        }

    def print_report(self, result: dict):
        """打印报告"""
        print("\n" + "=" * 70)
        print(" " * 15 + "🚀 V12-SIMPLE 回测报告")
        print("=" * 70)
        
        print("\n【基本指标】")
        print(f"  初始资金: ${self.initial_balance:,.2f}")
        print(f"  最终资金: ${self.balance:,.2f}")
        print(f"  总收益率: {result['total_return']:+7.2f}%")
        
        print("\n【交易统计】")
        print(f"  总交易数: {result['total_trades']:4d} 笔")
        print(f"  做多次数: {result['long_trades']:4d} 笔")
        print(f"  做空次数: {result['short_trades']:4d} 笔")
        print(f"  盈利次数: {result['wins']:4d} 次")
        print(f"  亏损次数: {result['losses']:4d} 次")
        print(f"  胜率:     {result['win_rate']:6.2f}%")
        
        if result['trade_log']:
            print("\n【最近交易】")
            for trade in result['trade_log'][-5:]:
                print(f"  {trade['side']:4s} | {trade['result']:4s} | {trade['pnl_pct']:+6.2f}%")
        
        # 评分
        score = 0
        if result['win_rate'] > 50: score += 30
        if result['total_return'] > 0: score += 40
        if result['total_trades'] > 100: score += 30
        
        print(f"\n【评分】{score}/100")
        if score >= 80:
            print("  🟢 优秀")
        elif score >= 60:
            print("  🟡 良好")
        else:
            print("  🔴 需优化")
        
        print("=" * 70)


def main():
    logger.info("加载数据...")
    df = pd.read_csv('eth_usdt_5m_2024_2026.csv')
    logger.info(f"数据条数: {len(df):,}")
    
    trader = SimpleTrader(initial_balance=1000.0)
    result = trader.run_backtest(df)
    trader.print_report(result)


if __name__ == "__main__":
    main()