#!/usr/bin/env python3
"""
V2.5-Hybrid 模拟回测系统
基于ETH历史统计特征生成2年模拟数据，进行完整回测分析
"""

import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SimulatedV2_5Backtest:
    """
    V2.5策略模拟回测引擎
    """
    
    def __init__(self, initial_balance: float = 1000.0, leverage: int = 5):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.leverage = leverage
        
        # 交易统计
        self.stats = {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'liquidations': 0,
            'dca_count': 0,
            'grid_tp_count': 0,
            'total_pnl': 0.0,
            'max_drawdown': 0.0,
            'max_equity': initial_balance,
            'consecutive_losses': 0,
            'max_consecutive_losses': 0
        }
        
        # 仓位状态
        self.position = None
        self.trades = []
        self.equity_curve = []
        
        # V2.5参数
        self.confidence_threshold = 0.60
        self.perfect_confidence = 0.88
        self.min_trade_interval = 4  # 4分钟
        self.last_trade_time = None
        
        # 网格参数
        self.grid_atr_multiplier = 1.4
        self.max_dca_count = 3
        self.dca_fib = [1.0, 1.618, 2.618]
        self.dca_accelerator = 1.2
        
        # 止盈止损
        self.stop_loss_pct = -0.05  # -5%
        self.trailing_start = 0.06
        self.trailing_stop = 0.03
        self.group_tp = 0.08
        
        logger.info("V2.5模拟回测引擎初始化完成")
    
    def generate_simulated_data(self, days: int = 730) -> pd.DataFrame:
        """
        生成2年ETH模拟数据（基于真实统计特征）
        """
        np.random.seed(42)  # 可复现
        
        # ETH历史统计参数（2024-2026）
        base_price = 2200.0
        annual_volatility = 0.65  # 65%年化波动率
        daily_return_mean = 0.0002  # 微正收益
        daily_vol = annual_volatility / np.sqrt(365)
        
        # 生成1小时K线（24 * 365 * 2 = 17520条）
        periods = days * 24
        timestamps = [datetime(2024, 1, 1) + timedelta(hours=i) for i in range(periods)]
        
        # 生成价格序列（几何布朗运动 + 跳跃）
        prices = [base_price]
        for i in range(1, periods):
            # 基础漂移
            drift = daily_return_mean / 24
            # 随机波动
            shock = np.random.normal(0, daily_vol / np.sqrt(24))
            # 偶尔的大波动（5%概率）
            if np.random.random() < 0.05:
                shock *= 3
            
            new_price = prices[-1] * (1 + drift + shock)
            
            # 限制价格范围（ETH合理区间）
            new_price = max(1000, min(5000, new_price))
            prices.append(new_price)
        
        # 生成OHLCV
        data = []
        for i, (ts, close) in enumerate(zip(timestamps, prices)):
            # 基于close生成open/high/low
            intraday_vol = close * 0.015  # 1.5%日内波动
            
            open_price = close + np.random.normal(0, intraday_vol * 0.3)
            high_price = max(open_price, close) + abs(np.random.normal(0, intraday_vol * 0.5))
            low_price = min(open_price, close) - abs(np.random.normal(0, intraday_vol * 0.5))
            
            # 成交量（与波动相关）
            volume = np.random.lognormal(15, 0.5) * (1 + abs(close - open_price) / close * 10)
            
            data.append({
                'timestamp': ts,
                'open': open_price,
                'high': high_price,
                'low': low_price,
                'close': close,
                'volume': volume
            })
        
        df = pd.DataFrame(data)
        
        # 计算技术指标
        df['ma20'] = df['close'].rolling(20, min_periods=1).mean()
        df['ma55'] = df['close'].rolling(55, min_periods=1).mean()
        df['ma200'] = df['close'].rolling(200, min_periods=1).mean()
        df['trend'] = np.where(df['ma55'] > df['ma200'], 1, -1)
        df['trend_short'] = np.where(df['ma20'] > df['ma55'], 1, -1)
        
        # RSI
        delta = df['close'].diff()
        gain = delta.clip(lower=0).rolling(14, min_periods=1).mean()
        loss = (-delta.clip(upper=0)).rolling(14, min_periods=1).mean()
        rs = gain / (loss + 1e-10)
        df['rsi'] = 100 - 100 / (1 + rs)
        
        # MACD
        ema12 = df['close'].ewm(span=12, min_periods=1).mean()
        ema26 = df['close'].ewm(span=26, min_periods=1).mean()
        df['macd'] = ema12 - ema26
        df['macd_signal'] = df['macd'].ewm(span=9, min_periods=1).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']
        
        # ATR
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['atr'] = tr.rolling(14, min_periods=1).mean()
        df['atr_pct'] = df['atr'] / df['close'] * 100
        
        # 布林带
        df['bb_mid'] = df['close'].rolling(20, min_periods=1).mean()
        df['bb_std'] = df['close'].rolling(20, min_periods=1).std()
        df['bb_upper'] = df['bb_mid'] + 2 * df['bb_std']
        df['bb_lower'] = df['bb_mid'] - 2 * df['bb_std']
        df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_mid']
        df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'] + 1e-10)
        
        # 量能
        df['volume_ma'] = df['volume'].rolling(30, min_periods=1).mean()
        df['volume_ratio'] = df['volume'] / (df['volume_ma'] + 1e-10)
        
        df['symbol'] = 'ETHUSDT'
        
        logger.info(f"生成模拟数据: {len(df)} 条记录 ({days}天)")
        logger.info(f"价格范围: ${df['close'].min():.0f} - ${df['close'].max():.0f}")
        
        return df.dropna()
    
    def calculate_signals(self, row, prev_row) -> Tuple[int, int, List[str]]:
        """计算V2信号"""
        long_signals = []
        short_signals = []
        
        trend = row['trend']
        trend_short = row.get('trend_short', trend)
        rsi = row['rsi']
        macd = row['macd']
        macd_signal = row['macd_signal']
        macd_hist = row.get('macd_hist', macd - macd_signal)
        
        macd_cross_up = (macd > macd_signal) and (prev_row['macd'] <= prev_row['macd_signal'])
        macd_cross_down = (macd < macd_signal) and (prev_row['macd'] >= prev_row['macd_signal'])
        
        volume_ratio = row.get('volume_ratio', 1.0)
        volume_spike = volume_ratio > 1.5
        bb_width = row.get('bb_width', 0.05)
        bb_position = row.get('bb_position', 0.5)
        price_change_5m = row.get('price_change_5m', 0)
        
        # 多头信号
        if (trend == 1 and rsi < 45 and macd_cross_up and volume_spike and bb_width < 0.05):
            long_signals.append('Perfect Long (90%)')
        if (trend == 1 and rsi < 40 and macd > macd_signal):
            long_signals.append('Trend Follow Long (75%)')
        if (macd_cross_up and volume_ratio > 1.2 and rsi < 60 and trend_short == 1):
            long_signals.append('MACD Cross Long (70%)')
        if (bb_position < 0.15 and rsi < 50 and macd_hist > 0):
            long_signals.append('BB Bounce Long (65%)')
        if (rsi < 35 and macd_hist > 0):
            long_signals.append('Oversold Bounce (60%)')
        
        # 空头信号
        if (trend == -1 and rsi > 55 and macd_cross_down and volume_spike and bb_width < 0.05):
            short_signals.append('Perfect Short (88%)')
        if (trend == -1 and rsi > 60 and macd < macd_signal):
            short_signals.append('Trend Follow Short (73%)')
        if (macd_cross_down and volume_ratio > 1.2 and rsi > 40 and trend_short == -1):
            short_signals.append('MACD Cross Short (68%)')
        if (bb_position > 0.85 and rsi > 50 and macd_hist < 0):
            short_signals.append('BB Reject Short (63%)')
        if (rsi > 65 and macd_hist < 0):
            short_signals.append('Overbought Drop (58%)')
        
        return len(long_signals), len(short_signals), long_signals + short_signals
    
    def get_dynamic_grid_multiplier(self, volume_ratio: float, atr_pct: float) -> float:
        """动态ATR网格倍数"""
        base_multiplier = 1.2
        volume_adjustment = 0.2 * (volume_ratio - 1.0)
        volume_adjustment = max(-0.1, min(0.3, volume_adjustment))
        atr_adjustment = 0.075 * (atr_pct - 2.5)
        atr_adjustment = max(-0.1, min(0.2, atr_adjustment))
        dynamic_multiplier = base_multiplier + volume_adjustment + atr_adjustment
        return max(1.0, min(1.8, dynamic_multiplier))
    
    def check_liquidation(self, entry_price: float, current_price: float, side: str) -> bool:
        """检查爆仓"""
        if side == 'LONG':
            loss_pct = (current_price - entry_price) / entry_price
        else:
            loss_pct = (entry_price - current_price) / entry_price
        
        # 5x杠杆，爆仓线-20%
        liquidation_threshold = -0.20
        
        return loss_pct <= liquidation_threshold
    
    def run_backtest(self, df: pd.DataFrame) -> Dict:
        """运行回测"""
        logger.info("开始V2.5回测...")
        
        position = None
        max_consecutive_losses = 0
        current_consecutive_losses = 0
        
        for i in range(200, len(df)):
            row = df.iloc[i]
            prev_row = df.iloc[i-1]
            timestamp = row['timestamp']
            
            # 检查信号
            long_count, short_count, signal_details = self.calculate_signals(row, prev_row)
            
            # 持仓管理
            if position:
                entry = position['entry_price']
                current = row['close']
                side = position['side']
                
                # 计算盈亏
                if side == 'LONG':
                    pnl_pct = (current - entry) / entry * self.leverage
                else:
                    pnl_pct = (entry - current) / entry * self.leverage
                
                # 更新最高盈利
                if pnl_pct > position['max_profit']:
                    position['max_profit'] = pnl_pct
                
                # 检查爆仓
                if self.check_liquidation(entry, current, side):
                    loss = position['margin'] * 0.9
                    self.balance -= loss
                    self.stats['liquidations'] += 1
                    self.stats['losing_trades'] += 1
                    self.stats['total_pnl'] -= loss
                    
                    current_consecutive_losses += 1
                    max_consecutive_losses = max(max_consecutive_losses, current_consecutive_losses)
                    
                    self.trades.append({
                        'time': timestamp,
                        'action': 'LIQUIDATION',
                        'pnl': -loss,
                        'pnl_pct': -90
                    })
                    
                    position = None
                    continue
                
                # 止损
                if pnl_pct <= self.stop_loss_pct * 100:
                    loss = position['margin'] * abs(pnl_pct) / 100 / self.leverage
                    self.balance -= loss
                    self.stats['losing_trades'] += 1
                    self.stats['total_pnl'] -= loss
                    current_consecutive_losses += 1
                    max_consecutive_losses = max(max_consecutive_losses, current_consecutive_losses)
                    
                    self.trades.append({
                        'time': timestamp,
                        'action': 'STOP_LOSS',
                        'pnl': -loss,
                        'pnl_pct': pnl_pct
                    })
                    
                    position = None
                    continue
                
                # 整组止盈
                if pnl_pct >= self.group_tp * 100:
                    profit = position['margin'] * pnl_pct / 100 / self.leverage
                    self.balance += profit
                    self.stats['winning_trades'] += 1
                    self.stats['total_pnl'] += profit
                    current_consecutive_losses = 0
                    
                    self.trades.append({
                        'time': timestamp,
                        'action': 'GROUP_TP',
                        'pnl': profit,
                        'pnl_pct': pnl_pct
                    })
                    
                    position = None
                    continue
                
                # 追踪止盈
                if position['max_profit'] >= self.trailing_start * 100:
                    drawdown = position['max_profit'] - pnl_pct
                    if drawdown >= self.trailing_stop * 100:
                        profit = position['margin'] * pnl_pct / 100 / self.leverage
                        self.balance += profit
                        self.stats['winning_trades'] += 1
                        self.stats['total_pnl'] += profit
                        current_consecutive_losses = 0
                        
                        self.trades.append({
                            'time': timestamp,
                            'action': 'TRAILING_TP',
                            'pnl': profit,
                            'pnl_pct': pnl_pct
                        })
                        
                        position = None
                        continue
                
                # 网格止盈（简化版）
                if i % 48 == 0:  # 每2天检查一次网格
                    if pnl_pct > 2:  # 简化网格止盈
                        profit = position['margin'] * 0.5 * pnl_pct / 100 / self.leverage
                        self.balance += profit
                        self.stats['grid_tp_count'] += 1
                        
                        self.trades.append({
                            'time': timestamp,
                            'action': 'GRID_TP',
                            'pnl': profit,
                            'pnl_pct': pnl_pct * 0.5
                        })
                
                # DCA补仓检查
                if len(position.get('dca_levels', [])) < self.max_dca_count:
                    last_price = position['dca_levels'][-1] if position.get('dca_levels') else entry
                    dca_idx = len(position.get('dca_levels', []))
                    fib_mult = self.dca_fib[dca_idx] * (self.dca_accelerator if dca_idx == 2 else 1)
                    
                    price_drop = (last_price - current) / last_price if side == 'LONG' else (current - last_price) / last_price
                    
                    if price_drop > 0.05 * fib_mult:  # 5% * fib
                        dca_margin = position['margin'] * 0.3 * fib_mult
                        if self.balance > dca_margin:
                            self.balance -= dca_margin
                            position['margin'] += dca_margin
                            position.setdefault('dca_levels', []).append(current)
                            self.stats['dca_count'] += 1
            
            # 新开仓
            else:
                # 强信号豁免
                action = None
                confidence = 0
                
                if long_count >= 1 and any('Perfect Long' in s for s in signal_details):
                    action = 'LONG'
                    confidence = self.perfect_confidence
                elif short_count >= 1 and any('Perfect Short' in s for s in signal_details):
                    action = 'SHORT'
                    confidence = self.perfect_confidence
                elif long_count >= 2:
                    action = 'LONG'
                    confidence = 0.45 + 0.15 * (long_count - 1)
                elif short_count >= 2:
                    action = 'SHORT'
                    confidence = 0.45 + 0.15 * (short_count - 1)
                
                if action and confidence >= self.confidence_threshold:
                    margin = self.balance * 0.08  # 8%保证金
                    if margin > 10:  # 最小仓位
                        self.balance -= margin
                        
                        position = {
                            'side': action,
                            'entry_price': row['close'],
                            'margin': margin,
                            'max_profit': 0,
                            'entry_time': timestamp,
                            'dca_levels': [row['close']]
                        }
                        
                        self.stats['total_trades'] += 1
            
            # 更新权益
            equity = self.balance
            if position:
                equity += position['margin']
                if position['side'] == 'LONG':
                    equity += position['margin'] * (row['close'] - position['entry_price']) / position['entry_price'] * self.leverage
                else:
                    equity += position['margin'] * (position['entry_price'] - row['close']) / position['entry_price'] * self.leverage
            
            self.equity_curve.append({'time': timestamp, 'equity': equity})
            
            # 更新最大回撤
            if equity > self.stats['max_equity']:
                self.stats['max_equity'] = equity
            
            drawdown = (self.stats['max_equity'] - equity) / self.stats['max_equity']
            if drawdown > self.stats['max_drawdown']:
                self.stats['max_drawdown'] = drawdown
        
        # 平仓所有持仓
        if position:
            current = df['close'].iloc[-1]
            entry = position['entry_price']
            side = position['side']
            
            if side == 'LONG':
                pnl_pct = (current - entry) / entry * self.leverage
            else:
                pnl_pct = (entry - current) / entry * self.leverage
            
            profit = position['margin'] * pnl_pct / 100 / self.leverage
            self.balance += profit
            self.stats['total_pnl'] += profit
            
            if pnl_pct > 0:
                self.stats['winning_trades'] += 1
            else:
                self.stats['losing_trades'] += 1
        
        self.stats['max_consecutive_losses'] = max_consecutive_losses
        
        return self.generate_report(df)
    
    def generate_report(self, df: pd.DataFrame) -> Dict:
        """生成回测报告"""
        total_return = (self.balance - self.initial_balance) / self.initial_balance * 100
        
        start_time = df['timestamp'].iloc[0]
        end_time = df['timestamp'].iloc[-1]
        years = (end_time - start_time).days / 365.25
        
        annual_return = ((self.balance / self.initial_balance) ** (1/years) - 1) * 100 if years > 0 else 0
        
        # 夏普比率
        if len(self.equity_curve) > 1:
            equity_values = [e['equity'] for e in self.equity_curve]
            returns = pd.Series(equity_values).pct_change().dropna()
            sharpe = (returns.mean() / returns.std()) * np.sqrt(252 * 24) if returns.std() != 0 else 0
        else:
            sharpe = 0
        
        win_rate = (self.stats['winning_trades'] / 
                   (self.stats['winning_trades'] + self.stats['losing_trades']) * 100 
                   if (self.stats['winning_trades'] + self.stats['losing_trades']) > 0 else 0)
        
        report = {
            'initial_balance': self.initial_balance,
            'final_balance': self.balance,
            'total_return_pct': total_return,
            'annual_return_pct': annual_return,
            'max_drawdown_pct': self.stats['max_drawdown'] * 100,
            'sharpe_ratio': sharpe,
            'total_trades': self.stats['total_trades'],
            'winning_trades': self.stats['winning_trades'],
            'losing_trades': self.stats['losing_trades'],
            'win_rate': win_rate,
            'liquidations': self.stats['liquidations'],
            'dca_count': self.stats['dca_count'],
            'grid_tp_count': self.stats['grid_tp_count'],
            'total_pnl': self.stats['total_pnl'],
            'max_consecutive_losses': self.stats['max_consecutive_losses'],
            'trading_period_years': years
        }
        
        return report


