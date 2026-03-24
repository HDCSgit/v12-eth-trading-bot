#!/usr/bin/env python3
"""
V7-5Min-Analysis: 基于5分钟数据的V7深度分析和优化
目标：分析各信号效果，优化阈值，提升胜率
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


class SignalAnalyzer:
    """信号分析器 - 分析各信号在5分钟数据中的有效性"""
    
    def __init__(self):
        self.signal_performance = {}
        
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算技术指标"""
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
        
        # 量能
        df['volume_ma'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma']
        
        # 价格变化
        df['price_change_3'] = df['close'].pct_change(3) * 100
        
        # 未来收益（用于验证信号效果）
        df['future_return'] = df['close'].shift(-5) / df['close'] - 1  # 25分钟后收益
        
        return df.dropna()
    
    def analyze_signals(self, df: pd.DataFrame) -> Dict:
        """分析各信号的有效性"""
        df = self.calculate_indicators(df)
        
        logger.info("\n" + "=" * 70)
        logger.info("📊 5分钟数据信号有效性分析")
        logger.info("=" * 70)
        
        results = {}
        
        # 1. RSI超卖信号分析（测试不同阈值）
        logger.info("\n🔍 RSI超卖信号分析:")
        for threshold in [30, 35, 40, 45]:
            mask = df['rsi'] < threshold
            if mask.sum() > 100:
                avg_return = df.loc[mask, 'future_return'].mean() * 100
                win_rate = (df.loc[mask, 'future_return'] > 0).mean() * 100
                count = mask.sum()
                
                results[f'rsi_oversold_{threshold}'] = {
                    'count': count,
                    'win_rate': win_rate,
                    'avg_return': avg_return
                }
                
                logger.info(f"  RSI < {threshold}: 触发{count:5d}次, 胜率{win_rate:5.1f}%, 收益{avg_return:+.3f}%")
        
        # 2. MACD金叉信号
        logger.info("\n🔍 MACD金叉信号分析:")
        df['macd_cross'] = (df['macd'] > df['macd_signal']) & (df['macd'].shift(1) <= df['macd_signal'].shift(1))
        mask = df['macd_cross']
        if mask.sum() > 100:
            avg_return = df.loc[mask, 'future_return'].mean() * 100
            win_rate = (df.loc[mask, 'future_return'] > 0).mean() * 100
            count = mask.sum()
            
            results['macd_cross'] = {
                'count': count,
                'win_rate': win_rate,
                'avg_return': avg_return
            }
            
            logger.info(f"  MACD金叉: 触发{count:5d}次, 胜率{win_rate:5.1f}%, 收益{avg_return:+.3f}%")
        
        # 3. 布林带下轨信号
        logger.info("\n🔍 布林带下轨信号分析:")
        for threshold in [1.00, 1.01, 1.02, 1.03]:
            mask = df['close'] < df['bb_lower'] * threshold
            if mask.sum() > 100:
                avg_return = df.loc[mask, 'future_return'].mean() * 100
                win_rate = (df.loc[mask, 'future_return'] > 0).mean() * 100
                count = mask.sum()
                
                results[f'bb_lower_{threshold}'] = {
                    'count': count,
                    'win_rate': win_rate,
                    'avg_return': avg_return
                }
                
                logger.info(f"  下轨×{threshold}: 触发{count:5d}次, 胜率{win_rate:5.1f}%, 收益{avg_return:+.3f}%")
        
        # 4. 均线金叉信号
        logger.info("\n🔍 均线金叉信号分析:")
        df['ma_cross'] = (df['ma5'] > df['ma10']) & (df['ma5'].shift(1) <= df['ma10'].shift(1))
        mask = df['ma_cross']
        if mask.sum() > 100:
            avg_return = df.loc[mask, 'future_return'].mean() * 100
            win_rate = (df.loc[mask, 'future_return'] > 0).mean() * 100
            count = mask.sum()
            
            results['ma_cross'] = {
                'count': count,
                'win_rate': win_rate,
                'avg_return': avg_return
            }
            
            logger.info(f"  MA5金叉MA10: 触发{count:5d}次, 胜率{win_rate:5.1f}%, 收益{avg_return:+.3f}%")
        
        # 5. 放量突破信号
        logger.info("\n🔍 放量突破信号分析:")
        for vol_threshold in [1.3, 1.5, 1.8, 2.0]:
            mask = (df['volume_ratio'] > vol_threshold) & (df['close'] > df['open'])
            if mask.sum() > 100:
                avg_return = df.loc[mask, 'future_return'].mean() * 100
                win_rate = (df.loc[mask, 'future_return'] > 0).mean() * 100
                count = mask.sum()
                
                results[f'volume_break_{vol_threshold}'] = {
                    'count': count,
                    'win_rate': win_rate,
                    'avg_return': avg_return
                }
                
                logger.info(f"  放量×{vol_threshold}: 触发{count:5d}次, 胜率{win_rate:5.1f}%, 收益{avg_return:+.3f}%")
        
        # 6. 超跌反弹信号
        logger.info("\n🔍 超跌反弹信号分析:")
        for drop_threshold in [-1.0, -1.5, -2.0, -2.5]:
            mask = df['price_change_3'] < drop_threshold
            if mask.sum() > 100:
                avg_return = df.loc[mask, 'future_return'].mean() * 100
                win_rate = (df.loc[mask, 'future_return'] > 0).mean() * 100
                count = mask.sum()
                
                results[f'drop_bounce_{drop_threshold}'] = {
                    'count': count,
                    'win_rate': win_rate,
                    'avg_return': avg_return
                }
                
                logger.info(f"  3期跌{drop_threshold}%: 触发{count:5d}次, 胜率{win_rate:5.1f}%, 收益{avg_return:+.3f}%")
        
        logger.info("\n" + "=" * 70)
        
        return results


class V7Optimized5MinTrader:
    """V7优化版 - 基于5分钟数据和信号分析"""
    
    def __init__(self, initial_balance: float = 1000.0, 
                 rsi_threshold=40, bb_threshold=1.02, 
                 volume_threshold=1.5, drop_threshold=-1.5):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        
        # 优化后的参数
        self.rsi_threshold = rsi_threshold
        self.bb_threshold = bb_threshold
        self.volume_threshold = volume_threshold
        self.drop_threshold = drop_threshold
        
        # 风控参数
        self.leverage = 2
        self.stop_loss = 0.015  # 1.5%
        self.take_profit = 0.03  # 3%
        self.position_size = 0.10  # 10%
        self.max_drawdown = 0.20
        
        # 统计
        self.stats = {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'liquidations': 0
        }
        
        logger.info("\n" + "=" * 70)
        logger.info("V7-Optimized-5Min 优化高频交易系统")
        logger.info(f"RSI阈值: {self.rsi_threshold} | 布林带: {self.bb_threshold}")
        logger.info(f"成交量: {self.volume_threshold} | 跌幅: {self.drop_threshold}%")
        logger.info("=" * 70)
    
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算指标"""
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
        
        # 布林带
        df['bb_mid'] = df['close'].rolling(20).mean()
        df['bb_std'] = df['close'].rolling(20).std()
        df['bb_upper'] = df['bb_mid'] + 2 * df['bb_std']
        df['bb_lower'] = df['bb_mid'] - 2 * df['bb_std']
        
        # 量能
        df['volume_ma'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma']
        
        # 价格变化
        df['price_change_3'] = df['close'].pct_change(3) * 100
        
        return df.dropna()
    
    def generate_signals(self, df: pd.DataFrame) -> Dict:
        """生成交易信号（使用优化后的阈值）"""
        df = self.calculate_indicators(df)
        
        if len(df) < 20:
            return {'action': 'HOLD', 'signals': []}
        
        row = df.iloc[-1]
        prev = df.iloc[-2]
        
        signals = []
        
        # 信号1: RSI超卖（优化阈值）
        if row['rsi'] < self.rsi_threshold:
            signals.append(('RSI_Oversold', 0.60))
        
        # 信号2: MACD金叉
        if row['macd'] > row['macd_signal'] and prev['macd'] <= prev['macd_signal']:
            signals.append(('MACD_Cross', 0.65))
        
        # 信号3: 布林带下轨（优化阈值）
        if row['close'] < row['bb_lower'] * self.bb_threshold:
            signals.append(('BB_Lower', 0.55))
        
        # 信号4: 均线金叉
        if row['ma5'] > row['ma10'] and prev['ma5'] <= prev['ma10']:
            signals.append(('MA_Cross', 0.60))
        
        # 信号5: 放量突破（优化阈值）
        if row['volume_ratio'] > self.volume_threshold and row['close'] > row['open']:
            signals.append(('Volume_Break', 0.55))
        
        # 信号6: 超跌反弹（优化阈值）
        if row['price_change_3'] < self.drop_threshold:
            signals.append(('Drop_Bounce', 0.50))
        
        # 高频交易：只要有任何一个信号就交易
        if len(signals) >= 1:  # 至少1个信号
            score = sum([conf for _, conf in signals])
            return {
                'action': 'BUY',
                'signals': signals,
                'score': score
            }
        else:
            return {'action': 'HOLD', 'signals': []}
    
    def run_backtest(self, df: pd.DataFrame) -> Dict:
        """运行回测"""
        logger.info("\n开始回测...")
        
        position = None
        equity_curve = []
        
        for i in range(50, len(df)):
            current_df = df.iloc[:i+1]
            current_price = df['close'].iloc[i]
            
            # 持仓管理
            if position:
                entry = position['entry_price']
                pnl_pct = (current_price - entry) / entry * self.leverage
                
                # 爆仓检查
                if pnl_pct <= -45:
                    self.stats['liquidations'] += 1
                    self.balance *= 0.1
                    position = None
                    continue
                
                # 止损
                if pnl_pct <= -self.stop_loss * self.leverage * 100:
                    self.balance -= position['margin'] * self.stop_loss * self.leverage
                    self.stats['losing_trades'] += 1
                    position = None
                    continue
                
                # 止盈
                if pnl_pct >= self.take_profit * self.leverage * 100:
                    profit = position['margin'] * self.take_profit * self.leverage
                    self.balance += position['margin'] + profit
                    self.stats['winning_trades'] += 1
                    position = None
                    continue
            
            # 新开仓
            else:
                signal = self.generate_signals(current_df)
                
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
        
        # 最终平仓
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
        
        # 年化计算（约2年数据）
        years = 2.2
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
    logger.info("加载5分钟ETH数据...")
    df = pd.read_csv('eth_usdt_5m_2024_2026.csv')
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    logger.info(f"数据条数: {len(df)}")
    
    # 第一步：信号分析
    analyzer = SignalAnalyzer()
    signal_results = analyzer.analyze_signals(df)
    
    # 找出最优参数
    best_rsi = max([k for k in signal_results.keys() if 'rsi_oversold' in k], 
                   key=lambda x: signal_results[x]['win_rate'] * 0.6 + signal_results[x]['avg_return'] * 0.4)
    best_bb = max([k for k in signal_results.keys() if 'bb_lower' in k], 
                  key=lambda x: signal_results[x]['win_rate'] * 0.6 + signal_results[x]['avg_return'] * 0.4)
    best_vol = max([k for k in signal_results.keys() if 'volume_break' in k], 
                   key=lambda x: signal_results[x]['win_rate'] * 0.6 + signal_results[x]['avg_return'] * 0.4)
    best_drop = max([k for k in signal_results.keys() if 'drop_bounce' in k], 
                    key=lambda x: signal_results[x]['win_rate'] * 0.6 + signal_results[x]['avg_return'] * 0.4)
    
    logger.info("\n🎯 最优参数推荐:")
    logger.info(f"  RSI超卖: {best_rsi} (胜率{signal_results[best_rsi]['win_rate']:.1f}%)")
    logger.info(f"  布林带: {best_bb} (胜率{signal_results[best_bb]['win_rate']:.1f}%)")
    logger.info(f"  成交量: {best_vol} (胜率{signal_results[best_vol]['win_rate']:.1f}%)")
    logger.info(f"  超跌: {best_drop} (胜率{signal_results[best_drop]['win_rate']:.1f}%)")
    
    # 第二步：使用默认参数回测
    logger.info("\n📈 使用默认参数回测:")
    trader_default = V7Optimized5MinTrader(
        rsi_threshold=40,
        bb_threshold=1.02,
        volume_threshold=1.5,
        drop_threshold=-1.5
    )
    results_default = trader_default.run_backtest(df)
    
    # 第三步：使用优化参数回测
    logger.info("\n📈 使用优化参数回测:")
    trader_optimized = V7Optimized5MinTrader(
        rsi_threshold=int(best_rsi.split('_')[-1]),
        bb_threshold=float(best_bb.split('_')[-1]),
        volume_threshold=float(best_vol.split('_')[-1]),
        drop_threshold=float(best_drop.split('_')[-1])
    )
    results_optimized = trader_optimized.run_backtest(df)
    
    # 对比报告
    print("\n" + "=" * 70)
    print("🚀 V7-5Min 优化对比报告")
    print("=" * 70)
    
    print("\n📊 默认参数结果:")
    print(f"  总收益: {results_default['total_return']:+.2f}%")
    print(f"  交易次数: {results_default['total_trades']} (年化{results_default['annual_trades']:.0f}笔)")
    print(f"  胜率: {results_default['win_rate']:.1f}%")
    print(f"  最大回撤: {results_default['max_drawdown']:.2f}%")
    print(f"  爆仓: {results_default['liquidations']}次")
    
    print("\n📊 优化参数结果:")
    print(f"  总收益: {results_optimized['total_return']:+.2f}%")
    print(f"  交易次数: {results_optimized['total_trades']} (年化{results_optimized['annual_trades']:.0f}笔)")
    print(f"  胜率: {results_optimized['win_rate']:.1f}%")
    print(f"  最大回撤: {results_optimized['max_drawdown']:.2f}%")
    print(f"  爆仓: {results_optimized['liquidations']}次")
    
    # 改进幅度
    return_improve = results_optimized['total_return'] - results_default['total_return']
    winrate_improve = results_optimized['win_rate'] - results_default['win_rate']
    
    print(f"\n📈 优化效果:")
    print(f"  收益提升: {return_improve:+.2f}%")
    print(f"  胜率提升: {winrate_improve:+.1f}%")
    
    print("=" * 70)


if __name__ == "__main__":
    main()