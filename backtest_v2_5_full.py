#!/usr/bin/env python3
"""
V2.5-Hybrid 完整回测系统
分析2年历史数据（2024-2026），评估爆仓次数、利润、最大回撤
"""

import pandas as pd
import numpy as np
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from dataclasses import dataclass, field
import json
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class BacktestTrade:
    """回测交易记录"""
    timestamp: datetime
    symbol: str
    action: str
    price: float
    qty: float
    side: str
    pnl: float = 0.0
    pnl_pct: float = 0.0
    trade_type: str = ''  # OPEN, DCA, GRID_TP, EXIT
    dca_index: int = 0


@dataclass
class BacktestPosition:
    """回测仓位状态"""
    symbol: str
    side: str
    entry_price: float
    total_qty: float = 0.0
    dca_levels: List[Dict] = field(default_factory=list)
    grid_levels: List[Dict] = field(default_factory=list)
    max_profit: float = 0.0
    entry_time: datetime = None
    is_active: bool = True
    total_invested: float = 0.0
    
    def get_avg_price(self) -> float:
        if not self.dca_levels:
            return self.entry_price
        total_cost = sum(l['price'] * l['qty'] for l in self.dca_levels)
        return total_cost / sum(l['qty'] for l in self.dca_levels) if self.dca_levels else self.entry_price


