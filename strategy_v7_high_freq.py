#!/usr/bin/env python3
"""
V7-HighFreq: 高频交易系统
目标：年交易900笔，快速进出，高胜率
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


class HighFreqSignalGenerator:
    """高频信号生成器 - 极简条件，快速触发"""
    
    def __init__(self):
        pass
    
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算基础指标"""
        df = df.copy()
        
        # RSI
        delta = df['close'].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        df['rsi'] = 100 - 100 / (1 + gain / (loss + 1e-10))
        
        # MACD
        ema12 = df['close'].ewm(span=12).mean()
        ema26 = df['close'].ewm(span=26).mean()
        df['macd'] = ema12 - ema26
        df['macd_signal'] = df['macd'].ewm(span=9).mean()
        
        # 均线
        df['ma5'] = df['close'].rolling(5).mean()
        df['ma10'] = df['close'].rolling(10).mean()
        df['ma20'] = df['close'].rolling(20).mean()
        
        # 布林带
        df['bb_mid'] = df['close'].rolling(20).mean()
        df['bb_std'] = df['close'].rolling(20).std()
        df['bb_upper'] = df['bb_mid'] + 2 * df['bb_std']
        df['bb_lower'] = df['bb_mid'] - 2 * df['bb_std']
        
        # 价格变化
        df['returns'] = df['close'].pct_change()
        df['price_change_3'] = df['close'].pct_change(3) * 100
        
        return df.dropna()
    
    def generate_signals(self, df: pd.DataFrame) -> Dict:
        """生成高频交易信号 - 极简条件"""
        df = self.calculate_indicators(df)
        row = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else row
        
        long_signals = []
        short_signals = []
        
        # ========== 极简多头信号 ==========
        
        # 信号1: RSI超卖（最简单）
        if row['rsi'] < 35:
            long_signals.append(('RSI_Oversold', 0.60))
        
        # 信号2: 价格触及布林带下轨
        if row['close'] < row['bb_lower'] * 1.01:
            long_signals.append(('BB_Lower_Touch', 0.55))
        
        # 信号3: 短期均线金叉
        if row['ma5'] > row['ma10'] and prev['ma5'] <= prev['ma10']:
            long_signals.append(('MA_Cross_Up', 0.65))
        
        # 信号4: MACD金叉
        if row['macd'] > row['macd_signal'] and prev['macd'] <= prev['macd_signal']:
            long_signals.append(('MACD_Cross_Up', 0.60))
        
        # 信号5: 连续下跌后反弹
        if row['price_change_3'] < -1.5:
            long_signals.append(('Drop_Bounce', 0.50))
        
        # ========== 极简空头信号 ==========
        
        # 信号1: RSI超买
        if row['rsi'] > 65:
            short_signals.append(('RSI_Overbought', 0.60))
        
        # 信号2: 价格触及布林带上轨
        if row['close'] > row['bb_upper'] * 0.99:
            short_signals.append(('BB_Upper_Touch', 0.55))
        
        # 信号3: 短期均线死叉
        if row['ma5'] < row['ma10'] and prev['ma5'] >= prev['ma10']:
            short_signals.append(('MA_Cross_Down', 0.65))
        
        # 信号4: MACD死叉
        if row['macd'] < row['macd_signal'] and prev['macd'] >= prev['macd_signal']:
            short_signals.append(('MACD_Cross_Down', 0.60))
        
        # 信号5: 连续上涨后回落
        if row['price_change_3'] > 1.5:
            short_signals.append(('Rise_Drop', 0.50))
        
        # 计算得分
        long_score = sum([conf for _, conf in long_signals])
        short_score = sum([conf for _, conf in short_signals])
        
        # 只要有信号就交易（高频模式）
        if len(long_signals) > 0:
            return {
                'action': 'BUY',
                'strength': min(long_score, 1.0),
                'signals': long_signals,
                'score': long_score
            }
        elif len(short_signals) > 0:
            return {
                'action': 'SELL',
                'strength': min(short_score, 1.0),
                'signals': short_signals,
                'score': short_score
            }
        else:
            return {
                'action': 'HOLD',
                'strength': 0,
                'signals': [],
                'score': 0
            }


