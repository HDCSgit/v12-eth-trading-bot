#!/usr/bin/env python3
"""
V9-Dual-Direction: 双向高频交易系统
核心：多空结合 + 10+信号 + 放宽阈值 + 高频套利
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


class V9DualSignalGenerator:
    """V9双向信号生成器 - 10+多头信号 + 10+空头信号"""
    
    def __init__(self):
        self.long_signals_count = 0
        self.short_signals_count = 0
        
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算全面技术指标"""
        df = df.copy()
        
        # RSI多周期
        for period in [6, 12, 24]:
            delta = df['close'].diff()
            gain = delta.clip(lower=0).rolling(period).mean()
            loss = (-delta.clip(upper=0)).rolling(period).mean()
            df[f'rsi_{period}'] = 100 - 100 / (1 + gain / (loss + 1e-10))
        
        # MACD多组
        for fast, slow, signal in [(12, 26, 9), (5, 35, 5)]:
            ema_fast = df['close'].ewm(span=fast).mean()
            ema_slow = df['close'].ewm(span=slow).mean()
            df[f'macd_{fast}_{slow}'] = ema_fast - ema_slow
            df[f'macd_signal_{fast}_{slow}'] = df[f'macd_{fast}_{slow}'].ewm(span=signal).mean()
        
        # 多周期均线
        for period in [5, 10, 20, 55, 200]:
            df[f'ma_{period}'] = df['close'].rolling(period).mean()
        
        # 趋势判断
        df['trend_long'] = np.where(df['ma_55'] > df['ma_200'], 1, -1)
        df['trend_short'] = np.where(df['ma_10'] > df['ma_20'], 1, -1)
        
        # 布林带
        for period in [20, 50]:
            df[f'bb_mid_{period}'] = df['close'].rolling(period).mean()
            df[f'bb_std_{period}'] = df['close'].rolling(period).std()
            df[f'bb_upper_{period}'] = df[f'bb_mid_{period}'] + 2 * df[f'bb_std_{period}']
            df[f'bb_lower_{period}'] = df[f'bb_mid_{period}'] - 2 * df[f'bb_std_{period}']
            df[f'bb_position_{period}'] = (df['close'] - df[f'bb_lower_{period}']) / (df[f'bb_upper_{period}'] - df[f'bb_lower_{period}'] + 1e-10)
        
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
        for period in [1, 3, 5, 10]:
            df[f'price_change_{period}m'] = df['close'].pct_change(period) * 100
        
        # 动量
        df['momentum_10'] = df['close'] / df['close'].shift(10) - 1
        
        # 统计特征
        df['volatility'] = df['close'].pct_change().rolling(20).std()
        df['volatility_ma'] = df['volatility'].rolling(20).mean()
        df['volatility_squeeze'] = df['volatility'] < df['volatility_ma'] * 0.8
        
        return df.dropna()
    
    def generate_signals(self, df: pd.DataFrame) -> Dict:
        """生成多空双向信号"""
        df = self.calculate_indicators(df)
        
        if len(df) < 2:
            return {'action': 'HOLD', 'long_signals': [], 'short_signals': []}
        
        row = df.iloc[-1]
        prev = df.iloc[-2]
        
        long_signals = []
        short_signals = []
        
        # ========== 多头信号（10个）==========
        
        # 1. RSI超卖（放宽到45）
        if row['rsi_12'] < 45:
            long_signals.append(('RSI_Oversold_45', 0.55))
        
        # 2. RSI极端超卖（更严格但更高胜率）
        if row['rsi_12'] < 30:
            long_signals.append(('RSI_Oversold_30', 0.70))
        
        # 3. MACD金叉
        if (row['macd_12_26'] > row['macd_signal_12_26'] and 
            prev['macd_12_26'] <= prev['macd_signal_12_26']):
            long_signals.append(('MACD_Cross', 0.60))
        
        # 4. 短期MACD金叉
        if (row['macd_5_35'] > row['macd_signal_5_35'] and 
            prev['macd_5_35'] <= prev['macd_signal_5_35']):
            long_signals.append(('MACD_Cross_Fast', 0.55))
        
        # 5. 布林带下轨（放宽到1.03）
        if row['close'] < row['bb_lower_20'] * 1.03:
            long_signals.append(('BB_Lower', 0.55))
        
        # 6. 布林带极度下轨
        if row['close'] < row['bb_lower_20']:
            long_signals.append(('BB_Lower_Extreme', 0.65))
        
        # 7. 均线金叉
        if (row['ma_5'] > row['ma_10'] and 
            prev['ma_5'] <= prev['ma_10']):
            long_signals.append(('MA_Cross', 0.60))
        
        # 8. 趋势跟随多头
        if row['trend_long'] == 1 and row['rsi_12'] < 50:
            long_signals.append(('Trend_Follow_Long', 0.50))
        
        # 9. 放量上涨
        if row['volume_ratio_5'] > 1.3 and row['close'] > row['open']:
            long_signals.append(('Volume_Break', 0.50))
        
        # 10. 超跌反弹（放宽到-1%）
        if row['price_change_3m'] < -1:
            long_signals.append(('Drop_Bounce', 0.55))
        
        # 11. 连续下跌后反弹
        if row['price_change_5m'] < -1.5:
            long_signals.append(('Drop_Bounce_Strong', 0.60))
        
        # 12. 波动率收缩突破
        if row['volatility_squeeze'] and row['close'] > row['ma_20']:
            long_signals.append(('Volatility_Squeeze', 0.55))
        
        # ========== 空头信号（10个）==========
        
        # 1. RSI超买（放宽到55）
        if row['rsi_12'] > 55:
            short_signals.append(('RSI_Overbought_55', 0.55))
        
        # 2. RSI极端超买
        if row['rsi_12'] > 70:
            short_signals.append(('RSI_Overbought_70', 0.70))
        
        # 3. MACD死叉
        if (row['macd_12_26'] < row['macd_signal_12_26'] and 
            prev['macd_12_26'] >= prev['macd_signal_12_26']):
            short_signals.append(('MACD_Cross_Down', 0.60))
        
        # 4. 短期MACD死叉
        if (row['macd_5_35'] < row['macd_signal_5_35'] and 
            prev['macd_5_35'] >= prev['macd_signal_5_35']):
            short_signals.append(('MACD_Cross_Fast_Down', 0.55))
        
        # 5. 布林带上轨（放宽到0.97）
        if row['close'] > row['bb_upper_20'] * 0.97:
            short_signals.append(('BB_Upper', 0.55))
        
        # 6. 布林带极度上轨
        if row['close'] > row['bb_upper_20']:
            short_signals.append(('BB_Upper_Extreme', 0.65))
        
        # 7. 均线死叉
        if (row['ma_5'] < row['ma_10'] and 
            prev['ma_5'] >= prev['ma_10']):
            short_signals.append(('MA_Cross_Down', 0.60))
        
        # 8. 趋势跟随空头
        if row['trend_long'] == -1 and row['rsi_12'] > 50:
            short_signals.append(('Trend_Follow_Short', 0.50))
        
        # 9. 放量下跌
        if row['volume_ratio_5'] > 1.3 and row['close'] < row['open']:
            short_signals.append(('Volume_Drop', 0.50))
        
        # 10. 连续上涨后回落（放宽到1%）
        if row['price_change_3m'] > 1:
            short_signals.append(('Rise_Drop', 0.55))
        
        # 11. 连续大涨后回落
        if row['price_change_5m'] > 1.5:
            short_signals.append(('Rise_Drop_Strong', 0.60))
        
        # 12. 波动率收缩下破
        if row['volatility_squeeze'] and row['close'] < row['ma_20']:
            short_signals.append(('Volatility_Squeeze_Down', 0.55))
        
        # 计算分数
        long_score = sum([conf for _, conf in long_signals])
        short_score = sum([conf for _, conf in short_signals])
        
        # 决策逻辑：只要有信号就交易（移除多空对决，提升交易频率）
        if len(long_signals) >= 1:
            return {
                'action': 'BUY',
                'signals': long_signals,
                'score': long_score,
                'opposing_score': short_score
            }
        elif len(short_signals) >= 1:
            return {
                'action': 'SELL',
                'signals': short_signals,
                'score': short_score,
                'opposing_score': long_score
            }
        else:
            return {
                'action': 'HOLD',
                'long_signals': long_signals,
                'short_signals': short_signals
            }


