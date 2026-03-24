#!/usr/bin/env python3
"""
V9-Simple: 极简高频交易系统
只用基础价格数据，无需复杂指标，立即交易
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


class SimpleSignalGenerator:
    """极简信号生成器 - 只用基础价格数据"""
    
    def generate_signals(self, df: pd.DataFrame) -> Dict:
        """生成极简信号"""
        if len(df) < 20:
            return {'action': 'HOLD', 'signals': []}
        
        # 只取最近几条数据
        recent = df.tail(5)
        current = recent.iloc[-1]
        prev = recent.iloc[-2]
        prev2 = recent.iloc[-3]
        
        long_signals = []
        short_signals = []
        
        # ========== 极简多头信号 ==========
        
        # 1. 连续下跌后买入（最简单的反弹策略）
        if current['close'] < prev['close'] and prev['close'] < prev2['close']:
            long_signals.append(('Drop_2', 0.50))
        
        # 2. 价格低于前3根K线最低点
        if current['close'] < min(prev['low'], prev2['low']):
            long_signals.append(('Below_Recent_Low', 0.55))
        
        # 3. 当前是阳线（close > open）
        if current['close'] > current['open']:
            long_signals.append(('Bullish_Candle', 0.45))
        
        # 4. 量比前一根大（放量）
        if current['volume'] > prev['volume'] * 1.2:
            long_signals.append(('Volume_Increase', 0.45))
        
        # 5. 价格在上涨
        if current['close'] > prev['close']:
            long_signals.append(('Price_Up', 0.40))
        
        # ========== 极简空头信号 ==========
        
        # 1. 连续上涨后卖出
        if current['close'] > prev['close'] and prev['close'] > prev2['close']:
            short_signals.append(('Rise_2', 0.50))
        
        # 2. 价格高于前3根K线最高点
        if current['close'] > max(prev['high'], prev2['high']):
            short_signals.append(('Above_Recent_High', 0.55))
        
        # 3. 当前是阴线（close < open）
        if current['close'] < current['open']:
            short_signals.append(('Bearish_Candle', 0.45))
        
        # 4. 放量下跌
        if current['volume'] > prev['volume'] * 1.2 and current['close'] < current['open']:
            short_signals.append(('Volume_Drop', 0.45))
        
        # 5. 价格在下跌
        if current['close'] < prev['close']:
            short_signals.append(('Price_Down', 0.40))
        
        # 决策：只要有信号就交易
        if len(long_signals) >= 1:
            return {
                'action': 'BUY',
                'signals': long_signals,
                'score': len(long_signals)
            }
        elif len(short_signals) >= 1:
            return {
                'action': 'SELL',
                'signals': short_signals,
                'score': len(short_signals)
            }
        else:
            return {'action': 'HOLD', 'signals': []}


class V9SimpleTrader:
    """V9极简高频交易系统"""
    
    def __init__(self, initial_balance: float = 1000.0):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        
        # 交易参数
        self.leverage = 2
        self.stop_loss = 0.015
        self.take_profit = 0.03
        self.position_size = 0.15
        
        # 策略
        self.signal_generator = SimpleSignalGenerator()
        
        # 统计
        self.stats = {
            'total_trades': 0,
            'long_trades': 0,
            'short_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'liquidations': 0
        }
        
        logger.info("\n" + "=" * 70)
        logger.info("🚀 V9-Simple 极简高频交易系统")
        logger.info(f"杠杆: {self.leverage}x | 仓位: {self.position_size*100}%")
        logger.info("信号: 连续涨跌、高低点、阴阳线、量能")
        logger.info("=" * 70)
    
    def run_backtest(self, df: pd.DataFrame) -> Dict:
        """运行极简回测"""
        logger.info("开始极简高频回测...")
        
        position = None
        position_side = None
        position_bars = 0  # 持仓周期计数
        
        # 从第3条开始（只需要3条数据）
        for i in range(3, len(df)):
            current_df = df.iloc[:i+1]
            current_price = df['close'].iloc[i]
            
            # 持仓管理
            if position:
                position_bars += 1
                entry = position['entry_price']
                
                if position_side == 'LONG':
                    pnl_pct = (current_price - entry) / entry * self.leverage
                else:
                    pnl_pct = (entry - current_price) / entry * self.leverage
                
                # 爆仓检查
                if pnl_pct <= -48:
                    self.stats['liquidations'] += 1
                    self.balance *= 0.04
                    position = None
                    position_side = None
                    position_bars = 0
                    continue
                
                # 止损
                if pnl_pct <= -self.stop_loss * self.leverage * 100:
                    self.balance -= position['margin'] * self.stop_loss * self.leverage
                    self.stats['losing_trades'] += 1
                    position = None
                    position_side = None
                    position_bars = 0
                    continue
                
                # 止盈
                if pnl_pct >= self.take_profit * self.leverage * 100:
                    profit = position['margin'] * self.take_profit * self.leverage
                    self.balance += position['margin'] + profit
                    self.stats['winning_trades'] += 1
                    position = None
                    position_side = None
                    position_bars = 0
                    continue
                
                # 强制平仓：持仓超过10个周期（50分钟）
                if position_bars >= 10:
                    # 按当前盈亏平仓
                    if pnl_pct > 0:
                        profit = position['margin'] * pnl_pct / 100
                        self.balance += position['margin'] + profit
                        self.stats['winning_trades'] += 1
                    else:
                        loss = position['margin'] * abs(pnl_pct) / 100
                        self.balance += position['margin'] - loss
                        self.stats['losing_trades'] += 1
                    
                    position = None
                    position_side = None
                    position_bars = 0
                    continue
            
            # 新开仓
            else:
                signal = self.signal_generator.generate_signals(current_df)
                
                if signal['action'] in ['BUY', 'SELL']:
                    margin = self.balance * self.position_size
                    self.balance -= margin
                    
                    position = {
                        'entry_price': current_price,
                        'margin': margin
                    }
                    position_side = 'LONG' if signal['action'] == 'BUY' else 'SHORT'
                    position_bars = 0
                    self.stats['total_trades'] += 1
                    
                    if position_side == 'LONG':
                        self.stats['long_trades'] += 1
                    else:
                        self.stats['short_trades'] += 1
        
        # 最终平仓
        if position:
            if position_side == 'LONG':
                pnl_pct = (current_price - position['entry_price']) / position['entry_price'] * self.leverage
            else:
                pnl_pct = (position['entry_price'] - current_price) / position['entry_price'] * self.leverage
            
            if pnl_pct > 0:
                self.stats['winning_trades'] += 1
            else:
                self.stats['losing_trades'] += 1
        
        # 计算结果
        total_return = (self.balance - self.initial_balance) / self.initial_balance * 100
        years = 2.2
        annual_trades = self.stats['total_trades'] / years
        
        return {
            'total_return': total_return,
            'total_trades': self.stats['total_trades'],
            'long_trades': self.stats['long_trades'],
            'short_trades': self.stats['short_trades'],
            'annual_trades': annual_trades,
            'winning_trades': self.stats['winning_trades'],
            'losing_trades': self.stats['losing_trades'],
            'win_rate': self.stats['winning_trades'] / max(self.stats['total_trades'], 1) * 100,
            'liquidations': self.stats['liquidations']
        }


def main():
    """主函数"""
    logger.info("加载5分钟ETH数据...")
    df = pd.read_csv('eth_usdt_5m_2024_2026.csv')
    logger.info(f"数据条数: {len(df):,}")
    
    # 运行回测
    trader = V9SimpleTrader(initial_balance=1000.0)
    result = trader.run_backtest(df)
    
    # 打印报告
    print("\n" + "=" * 70)
    print("🚀 V9-Simple 极简高频回测报告")
    print("=" * 70)
    print(f"\n💰 收益: {result['total_return']:+.2f}%")
    print(f"\n📊 交易: {result['total_trades']} 笔 (年化{result['annual_trades']:.0f}笔)")
    print(f"  做多: {result['long_trades']} | 做空: {result['short_trades']}")
    print(f"  胜率: {result['win_rate']:.1f}%")
    print(f"\n🛡️ 爆仓: {result['liquidations']} 次")
    print("=" * 70)


if __name__ == "__main__":
    main()