#!/usr/bin/env python3
"""
Backtrader 回测框架 - 对比 V2 和 V3 策略
研究员级回测验证
"""

import backtrader as bt
import pandas as pd
import numpy as np
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class V2StrategyBT(bt.Strategy):
    """
    V2策略的Backtrader实现
    """
    params = (
        ('leverage', 5),
        ('risk_pct', 0.008),
        ('stop_loss_pct', 0.04),
        ('take_profit_pct', 0.08),
        ('trailing_start', 0.06),
        ('trailing_stop', 0.03),
    )
    
    def __init__(self):
        # 技术指标
        self.rsi = bt.indicators.RSI(self.data.close, period=14)
        self.macd = bt.indicators.MACD(self.data.close)
        self.bb = bt.indicators.BollingerBands(self.data.close, period=20)
        self.atr = bt.indicators.ATR(self.data.close, period=14)
        
        # 均线
        self.ma20 = bt.indicators.SMA(self.data.close, period=20)
        self.ma55 = bt.indicators.SMA(self.data.close, period=55)
        self.ma200 = bt.indicators.SMA(self.data.close, period=200)
        
        # 交易量
        self.volume_ma = bt.indicators.SMA(self.data.volume, period=30)
        
        # 状态
        self.order = None
        self.entry_price = None
        self.max_profit = 0
        self.consecutive_losses = 0
        
    def next(self):
        if self.order:
            return
        
        # 计算信号
        current_close = self.data.close[0]
        current_volume = self.data.volume[0]
        
        # 趋势判断
        trend = 1 if self.ma55[0] > self.ma200[0] else -1
        trend_short = 1 if self.ma20[0] > self.ma55[0] else -1
        
        # RSI
        rsi = self.rsi[0]
        
        # MACD
        macd = self.macd.macd[0]
        macd_signal = self.macd.signal[0]
        macd_hist = macd - macd_signal
        macd_cross_up = macd > macd_signal and self.macd.macd[-1] <= self.macd.signal[-1]
        macd_cross_down = macd < macd_signal and self.macd.macd[-1] >= self.macd.signal[-1]
        
        # 布林带
        bb_width = (self.bb.top[0] - self.bb.bot[0]) / self.bb.mid[0]
        bb_position = (current_close - self.bb.bot[0]) / (self.bb.top[0] - self.bb.bot[0])
        
        # 成交量
        volume_ratio = current_volume / self.volume_ma[0] if self.volume_ma[0] > 0 else 1
        
        # 统计信号
        long_signals = 0
        short_signals = 0
        
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
        
        # 持仓管理
        if self.position:
            # 计算当前盈亏
            if self.position.size > 0:  # 多头
                pnl_pct = (current_close - self.entry_price) / self.entry_price
            else:  # 空头
                pnl_pct = (self.entry_price - current_close) / self.entry_price
            
            # 更新最高盈利
            if pnl_pct > self.max_profit:
                self.max_profit = pnl_pct
            
            # 止损
            if pnl_pct <= -self.p.stop_loss_pct:
                self.consecutive_losses += 1
                self.close()
                return
            
            # 止盈
            if pnl_pct >= self.p.take_profit_pct:
                self.consecutive_losses = 0
                self.close()
                return
            
            # 追踪止盈
            if self.max_profit >= self.p.trailing_start:
                if pnl_pct <= self.p.trailing_stop:
                    self.consecutive_losses = 0
                    self.close()
                    return
        else:
            # 开仓逻辑
            if long_signals >= 2 and self.consecutive_losses < 2:
                size = self.calculate_position_size(current_close)
                self.buy(size=size)
                self.entry_price = current_close
                self.max_profit = 0
            
            elif short_signals >= 2 and self.consecutive_losses < 2:
                size = self.calculate_position_size(current_close)
                self.sell(size=size)
                self.entry_price = current_close
                self.max_profit = 0
    
    def calculate_position_size(self, price):
        """计算仓位大小"""
        cash = self.broker.getcash()
        risk_amount = cash * self.p.risk_pct
        stop_distance = price * self.p.stop_loss_pct
        
        if stop_distance == 0:
            return 0
        
        qty = risk_amount / stop_distance
        max_qty = cash * 0.3 / price  # 最大30%资金
        
        return min(qty, max_qty)
    
    def notify_order(self, order):
        if order.status in [order.Completed]:
            if order.isbuy():
                pass
            elif order.issell():
                pass
            self.order = None


