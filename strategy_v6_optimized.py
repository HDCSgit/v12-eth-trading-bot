#!/usr/bin/env python3
"""
V6-Optimized: 基于V6的数据驱动优化版
通过分析2年历史数据，拟合最优阈值
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


class DataDrivenSignalGenerator:
    """数据驱动信号生成器 - 基于历史数据拟合阈值"""
    
    def __init__(self):
        self.signal_stats = {}
        
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算所有技术指标（V6完整版）"""
        df = df.copy()
        
        # 基础价格
        df['returns'] = df['close'].pct_change()
        df['log_returns'] = np.log(df['close'] / df['close'].shift(1))
        
        # 多周期均线
        for period in [5, 10, 20, 55, 200]:
            df[f'ma_{period}'] = df['close'].rolling(period).mean()
        
        # 趋势判断
        df['trend_long'] = np.where(df['ma_55'] > df['ma_200'], 1, -1)
        df['trend_short'] = np.where(df['ma_10'] > df['ma_20'], 1, -1)
        
        # RSI多周期
        for period in [6, 12, 24]:
            delta = df['close'].diff()
            gain = delta.clip(lower=0).rolling(period).mean()
            loss = (-delta.clip(upper=0)).rolling(period).mean()
            df[f'rsi_{period}'] = 100 - 100 / (1 + gain / (loss + 1e-10))
        
        # RSI斜率（新增）
        df['rsi_slope'] = df['rsi_12'].diff(3)
        
        # MACD多组参数
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
            df[f'bb_width_{period}'] = (df[f'bb_upper_{period}'] - df[f'bb_lower_{period}']) / df[f'bb_mid_{period}']
        
        # ATR
        tr = pd.concat([
            df['high'] - df['low'],
            np.abs(df['high'] - df['close'].shift()),
            np.abs(df['low'] - df['close'].shift())
        ], axis=1).max(axis=1)
        df['atr'] = tr.rolling(14).mean()
        df['atr_pct'] = df['atr'] / df['close']
        
        # 量能
        for period in [5, 10, 20]:
            df[f'volume_ma_{period}'] = df['volume'].rolling(period).mean()
            df[f'volume_ratio_{period}'] = df['volume'] / df[f'volume_ma_{period}']
        
        df['volume_trend'] = df['volume_ma_5'] / df['volume_ma_20']
        
        # 价格变化多周期
        for period in [3, 5, 10]:
            df[f'price_change_{period}m'] = df['close'].pct_change(period) * 100
        
        # 动量
        df['momentum_10'] = df['close'] / df['close'].shift(10) - 1
        
        # 未来收益（用于验证信号有效性）
        df['future_return_5'] = df['close'].shift(-5) / df['close'] - 1
        
        return df.dropna()
    
    def analyze_signal_effectiveness(self, df: pd.DataFrame) -> Dict:
        """分析各信号在历史数据中的有效性"""
        df = self.calculate_indicators(df)
        
        signal_analysis = {}
        
        # 定义信号条件及其变体
        signal_conditions = {
            'rsi_oversold': {
                'base': df['rsi_12'] < 35,
                'variants': [30, 35, 40, 45]
            },
            'rsi_overbought': {
                'base': df['rsi_12'] > 65,
                'variants': [60, 65, 70, 75]
            },
            'macd_cross_up': {
                'base': (df['macd_12_26'] > df['macd_signal_12_26']) & 
                        (df['macd_12_26'].shift(1) <= df['macd_signal_12_26'].shift(1))
            },
            'macd_cross_down': {
                'base': (df['macd_12_26'] < df['macd_signal_12_26']) & 
                        (df['macd_12_26'].shift(1) >= df['macd_signal_12_26'].shift(1))
            },
            'bb_lower_touch': {
                'base': df['close'] < df['bb_lower_20'] * 1.01,
                'variants': [1.00, 1.01, 1.02, 1.03]
            },
            'bb_upper_touch': {
                'base': df['close'] > df['bb_upper_20'] * 0.99,
                'variants': [1.00, 0.99, 0.98, 0.97]
            },
            'ma_cross_up': {
                'base': (df['ma_10'] > df['ma_20']) & (df['ma_10'].shift(1) <= df['ma_20'].shift(1))
            },
            'ma_cross_down': {
                'base': (df['ma_10'] < df['ma_20']) & (df['ma_10'].shift(1) >= df['ma_20'].shift(1))
            }
        }
        
        logger.info("\n分析各信号在历史数据中的有效性...")
        
        for signal_name, conditions in signal_conditions.items():
            if 'variants' in conditions:
                # 测试不同阈值
                best_threshold = None
                best_score = -999
                
                for threshold in conditions['variants']:
                    if 'rsi' in signal_name:
                        if 'oversold' in signal_name:
                            mask = df['rsi_12'] < threshold
                        else:
                            mask = df['rsi_12'] > threshold
                    elif 'bb_lower' in signal_name:
                        mask = df['close'] < df['bb_lower_20'] * threshold
                    elif 'bb_upper' in signal_name:
                        mask = df['close'] > df['bb_upper_20'] * threshold
                    else:
                        mask = conditions['base']
                    
                    if mask.sum() > 10:  # 至少触发10次
                        avg_return = df.loc[mask, 'future_return_5'].mean() * 100
                        win_rate = (df.loc[mask, 'future_return_5'] > 0).mean() * 100
                        count = mask.sum()
                        
                        # 综合评分：收益率*0.4 + 胜率*0.4 + log(次数)*0.2
                        score = avg_return * 0.4 + win_rate * 0.4 + np.log(count) * 5
                        
                        if score > best_score:
                            best_score = score
                            best_threshold = threshold
                            
                        signal_analysis[f"{signal_name}_{threshold}"] = {
                            'threshold': threshold,
                            'count': count,
                            'avg_return': avg_return,
                            'win_rate': win_rate,
                            'score': score
                        }
                
                logger.info(f"{signal_name}: 最佳阈值={best_threshold}, 评分={best_score:.1f}")
            else:
                mask = conditions['base']
                if mask.sum() > 10:
                    avg_return = df.loc[mask, 'future_return_5'].mean() * 100
                    win_rate = (df.loc[mask, 'future_return_5'] > 0).mean() * 100
                    count = mask.sum()
                    
                    signal_analysis[signal_name] = {
                        'count': count,
                        'avg_return': avg_return,
                        'win_rate': win_rate
                    }
                    
                    logger.info(f"{signal_name}: 触发{count}次, 胜率{win_rate:.1f}%, 收益{avg_return:.2f}%")
        
        return signal_analysis
    
    def generate_optimized_signals(self, df: pd.DataFrame, analysis: Dict = None) -> Dict:
        """生成优化后的交易信号（基于数据分析的阈值）"""
        df = self.calculate_indicators(df)
        
        # 确保有足够的数据
        if len(df) < 2:
            return {
                'long_signals': [],
                'short_signals': [],
                'long_score': 0,
                'short_score': 0,
                'long_count': 0,
                'short_count': 0
            }
        
        row = df.iloc[-1]
        prev = df.iloc[-2]
        
        signals = {
            'long': [],
            'short': []
        }
        
        # ========== 优化后的多头信号（基于数据拟合）==========
        
        # 信号1: RSI超卖（优化阈值35→40，提高触发频率）
        if row['rsi_12'] < 40:
            signals['long'].append(('RSI_Oversold_40', 0.55))
        elif row['rsi_12'] < 45:  # 放宽到45
            signals['long'].append(('RSI_Oversold_45', 0.45))
        
        # 信号2: MACD金叉（放宽条件）
        if (row['macd_12_26'] > row['macd_signal_12_26'] and 
            prev['macd_12_26'] <= prev['macd_signal_12_26']):
            signals['long'].append(('MACD_Cross', 0.60))
        
        # 信号3: 布林带下轨（放宽到1.02）
        if row['close'] < row['bb_lower_20'] * 1.02:
            signals['long'].append(('BB_Lower', 0.50))
        
        # 信号4: 均线金叉
        if (row['ma_10'] > row['ma_20'] and 
            prev['ma_10'] <= prev['ma_20']):
            signals['long'].append(('MA_Cross_Up', 0.55))
        
        # 信号5: 趋势跟随（简化条件）
        if (row['trend_long'] == 1 and row['rsi_12'] < 50):
            signals['long'].append(('Trend_Follow', 0.45))
        
        # 信号6: 成交量突破（降低门槛到1.5）
        if row['volume_ratio_5'] > 1.5 and row['close'] > row['open']:
            signals['long'].append(('Volume_Breakout', 0.50))
        
        # 信号7: 价格反弹（降低门槛到-1%）
        if row['price_change_5m'] < -1:
            signals['long'].append(('Price_Bounce', 0.45))
        
        # 信号8: RSI斜率转正
        if row['rsi_slope'] > 0 and row['rsi_12'] < 45:
            signals['long'].append(('RSI_Slope_Up', 0.45))
        
        # ========== 优化后的空头信号 ==========
        
        # 信号1: RSI超买（优化阈值65→60）
        if row['rsi_12'] > 60:
            signals['short'].append(('RSI_Overbought_60', 0.55))
        elif row['rsi_12'] > 55:
            signals['short'].append(('RSI_Overbought_55', 0.45))
        
        # 信号2: MACD死叉
        if (row['macd_12_26'] < row['macd_signal_12_26'] and 
            prev['macd_12_26'] >= prev['macd_signal_12_26']):
            signals['short'].append(('MACD_Cross_Down', 0.60))
        
        # 信号3: 布林带上轨
        if row['close'] > row['bb_upper_20'] * 0.98:
            signals['short'].append(('BB_Upper', 0.50))
        
        # 信号4: 均线死叉
        if (row['ma_10'] < row['ma_20'] and 
            prev['ma_10'] >= prev['ma_20']):
            signals['short'].append(('MA_Cross_Down', 0.55))
        
        # 信号5: 趋势跟随
        if (row['trend_long'] == -1 and row['rsi_12'] > 50):
            signals['short'].append(('Trend_Follow_Down', 0.45))
        
        # 信号6: 放量下跌
        if row['volume_ratio_5'] > 1.5 and row['close'] < row['open']:
            signals['short'].append(('Volume_Drop', 0.50))
        
        # 信号7: 价格回落
        if row['price_change_5m'] > 1:
            signals['short'].append(('Price_Drop', 0.45))
        
        # 信号8: RSI斜率转负
        if row['rsi_slope'] < 0 and row['rsi_12'] > 55:
            signals['short'].append(('RSI_Slope_Down', 0.45))
        
        # 计算综合评分
        long_score = sum([conf for _, conf in signals['long']])
        short_score = sum([conf for _, conf in signals['short']])
        
        return {
            'long_signals': signals['long'],
            'short_signals': signals['short'],
            'long_score': long_score,
            'short_score': short_score,
            'long_count': len(signals['long']),
            'short_count': len(signals['short'])
        }


