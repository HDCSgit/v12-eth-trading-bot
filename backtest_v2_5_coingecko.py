#!/usr/bin/env python3
"""
V2.5-Hybrid 回测系统 - 适配CoinGecko数据格式
使用已有eth_usdt_1h.csv（2015-2026，10年历史）
"""

import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


class V2_5BacktestEngine:
    """V2.5回测引擎"""
    
    def __init__(self, initial_balance: float = 1000.0, leverage: int = 5):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.leverage = leverage
        
        # 统计
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
        
        self.position = None
        self.trades = []
        self.equity_curve = []
        
        # V2.5参数（优化版）
        self.confidence_threshold = 0.55
        self.perfect_confidence = 0.88
        
        # 网格/DCA参数
        self.grid_atr_multiplier = 1.4
        self.max_dca_count = 3
        self.dca_fib = [1.0, 1.618, 2.618]
        
        # 止盈止损
        self.stop_loss_pct = -0.05
        self.trailing_start = 0.06
        self.trailing_stop = 0.03
        self.group_tp = 0.08
        
        logger.info("=" * 80)
        logger.info("V2.5-Hybrid 回测引擎初始化")
        logger.info(f"初始资金: ${initial_balance}, 杠杆: {leverage}x")
        logger.info("=" * 80)
    
    def load_and_prepare_data(self, filepath: str) -> pd.DataFrame:
        """加载币安数据（支持eth_usdt_1h_binance.csv格式）"""
        logger.info(f"\n加载数据: {filepath}")
        
        df = pd.read_csv(filepath)
        
        # 检查数据格式
        if 'timestamp' in df.columns:
            # 币安格式
            df['timestamp'] = pd.to_datetime(df['timestamp'])
        elif 'snapped_at' in df.columns:
            # CoinGecko格式
            df['timestamp'] = pd.to_datetime(df['snapped_at'])
            df['close'] = df['price']
            df['open'] = df['close'].shift(1)
            df.loc[0, 'open'] = df.loc[0, 'close'] * 0.99
            df['high'] = df['close'] * 1.01
            df['low'] = df['close'] * 0.99
            df['volume'] = df['total_volume']
        
        df = df.sort_values('timestamp').reset_index(drop=True)
        
        # 只保留2024年以后的数据
        start_date = datetime(2024, 1, 1)
        df = df[df['timestamp'] >= start_date].reset_index(drop=True)
        
        logger.info(f"数据时间范围: {df['timestamp'].min()} 到 {df['timestamp'].max()}")
        logger.info(f"数据条数: {len(df)}")
        logger.info(f"价格范围: ${df['close'].min():.0f} - ${df['close'].max():.0f}")
        logger.info(f"数据类型: 币安1小时K线" if 'trades' in df.columns else "CoinGecko日线")
        
        return self.calculate_indicators(df)
    
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算技术指标"""
        # 均线
        df['ma20'] = df['close'].rolling(20, min_periods=1).mean()
        df['ma55'] = df['close'].rolling(55, min_periods=1).mean()
        df['ma200'] = df['close'].rolling(200, min_periods=1).mean()
        
        # 趋势
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
        df['volume_spike'] = df['volume_ratio'] > 1.5
        
        # 价格变化
        df['price_change_5m'] = df['close'].pct_change(5) * 100
        df['price_change_15m'] = df['close'].pct_change(15) * 100
        
        return df.dropna()
    
    def calculate_signals(self, row, prev) -> Tuple[int, int, List[str]]:
        """计算信号（V2.5优化版逻辑）"""
        long_signals = []
        short_signals = []
        
        trend = row['trend']
        trend_short = row['trend_short']
        rsi = row['rsi']
        macd = row['macd']
        macd_signal = row['macd_signal']
        macd_hist = row['macd_hist']
        
        # MACD交叉
        macd_cross_up = (macd > macd_signal) and (prev['macd'] <= prev['macd_signal'])
        macd_cross_down = (macd < macd_signal) and (prev['macd'] >= prev['macd_signal'])
        
        volume_ratio = row['volume_ratio']
        volume_spike = row['volume_spike']
        bb_width = row['bb_width']
        bb_position = row['bb_position']
        price_change_5m = row['price_change_5m']
        
        # ===== 多头信号 =====
        if (trend == 1 and rsi < 45 and macd_cross_up and volume_spike and bb_width < 0.05):
            long_signals.append('Perfect Long (90%)')
        
        if (trend == 1 and rsi < 40 and macd > macd_signal and price_change_5m > -2):
            long_signals.append('Trend Follow Long (75%)')
        
        if (macd_cross_up and volume_ratio > 1.2 and rsi < 60 and trend_short == 1):
            long_signals.append('MACD Cross Long (70%)')
        
        if (bb_position < 0.15 and rsi < 50 and macd_hist > 0 and trend >= 0):
            long_signals.append('BB Bounce Long (65%)')
        
        if (rsi < 35 and macd_hist > 0):
            long_signals.append('Oversold Bounce (60%)')
        
        # ===== 空头信号 =====
        if (trend == -1 and rsi > 55 and macd_cross_down and volume_spike and bb_width < 0.05):
            short_signals.append('Perfect Short (88%)')
        
        if (trend == -1 and rsi > 60 and macd < macd_signal and price_change_5m < 2):
            short_signals.append('Trend Follow Short (73%)')
        
        if (macd_cross_down and volume_ratio > 1.2 and rsi > 40 and trend_short == -1):
            short_signals.append('MACD Cross Short (68%)')
        
        if (bb_position > 0.85 and rsi > 50 and macd_hist < 0 and trend <= 0):
            short_signals.append('BB Reject Short (63%)')
        
        if (rsi > 65 and macd_hist < 0):
            short_signals.append('Overbought Drop (58%)')
        
        return len(long_signals), len(short_signals), long_signals + short_signals
    
    def should_open_position(self, long_count: int, short_count: int, signal_details: List[str]) -> Tuple[str, float, str]:
        """V2.5频率优化版 - 单/双信号混合"""
        # 1. Perfect信号（90%）单信号直接开仓
        if long_count >= 1 and any('Perfect Long' in s for s in signal_details):
            return 'BUY', 0.88, 'Perfect Long (单信号豁免)'
        if short_count >= 1 and any('Perfect Short' in s for s in signal_details):
            return 'SELL', 0.86, 'Perfect Short (单信号豁免)'
        
        # 2. Trend Follow / MACD Cross（75%）单信号可开仓
        if long_count >= 1 and any('Trend Follow' in s or 'MACD Cross' in s for s in signal_details):
            return 'BUY', 0.72, 'Trend/MACD Single Signal (单信号豁免)'
        if short_count >= 1 and any('Trend Follow' in s or 'MACD Cross' in s for s in signal_details):
            return 'SELL', 0.70, 'Trend/MACD Single Signal (单信号豁免)'
        
        # 3. 双信号（保守网）
        if long_count >= 2:
            confidence = 0.55 + 0.10 * (long_count - 2)
            return 'BUY', min(confidence, 0.85), f'Multi-Signal Long ({long_count})'
        if short_count >= 2:
            confidence = 0.53 + 0.10 * (short_count - 2)
            return 'SELL', min(confidence, 0.83), f'Multi-Signal Short ({short_count})'
        
        return 'HOLD', 0.0, 'No valid signals'
    
    def run_backtest(self, df: pd.DataFrame) -> Dict:
        """运行回测"""
        logger.info("\n" + "=" * 80)
        logger.info("开始回测...")
        logger.info("=" * 80)
        
        position = None
        max_consecutive_losses = 0
        current_consecutive_losses = 0
        
        for i in range(200, len(df)):
            row = df.iloc[i]
            prev = df.iloc[i-1]
            timestamp = row['timestamp']
            
            long_count, short_count, signal_details = self.calculate_signals(row, prev)
            
            # 持仓管理
            if position:
                entry = position['entry_price']
                current = row['close']
                side = position['side']
                
                # 计算盈亏百分比（杠杆后）
                if side == 'LONG':
                    pnl_pct = (current - entry) / entry * self.leverage * 100
                else:
                    pnl_pct = (entry - current) / entry * self.leverage * 100
                
                # 更新最高盈利
                if pnl_pct > position['max_profit']:
                    position['max_profit'] = pnl_pct
                
                # 爆仓检查（5x杠杆，-20%）
                if pnl_pct <= -20:
                    loss = position['margin'] * 0.9
                    self.balance += position['margin'] * 0.1
                    self.stats['liquidations'] += 1
                    self.stats['losing_trades'] += 1
                    self.stats['total_pnl'] -= loss
                    
                    current_consecutive_losses += 1
                    max_consecutive_losses = max(max_consecutive_losses, current_consecutive_losses)
                    
                    self.trades.append({
                        'time': timestamp,
                        'action': 'LIQUIDATION',
                        'pnl': -loss,
                        'pnl_pct': -90,
                        'price': current
                    })
                    
                    position = None
                    continue
                
                # 止损（-5%）
                if pnl_pct <= self.stop_loss_pct * 100:
                    loss = position['margin'] * abs(self.stop_loss_pct)
                    self.balance += position['margin'] - loss
                    self.stats['losing_trades'] += 1
                    self.stats['total_pnl'] -= loss
                    
                    current_consecutive_losses += 1
                    max_consecutive_losses = max(max_consecutive_losses, current_consecutive_losses)
                    
                    self.trades.append({
                        'time': timestamp,
                        'action': 'STOP_LOSS',
                        'pnl': -loss,
                        'pnl_pct': pnl_pct,
                        'price': current
                    })
                    
                    position = None
                    continue
                
                # 整组止盈（8%）
                if pnl_pct >= self.group_tp * 100:
                    profit = position['margin'] * self.group_tp
                    self.balance += position['margin'] + profit
                    self.stats['winning_trades'] += 1
                    self.stats['total_pnl'] += profit
                    current_consecutive_losses = 0
                    
                    self.trades.append({
                        'time': timestamp,
                        'action': 'GROUP_TP',
                        'pnl': profit,
                        'pnl_pct': pnl_pct,
                        'price': current
                    })
                    
                    position = None
                    continue
                
                # 追踪止盈
                if position['max_profit'] >= self.trailing_start * 100:
                    drawdown = position['max_profit'] - pnl_pct
                    if drawdown >= self.trailing_stop * 100:
                        profit = position['margin'] * (pnl_pct / 100)
                        self.balance += position['margin'] + profit
                        self.stats['winning_trades'] += 1
                        self.stats['total_pnl'] += profit
                        current_consecutive_losses = 0
                        
                        self.trades.append({
                            'time': timestamp,
                            'action': 'TRAILING_TP',
                            'pnl': profit,
                            'pnl_pct': pnl_pct,
                            'price': current
                        })
                        
                        position = None
                        continue
                
                # 网格止盈（简化：持仓3天以上且盈利>2%）
                days_held = (timestamp - position['entry_time']).days
                if days_held >= 3 and pnl_pct > 2 and not position.get('grid_closed', False):
                    profit = position['margin'] * 0.3  # 止盈30%
                    self.balance += profit
                    position['margin'] -= profit
                    position['grid_closed'] = True
                    self.stats['grid_tp_count'] += 1
                    
                    self.trades.append({
                        'time': timestamp,
                        'action': 'GRID_TP',
                        'pnl': profit,
                        'pnl_pct': pnl_pct * 0.3,
                        'price': current
                    })
                
                # DCA补仓
                if len(position.get('dca_levels', [])) < self.max_dca_count:
                    last_price = position['dca_levels'][-1] if position.get('dca_levels') else entry
                    dca_idx = len(position.get('dca_levels', []))
                    fib_mult = self.dca_fib[dca_idx] * (self.dca_accelerator if dca_idx == 2 else 1)
                    
                    if side == 'LONG':
                        price_drop = (last_price - current) / last_price
                    else:
                        price_drop = (current - last_price) / last_price
                    
                    if price_drop > 0.05 * fib_mult:  # 5% * fib
                        dca_margin = self.balance * 0.05 * fib_mult  # 使用5%可用资金
                        if dca_margin > 10 and self.balance > dca_margin:
                            self.balance -= dca_margin
                            position['margin'] += dca_margin
                            position.setdefault('dca_levels', []).append(current)
                            self.stats['dca_count'] += 1
            
            # 新开仓
            else:
                action, confidence, reason = self.should_open_position(long_count, short_count, signal_details)
                
                if action != 'HOLD':
                    margin = self.balance * 0.08  # 8%保证金
                    if margin > 10:
                        self.balance -= margin
                        
                        position = {
                            'side': 'LONG' if action == 'BUY' else 'SHORT',
                            'entry_price': row['close'],
                            'margin': margin,
                            'max_profit': 0,
                            'entry_time': timestamp,
                            'dca_levels': [row['close']]
                        }
                        
                        self.stats['total_trades'] += 1
            
            # 更新权益曲线
            equity = self.balance
            if position:
                equity += position['margin']
                if position['side'] == 'LONG':
                    unrealized = position['margin'] * (row['close'] - position['entry_price']) / position['entry_price'] * self.leverage
                else:
                    unrealized = position['margin'] * (position['entry_price'] - row['close']) / position['entry_price'] * self.leverage
                equity += unrealized
            
            self.equity_curve.append({'time': timestamp, 'equity': equity})
            
            # 更新最大回撤
            if equity > self.stats['max_equity']:
                self.stats['max_equity'] = equity
            
            drawdown = (self.stats['max_equity'] - equity) / self.stats['max_equity']
            if drawdown > self.stats['max_drawdown']:
                self.stats['max_drawdown'] = drawdown
        
        # 平仓剩余持仓
        if position:
            current = df['close'].iloc[-1]
            entry = position['entry_price']
            side = position['side']
            
            if side == 'LONG':
                pnl_pct = (current - entry) / entry * self.leverage * 100
            else:
                pnl_pct = (entry - current) / entry * self.leverage * 100
            
            unrealized = position['margin'] * (pnl_pct / 100)
            self.balance += position['margin'] + unrealized
            self.stats['total_pnl'] += unrealized
            
            if pnl_pct > 0:
                self.stats['winning_trades'] += 1
            else:
                self.stats['losing_trades'] += 1
        
        self.stats['max_consecutive_losses'] = max_consecutive_losses
        
        return self.generate_report(df)
    
    def generate_report(self, df: pd.DataFrame) -> Dict:
        """生成回测报告"""
        total_return = (self.balance - self.initial_balance) / self.initial_balance * 100
        
        start_time = df['timestamp'].iloc[200]  # 从第200条开始
        end_time = df['timestamp'].iloc[-1]
        years = (end_time - start_time).days / 365.25
        
        annual_return = ((self.balance / self.initial_balance) ** (1/years) - 1) * 100 if years > 0 else 0
        
        # 夏普比率
        if len(self.equity_curve) > 1:
            equity_values = [e['equity'] for e in self.equity_curve]
            returns = pd.Series(equity_values).pct_change().dropna()
            sharpe = (returns.mean() / returns.std()) * np.sqrt(365) if returns.std() != 0 else 0
        else:
            sharpe = 0
        
        win_rate = (self.stats['winning_trades'] / 
                   (self.stats['winning_trades'] + self.stats['losing_trades']) * 100 
                   if (self.stats['winning_trades'] + self.stats['losing_trades']) > 0 else 0)
        
        # 盈亏比
        total_profit = sum([t['pnl'] for t in self.trades if t['pnl'] > 0])
        total_loss = abs(sum([t['pnl'] for t in self.trades if t['pnl'] < 0]))
        profit_factor = total_profit / total_loss if total_loss > 0 else 0
        
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
            'profit_factor': profit_factor,
            'liquidations': self.stats['liquidations'],
            'dca_count': self.stats['dca_count'],
            'grid_tp_count': self.stats['grid_tp_count'],
            'total_pnl': self.stats['total_pnl'],
            'max_consecutive_losses': self.stats['max_consecutive_losses'],
            'trading_period_years': years
        }
        
        return report


def print_report(report: Dict):
    """打印详细报告"""
    print("\n" + "=" * 80)
    print("📊 V2.5-Hybrid 回测报告（2年数据）")
    print("=" * 80)
    
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
    print(f"  盈亏比: {report['profit_factor']:.2f}")
    
    print(f"\n⚠️  风险事件:")
    print(f"  💥 爆仓次数: {report['liquidations']}")
    print(f"  🔄 DCA补仓次数: {report['dca_count']}")
    print(f"  🎯 网格止盈次数: {report['grid_tp_count']}")
    
    print(f"\n📅 回测期间: {report['trading_period_years']:.2f} 年")
    
    # 风险评估
    print("\n🔍 风险评估:")
    
    risk_level = "低"
    if report['liquidations'] > 2 or report['max_drawdown_pct'] > 30:
        risk_level = "高"
        print(f"  ❌ 风险等级: {risk_level}")
    elif report['liquidations'] > 0 or report['max_drawdown_pct'] > 20:
        risk_level = "中"
        print(f"  ⚠️  风险等级: {risk_level}")
    else:
        print(f"  ✅ 风险等级: {risk_level}")
    
    if report['liquidations'] > 0:
        print(f"  ⚠️  爆仓 {report['liquidations']} 次 - 建议降低杠杆")
    
    if report['max_drawdown_pct'] > 25:
        print(f"  ❌ 最大回撤 {report['max_drawdown_pct']:.1f}% - 建议收紧止损")
    elif report['max_drawdown_pct'] > 15:
        print(f"  ⚠️  最大回撤 {report['max_drawdown_pct']:.1f}% - 可接受范围")
    else:
        print(f"  ✅ 最大回撤 {report['max_drawdown_pct']:.1f}% - 优秀")
    
    # 收益评价
    if report['annual_return_pct'] > 100 and report['max_drawdown_pct'] < 20:
        print(f"  ✅ 收益风险比优秀 (Calmar: {report['annual_return_pct']/report['max_drawdown_pct']:.1f})")
    elif report['annual_return_pct'] > 50:
        print(f"  ✅ 收益表现良好")
    elif report['annual_return_pct'] > 0:
        print(f"  ⚠️  收益偏低")
    else:
        print(f"  ❌ 策略亏损")
    
    # 综合评分
    print(f"\n📊 综合评分:")
    score = 0
    if report['liquidations'] == 0: score += 30
    elif report['liquidations'] <= 2: score += 15
    
    if report['max_drawdown_pct'] < 15: score += 25
    elif report['max_drawdown_pct'] < 25: score += 15
    
    if report['win_rate'] > 60: score += 20
    elif report['win_rate'] > 50: score += 10
    
    if report['sharpe_ratio'] > 1.5: score += 15
    elif report['sharpe_ratio'] > 1.0: score += 10
    
    if report['annual_return_pct'] > 100: score += 10
    elif report['annual_return_pct'] > 50: score += 5
    
    print(f"  策略健康度: {score}/100 分")
    
    if score >= 80:
        print(f"  🟢 评级: 优秀 - 可用于实盘")
    elif score >= 60:
        print(f"  🟡 评级: 良好 - 需优化后使用")
    elif score >= 40:
        print(f"  🟠 评级: 一般 - 建议改进")
    else:
        print(f"  🔴 评级: 差 - 不建议使用")
    
    print("\n" + "=" * 80)


def main():
    # 创建回测引擎
    engine = V2_5BacktestEngine(initial_balance=1000.0, leverage=5)
    
    # 加载币安数据
    df = engine.load_and_prepare_data('eth_usdt_1h_binance.csv')
    
    # 运行回测
    report = engine.run_backtest(df)
    
    # 打印报告
    print_report(report)
    
    # 保存结果
    import json
    with open('v2_5_backtest_report.json', 'w') as f:
        json.dump(report, f, indent=2, default=str)
    
    print("\n📄 详细报告已保存: v2_5_backtest_report.json")


if __name__ == "__main__":
    main()