def print_report(report: Dict):
    """打印详细回测报告"""
    print("\n" + "="*80)
    print("📊 V2.5-Hybrid 模拟回测报告（2年数据）")
    print("="*80)
    
    print(f"\n💰 资金表现:")
    print(f"  初始资金: ${report['initial_balance']:.2f}")
    print(f"  最终资金: ${report['final_balance']:.2f}")
    print(f"  总收益率: {report['total_return_pct']:+.2f}%")
    print(f"  年化收益率: {report['annual_return_pct']:+.2f}%")
    print(f"  月均收益: {report['annual_return_pct']/12:+.2f}%")
    
    print(f"\n📉 风险指标:")
    print(f"  最大回撤: {report['max_drawdown_pct']:.2f}%")
    print(f"  夏普比率: {report['sharpe_ratio']:.2f}")
    print(f"  连续最大亏损: {report['max_consecutive_losses']} 次")
    
    print(f"\n🎯 交易统计:")
    print(f"  总交易次数: {report['total_trades']}")
    print(f"  盈利次数: {report['winning_trades']}")
    print(f"  亏损次数: {report['losing_trades']}")
    print(f"  胜率: {report['win_rate']:.2f}%")
    print(f"  盈亏比: {report['total_pnl']/abs(report['total_pnl'] - report['final_balance'] + report['initial_balance']):.2f}")
    
    print(f"\n⚠️  风险事件:")
    print(f"  💥 爆仓次数: {report['liquidations']}")
    print(f"  🔄 DCA补仓次数: {report['dca_count']}")
    print(f"  🎯 网格止盈次数: {report['grid_tp_count']}")
    
    print(f"\n📅 回测期间: {report['trading_period_years']:.2f} 年")
    
    # 风险评估
    print("\n🔍 风险评估:")
    
    if report['liquidations'] > 0:
        print(f"  ❌ 警告: 发生 {report['liquidations']} 次爆仓！")
        print(f"     风险等级: 高")
        print(f"     建议: 降低杠杆至3x或收紧止损至3%")
    else:
        print(f"  ✅ 无爆仓，风控良好")
    
    if report['max_drawdown_pct'] > 25:
        print(f"  ❌ 最大回撤 {report['max_drawdown_pct']:.1f}% 过高")
        print(f"     风险等级: 高")
        print(f"     建议: 减少仓位或降低杠杆")
    elif report['max_drawdown_pct'] > 15:
        print(f"  ⚠️  最大回撤 {report['max_drawdown_pct']:.1f}% 中等")
        print(f"     风险等级: 中等")
        print(f"     建议: 可接受，但需监控")
    else:
        print(f"  ✅ 最大回撤 {report['max_drawdown_pct']:.1f}% 优秀")
    
    if report['annual_return_pct'] > 100 and report['max_drawdown_pct'] < 20:
        print(f"  ✅ 收益风险比优秀!")
        print(f"     Calmar比率: {report['annual_return_pct'] / report['max_drawdown_pct']:.2f}")
    elif report['annual_return_pct'] > 50:
        print(f"  ✅ 收益表现良好")
    else:
        print(f"  ⚠️  收益偏低")
    
    # 策略健康度
    print(f"\n📊 策略健康度:")
    health_score = 0
    
    if report['liquidations'] == 0:
        health_score += 30
        print(f"  风控安全: +30分")
    elif report['liquidations'] <= 2:
        health_score += 15
        print(f"  风控可接受: +15分")
    
    if report['max_drawdown_pct'] < 15:
        health_score += 25
        print(f"  回撤控制优秀: +25分")
    elif report['max_drawdown_pct'] < 25:
        health_score += 15
        print(f"  回撤控制良好: +15分")
    
    if report['win_rate'] > 60:
        health_score += 20
        print(f"  胜率优秀: +20分")
    elif report['win_rate'] > 50:
        health_score += 10
        print(f"  胜率良好: +10分")
    
    if report['sharpe_ratio'] > 1.5:
        health_score += 15
        print(f"  夏普比率优秀: +15分")