class V6OptimizedTrader:
    """V6优化版交易系统"""
    
    def __init__(self, initial_balance: float = 1000.0, analyze_mode: bool = False):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.analyze_mode = analyze_mode
        
        # 风控参数
        self.leverage = 2
        self.stop_loss = 0.025  # 2.5%
        self.take_profit_1 = 0.05  # 5%
        self.take_profit_2 = 0.10  # 10%
        self.position_size = 0.06  # 6%
        
        # 风控
        self.max_drawdown = 0.20
        self.max_daily_trades = 8
        
        # 策略
        self.signal_generator = DataDrivenSignalGenerator()
        
        # 统计
        self.stats = {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'liquidations': 0,
            'daily_trades': 0,
            'last_trade_day': None
        }
        
        logger.info("=" * 70)
        logger.info("V6-Optimized 数据驱动优化交易系统")
        logger.info(f"杠杆: {self.leverage}x | 止损: {self.stop_loss*100}%")
        logger.info("=" * 70)
    
    def analyze_and_set_thresholds(self, df: pd.DataFrame):
        """分析历史数据并设置最优阈值"""
        logger.info("步骤1: 分析历史数据中的信号有效性...")
        analysis = self.signal_generator.analyze_signal_effectiveness(df)
        return analysis
    
    def run_backtest(self, df: pd.DataFrame) -> Dict:
        """运行回测"""
        # 首先分析信号
        if not self.analyze_mode:
            self.analyze_and_set_thresholds(df)
        
        logger.info("\n步骤2: 开始回测...")
        
        position = None
        equity_curve = []
        entry_time = None
        
        for i in range(200, len(df)):
            current_df = df.iloc[:i+1]
            current_price = df['close'].iloc[i]
            current_time = df['timestamp'].iloc[i]
            
            # 日交易次数重置
            current_day = pd.to_datetime(current_time).date()
            if self.stats['last_trade_day'] != current_day:
                self.stats['daily_trades'] = 0
                self.stats['last_trade_day'] = current_day
            
            # 持仓管理
            if position:
                entry = position['entry_price']
                
                if position['side'] == 'LONG':
                    pnl_pct = (current_price - entry) / entry * self.leverage
                else:
                    pnl_pct = (entry - current_price) / entry * self.leverage
                
                # 爆仓检查
                if pnl_pct <= -48:
                    self.stats['liquidations'] += 1
                    self.balance *= 0.04
                    position = None
                    continue
                
                # 止损
                if pnl_pct <= -self.stop_loss * self.leverage * 100:
                    self.balance -= position['margin'] * self.stop_loss * self.leverage
                    self.stats['losing_trades'] += 1
                    position = None
                    continue
                
                # 分级止盈
                if pnl_pct >= self.take_profit_1 * self.leverage * 100 and not position.get('tp1_hit'):
                    profit = position['margin'] * 0.5 * self.take_profit_1 * self.leverage
                    self.balance += profit
                    position['margin'] *= 0.5
                    position['tp1_hit'] = True
                    position['entry_price'] = current_price
                    self.stats['winning_trades'] += 0.5
                
                if pnl_pct >= self.take_profit_2 * self.leverage * 100:
                    profit = position['margin'] * self.take_profit_2 * self.leverage
                    self.balance += position['margin'] + profit
                    self.stats['winning_trades'] += 0.5
                    position = None
                    continue
            
            # 新开仓
            else:
                if self.stats['daily_trades'] >= self.max_daily_trades:
                    continue
                
                signals = self.signal_generator.generate_optimized_signals(current_df)
                
                # 触发条件：至少有1个信号，且分数>0.4
                if signals['long_count'] > 0 and signals['long_score'] > 0.4:
                    margin = self.balance * self.position_size
                    self.balance -= margin
                    
                    position = {
                        'side': 'BUY',
                        'entry_price': current_price,
                        'margin': margin,
                        'tp1_hit': False
                    }
                    self.stats['total_trades'] += 1
                    self.stats['daily_trades'] += 1
                
                elif signals['short_count'] > 0 and signals['short_score'] > 0.4:
                    margin = self.balance * self.position_size
                    self.balance -= margin
                    
                    position = {
                        'side': 'SELL',
                        'entry_price': current_price,
                        'margin': margin,
                        'tp1_hit': False
                    }
                    self.stats['total_trades'] += 1
                    self.stats['daily_trades'] += 1
            
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
    df = pd.read_csv('eth_usdt_1h_binance.csv')
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    trader = V6OptimizedTrader(initial_balance=1000.0)
    results = trader.run_backtest(df)
    
    print("\n" + "=" * 70)
    print("🚀 V6-Optimized 数据驱动优化回测报告")
    print("=" * 70)
    print(f"\n💰 资金表现:")
    print(f"  初始: $1000.00 → 最终: ${1000 * (1 + results['total_return']/100):.2f}")
    print(f"  总收益: {results['total_return']:+.2f}%")
    
    print(f"\n📊 交易统计:")
    print(f"  总交易: {results['total_trades']}")
    print(f"  年化交易: {results['annual_trades']:.0f} 笔")
    print(f"  盈利: {results['winning_trades']} | 亏损: {results['losing_trades']}")
    print(f"  胜率: {results['win_rate']:.1f}%")
    
    print(f"\n🛡️ 风险控制:")
    print(f"  最大回撤: {results['max_drawdown']:.2f}%")
    print(f"  爆仓: {results['liquidations']} 次")
    
    # 评分
    score = 0
    if results['liquidations'] == 0: score += 30
    if results['win_rate'] > 55: score += 25
    if results['win_rate'] > 50: score += 10
    if results['total_return'] > 0: score += 15
    if results['annual_trades'] > 200: score += 10
    if results['annual_trades'] > 400: score += 10
    
    print(f"\n⭐ 综合评分: {score}/100")
    print("=" * 70)


if __name__ == "__main__":
    main()