class V2_5BacktestEngine:
    """
    V2.5策略回测引擎
    """
    
    def __init__(self, initial_balance: float = 1000.0, leverage: int = 5):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.leverage = leverage
        self.positions = {}
        self.trades = []
        self.equity_curve = []
        
        # V2.5参数
        self.confidence_threshold = 0.60
        self.min_trade_interval = 4  # 4分钟
        self.last_trade_time = None
        self.consecutive_losses = 0
        self.daily_stop_triggered = False
        
        # 网格参数
        self.grid_atr_multiplier = 1.4
        self.max_dca_count = 3
        self.dca_fib = [1.0, 1.618, 2.618]
        self.dca_accelerator = 1.2
        
        # 止盈止损
        self.stop_loss_pct = 0.05  # 杠杆后-5%
        self.trailing_start = 0.06
        self.trailing_stop = 0.03
        self.group_tp = 0.08
        
        # 统计
        self.stats = {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'total_pnl': 0.0,
            'max_drawdown': 0.0,
            'max_equity': initial_balance,
            'liquidations': 0,
            'dca_count': 0,
            'grid_tp_count': 0,
            'consecutive_loss_stops': 0
        }
        
        logger.info(f"回测引擎初始化: 初始资金=${initial_balance}, 杠杆={leverage}x")
    
    def calculate_signals(self, row, prev_row) -> Tuple[int, int, float]:
        """计算V2信号"""
        long_signals = 0
        short_signals = 0
        
        trend = row['trend']
        trend_short = row.get('trend_short', trend)
        rsi = row['rsi']
        macd = row['macd']
        macd_signal = row['macd_signal']
        macd_hist = macd - macd_signal
        
        # MACD交叉
        macd_cross_up = (macd > macd_signal) and (prev_row['macd'] <= prev_row['macd_signal'])
        macd_cross_down = (macd < macd_signal) and (prev_row['macd'] >= prev_row['macd_signal'])
        
        volume_ratio = row.get('volume_ratio', 1.0)
        bb_width = row.get('bb_width', 0.05)
        bb_position = row.get('bb_position', 0.5)
        
        # 多头信号
        if trend == 1 and rsi < 45 and macd_cross_up and volume_ratio > 1.2 and bb_width < 0.05:
            long_signals += 1
        if trend == 1 and rsi < 40 and macd > macd_signal:
            long_signals += 1
        if macd_cross_up and volume_ratio > 1.2 and rsi < 60 and trend_short == 1:
            long_signals += 1
        if bb_position < 0.15 and rsi < 50 and macd_hist > 0:
            long_signals += 1
        if rsi < 35 and macd_hist > 0:
            long_signals += 1
        
        # 空头信号
        if trend == -1 and rsi > 55 and macd_cross_down and volume_ratio > 1.2 and bb_width < 0.05:
            short_signals += 1
        if trend == -1 and rsi > 60 and macd < macd_signal:
            short_signals += 1
        if macd_cross_down and volume_ratio > 1.2 and rsi > 40 and trend_short == -1:
            short_signals += 1
        if bb_position > 0.85 and rsi > 50 and macd_hist < 0:
            short_signals += 1
        if rsi > 65 and macd_hist < 0:
            short_signals += 1
        
        confidence = 0.45 + 0.15 * (max(long_signals, short_signals) - 1) if max(long_signals, short_signals) > 0 else 0
        
        return long_signals, short_signals, confidence
    
    def calculate_position_size(self, price: float, atr: float) -> float:
        """计算仓位大小"""
        risk_amount = self.balance * 0.008  # 0.8%风险
        stop_distance = atr * 2.0
        
        if stop_distance <= 0:
            return 0.001
        
        qty = risk_amount / stop_distance
        max_qty = self.balance * 0.3 / price
        
        return max(0.001, min(qty, max_qty))
    
    def check_liquidation(self, position: BacktestPosition, current_price: float) -> bool:
        """检查是否爆仓"""
        if not position.is_active:
            return False
        
        avg_price = position.get_avg_price()
        margin_used = position.total_invested * 0.2  # 5x杠杆需要20%保证金
        
        if position.side == 'LONG':
            loss_pct = (current_price - avg_price) / avg_price
        else:
            loss_pct = (avg_price - current_price) / avg_price
        
        # 10倍杠杆下，价格反向10%爆仓
        liquidation_threshold = -0.10 * (10 / self.leverage)
        
        if loss_pct <= liquidation_threshold:
            return True
        
        return False
    
    def open_position(self, timestamp: datetime, symbol: str, side: str, 
                     price: float, atr: float, confidence: float, reason: str):
        """开仓"""
        qty = self.calculate_position_size(price, atr)
        cost = qty * price / self.leverage  # 保证金
        
        if cost > self.balance * 0.7:  # 保留30%安全垫
            return
        
        position = BacktestPosition(
            symbol=symbol,
            side=side,
            entry_price=price,
            total_qty=qty,
            entry_time=timestamp,
            total_invested=cost
        )
        
        # 初始化DCA
        position.dca_levels = [{
            'price': price,
            'qty': qty,
            'timestamp': timestamp,
            'dca_index': 0
        }]
        
        # 初始化网格
        grid_spacing = atr * self.grid_atr_multiplier
        for i in range(1, 4):
            if side == 'LONG':
                grid_price = price + grid_spacing * i
            else:
                grid_price = price - grid_spacing * i
            
            position.grid_levels.append({
                'price': grid_price,
                'qty': qty * (0.5 ** (i-1)),
                'filled': False
            })
        
        self.positions[symbol] = position
        self.balance -= cost
        
        self.trades.append(BacktestTrade(
            timestamp=timestamp,
            symbol=symbol,
            action='OPEN',
            price=price,
            qty=qty,
            side=side,
            trade_type='OPEN'
        ))
        
        self.stats['total_trades'] += 1
        logger.debug(f"开仓 {side} {qty:.4f} @ ${price:.2f}, 剩余资金: ${self.balance:.2f}")
    
    def check_dca(self, timestamp: datetime, symbol: str, price: float, atr: float):
        """检查补仓"""
        if symbol not in self.positions:
            return
        
        pos = self.positions[symbol]
        if not pos.is_active or len(pos.dca_levels) >= self.max_dca_count:
            return
        
        last_entry = pos.dca_levels[-1]['price']
        dca_idx = len(pos.dca_levels)
        fib_mult = self.dca_fib[dca_idx]
        if dca_idx == 2:
            fib_mult *= self.dca_accelerator
        
        trigger_dist = atr * 1.2 * fib_mult
        
        should_dca = False
        if pos.side == 'LONG' and price <= last_entry - trigger_dist:
            should_dca = True
        elif pos.side == 'SHORT' and price >= last_entry + trigger_dist:
            should_dca = True
        
        if should_dca:
            base_qty = pos.dca_levels[0]['qty']
            dca_qty = base_qty * fib_mult
            cost = dca_qty * price / self.leverage
            
            if cost > self.balance * 0.5:  # 检查资金
                return
            
            pos.dca_levels.append({
                'price': price,
                'qty': dca_qty,
                'timestamp': timestamp,
                'dca_index': dca_idx
            })
            pos.total_qty += dca_qty
            pos.total_invested += cost
            self.balance -= cost
            
            self.trades.append(BacktestTrade(
                timestamp=timestamp,
                symbol=symbol,
                action='DCA',
                price=price,
                qty=dca_qty,
                side=pos.side,
                trade_type='DCA',
                dca_index=dca_idx + 1
            ))
            
            self.stats['dca_count'] += 1
            logger.debug(f"补仓 #{dca_idx+1} {dca_qty:.4f} @ ${price:.2f}, Fib: {fib_mult:.2f}")
    
    def check_exit(self, timestamp: datetime, symbol: str, price: float) -> bool:
        """检查平仓条件"""
        if symbol not in self.positions:
            return False
        
        pos = self.positions[symbol]
        if not pos.is_active:
            return False
        
        avg_price = pos.get_avg_price()
        
        # 计算盈亏
        if pos.side == 'LONG':
            pnl_pct = (price - avg_price) / avg_price * self.leverage
        else:
            pnl_pct = (avg_price - price) / avg_price * self.leverage
        
        # 更新最高盈利
        if pnl_pct > pos.max_profit:
            pos.max_profit = pnl_pct
        
        # 检查爆仓
        if self.check_liquidation(pos, price):
            # 爆仓处理
            loss = pos.total_invested * 0.9  # 损失90%保证金
            self.balance += pos.total_invested * 0.1  # 返还10%
            pos.is_active = False
            
            self.trades.append(BacktestTrade(
                timestamp=timestamp,
                symbol=symbol,
                action='LIQUIDATION',
                price=price,
                qty=pos.total_qty,
                side=pos.side,
                pnl=-loss,
                pnl_pct=-90.0,
                trade_type='EXIT'
            ))
            
            self.stats['liquidations'] += 1
            self.stats['losing_trades'] += 1
            self.stats['total_pnl'] -= loss
            self.consecutive_losses += 1
            
            logger.warning(f"💥 爆仓! {symbol} {pos.side} @ ${price:.2f}, 损失: ${loss:.2f}")
            return True
        
        # 止损检查
        if pnl_pct <= -self.stop_loss_pct * 100:
            self.close_position(timestamp, symbol, price, 'STOP_LOSS', pnl_pct)
            return True
        
        # 整组止盈
        if pnl_pct >= self.group_tp * 100:
            self.close_position(timestamp, symbol, price, 'GROUP_TP', pnl_pct)
            return True
        
        # 追踪止盈
        if pos.max_profit >= self.trailing_start * 100:
            drawdown = pos.max_profit - pnl_pct
            if drawdown >= self.trailing_stop * 100:
                self.close_position(timestamp, symbol, price, 'TRAILING_STOP', pnl_pct)
                return True
        
        # 网格止盈
        for grid in pos.grid_levels:
            if not grid['filled']:
                if pos.side == 'LONG' and price >= grid['price']:
                    grid['filled'] = True
                    grid_pnl = (grid['price'] - avg_price) / avg_price * self.leverage * 100
                    
                    # 部分平仓
                    close_qty = min(grid['qty'], pos.total_qty * 0.5)
                    profit = close_qty * (grid['price'] - avg_price) if pos.side == 'LONG' else close_qty * (avg_price - grid['price'])
                    
                    self.balance += profit + (close_qty * grid['price'] / self.leverage)
                    pos.total_qty -= close_qty
                    
                    self.trades.append(BacktestTrade(
                        timestamp=timestamp,
                        symbol=symbol,
                        action='GRID_TP',
                        price=grid['price'],
                        qty=close_qty,
                        side=pos.side,
                        pnl=profit,
                        pnl_pct=grid_pnl,
                        trade_type='GRID_TP'
                    ))
                    
                    self.stats['grid_tp_count'] += 1
                    logger.debug(f"网格止盈 ${grid['price']:.2f}, 盈利: ${profit:.2f}")
                    
                    if pos.total_qty <= 0.001:
                        pos.is_active = False
                        return True
                    break
        
        return False
    
    def close_position(self, timestamp: datetime, symbol: str, price: float, 
                      reason: str, pnl_pct: float):
        """平仓"""
        pos = self.positions[symbol]
        avg_price = pos.get_avg_price()
        
        if pos.side == 'LONG':
            profit = pos.total_qty * (price - avg_price)
        else:
            profit = pos.total_qty * (avg_price - price)
        
        # 返还保证金 + 盈亏
        self.balance += pos.total_invested + profit
        pos.is_active = False
        
        self.trades.append(BacktestTrade(
            timestamp=timestamp,
            symbol=symbol,
            action='CLOSE',
            price=price,
            qty=pos.total_qty,
            side=pos.side,
            pnl=profit,
            pnl_pct=pnl_pct,
            trade_type='EXIT'
        ))
        
        if profit > 0:
            self.stats['winning_trades'] += 1
            self.consecutive_losses = 0
        else:
            self.stats['losing_trades'] += 1
            self.consecutive_losses += 1
        
        self.stats['total_pnl'] += profit
        
        logger.info(f"平仓 {reason}: {symbol} {pos.side} @ ${price:.2f}, "
                   f"盈亏: ${profit:.2f} ({pnl_pct:+.2f}%)")
    
    def update_equity(self, timestamp: datetime, current_prices: Dict[str, float]):
        """更新权益曲线"""
        total_equity = self.balance
        
        for symbol, pos in self.positions.items():
            if pos.is_active and symbol in current_prices:
                avg_price = pos.get_avg_price()
                price = current_prices[symbol]
                
                if pos.side == 'LONG':
                    unrealized = pos.total_qty * (price - avg_price)
                else:
                    unrealized = pos.total_qty * (avg_price - price)
                
                margin = pos.total_qty * avg_price / self.leverage
                total_equity += margin + unrealized
        
        self.equity_curve.append({
            'timestamp': timestamp,
            'equity': total_equity,
            'balance': self.balance
        })
        
        # 更新最大回撤
        if total_equity > self.stats['max_equity']:
            self.stats['max_equity'] = total_equity
        
        drawdown = (self.stats['max_equity'] - total_equity) / self.stats['max_equity']
        if drawdown > self.stats['max_drawdown']:
            self.stats['max_drawdown'] = drawdown
    
    def run_backtest(self, df: pd.DataFrame) -> Dict:
        """
        运行回测
        """
        logger.info(f"开始回测，数据条数: {len(df)}")
        
        # 预处理数据
        df = df.copy()
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp')
        
        symbol = df['symbol'].iloc[0] if 'symbol' in df.columns else 'ETHUSDT'
        
        for i in range(200, len(df)):
            row = df.iloc[i]
            prev_row = df.iloc[i-1]
            timestamp = row['timestamp']
            
            # 每日重置
            if i > 0:
                prev_timestamp = df.iloc[i-1]['timestamp']
                if timestamp.day != prev_timestamp.day:
                    self.consecutive_losses = 0
                    self.daily_stop_triggered = False
            
            # 检查信号
            long_count, short_count, confidence = self.calculate_signals(row, prev_row)
            
            # 检查现有仓位
            if symbol in self.positions and self.positions[symbol].is_active:
                self.check_dca(timestamp, symbol, row['close'], row['atr'])
                
                exited = self.check_exit(timestamp, symbol, row['close'])
                
                if not exited:
                    # 更新权益
                    self.update_equity(timestamp, {symbol: row['close']})
                    continue
            
            # 新开仓
            if confidence >= self.confidence_threshold and self.consecutive_losses < 2:
                # 检查交易间隔
                if self.last_trade_time is None or \
                   (timestamp - self.last_trade_time).total_seconds() >= self.min_trade_interval * 60:
                    
                    if long_count >= 2:
                        self.open_position(timestamp, symbol, 'LONG', 
                                         row['close'], row['atr'], confidence, 
                                         f'L{long_count} signals')
                        self.last_trade_time = timestamp
                    
                    elif short_count >= 2:
                        self.open_position(timestamp, symbol, 'SHORT',
                                         row['close'], row['atr'], confidence,
                                         f'S{short_count} signals')
                        self.last_trade_time = timestamp
            
            # 更新权益
            self.update_equity(timestamp, {symbol: row['close']})
        
        # 强制平掉所有持仓
        final_price = df['close'].iloc[-1]
        final_time = df['timestamp'].iloc[-1]
        
        for symbol, pos in list(self.positions.items()):
            if pos.is_active:
                avg_price = pos.get_avg_price()
                if pos.side == 'LONG':
                    pnl_pct = (final_price - avg_price) / avg_price * self.leverage * 100
                else:
                    pnl_pct = (avg_price - final_price) / avg_price * self.leverage * 100
                
                self.close_position(final_time, symbol, final_price, 'END_OF_BACKTEST', pnl_pct)
        
        return self.generate_report()
    
    def generate_report(self) -> Dict:
        """生成回测报告"""
        total_return = (self.balance - self.initial_balance) / self.initial_balance * 100
        
        # 计算年化收益
        if len(self.equity_curve) > 1:
            start_time = self.equity_curve[0]['timestamp']
            end_time = self.equity_curve[-1]['timestamp']
            years = (end_time - start_time).days / 365.25
            annual_return = ((self.balance / self.initial_balance) ** (1/years) - 1) * 100 if years > 0 else 0
        else:
            years = 0
            annual_return = 0
        
        # 计算夏普比率（简化版）
        if len(self.equity_curve) > 1:
            equity_values = [e['equity'] for e in self.equity_curve]
            returns = pd.Series(equity_values).pct_change().dropna()
            sharpe = (returns.mean() / returns.std()) * np.sqrt(252) if returns.std() != 0 else 0
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
            'consecutive_loss_stops': self.stats['consecutive_loss_stops'],
            'trading_period_years': years
        }
        
        return report