class V9DualTrader:
    """V9双向高频交易系统"""
    
    def __init__(self, initial_balance: float = 1000.0, params: Dict = None):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.params = params or {}
        
        # 交易参数（优化套利效率）
        self.leverage = self.params.get('leverage', 2)
        self.stop_loss = self.params.get('stop_loss', 0.015)  # 1.5%快速止损
        self.take_profit = self.params.get('take_profit', 0.03)  # 3%快速止盈
        self.position_size = self.params.get('position_size', 0.15)  # 15%仓位（提高）
        
        # 风控
        self.max_drawdown = self.params.get('max_drawdown', 0.25)
        self.max_trades_per_day = self.params.get('max_trades_per_day', 50)
        
        # 策略
        self.signal_generator = V9DualSignalGenerator()
        
        # 统计
        self.stats = {
            'total_trades': 0,
            'long_trades': 0,
            'short_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'liquidations': 0,
            'daily_trades': 0,
            'last_date': None
        }
        
        self.trade_log = []
        self.equity_curve = []
        
        logger.info("\n" + "=" * 70)
        logger.info("🚀 V9-Dual-Direction 双向高频交易系统")
        logger.info(f"杠杆: {self.leverage}x | 仓位: {self.position_size*100}%")
        logger.info(f"止损: {self.stop_loss*100}% | 止盈: {self.take_profit*100}%")
        logger.info(f"多头信号: 12个 | 空头信号: 12个")
        logger.info("=" * 70)
    
    def run_backtest(self, df: pd.DataFrame) -> Dict:
        """运行双向回测"""
        logger.info("开始双向高频回测...")
        
        position = None
        position_side = None
        
        for i in range(1, len(df)):
            current_df = df.iloc[:i+1]
            current_price = df['close'].iloc[i]
            current_time = df['timestamp'].iloc[i]
            
            # 日交易次数限制
            current_date = pd.to_datetime(current_time).date()
            if self.stats['last_date'] != current_date:
                self.stats['daily_trades'] = 0
                self.stats['last_date'] = current_date
            
            # 持仓管理
            if position:
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
                    continue
                
                # 止损
                if pnl_pct <= -self.stop_loss * self.leverage * 100:
                    loss = position['margin'] * self.stop_loss * self.leverage
                    self.balance -= loss
                    self.stats['losing_trades'] += 1
                    
                    self.trade_log.append({
                        'type': 'LOSE',
                        'side': position_side,
                        'pnl': -self.stop_loss * self.leverage
                    })
                    
                    position = None
                    position_side = None
                    continue
                
                # 止盈
                if pnl_pct >= self.take_profit * self.leverage * 100:
                    profit = position['margin'] * self.take_profit * self.leverage
                    self.balance += position['margin'] + profit
                    self.stats['winning_trades'] += 1
                    
                    self.trade_log.append({
                        'type': 'WIN',
                        'side': position_side,
                        'pnl': self.take_profit * self.leverage
                    })
                    
                    position = None
                    position_side = None
                    continue
            
            # 新开仓
            else:
                if self.stats['daily_trades'] >= self.max_trades_per_day:
                    continue
                
                signal = self.signal_generator.generate_signals(current_df)
                
                if signal['action'] in ['BUY', 'SELL']:
                    margin = self.balance * self.position_size
                    self.balance -= margin
                    
                    position = {
                        'entry_price': current_price,
                        'margin': margin,
                        'signals': signal['signals']
                    }
                    position_side = 'LONG' if signal['action'] == 'BUY' else 'SHORT'
                    self.stats['total_trades'] += 1
                    self.stats['daily_trades'] += 1
                    
                    if position_side == 'LONG':
                        self.stats['long_trades'] += 1
                    else:
                        self.stats['short_trades'] += 1
            
            # 记录权益
            equity = self.balance
            if position:
                if position_side == 'LONG':
                    unrealized = position['margin'] * (current_price - position['entry_price']) / position['entry_price'] * self.leverage
                else:
                    unrealized = position['margin'] * (position['entry_price'] - current_price) / position['entry_price'] * self.leverage
                equity += position['margin'] + unrealized
            
            self.equity_curve.append(equity)
        
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
        final_equity = self.equity_curve[-1] if self.equity_curve else self.initial_balance
        total_return = (final_equity - self.initial_balance) / self.initial_balance * 100
        
        max_dd = 0
        peak = self.initial_balance
        for eq in self.equity_curve:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak
            if dd > max_dd:
                max_dd = dd
        
        # 年化
        years = 2.2
        annual_trades = self.stats['total_trades'] / years
        annual_return = total_return / years
        
        # 盈亏比
        wins = [t for t in self.trade_log if t['type'] == 'WIN']
        losses = [t for t in self.trade_log if t['type'] == 'LOSE']
        profit_factor = sum([t['pnl'] for t in wins]) / abs(sum([t['pnl'] for t in losses])) if losses else 0
        
        return {
            'total_return': total_return,
            'annual_return': annual_return,
            'max_drawdown': max_dd * 100,
            'total_trades': self.stats['total_trades'],
            'long_trades': self.stats['long_trades'],
            'short_trades': self.stats['short_trades'],
            'annual_trades': annual_trades,
            'winning_trades': self.stats['winning_trades'],
            'losing_trades': self.stats['losing_trades'],
            'win_rate': self.stats['winning_trades'] / max(self.stats['total_trades'], 1) * 100,
            'liquidations': self.stats['liquidations'],
            'profit_factor': profit_factor
        }


