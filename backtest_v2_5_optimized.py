#!/usr/bin/env python3
"""
V2.5-Hybrid 优化版回测
目标：爆仓=0，胜率>60%，盈利>亏损
"""

import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


class V2_5OptimizedEngine:
    """V2.5优化版回测引擎"""
    
    def __init__(self, initial_balance: float = 1000.0):
        # ========== 核心优化1：降低杠杆防爆仓 ==========
        self.leverage = 3  # 5x → 3x，爆仓线从-20%降到-33%
        
        self.initial_balance = initial_balance
        self.balance = initial_balance
        
        # 风控：最大回撤15%停止交易
        self.max_portfolio_drawdown = 0.15
        self.daily_loss_limit = 0.10  # 日亏损10%停止
        self.daily_loss = 0
        
        # 统计
        self.stats = {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'liquidations': 0,
            'dca_count': 0,
            'grid_tp_count': 0,
            'max_consecutive_losses': 0,
            'stopped_by_drawdown': False
        }
        
        self.position = None
        self.trades = []
        self.equity_curve = []
        self.daily_equity = {}  # 记录每日权益
        
        # ========== 核心优化2：严格信号过滤 ==========
        self.min_signals = 2  # 最少2个信号才开仓（Perfect除外）
        self.use_adx_filter = True  # ADX趋势强度过滤
        self.adx_threshold = 20  # ADX>20才认为是趋势（放宽）
        
        # ========== 核心优化3：改进止盈止损 ==========
        self.stop_loss_pct = 0.03  # 3%止损（3x杠杆=-9%，远离-33%爆仓线）
        self.take_profit_1 = 0.06  # 第一目标6%
        self.take_profit_2 = 0.12  # 第二目标12%
        self.trailing_start = 0.08  # 8%启动追踪止盈
        self.trailing_stop = 0.04   # 回撤4%止盈
        
        # DCA参数优化
        self.max_dca_count = 3
        self.dca_fib = [1.0, 1.5, 2.0]  # 更保守的补仓
        self.dca_trigger = 0.03  # 跌3%触发第一次补仓
        
        logger.info("=" * 80)
        logger.info("V2.5-Hybrid 优化版回测引擎")
        logger.info(f"杠杆: {self.leverage}x (爆仓线-33%，安全垫充足)")
        logger.info(f"止损: {self.stop_loss_pct*100}% (实际最大亏损{self.stop_loss_pct*self.leverage*100}%)")
        logger.info("=" * 80)
    
    def calculate_adx(self, df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """计算ADX趋势强度"""
        # +DM和-DM
        df['plus_dm'] = np.where(
            (df['high'] - df['high'].shift(1)) > (df['low'].shift(1) - df['low']),
            np.maximum(df['high'] - df['high'].shift(1), 0),
            0
        )
        df['minus_dm'] = np.where(
            (df['low'].shift(1) - df['low']) > (df['high'] - df['high'].shift(1)),
            np.maximum(df['low'].shift(1) - df['low'], 0),
            0
        )
        
        # TR
        df['tr'] = np.maximum(
            df['high'] - df['low'],
            np.maximum(
                np.abs(df['high'] - df['close'].shift(1)),
                np.abs(df['low'] - df['close'].shift(1))
            )
        )
        
        # 平滑
        df['+di'] = 100 * df['plus_dm'].rolling(period).mean() / df['tr'].rolling(period).mean()
        df['-di'] = 100 * df['minus_dm'].rolling(period).mean() / df['tr'].rolling(period).mean()
        
        # DX和ADX
        df['dx'] = 100 * np.abs(df['+di'] - df['-di']) / (df['+di'] + df['-di'] + 1e-10)
        df['adx'] = df['dx'].rolling(period).mean()
        
        return df
    
    def load_and_prepare_data(self, filepath: str) -> pd.DataFrame:
        """加载数据"""
        logger.info(f"\n加载数据: {filepath}")
        
        df = pd.read_csv(filepath)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp').reset_index(drop=True)
        
        # 只保留2024年以后
        start_date = datetime(2024, 1, 1)
        df = df[df['timestamp'] >= start_date].reset_index(drop=True)
        
        # 计算指标
        df = self.calculate_indicators(df)
        df = self.calculate_adx(df)
        
        logger.info(f"数据条数: {len(df)}")
        logger.info(f"价格范围: ${df['close'].min():.0f} - ${df['close'].max():.0f}")
        
        return df.dropna()
    
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
        df['rsi'] = 100 - 100 / (1 + gain / (loss + 1e-10))
        
        # MACD
        ema12 = df['close'].ewm(span=12, min_periods=1).mean()
        ema26 = df['close'].ewm(span=26, min_periods=1).mean()
        df['macd'] = ema12 - ema26
        df['macd_signal'] = df['macd'].ewm(span=9, min_periods=1).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']
        
        # ATR
        tr = pd.concat([
            df['high'] - df['low'],
            np.abs(df['high'] - df['close'].shift()),
            np.abs(df['low'] - df['close'].shift())
        ], axis=1).max(axis=1)
        df['atr'] = tr.rolling(14, min_periods=1).mean()
        df['atr_pct'] = df['atr'] / df['close'] * 100
        
        # 布林带
        df['bb_mid'] = df['close'].rolling(20, min_periods=1).mean()
        df['bb_std'] = df['close'].rolling(20, min_periods=1).std()
        df['bb_upper'] = df['bb_mid'] + 2 * df['bb_std']
        df['bb_lower'] = df['bb_mid'] - 2 * df['bb_std']
        df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'] + 1e-10)
        
        # 量能
        df['volume_ma'] = df['volume'].rolling(30, min_periods=1).mean()
        df['volume_ratio'] = df['volume'] / (df['volume_ma'] + 1e-10)
        
        return df
    
    def calculate_signals(self, row, prev) -> Tuple[int, int, List[str], bool]:
        """
        计算信号（优化版）
        返回: (多头信号数, 空头信号数, 信号详情, 是否趋势强劲)
        """
        long_signals = []
        short_signals = []
        
        trend = row['trend']
        trend_short = row['trend_short']
        rsi = row['rsi']
        macd = row['macd']
        macd_signal = row['macd_signal']
        macd_hist = row['macd_hist']
        adx = row.get('adx', 0)
        
        # 趋势强度判断
        is_trending = adx > self.adx_threshold
        
        macd_cross_up = (macd > macd_signal) and (prev['macd'] <= prev['macd_signal'])
        macd_cross_down = (macd < macd_signal) and (prev['macd'] >= prev['macd_signal'])
        
        volume_ratio = row['volume_ratio']
        bb_position = row['bb_position']
        
        # ========== 多头信号（提高门槛）==========
        # Perfect信号：需要趋势确认
        if (trend == 1 and rsi < 40 and macd_cross_up and 
            volume_ratio > 1.5 and is_trending):
            long_signals.append('Perfect Long (95%)')
        
        # Trend Follow：需要ADX确认趋势
        if (trend == 1 and rsi < 35 and macd > macd_signal and 
            macd_hist > 0 and is_trending):
            long_signals.append('Trend Follow Long (80%)')
        
        # MACD Cross：需要量能配合
        if (macd_cross_up and volume_ratio > 1.5 and 
            rsi < 55 and trend_short == 1):
            long_signals.append('MACD Cross Long (75%)')
        
        # 超卖反弹：需要背离信号
        if (rsi < 30 and macd_hist > 0 and trend == 1):
            long_signals.append('Oversold Bounce (70%)')
        
        # ========== 空头信号 ==========
        if (trend == -1 and rsi > 60 and macd_cross_down and 
            volume_ratio > 1.5 and is_trending):
            short_signals.append('Perfect Short (93%)')
        
        if (trend == -1 and rsi > 65 and macd < macd_signal and 
            macd_hist < 0 and is_trending):
            short_signals.append('Trend Follow Short (78%)')
        
        if (macd_cross_down and volume_ratio > 1.5 and 
            rsi > 45 and trend_short == -1):
            short_signals.append('MACD Cross Short (73%)')
        
        if (rsi > 70 and macd_hist < 0 and trend == -1):
            short_signals.append('Overbought Drop (68%)')
        
        return len(long_signals), len(short_signals), long_signals + short_signals, is_trending
    
    def should_open_position(self, long_count, short_count, signal_details, is_trending):
        """开仓判断（优化版）"""
        # 无趋势不交易
        if not is_trending:
            return 'HOLD', 0, 'No trend (ADX too low)'
        
        # Perfect信号单信号可开（但已要求ADX）
        if long_count >= 1 and any('Perfect Long' in s for s in signal_details):
            return 'BUY', 0.90, 'Perfect Long'
        if short_count >= 1 and any('Perfect Short' in s for s in signal_details):
            return 'SELL', 0.88, 'Perfect Short'
        
        # 其他信号需要2个以上
        if long_count >= self.min_signals:
            confidence = 0.60 + 0.10 * (long_count - self.min_signals)
            return 'BUY', min(confidence, 0.85), f'Strong Long ({long_count} signals)'
        
        if short_count >= self.min_signals:
            confidence = 0.58 + 0.10 * (short_count - self.min_signals)
            return 'SELL', min(confidence, 0.83), f'Strong Short ({short_count} signals)'
        
        return 'HOLD', 0, 'Insufficient signals'
    
    def check_portfolio_stop(self, current_equity):
        """检查组合止损"""
        drawdown = (self.initial_balance - current_equity) / self.initial_balance
        if drawdown > self.max_portfolio_drawdown:
            return True, f"Portfolio drawdown {drawdown*100:.1f}% > limit"
        return False, ""
    
    def run_backtest(self, df: pd.DataFrame) -> Dict:
        """运行优化版回测"""
        logger.info("\n开始优化版回测...")
        
        position = None
        max_consecutive_losses = 0
        current_consecutive_losses = 0
        last_trade_day = None
        
        for i in range(200, len(df)):
            row = df.iloc[i]
            prev = df.iloc[i-1]
            timestamp = row['timestamp']
            current_price = row['close']
            
            # 日重置
            current_day = timestamp.date()
            if last_trade_day != current_day:
                self.daily_loss = 0
                last_trade_day = current_day
            
            # 组合止损检查
            if position is None:
                portfolio_dd = (self.initial_balance - self.balance) / self.initial_balance
                if portfolio_dd > self.max_portfolio_drawdown:
                    self.stats['stopped_by_drawdown'] = True
                    logger.warning(f"组合回撤超限 {portfolio_dd*100:.1f}%，停止交易")
                    break
            
            # 持仓管理
            if position:
                entry = position['entry_price']
                side = position['side']
                
                # 计算盈亏
                if side == 'LONG':
                    pnl_pct = (current_price - entry) / entry * self.leverage
                else:
                    pnl_pct = (entry - current_price) / entry * self.leverage
                
                # 更新最高盈利
                if pnl_pct > position['max_profit']:
                    position['max_profit'] = pnl_pct
                
                # ========== 爆仓检查（3x杠杆，-33%线）==========
                if pnl_pct <= -30:  # 接近爆仓
                    logger.error(f"⚠️ 接近爆仓！pnl={pnl_pct:.1f}%")
                
                if pnl_pct <= -33:
                    loss = position['margin'] * 0.95
                    self.balance += position['margin'] * 0.05
                    self.stats['liquidations'] += 1
                    self.daily_loss += loss
                    
                    self.trades.append({
                        'time': timestamp, 'action': 'LIQUIDATION',
                        'pnl': -loss, 'pnl_pct': -95
                    })
                    
                    position = None
                    current_consecutive_losses += 1
                    max_consecutive_losses = max(max_consecutive_losses, current_consecutive_losses)
                    continue
                
                # ========== 止损（3%）==========
                if pnl_pct <= -self.stop_loss_pct * self.leverage * 100:
                    loss = position['margin'] * self.stop_loss_pct * self.leverage
                    self.balance += position['margin'] - loss
                    self.stats['losing_trades'] += 1
                    self.daily_loss += loss
                    current_consecutive_losses += 1
                    max_consecutive_losses = max(max_consecutive_losses, current_consecutive_losses)
                    
                    self.trades.append({
                        'time': timestamp, 'action': 'STOP_LOSS',
                        'pnl': -loss, 'pnl_pct': pnl_pct
                    })
                    
                    position = None
                    continue
                
                # ========== 分级止盈 ==========
                # 第一目标6%
                if pnl_pct >= self.take_profit_1 * self.leverage * 100 and not position.get('tp1_hit'):
                    # 平仓50%
                    profit = position['margin'] * 0.5 * self.take_profit_1 * self.leverage
                    self.balance += profit
                    position['margin'] *= 0.5
                    position['tp1_hit'] = True
                    position['entry_price'] = current_price  # 更新成本
                    
                    self.stats['winning_trades'] += 0.5
                    current_consecutive_losses = 0
                    
                    self.trades.append({
                        'time': timestamp, 'action': 'TP1',
                        'pnl': profit, 'pnl_pct': pnl_pct
                    })
                
                # 第二目标12%或追踪止盈
                if position['tp1_hit']:
                    # 追踪止盈
                    if position['max_profit'] >= self.trailing_start * self.leverage * 100:
                        drawdown_from_max = position['max_profit'] - pnl_pct
                        if drawdown_from_max >= self.trailing_stop * self.leverage * 100:
                            # 剩余仓位止盈
                            profit = position['margin'] * (pnl_pct / 100)
                            self.balance += position['margin'] + profit
                            self.stats['winning_trades'] += 0.5
                            current_consecutive_losses = 0
                            
                            self.trades.append({
                                'time': timestamp, 'action': 'TRAILING_TP',
                                'pnl': profit, 'pnl_pct': pnl_pct
                            })
                            
                            position = None
                            continue
                    
                    # 第二目标
                    if pnl_pct >= self.take_profit_2 * self.leverage * 100:
                        profit = position['margin'] * self.take_profit_2 * self.leverage
                        self.balance += position['margin'] + profit
                        self.stats['winning_trades'] += 0.5
                        current_consecutive_losses = 0
                        
                        self.trades.append({
                            'time': timestamp, 'action': 'TP2',
                            'pnl': profit, 'pnl_pct': pnl_pct
                        })
                        
                        position = None
                        continue
                
                # ========== DCA补仓 ==========
                if len(position.get('dca_levels', [])) < self.max_dca_count:
                    last_entry = position['dca_levels'][-1]
                    price_drop = (last_entry - current_price) / last_entry if side == 'LONG' else (current_price - last_entry) / last_entry
                    
                    dca_idx = len(position['dca_levels'])
                    trigger_pct = self.dca_trigger * self.dca_fib[dca_idx]
                    
                    if price_drop > trigger_pct:
                        dca_margin = position['initial_margin'] * 0.5 * self.dca_fib[dca_idx]
                        if self.balance > dca_margin:
                            self.balance -= dca_margin
                            position['margin'] += dca_margin
                            position['dca_levels'].append(current_price)
                            
                            # 更新平均成本
                            total_cost = sum(p * m for p, m in zip(position['dca_levels'], 
                                                                     [position['initial_margin']] + [dca_margin]*dca_idx))
                            position['avg_price'] = total_cost / position['margin']
                            self.stats['dca_count'] += 1
            
            # 新开仓
            else:
                long_count, short_count, signal_details, is_trending = self.calculate_signals(row, prev)
                
                action, confidence, reason = self.should_open_position(
                    long_count, short_count, signal_details, is_trending
                )
                
                if action != 'HOLD':
                    # 日亏损限制
                    if self.daily_loss > self.initial_balance * self.daily_loss_limit:
                        continue
                    
                    margin = self.balance * 0.05  # 5%仓位（更保守）
                    if margin > 10:
                        self.balance -= margin
                        
                        position = {
                            'side': 'LONG' if action == 'BUY' else 'SHORT',
                            'entry_price': current_price,
                            'initial_margin': margin,
                            'margin': margin,
                            'max_profit': 0,
                            'entry_time': timestamp,
                            'dca_levels': [current_price],
                            'avg_price': current_price,
                            'tp1_hit': False
                        }
                        
                        self.stats['total_trades'] += 1
            
            # 更新权益
            equity = self.balance
            if position:
                if position['side'] == 'LONG':
                    unrealized = position['margin'] * (current_price - position['avg_price']) / position['avg_price'] * self.leverage
                else:
                    unrealized = position['margin'] * (position['avg_price'] - current_price) / position['avg_price'] * self.leverage
                equity += position['margin'] + unrealized
            
            self.equity_curve.append({'time': timestamp, 'equity': equity})
        
        # 平仓
        if position:
            entry = position['avg_price']
            if position['side'] == 'LONG':
                pnl_pct = (current_price - entry) / entry * self.leverage
            else:
                pnl_pct = (entry - current_price) / entry * self.leverage
            
            unrealized = position['margin'] * (pnl_pct / 100)
            self.balance += position['margin'] + unrealized
            
            if pnl_pct > 0:
                self.stats['winning_trades'] += 1
            else:
                self.stats['losing_trades'] += 1
        
        self.stats['max_consecutive_losses'] = max_consecutive_losses
        
        return self.generate_report(df)
    
    def generate_report(self, df):
        """生成报告"""
        total_return = (self.balance - self.initial_balance) / self.initial_balance * 100
        
        start_time = df['timestamp'].iloc[200]
        end_time = df['timestamp'].iloc[-1]
        years = (end_time - start_time).days / 365.25
        
        annual_return = ((self.balance / self.initial_balance) ** (1/years) - 1) * 100 if years > 0 else 0
        
        # 计算最大回撤
        max_dd = 0
        peak = self.initial_balance
        for eq in self.equity_curve:
            if eq['equity'] > peak:
                peak = eq['equity']
            dd = (peak - eq['equity']) / peak
            if dd > max_dd:
                max_dd = dd
        
        # 胜率
        total_closed = int(self.stats['winning_trades'] + self.stats['losing_trades'])
        win_rate = (self.stats['winning_trades'] / total_closed * 100) if total_closed > 0 else 0
        
        # 盈亏比
        profits = [t['pnl'] for t in self.trades if t['pnl'] > 0]
        losses = [abs(t['pnl']) for t in self.trades if t['pnl'] < 0]
        avg_profit = np.mean(profits) if profits else 0
        avg_loss = np.mean(losses) if losses else 1
        profit_factor = avg_profit / avg_loss if avg_loss > 0 else 0
        
        return {
            'initial_balance': self.initial_balance,
            'final_balance': self.balance,
            'total_return_pct': total_return,
            'annual_return_pct': annual_return,
            'max_drawdown_pct': max_dd * 100,
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'total_trades': int(self.stats['total_trades']),
            'winning_trades': int(self.stats['winning_trades']),
            'losing_trades': int(self.stats['losing_trades']),
            'liquidations': self.stats['liquidations'],
            'dca_count': self.stats['dca_count'],
            'avg_profit': avg_profit,
            'avg_loss': avg_loss,
            'stopped': self.stats['stopped_by_drawdown']
        }


def print_report(report):
    """打印报告"""
    print("\n" + "=" * 80)
    print("🚀 V2.5-Hybrid 优化版回测报告")
    print("=" * 80)
    
    print(f"\n💰 资金表现:")
    print(f"  初始: ${report['initial_balance']:.2f} → 最终: ${report['final_balance']:.2f}")
    print(f"  总收益: {report['total_return_pct']:+.2f}% | 年化: {report['annual_return_pct']:+.2f}%")
    
    print(f"\n📊 交易统计:")
    print(f"  总交易: {report['total_trades']} | 胜: {report['winning_trades']} | 负: {report['losing_trades']}")
    print(f"  胜率: {report['win_rate']:.1f}% {'✅' if report['win_rate'] > 50 else '❌'}")
    print(f"  盈亏比: {report['profit_factor']:.2f} {'✅' if report['profit_factor'] > 1 else '❌'}")
    print(f"  平均盈利: ${report['avg_profit']:.2f} | 平均亏损: ${report['avg_loss']:.2f}")
    
    print(f"\n🛡️ 风险控制:")
    print(f"  爆仓: {report['liquidations']} {'✅' if report['liquidations'] == 0 else '❌'}")
    print(f"  最大回撤: {report['max_drawdown_pct']:.1f}%")
    print(f"  DCA补仓: {report['dca_count']}")
    print(f"  提前停止: {'是' if report['stopped'] else '否'}")
    
    # 评分
    score = 0
    if report['liquidations'] == 0: score += 30
    if report['win_rate'] > 55: score += 25
    if report['profit_factor'] > 1: score += 20
    if report['total_return_pct'] > 0: score += 15
    if report['max_drawdown_pct'] < 20: score += 10
    
    print(f"\n⭐ 综合评分: {score}/100")
    if score >= 80:
        print("🟢 优秀 - 可用于实盘")
    elif score >= 60:
        print("🟡 良好 - 可谨慎使用")
    elif score >= 40:
        print("🟠 一般 - 需继续优化")
    else:
        print("🔴 差 - 不建议使用")
    
    print("=" * 80)


def main():
    engine = V2_5OptimizedEngine(initial_balance=1000.0)
    df = engine.load_and_prepare_data('eth_usdt_1h_binance.csv')
    report = engine.run_backtest(df)
    print_report(report)
    
    import json
    with open('v2_5_optimized_report.json', 'w') as f:
        json.dump(report, f, indent=2, default=str)


if __name__ == "__main__":
    main()