class V3StrategyBT(bt.Strategy):
    """
    V3策略的Backtrader实现 - ATR动态止损
    """
    params = (
        ('leverage', 5),
        ('risk_pct', 0.008),
        ('atr_multiplier_sl', 2.0),
        ('atr_multiplier_tp1', 2.0),
        ('atr_multiplier_tp2', 3.5),
        ('atr_multiplier_tp3', 5.0),
        ('trailing_atr_multiplier', 3.0),
    )
    
    def __init__(self):
        # 技术指标
        self.rsi = bt.indicators.RSI(self.data.close, period=14)
        self.macd = bt.indicators.MACD(self.data.close)
        self.bb = bt.indicators.BollingerBands(self.data.close, period=20)
        self.atr = bt.indicators.ATR(self.data.close, period=14)
        
        # ADX用于判断趋势/震荡
        self.adx = bt.indicators.AverageDirectionalMovementIndex(self.data.high, 
                                                                  self.data.low, 
                                                                  self.data.close)
        
        # 均线
        self.ma20 = bt.indicators.SMA(self.data.close, period=20)
        self.ma55 = bt.indicators.SMA(self.data.close, period=55)
        
        # 状态
        self.order = None
        self.entry_price = None
        self.max_profit = 0
        self.consecutive_losses = 0
        self.market_regime = 'unknown'
        
    def detect_market_regime(self):
        """检测市场状态"""
        if len(self.adx) < 2:
            return 'unknown'
        
        adx_value = self.adx[0]
        
        if adx_value > 25:
            return 'trending'
        elif adx_value < 20:
            return 'ranging'
        else:
            return 'mixed'
    
    def get_dynamic_stop_loss(self, entry_price, side, atr, regime):
        """ATR动态止损"""
        if regime == 'trending':
            multiplier = 2.5
        elif regime == 'ranging':
            multiplier = 1.5
        else:
            multiplier = self.p.atr_multiplier_sl
        
        if side == 'long':
            return entry_price - atr * multiplier
        else:
            return entry_price + atr * multiplier
    
    def next(self):
        if self.order:
            return
        
        current_close = self.data.close[0]
        current_atr = self.atr[0]
        regime = self.detect_market_regime()
        
        # 简单信号（多头：RSI<35，空头：RSI>65）
        if self.position:
            # 持仓管理 - ATR动态止损
            if self.position.size > 0:  # 多头
                sl_price = self.get_dynamic_stop_loss(self.entry_price, 'long', 
                                                      current_atr, regime)
                pnl_pct = (current_close - self.entry_price) / self.entry_price
                
                if current_close <= sl_price:
                    self.consecutive_losses += 1
                    self.close()
                    return
                
                # 追踪止盈
                if pnl_pct > self.max_profit:
                    self.max_profit = pnl_pct
                
                trailing_threshold = max(0.03, current_atr / self.entry_price * self.p.trailing_atr_multiplier)
                if self.max_profit >= 0.05 and (self.max_profit - pnl_pct) >= trailing_threshold:
                    self.close()
                    return
            
            else:  # 空头
                sl_price = self.get_dynamic_stop_loss(self.entry_price, 'short',
                                                      current_atr, regime)
                pnl_pct = (self.entry_price - current_close) / self.entry_price
                
                if current_close >= sl_price:
                    self.consecutive_losses += 1
                    self.close()
                    return
                
                # 追踪止盈
                if pnl_pct > self.max_profit:
                    self.max_profit = pnl_pct
                
                trailing_threshold = max(0.03, current_atr / self.entry_price * self.p.trailing_atr_multiplier)
                if self.max_profit >= 0.05 and (self.max_profit - pnl_pct) >= trailing_threshold:
                    self.close()
                    return
        
        else:
            # 开仓逻辑
            rsi = self.rsi[0]
            
            if rsi < 35 and self.consecutive_losses < 2:
                size = self.calculate_position_size(current_close, current_atr)
                self.buy(size=size)
                self.entry_price = current_close
                self.max_profit = 0
            
            elif rsi > 65 and self.consecutive_losses < 2:
                size = self.calculate_position_size(current_close, current_atr)
                self.sell(size=size)
                self.entry_price = current_close
                self.max_profit = 0
    
    def calculate_position_size(self, price, atr):
        """ATR-based仓位计算"""
        cash = self.broker.getcash()
        
        # ATR-based风险计算
        stop_distance = atr * self.p.atr_multiplier_sl
        risk_amount = cash * self.p.risk_pct
        
        if stop_distance == 0:
            return 0
        
        qty = risk_amount / stop_distance
        max_qty = cash * 0.3 / price
        
        return min(qty, max_qty)


