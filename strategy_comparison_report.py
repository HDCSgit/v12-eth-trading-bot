#!/usr/bin/env python3
"""
策略版本对比分析 - 全面对比V2到V9
"""

import pandas as pd
import numpy as np
import logging
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def run_v2_5_backtest(df):
    """V2.5 混合策略回测"""
    position = None
    balance = 1000.0
    stats = {'total_trades': 0, 'wins': 0, 'losses': 0, 'liquidations': 0}
    
    for i in range(55, len(df)):
        current_price = df['close'].iloc[i]
        
        if position:
            pnl_pct = (current_price - position['entry']) / position['entry'] * 10
            if pnl_pct <= -50:
                stats['liquidations'] += 1
                balance *= 0.5
                position = None
            elif pnl_pct <= -10:
                stats['losses'] += 1
                balance -= position['margin'] * 0.1
                position = None
            elif pnl_pct >= 15:
                stats['wins'] += 1
                balance += position['margin'] * 0.15
                position = None
        else:
            # 简化信号
            if i > 55 and df['close'].iloc[i] < df['close'].iloc[i-1] * 0.99:
                position = {'entry': current_price, 'margin': balance * 0.15}
                balance -= position['margin']
                stats['total_trades'] += 1
    
    win_rate = stats['wins'] / max(stats['total_trades'], 1) * 100
    return {
        'version': 'V2.5 Hybrid',
        'total_return': (balance - 1000) / 10,
        'trades': stats['total_trades'],
        'win_rate': win_rate,
        'liquidations': stats['liquidations'],
        'data_period': '1h'
    }


def run_v7_backtest(df):
    """V7 高频策略回测（1小时数据）"""
    position = None
    balance = 1000.0
    stats = {'total_trades': 0, 'wins': 0, 'losses': 0, 'liquidations': 0}
    
    for i in range(50, len(df)):
        current_price = df['close'].iloc[i]
        
        if position:
            pnl_pct = (current_price - position['entry']) / position['entry'] * 2
            if pnl_pct <= -4:
                stats['losses'] += 1
                balance -= position['margin'] * 0.04
                position = None
            elif pnl_pct >= 8:
                stats['wins'] += 1
                balance += position['margin'] * 0.08
                position = None
        else:
            # 简化RSI信号
            if i > 14:
                delta = df['close'].diff()
                gain = delta.clip(lower=0).rolling(14).mean().iloc[i]
                loss = (-delta.clip(upper=0)).rolling(14).mean().iloc[i]
                rsi = 100 - 100 / (1 + gain / (loss + 1e-10))
                if rsi < 35:
                    position = {'entry': current_price, 'margin': balance * 0.10}
                    balance -= position['margin']
                    stats['total_trades'] += 1
    
    win_rate = stats['wins'] / max(stats['total_trades'], 1) * 100
    return {
        'version': 'V7 HighFreq (1h)',
        'total_return': (balance - 1000) / 10,
        'trades': stats['total_trades'],
        'win_rate': win_rate,
        'liquidations': 0,
        'data_period': '1h'
    }


def run_v9_simple_backtest(df):
    """V9 极简策略回测（5分钟数据）"""
    position = None
    balance = 1000.0
    stats = {'total_trades': 0, 'wins': 0, 'losses': 0, 'liquidations': 0, 'longs': 0, 'shorts': 0}
    position_bars = 0
    
    for i in range(3, len(df)):
        current = df.iloc[i]
        prev = df.iloc[i-1]
        prev2 = df.iloc[i-2]
        current_price = current['close']
        
        if position:
            position_bars += 1
            if position['side'] == 'LONG':
                pnl_pct = (current_price - position['entry']) / position['entry'] * 2
            else:
                pnl_pct = (position['entry'] - current_price) / position['entry'] * 2
            
            # 止损止盈或强制平仓
            exit_trade = False
            if pnl_pct <= -3:
                stats['losses'] += 1
                balance -= position['margin'] * 0.03
                exit_trade = True
            elif pnl_pct >= 6:
                stats['wins'] += 1
                balance += position['margin'] * 0.06
                exit_trade = True
            elif position_bars >= 10:
                if pnl_pct > 0:
                    stats['wins'] += 1
                    balance += position['margin'] * pnl_pct / 100
                else:
                    stats['losses'] += 1
                    balance -= position['margin'] * abs(pnl_pct) / 100
                exit_trade = True
            
            if exit_trade:
                position = None
                position_bars = 0
        else:
            # 多空信号
            long_signals = []
            short_signals = []
            
            if current['close'] < prev['close'] and prev['close'] < prev2['close']:
                long_signals.append('Drop_2')
            if current['close'] < min(prev['low'], prev2['low']):
                long_signals.append('Below_Low')
            if current['close'] > current['open']:
                long_signals.append('Bullish')
            
            if current['close'] > prev['close'] and prev['close'] > prev2['close']:
                short_signals.append('Rise_2')
            if current['close'] > max(prev['high'], prev2['high']):
                short_signals.append('Above_High')
            if current['close'] < current['open']:
                short_signals.append('Bearish')
            
            if len(long_signals) >= 1:
                position = {'entry': current_price, 'margin': balance * 0.15, 'side': 'LONG'}
                balance -= position['margin']
                stats['total_trades'] += 1
                stats['longs'] += 1
                position_bars = 0
            elif len(short_signals) >= 1:
                position = {'entry': current_price, 'margin': balance * 0.15, 'side': 'SHORT'}
                balance -= position['margin']
                stats['total_trades'] += 1
                stats['shorts'] += 1
                position_bars = 0
    
    win_rate = stats['wins'] / max(stats['total_trades'], 1) * 100
    return {
        'version': 'V9 Simple (5m)',
        'total_return': (balance - 1000) / 10,
        'trades': stats['total_trades'],
        'win_rate': win_rate,
        'liquidations': 0,
        'longs': stats['longs'],
        'shorts': stats['shorts'],
        'data_period': '5m'
    }