def load_historical_data(data_path: str) -> pd.DataFrame:
    """加载历史数据"""
    logger.info(f"加载历史数据: {data_path}")
    
    if not os.path.exists(data_path):
        logger.error(f"数据文件不存在: {data_path}")
        return None
    
    try:
        df = pd.read_csv(data_path)
        
        # 标准化列名
        column_mapping = {
            'Open Time': 'timestamp',
            'open_time': 'timestamp',
            'Open': 'open',
            'High': 'high',
            'Low': 'low',
            'Close': 'close',
            'Volume': 'volume',
            'Quote asset volume': 'quote_volume'
        }
        df = df.rename(columns=column_mapping)
        
        # 转换时间戳
        if 'timestamp' in df.columns:
            if df['timestamp'].dtype == 'int64':
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            else:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # 确保数值类型
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in df.columns:
                df[col] = df[col].astype(float)
        
        # 计算技术指标
        df['ma20'] = df['close'].rolling(20).mean()
        df['ma55'] = df['close'].rolling(55).mean()
        df['ma200'] = df['close'].rolling(200).mean()
        df['trend'] = np.where(df['ma55'] > df['ma200'], 1, -1)
        df['trend_short'] = np.where(df['ma20'] > df['ma55'], 1, -1)
        
        # RSI
        delta = df['close'].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss
        df['rsi'] = 100 - 100 / (1 + rs)
        
        # MACD
        ema12 = df['close'].ewm(span=12).mean()
        ema26 = df['close'].ewm(span=26).mean()
        df['macd'] = ema12 - ema26
        df['macd_signal'] = df['macd'].ewm(span=9).mean()
        
        # ATR
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['atr'] = tr.rolling(14).mean()
        
        # 布林带
        df['bb_mid'] = df['close'].rolling(20).mean()
        df['bb_std'] = df['close'].rolling(20).std()
        df['bb_upper'] = df['bb_mid'] + 2 * df['bb_std']
        df['bb_lower'] = df['bb_mid'] - 2 * df['bb_std']
        df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_mid']
        df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])
        
        # 量能
        df['volume_ma'] = df['volume'].rolling(30).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma']
        
        # 添加symbol列
        df['symbol'] = 'ETHUSDT'
        
        logger.info(f"数据加载完成: {len(df)} 条记录")
        logger.info(f"时间范围: {df['timestamp'].min()} 到 {df['timestamp'].max()}")
        
        return df
        
    except Exception as e:
        logger.error(f"加载数据失败: {e}")
        return None