class V7HighFreqTrader:
    """V7高频交易系统"""
    
    def __init__(self, initial_balance: float = 1000.0):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        
        # 高频交易参数
        self.leverage = 2
        self.stop_loss = 0.02  # 2%止损（快速止损）
        self.take_profit = 0.04  # 4%止盈（快速止盈）
        self.position_size = 0.10  # 10%仓位（提高仓位）
        
        # 风控
        self.max_drawdown = 0.25  # 25%最大回撤
        
        # 策略
        self.signal_generator = HighFreqSignalGenerator()
        
        # 统计
        self.stats = {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'liquidations': 0
        }
        
        logger.info("=" * 70)
        logger.info("V7-HighFreq 高频交易系统")
        logger.info(f"杠杆: {self.leverage}x | 止损: {self.stop_loss*100}% | 止盈: {self.take_profit*100}%")
        logger.info(f"仓位: {self.position_size*100}% | 目标: 年交易900笔")
        logger.info("=" * 70)
    
    def run_backtest(self, df: pd.DataFrame) -> Dict:
        """运行高频回测"""
        logger.info("开始V7-HighFreq高频回测...")
        
        position = None
        equity_curve = []
        entry_time = None
        
        # 高频交易：减少预热期，增加交易频率
        for i in range(50, len(df)):
            current_df = df.iloc[:i+1]
            current_price = df['close'].iloc[i]
            current_time = df['timestamp'].iloc[i] if 'timestamp' in df.columns else i
            
            # 持仓管理
            if position:
                entry = position['entry_price']
                
                if position['side'] == 'LONG':
                    pnl_pct = (current_price - entry) / entry * self.leverage
                else:
                    pnl_pct = (entry - current_price) / entry * self.leverage
                
                # 快速止损（2%）
                if pnl_pct <= -self.stop_loss * self.leverage * 100:
                    self.balance -= position['margin'] * self.stop_loss * self.leverage
                    self.stats['losing_trades'] += 1
                    position = None
                    continue
                
                # 快速止盈（4%）
                if pnl_pct >= self.take_profit * self.leverage * 100:
                    profit = position['margin'] * self.take_profit * self.leverage
                    self.balance += position['margin'] + profit
                    self.stats['winning_trades'] += 1
                    position = None
                    continue
                
                # 持仓时间限制（最多20周期）
                if entry_time and (i - entry_time) > 20:
                    # 强制平仓
                    if pnl_pct > 0:
                        self.stats['winning_trades'] += 1
                    else:
                        self.stats['losing_trades'] += 1
                    self.balance += position['margin'] * (1 + pnl_pct / 100)
                    position = None
                    continue
            
            # 新开仓（高频模式：几乎每周期都检查）
            else:
                signal = self.signal_generator.generate_signals(current_df)
                
                # 只要有信号就交易
                if signal['action'] != 'HOLD':
                    margin = self.balance * self.position_size
                    self.balance -= margin
                    
                    position = {
                        'side': signal['action'],
                        'entry_price': current_price,
                        'margin': margin
                    }
                    entry_time = i
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
        
        # 最终平仓
        if position:
            if position['side'] == 'LONG':
                pnl_pct = (current_price - position['entry_price']) / position['entry_price'] * self.leverage
            else:
                pnl_pct = (position['entry_price'] - current_price) / position['entry_price'] * self.leverage
            
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
        
        return {
            'total_return': total_return,
            'max_drawdown': max_dd * 100,
            'total_trades': self.stats['total_trades'],
            'winning_trades': self.stats['winning_trades'],
            'losing_trades': self.stats['losing_trades'],
            'win_rate': self.stats['winning_trades'] / max(self.stats['total_trades'], 1) * 100,
            'liquidations': self.stats['liquidations']
        }


def main():
    """主函数"""
    df = pd.read_csv('eth_usdt_1h_binance.csv')
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    trader = V7HighFreqTrader(initial_balance=1000.0)
    results = trader.run_backtest(df)
    
    print("\n" + "=" * 70)
    print("🚀 V7-HighFreq 高频交易回测报告")
    print("=" * 70)
    print(f"\n💰 资金表现:")
    print(f"  初始: $1000.00 → 最终: ${1000 * (1 + results['total_return']/100):.2f}")
    print(f"  总收益: {results['total_return']:+.2f}%")
    
    print(f"\n📊 交易统计:")
    print(f"  总交易: {results['total_trades']}")
    print(f"  盈利: {results['winning_trades']} | 亏损: {results['losing_trades']}")
    print(f"  胜率: {results['win_rate']:.1f}%")
    
    # 计算年化交易次数
    years = 2.2  # 约2.2年数据
    annual_trades = results['total_trades'] / years
    print(f"\n📈 高频统计:")
    print(f"  年化交易次数: {annual_trades:.0f} 笔/年")
    print(f"  日均交易: {annual_trades/365:.1f} 笔")
    
    print(f"\n🛡️ 风险控制:")
    print(f"  最大回撤: {results['max_drawdown']:.2f}%")
    print(f"  爆仓: {results['liquidations']} 次")
    
    # 评分
    score = 0
    if results['liquidations'] == 0: score += 30
    if results['win_rate'] > 55: score += 25
    if results['win_rate'] > 50: score += 10
    if results['total_return'] > 0: score += 15
    if annual_trades > 400: score += 10
    if annual_trades > 800: score += 10
    
    print(f"\n⭐ 综合评分: {score}/100")
    print("=" * 70)


if __name__ == "__main__":
    main()