def run_backtest(strategy_class, data_path, cash=1000.0, commission=0.0004):
    """
    运行回测
    """
    cerebro = bt.Cerebro()
    
    # 设置初始资金
    cerebro.broker.setcash(cash)
    
    # 设置手续费（币安期货约0.04%）
    cerebro.broker.setcommission(commission=commission)
    
    # 加载数据
    data = bt.feeds.YahooFinanceCSVData(
        dataname=data_path,
        datetime=0,
        open=1,
        high=2,
        low=3,
        close=4,
        volume=5,
        openinterest=-1
    )
    cerebro.adddata(data)
    
    # 添加策略
    cerebro.addstrategy(strategy_class)
    
    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    
    # 运行回测
    logger.info(f"开始回测: {strategy_class.__name__}")
    results = cerebro.run()
    strat = results[0]
    
    # 打印结果
    final_value = cerebro.broker.getvalue()
    logger.info(f"最终资金: ${final_value:.2f}")
    logger.info(f"收益率: {(final_value/cash - 1)*100:.2f}%")
    
    # 分析器结果
    sharpe = strat.analyzers.sharpe.get_analysis()
    drawdown = strat.analyzers.drawdown.get_analysis()
    trades = strat.analyzers.trades.get_analysis()
    
    logger.info(f"夏普比率: {sharpe.get('sharperatio', 'N/A')}")
    logger.info(f"最大回撤: {drawdown.get('max', {}).get('drawdown', 'N/A')}%")
    
    if trades and trades.get('total', {}).get('total', 0) > 0:
        total_trades = trades['total']['total']
        won_trades = trades.get('won', {}).get('total', 0)
        win_rate = won_trades / total_trades if total_trades > 0 else 0
        logger.info(f"总交易次数: {total_trades}")
        logger.info(f"胜率: {win_rate*100:.2f}%")
    
    return {
        'final_value': final_value,
        'return_pct': (final_value/cash - 1) * 100,
        'sharpe': sharpe.get('sharperatio'),
        'max_drawdown': drawdown.get('max', {}).get('drawdown'),
        'trades': trades
    }


def compare_strategies(data_path):
    """
    对比V2和V3策略
    """
    logger.info("=" * 80)
    logger.info("V2 vs V3 策略回测对比")
    logger.info("=" * 80)
    
    # 运行V2
    logger.info("\n【V2策略回测】")
    v2_results = run_backtest(V2StrategyBT, data_path)
    
    # 运行V3
    logger.info("\n【V3策略回测】")
    v3_results = run_backtest(V3StrategyBT, data_path)
    
    # 对比
    logger.info("\n" + "=" * 80)
    logger.info("对比结果")
    logger.info("=" * 80)
    
    metrics = ['return_pct', 'sharpe', 'max_drawdown']
    for metric in metrics:
        v2_val = v2_results.get(metric, 'N/A')
        v3_val = v3_results.get(metric, 'N/A')
        
        if v2_val != 'N/A' and v3_val != 'N/A':
            if metric == 'max_drawdown':
                better = "V3更好" if v3_val < v2_val else "V2更好"
            else:
                better = "V3更好" if v3_val > v2_val else "V2更好"
        else:
            better = "无法比较"
        
        logger.info(f"{metric}: V2={v2_val}, V3={v3_val} -> {better}")


if __name__ == "__main__":
    # 使用示例数据路径
    # 实际使用时需要提供ETHUSDT的CSV数据文件
    data_path = "eth_usdt_1h.csv"
    
    logger.info("注意：需要提供历史数据文件才能运行回测")
    logger.info("数据格式：date,open,high,low,close,volume")
    logger.info("可从币安下载历史K线数据")
    
    # 如果数据存在，运行回测
    import os
    if os.path.exists(data_path):
        compare_strategies(data_path)
    else:
        logger.info(f"数据文件 {data_path} 不存在，请准备数据后运行")
        logger.info("准备数据步骤：")
        logger.info("1. 从币安下载ETHUSDT 1小时K线数据")
        logger.info("2. 保存为 eth_usdt_1h.csv")
        logger.info("3. 格式：datetime,open,high,low,close,volume")