def print_comparison(results):
    """打印对比报告"""
    print("\n" + "=" * 90)
    print("📊 交易系统版本全面对比报告")
    print("=" * 90)
    
    print("\n" + "-" * 90)
    print(f"{'版本':<20} {'收益':>10} {'交易次数':>12} {'胜率':>10} {'爆仓':>8} {'数据周期':>10}")
    print("-" * 90)
    
    for r in results:
        print(f"{r['version']:<20} {r['total_return']:>+9.2f}% {r['trades']:>12,} {r['win_rate']:>9.1f}% {r['liquidations']:>8} {r['data_period']:>10}")
    
    print("-" * 90)
    
    # 找出最优
    best_profit = max(results, key=lambda x: x['total_return'])
    best_trades = max(results, key=lambda x: x['trades'])
    best_winrate = max(results, key=lambda x: x['win_rate'])
    safest = min(results, key=lambda x: x['liquidations'])
    
    print("\n🏆 各项指标冠军:")
    print(f"  最高收益: {best_profit['version']} ({best_profit['total_return']:+.2f}%)")
    print(f"  最多交易: {best_trades['version']} ({best_trades['trades']:,}笔)")
    print(f"  最高胜率: {best_winrate['version']} ({best_winrate['win_rate']:.1f}%)")
    print(f"  最安全:   {safest['version']} ({safest['liquidations']}次爆仓)")
    
    # 综合评分
    print("\n⭐ 综合评分排名:")
    scores = []
    for r in results:
        score = 0
        if r['liquidations'] == 0: score += 30
        if r['win_rate'] > 50: score += 20
        if r['win_rate'] > 45: score += 10
        if r['total_return'] > 0: score += 20
        if r['trades'] > 500: score += 15
        if r['trades'] > 1000: score += 5
        scores.append((r['version'], score, r))
    
    scores.sort(key=lambda x: x[1], reverse=True)
    
    for i, (version, score, r) in enumerate(scores, 1):
        rank = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        status = "🟢 优秀" if score >= 80 else "🟡 良好" if score >= 60 else "🟠 一般"
        print(f"  {rank} {version:<20} 评分: {score}/100 {status}")
    
    print("=" * 90)


def main():
    """主函数"""
    logger.info("加载数据...")
    
    # 加载1小时数据
    df_1h = pd.read_csv('eth_usdt_1h_binance.csv')
    
    # 加载5分钟数据
    df_5m = pd.read_csv('eth_usdt_5m_2024_2026.csv')
    
    results = []
    
    # 运行各版本回测
    logger.info("运行V2.5回测...")
    results.append(run_v2_5_backtest(df_1h))
    
    logger.info("运行V7回测...")
    results.append(run_v7_backtest(df_1h))
    
    logger.info("运行V9回测...")
    v9_result = run_v9_simple_backtest(df_5m)
    results.append(v9_result)
    
    # 打印对比
    print_comparison(results)
    
    # V9详细分析
    print("\n" + "=" * 90)
    print("📈 V9-Simple 详细分析")
    print("=" * 90)
    print(f"总交易: {v9_result['trades']:,} 笔")
    print(f"做多: {v9_result['longs']:,} 笔 ({v9_result['longs']/v9_result['trades']*100:.1f}%)")
    print(f"做空: {v9_result['shorts']:,} 笔 ({v9_result['shorts']/v9_result['trades']*100:.1f}%)")
    print(f"年化交易: {v9_result['trades']/2.2:,.0f} 笔")
    print(f"胜率: {v9_result['win_rate']:.1f}%")
    print(f"爆仓: {v9_result['liquidations']} 次")
    print("=" * 90)


if __name__ == "__main__":
    main()