def print_report(result: Dict):
    """打印详细报告"""
    print("\n" + "=" * 70)
    print("🚀 V9-Dual-Direction 双向高频回测报告")
    print("=" * 70)
    
    print("\n💰 收益表现:")
    print(f"  初始: $1,000.00 → 最终: ${1000 * (1 + result['total_return']/100):.2f}")
    print(f"  总回报: {result['total_return']:+.2f}%")
    print(f"  年化回报: {result['annual_return']:+.2f}%")
    
    print("\n📊 交易统计:")
    print(f"  总交易: {result['total_trades']}")
    print(f"  做多: {result['long_trades']} | 做空: {result['short_trades']}")
    print(f"  年化交易: {result['annual_trades']:.0f} 笔")
    print(f"  盈利: {result['winning_trades']} | 亏损: {result['losing_trades']}")
    print(f"  胜率: {result['win_rate']:.1f}%")
    print(f"  盈亏比: {result['profit_factor']:.2f}")
    
    print("\n🛡️ 风险控制:")
    print(f"  最大回撤: {result['max_drawdown']:.2f}%")
    print(f"  爆仓: {result['liquidations']} 次")
    
    # 评分
    score = 0
    if result['liquidations'] == 0: score += 30
    if result['win_rate'] > 55: score += 25
    if result['win_rate'] > 50: score += 10
    if result['total_return'] > 0: score += 20
    if result['annual_trades'] > 500: score += 10
    if result['profit_factor'] > 1.5: score += 5
    
    print(f"\n⭐ 综合评分: {score}/100")
    
    if score >= 80:
        print("🟢 优秀 - 建议实盘")
    elif score >= 60:
        print("🟡 良好 - 可谨慎使用")
    elif score >= 40:
        print("🟠 一般 - 需继续优化")
    else:
        print("🔴 较差 - 不建议使用")
    
    print("=" * 70)


def main():
    """主函数"""
    logger.info("加载5分钟ETH数据...")
    df = pd.read_csv('eth_usdt_5m_2024_2026.csv')
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    logger.info(f"数据条数: {len(df):,}")
    
    # 运行回测
    trader = V9DualTrader(initial_balance=1000.0)
    result = trader.run_backtest(df)
    
    # 打印报告
    print_report(result)


if __name__ == "__main__":
    main()