def print_report(report: Dict):
    """打印回测报告"""
    print("\n" + "="*80)
    print("📊 V2.5-Hybrid 回测报告")
    print("="*80)
    
    print(f"\n💰 资金表现:")
    print(f"  初始资金: ${report['initial_balance']:.2f}")
    print(f"  最终资金: ${report['final_balance']:.2f}")
    print(f"  总收益率: {report['total_return_pct']:+.2f}%")
    print(f"  年化收益率: {report['annual_return_pct']:+.2f}%")
    
    print(f"\n📉 风险指标:")
    print(f"  最大回撤: {report['max_drawdown_pct']:.2f}%")
    print(f"  夏普比率: {report['sharpe_ratio']:.2f}")
    
    print(f"\n🎯 交易统计:")
    print(f"  总交易次数: {report['total_trades']}")
    print(f"  盈利次数: {report['winning_trades']}")
    print(f"  亏损次数: {report['losing_trades']}")
    print(f"  胜率: {report['win_rate']:.2f}%")
    print(f"  总盈亏: ${report['total_pnl']:.2f}")
    
    print(f"\n⚠️  风险事件:")
    print(f"  💥 爆仓次数: {report['liquidations']}")
    print(f"  🔄 DCA补仓次数: {report['dca_count']}")
    print(f"  🎯 网格止盈次数: {report['grid_tp_count']}")
    print(f"  🛑 连续止损暂停: {report['consecutive_loss_stops']}")
    
    print(f"\n📅 回测期间: {report['trading_period_years']:.2f} 年")
    
    print("\n" + "="*80)
    
    # 风险评估
    print("\n🔍 风险评估:")
    if report['liquidations'] > 0:
        print(f"  ❌ 警告: 发生 {report['liquidations']} 次爆仓！")
        print(f"     建议: 降低杠杆或收紧止损")
    else:
        print(f"  ✅ 无爆仓，风控良好")
    
    if report['max_drawdown_pct'] > 20:
        print(f"  ⚠️  最大回撤 {report['max_drawdown_pct']:.1f}% 偏高")
    else:
        print(f"  ✅ 最大回撤控制在 {report['max_drawdown_pct']:.1f}%")
    
    if report['annual_return_pct'] > 100 and report['max_drawdown_pct'] < 15:
        print(f"  ✅ 收益风险比优秀!")
    elif report['annual_return_pct'] > 50:
        print(f"  ✅ 收益表现良好")
    else:
        print(f"  ⚠️  收益偏低，建议优化参数")
    
    print("="*80)


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='V2.5-Hybrid 回测')
    parser.add_argument('--data', type=str, default='eth_usdt_1h.csv',
                       help='历史数据文件路径')
    parser.add_argument('--balance', type=float, default=1000.0,
                       help='初始资金')
    parser.add_argument('--leverage', type=int, default=5,
                       help='杠杆倍数')
    
    args = parser.parse_args()
    
    # 加载数据
    df = load_historical_data(args.data)
    if df is None:
        print("\n❌ 无法加载数据，请检查文件路径")
        print("\n数据格式要求:")
        print("  - CSV文件")
        print("  - 列: timestamp, open, high, low, close, volume")
        print("  - 可从币安下载历史K线数据")
        print("\n下载方法:")
        print("  1. 访问 https://www.binance.com/en/landing/data")
        print("  2. 选择 ETHUSDT, 1h 时间框架")
        print("  3. 下载 2024-01-01 到 2026-03-20 的数据")
        return
    
    # 运行回测
    engine = V2_5BacktestEngine(
        initial_balance=args.balance,
        leverage=args.leverage
    )
    
    report = engine.run_backtest(df)
    print_report(report)
    
    # 保存详细结果
    output_file = f"v2_5_backtest_report_{datetime.now():%Y%m%d_%H%M%S}.json"
    with open(output_file, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    
    print(f"\n📄 详细报告已保存: {output_file}")


if __name__ == "__main__":
    main()