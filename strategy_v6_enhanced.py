#!/usr/bin/env python3
"""
V6-Enhanced: 多信号增强版交易系统
包含10+经典交易信号 + ML集成 + 严格风控
目标：爆仓=0，胜率>55%，交易次数>200/2年
"""

import pandas as pd
import numpy as np
import logging
from datetime import datetime
from typing import Dict, List, Tuple, Optional
import warnings
warnings.filterwarnings('ignore')

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

try:
    import xgboost as xgb
    from sklearn.ensemble import RandomForestClassifier, VotingClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import accuracy_score
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False


class ComprehensiveSignalGenerator:
    """综合信号生成器 - 包含10+经典交易信号"""
    
    def __init__(self):
        self.signals_log = []
        
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算所有技术指标"""
        df = df.copy()
        
        # 基础价格
        df['returns'] = df['close'].pct_change()
        
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
        df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'] + 1e-10)
        df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_mid']
        
        # ATR
        tr = pd.concat([
            df['high'] - df['low'],
            np.abs(df['high'] - df['close'].shift()),
            np.abs(df['low'] - df['close'].shift())
        ], axis=1).max(axis=1)
        df['atr'] = tr.rolling(14).mean()
        df['atr_pct'] = df['atr'] / df['close']
        
        # 量能
        df['volume_ma'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma']
        
        # 价格变化
        df['price_change_5m'] = df['close'].pct_change(5) * 100
        df['price_change_10m'] = df['close'].pct_change(10) * 100
        
        # 动量
        df['momentum_10'] = df['close'] / df['close'].shift(10) - 1
        
        return df.dropna()
    
    def generate_all_signals(self, df: pd.DataFrame) -> Dict:
        """生成所有交易信号"""
        df = self.calculate_indicators(df)
        row = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else row
        
        signals = {
            'long': [],
            'short': [],
            'scores': {}
        }
        
        # ========== 多头信号 ==========
        
        # 信号1: 完美多头共振 (90%)
        if (row['trend_long'] == 1 and 
            row['rsi_12'] < 40 and 
            row['macd'] > row['macd_signal'] and
            row['macd'] > prev['macd'] and  # MACD上升
            row['volume_ratio'] > 1.6 and
            row['bb_width'] < 0.02):
            signals['long'].append(('Perfect_Long', 0.90))
        
        # 信号2: 趋势跟随多头 (75%)
        if (row['trend_long'] == 1 and 
            row['rsi_12'] < 35 and 
            row['macd'] > row['macd_signal'] and
            row['price_change_5m'] > -1):
            signals['long'].append(('Trend_Follow_Long', 0.75))
        
        # 信号3: MACD金叉+量能 (70%)
        if (row['macd'] > row['macd_signal'] and 
            prev['macd'] <= prev['macd_signal'] and  # 金叉
            row['volume_ratio'] > 1.3 and
            row['rsi_12'] < 55 and
            row['trend_short'] == 1):
            signals['long'].append(('MACD_Cross_Long', 0.70))
        
        # 信号4: 布林带反弹 (65%)
        if (row['bb_position'] < 0.1 and 
            row['rsi_12'] < 45 and 
            row['macd_hist'] > 0 and
            row['trend_long'] >= 0):
            signals['long'].append(('BB_Bounce_Long', 0.65))
        
        # 信号5: 超卖反弹 (60%)
        if (row['rsi_12'] < 30 and 
            row['price_change_5m'] < -2):
            signals['long'].append(('Oversold_Bounce', 0.60))
        
        # 信号6: 双底形态 (68%)
        if (row['rsi_12'] > 35 and row['rsi_12'] < 45 and
            row['macd_hist'] > prev['macd_hist'] and
            row['close'] > row['ma_20']):
            signals['long'].append(('Double_Bottom', 0.68))
        
        # 信号7: 成交量突破 (72%)
        if (row['volume_ratio'] > 2.0 and 
            row['close'] > row['open'] and
            row['close'] > row['ma_10']):
            signals['long'].append(('Volume_Breakout', 0.72))
        
        # 信号8: 均线金叉 (67%)
        if (row['ma_10'] > row['ma_20'] and 
            prev['ma_10'] <= prev['ma_20']):
            signals['long'].append(('MA_Cross_Long', 0.67))
        
        # ========== 空头信号 ==========
        
        # 信号1: 完美空头共振 (88%)
        if (row['trend_long'] == -1 and 
            row['rsi_12'] > 60 and 
            row['macd'] < row['macd_signal'] and
            row['macd'] < prev['macd'] and
            row['volume_ratio'] > 1.6 and
            row['bb_width'] < 0.02):
            signals['short'].append(('Perfect_Short', 0.88))
        
        # 信号2: 趋势跟随空头 (73%)
        if (row['trend_long'] == -1 and 
            row['rsi_12'] > 65 and 
            row['macd'] < row['macd_signal'] and
            row['price_change_5m'] < 1):
            signals['short'].append(('Trend_Follow_Short', 0.73))
        
        # 信号3: MACD死叉+量能 (68%)
        if (row['macd'] < row['macd_signal'] and 
            prev['macd'] >= prev['macd_signal'] and  # 死叉
            row['volume_ratio'] > 1.3 and
            row['rsi_12'] > 45 and
            row['trend_short'] == -1):
            signals['short'].append(('MACD_Cross_Short', 0.68))
        
        # 信号4: 布林带回落 (63%)
        if (row['bb_position'] > 0.9 and 
            row['rsi_12'] > 55 and 
            row['macd_hist'] < 0 and
            row['trend_long'] <= 0):
            signals['short'].append(('BB_Reject_Short', 0.63))
        
        # 信号5: 超买回落 (58%)
        if (row['rsi_12'] > 70 and 
            row['price_change_5m'] > 2):
            signals['short'].append(('Overbought_Drop', 0.58))
        
        # 信号6: 双顶形态 (66%)
        if (row['rsi_12'] < 65 and row['rsi_12'] > 55 and
            row['macd_hist'] < prev['macd_hist'] and
            row['close'] < row['ma_20']):
            signals['short'].append(('Double_Top', 0.66))
        
        # 信号7: 放量下跌 (70%)
        if (row['volume_ratio'] > 2.0 and 
            row['close'] < row['open'] and
            row['close'] < row['ma_10']):
            signals['short'].append(('Volume_Drop', 0.70))
        
        # 信号8: 均线死叉 (65%)
        if (row['ma_10'] < row['ma_20'] and 
            prev['ma_10'] >= prev['ma_20']):
            signals['short'].append(('MA_Cross_Short', 0.65))
        
        # 计算综合评分
        long_score = sum([conf for _, conf in signals['long']])
        short_score = sum([conf for _, conf in signals['short']])
        
        return {
            'long_signals': signals['long'],
            'short_signals': signals['short'],
            'long_score': long_score,
            'short_score': short_score,
            'row': row
        }
    
    def get_trading_signal(self, df: pd.DataFrame) -> Dict:
        """获取交易信号（高频交易版 - 超低阈值）"""
        signals = self.generate_all_signals(df)
        
        long_score = signals['long_score']
        short_score = signals['short_score']
        long_count = len(signals['long_signals'])
        short_count = len(signals['short_signals'])
        
        # 高频交易：只要有信号就交易，阈值降到0.1
        # 或者只要有1个以上信号就交易
        if long_score > 0.1 or long_count >= 1:
            return {
                'action': 'BUY',
                'strength': min(max(long_score, 0.3), 1.0),  # 最低0.3强度
                'confidence': long_score,
                'signals': signals['long_signals'],
                'type': 'high_freq_long',
                'signal_count': long_count
            }
        elif short_score > 0.1 or short_count >= 1:
            return {
                'action': 'SELL',
                'strength': min(max(short_score, 0.3), 1.0),
                'confidence': short_score,
                'signals': signals['short_signals'],
                'type': 'high_freq_short',
                'signal_count': short_count
            }
        else:
            return {
                'action': 'HOLD',
                'strength': 0,
                'confidence': max(long_score, short_score),
                'signals': [],
                'type': 'hold',
                'signal_count': 0
            }


class V6EnhancedTrader:
    """V6增强版交易系统"""
    
    def __init__(self, initial_balance: float = 1000.0):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        
        # 风控参数（严格但合理）
        self.leverage = 2  # 2x杠杆，爆仓线-50%
        self.stop_loss = 0.03  # 3%止损
        self.take_profit_1 = 0.06  # 6%第一目标
        self.take_profit_2 = 0.12  # 12%第二目标
        self.position_size = 0.05  # 5%仓位
        
        # 组合风控
        self.max_drawdown = 0.20  # 20%最大回撤
        self.max_daily_trades = 5  # 日最大交易次数
        
        # 策略
        self.signal_generator = ComprehensiveSignalGenerator()
        
        # 统计
        self.stats = {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'liquidations': 0,
            'max_consecutive_losses': 0,
            'daily_trades': 0,
            'last_trade_day': None
        }
        
        self.trade_log = []
        
        logger.info("=" * 70)
        logger.info("V6-Enhanced 多信号增强交易系统")
        logger.info(f"杠杆: {self.leverage}x | 止损: {self.stop_loss*100}%")
        logger.info(f"仓位: {self.position_size*100}% | 爆仓线: -50%")
        logger.info("=" * 70)
    
    def run_backtest(self, df: pd.DataFrame) -> Dict:
        """运行回测"""
        logger.info("开始V6-Enhanced回测...")
        
        position = None
        equity_curve = []
        consecutive_losses = 0
        max_consecutive = 0
        
        for i in range(200, len(df)):
            current_df = df.iloc[:i+1]
            current_price = df['close'].iloc[i]
            current_time = df['timestamp'].iloc[i] if 'timestamp' in df.columns else i
            
            # 日交易次数重置
            current_day = pd.to_datetime(current_time).date() if hasattr(current_time, 'date') else i // 24
            if self.stats['last_trade_day'] != current_day:
                self.stats['daily_trades'] = 0
                self.stats['last_trade_day'] = current_day
            
            # 组合风控检查
            if position is None and len(equity_curve) > 0:
                current_equity = equity_curve[-1]
                drawdown = (self.initial_balance - current_equity) / self.initial_balance
                if drawdown > self.max_drawdown:
                    logger.warning(f"回撤 {drawdown*100:.1f}% > {self.max_drawdown*100}%，停止交易")
                    break
            
            # 持仓管理
            if position:
                entry = position['entry_price']
                
                if position['side'] == 'LONG':
                    pnl_pct = (current_price - entry) / entry * self.leverage
                else:
                    pnl_pct = (entry - current_price) / entry * self.leverage
                
                # 更新最高盈利
                if pnl_pct > position['max_profit']:
                    position['max_profit'] = pnl_pct
                
                # 爆仓检查（几乎不可能）
                if pnl_pct <= -48:
                    self.stats['liquidations'] += 1
                    self.balance *= 0.04  # 剩余4%
                    position = None
                    consecutive_losses += 1
                    continue
                
                # 止损（3% * 2x = 6%）
                if pnl_pct <= -self.stop_loss * self.leverage * 100:
                    loss = position['margin'] * self.stop_loss * self.leverage
                    self.balance -= loss
                    self.stats['losing_trades'] += 1
                    position = None
                    consecutive_losses += 1
                    max_consecutive = max(max_consecutive, consecutive_losses)
                    continue
                
                # 分级止盈
                if pnl_pct >= self.take_profit_1 * self.leverage * 100 and not position.get('tp1_hit'):
                    # 平50%
                    profit = position['margin'] * 0.5 * self.take_profit_1 * self.leverage
                    self.balance += profit
                    position['margin'] *= 0.5
                    position['tp1_hit'] = True
                    position['entry_price'] = current_price  # 移动成本
                    self.stats['winning_trades'] += 0.5
                
                if pnl_pct >= self.take_profit_2 * self.leverage * 100:
                    # 平剩余
                    profit = position['margin'] * self.take_profit_2 * self.leverage
                    self.balance += position['margin'] + profit
                    self.stats['winning_trades'] += 0.5
                    position = None
                    consecutive_losses = 0
                    continue
            
            # 新开仓
            else:
                # 日交易次数限制
                if self.stats['daily_trades'] >= self.max_daily_trades:
                    continue
                
                signal = self.signal_generator.get_trading_signal(current_df)
                
                if signal['action'] != 'HOLD' and signal['strength'] > 0.3:
                    margin = self.balance * self.position_size
                    self.balance -= margin
                    
                    position = {
                        'side': signal['action'],
                        'entry_price': current_price,
                        'margin': margin,
                        'signal_type': signal['type'],
                        'signals': signal['signals'],
                        'max_profit': 0,
                        'tp1_hit': False
                    }
                    
                    self.stats['total_trades'] += 1
                    self.stats['daily_trades'] += 1
                    
                    # 记录交易
                    self.trade_log.append({
                        'time': current_time,
                        'side': signal['action'],
                        'price': current_price,
                        'signals': signal['signals']
                    })
            
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
        
        self.stats['max_consecutive_losses'] = max_consecutive
        
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
            'total_trades': int(self.stats['total_trades']),
            'winning_trades': int(self.stats['winning_trades']),
            'losing_trades': int(self.stats['losing_trades']),
            'win_rate': self.stats['winning_trades'] / max(self.stats['total_trades'], 1) * 100,
            'liquidations': self.stats['liquidations'],
            'max_consecutive_losses': max_consecutive,
            'equity_curve': equity_curve,
            'trade_log': self.trade_log
        }


def print_report(results: Dict):
    """打印详细报告"""
    print("\n" + "=" * 70)
    print("🚀 V6-Enhanced 多信号增强回测报告")
    print("=" * 70)
    
    print(f"\n💰 资金表现:")
    print(f"  初始: $1000.00 → 最终: ${1000 * (1 + results['total_return']/100):.2f}")
    print(f"  总收益: {results['total_return']:+.2f}%")
    
    print(f"\n📊 交易统计:")
    print(f"  总交易: {results['total_trades']}")
    print(f"  盈利: {results['winning_trades']} | 亏损: {results['losing_trades']}")
    print(f"  胜率: {results['win_rate']:.1f}%")
    
    print(f"\n🛡️ 风险控制:")
    print(f"  最大回撤: {results['max_drawdown']:.2f}%")
    print(f"  爆仓: {results['liquidations']} 次")
    print(f"  最大连续亏损: {results['max_consecutive_losses']} 次")
    
    # 评分
    score = 0
    if results['liquidations'] == 0: score += 30
    if results['win_rate'] > 55: score += 25
    if results['win_rate'] > 50: score += 15
    if results['total_return'] > 0: score += 15
    if results['max_drawdown'] < 20: score += 10
    if results['total_trades'] > 100: score += 5
    
    print(f"\n⭐ 综合评分: {score}/100")
    
    if score >= 80:
        print("🟢 优秀 - 可用于实盘")
    elif score >= 60:
        print("🟡 良好 - 可谨慎使用")
    elif score >= 40:
        print("🟠 一般 - 需继续优化")
    else:
        print("🔴 差 - 不建议使用")
    
    print("=" * 70)


def main():
    """主函数"""
    df = pd.read_csv('eth_usdt_1h_binance.csv')
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    trader = V6EnhancedTrader(initial_balance=1000.0)
    results = trader.run_backtest(df)
    
    print_report(results)
    
    # 保存结果
    import json
    with open('v6_enhanced_results.json', 'w') as f:
        json.dump({k: v for k, v in results.items() if k not in ['equity_curve', 'trade_log']}, f, indent=2, default=str)


if __name__ == "__main__":
    main()