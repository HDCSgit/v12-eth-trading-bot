#!/usr/bin/env python3
"""
V12-LIVE: 实盘交易主程序
基于V12-simple策略，整合完整风控和监控
"""

import pandas as pd
import numpy as np
import logging
import time
import sqlite3
import json
from datetime import datetime
from typing import Dict, Optional
import warnings
warnings.filterwarnings('ignore')

from binance_api import BinanceExpertAPI
from config import CONFIG, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
import requests

# ==================== 配置日志 ====================
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler(f'logs/v12_live_{datetime.now().strftime("%Y%m%d")}.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class V12LiveTrader:
    """V12实盘交易器"""
    
    def __init__(self):
        self.api = BinanceExpertAPI()
        self.symbol = CONFIG["SYMBOLS"][0]  # ETHUSDT
        self.leverage = 3  # V12使用3倍杠杆
        self.position_pct = 0.10  # 10%仓位
        
        # 风控参数
        self.stop_loss_pct = 0.03  # 3%止损
        self.take_profit_pct = 0.06  # 6%止盈
        self.max_daily_loss = 0.05  # 日最大亏损5%
        self.max_positions = 1  # 最大持仓1个
        
        # 状态跟踪
        self.daily_pnl = 0
        self.last_trade_day = datetime.now().day
        self.trade_count = 0
        self.position = None  # 当前持仓
        
        # 初始化数据库
        self.init_database()
        
        logger.info("=" * 60)
        logger.info("V12-LIVE 实盘交易器初始化完成")
        logger.info(f"   交易对: {self.symbol}")
        logger.info(f"   杠杆: {self.leverage}x")
        logger.info(f"   仓位: {self.position_pct*100}%")
        logger.info(f"   止损: {self.stop_loss_pct*100}%")
        logger.info(f"   止盈: {self.take_profit_pct*100}%")
        logger.info("=" * 60)

    def init_database(self):
        """初始化交易记录数据库"""
        conn = sqlite3.connect('v12_trades.db')
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                symbol TEXT,
                side TEXT,
                entry_price REAL,
                exit_price REAL,
                qty REAL,
                pnl_pct REAL,
                pnl_usdt REAL,
                result TEXT,
                status TEXT
            )
        ''')
        conn.commit()
        conn.close()

    def send_telegram(self, message: str):
        """发送Telegram通知"""
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
            return
        
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML"
            }
            requests.post(url, json=payload, timeout=5)
        except Exception as e:
            logger.error(f"Telegram发送失败: {e}")

    def calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """计算RSI"""
        delta = prices.diff()
        gain = delta.clip(lower=0).rolling(window=period).mean()
        loss = (-delta.clip(upper=0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    def get_signals(self, df: pd.DataFrame) -> Dict:
        """生成交易信号"""
        current = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else current
        
        # 计算指标
        df['rsi'] = self.calculate_rsi(df['close'])
        df['ma10'] = df['close'].rolling(10).mean()
        df['ma20'] = df['close'].rolling(20).mean()
        
        current = df.iloc[-1]
        prev = df.iloc[-2]
        
        signals = {
            'action': 'HOLD',
            'reason': '',
            'rsi': current['rsi'],
            'ma10': current['ma10'],
            'ma20': current['ma20']
        }
        
                # 超卖反弹做多
        if current['rsi'] < 35 and current['close'] > prev['close']:
            signals['action'] = 'BUY'
            signals['reason'] = f"RSI超卖({current['rsi']:.1f})"
        
        # 超买回落做空
        elif current['rsi'] > 65 and current['close'] < prev['close']:
            signals['action'] = 'SELL'
            signals['reason'] = f"RSI超买({current['rsi']:.1f})"
        
        # 均线金叉做多
        elif current['ma10'] > current['ma20'] and prev['ma10'] <= prev['ma20']:
            signals['action'] = 'BUY'
            signals['reason'] = "MA金叉"
        
        # 均线死叉做空
        elif current['ma10'] < current['ma20'] and prev['ma10'] >= prev['ma20']:
            signals['action'] = 'SELL'
            signals['reason'] = "MA死叉"
        
        return signals

    def check_risk_limits(self) -> bool:
        """检查风控限制"""
        # 检查日亏损
        if self.daily_pnl < -self.max_daily_loss:
            logger.warning(f"⚠️ 日亏损已达{self.daily_pnl*100:.2f}%，暂停交易")
            return False
        
        # 检查持仓数量
        positions = self.api.get_all_positions()
        if len(positions) >= self.max_positions:
            return False
        
        return True

    def calculate_position_size(self, price: float) -> float:
        """计算仓位大小"""
        balance = self.api.get_balance()
        position_value = balance * self.position_pct
        qty = position_value / price
        
        # 最小数量限制
        min_qty = 0.001
        if qty < min_qty:
            logger.warning(f"仓位计算{qty:.4f}小于最小限制{min_qty}，调整为{min_qty}")
            qty = min_qty
        
        return qty

    def open_position(self, side: str, price: float, reason: str):
        """开仓"""
        try:
            # 设置杠杆
            self.api.set_leverage(self.symbol, self.leverage)
            
            # 计算仓位
            qty = self.calculate_position_size(price)
            
            # 下单
            order = self.api.place_order(self.symbol, side, qty)
            
            if order and order.get('orderId'):
                self.position = {
                    'side': side,
                    'entry_price': price,
                    'qty': qty,
                    'entry_time': datetime.now(),
                    'reason': reason
                }
                
                self.trade_count += 1
                
                msg = (f"🟢 <b>开仓成功</b>\n"
                       f"方向: {side}\n"
                       f"价格: ${price:.2f}\n"
                       f"数量: {qty:.4f} ETH\n"
                       f"原因: {reason}")
                
                logger.info(f"✅ 开仓: {side} {qty} @ ${price:.2f} | {reason}")
                self.send_telegram(msg)
                return True
            
        except Exception as e:
            logger.error(f"❌ 开仓失败: {e}")
        
        return False

    def close_position(self, price: float, reason: str = "止盈/止损"):
        """平仓"""
        try:
            if not self.position:
                return False
            
            # 计算盈亏
            entry_price = self.position['entry_price']
            qty = self.position['qty']
            side = self.position['side']
            
            if side == 'BUY':
                pnl_pct = (price - entry_price) / entry_price * self.leverage
            else:
                pnl_pct = (entry_price - price) / entry_price * self.leverage
            
            pnl_usdt = qty * entry_price * pnl_pct
            
            # 平仓订单
            close_side = 'SELL' if side == 'BUY' else 'BUY'
            order = self.api.place_order(self.symbol, close_side, qty, reduce_only=True)
            
            if order:
                result = 'WIN' if pnl_pct > 0 else 'LOSS'
                self.daily_pnl += pnl_pct
                
                # 记录到数据库
                conn = sqlite3.connect('v12_trades.db')
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO trades (timestamp, symbol, side, entry_price, exit_price, 
                                      qty, pnl_pct, pnl_usdt, result, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    datetime.now().isoformat(),
                    self.symbol,
                    side,
                    entry_price,
                    price,
                    qty,
                    pnl_pct,
                    pnl_usdt,
                    result,
                    'CLOSED'
                ))
                conn.commit()
                conn.close()
                
                emoji = "🟢" if pnl_pct > 0 else "🔴"
                msg = (f"{emoji} <b>平仓成功</b>\n"
                       f"方向: {side}\n"
                       f"入场: ${entry_price:.2f}\n"
                       f"出场: ${price:.2f}\n"
                       f"盈亏: {pnl_pct*100:+.2f}%\n"
                       f"金额: ${pnl_usdt:+.2f}\n"
                       f"原因: {reason}")
                
                logger.info(f"✅ 平仓: {side} | PnL: {pnl_pct*100:+.2f}% | {reason}")
                self.send_telegram(msg)
                
                self.position = None
                return True
            
        except Exception as e:
            logger.error(f"❌ 平仓失败: {e}")
        
        return False

    def check_position_pnl(self, current_price: float):
        """检查持仓盈亏"""
        if not self.position:
            return
        
        entry_price = self.position['entry_price']
        side = self.position['side']
        
        if side == 'BUY':
            pnl_pct = (current_price - entry_price) / entry_price * self.leverage
        else:
            pnl_pct = (entry_price - current_price) / entry_price * self.leverage
        
        # 止损
        if pnl_pct <= -self.stop_loss_pct:
            logger.info(f"⛔ 触发止损: {pnl_pct*100:.2f}%")
            self.close_position(current_price, "止损")
        
        # 止盈
        elif pnl_pct >= self.take_profit_pct:
            logger.info(f"✨ 触发止盈: {pnl_pct*100:.2f}%")
            self.close_position(current_price, "止盈")

    def run(self):
        """主循环"""
        logger.info("🚀 V12实盘交易启动...")
        self.send_telegram("🚀 <b>V12实盘交易启动</b>")
        
        while True:
            try:
                # 重置日统计
                if datetime.now().day != self.last_trade_day:
                    self.daily_pnl = 0
                    self.last_trade_day = datetime.now().day
                    logger.info("📅 新的一天，重置日统计")
                
                # 获取K线数据
                logger.info("正在获取K线数据...")
                df = self.api.get_klines(self.symbol, limit=100)
                
                if df is None:
                    logger.error("获取K线数据返回None，重试...")
                    time.sleep(5)
                    continue
                    
                if len(df) < 30:
                    logger.warning(f"K线数据不足: {len(df)} < 30，重试...")
                    time.sleep(5)
                    continue
                
                current_price = float(df['close'].iloc[-1])
                logger.info(f"当前价格: ${current_price:.2f}")
                
                # 如果有持仓，检查盈亏
                if self.position:
                    self.check_position_pnl(current_price)
                
                # 如果没有持仓，检查开仓信号
                elif self.check_risk_limits():
                    signals = self.get_signals(df)
                    
                    if signals['action'] != 'HOLD':
                        self.open_position(
                            signals['action'], 
                            current_price, 
                            signals['reason']
                        )
                
                # 显示状态
                if self.position:
                    entry = self.position['entry_price']
                    pnl = (current_price - entry) / entry * self.leverage
                    if self.position['side'] == 'SELL':
                        pnl = -pnl
                    logger.info(f"📊 持仓: {self.position['side']} | "
                              f"入场: ${entry:.2f} | 当前: ${current_price:.2f} | "
                              f"盈亏: {pnl*100:+.2f}%")
                
                time.sleep(CONFIG.get("POLL_INTERVAL", 10))
                
            except KeyboardInterrupt:
                logger.info("🛑 收到停止信号，正在关闭...")
                if self.position:
                    price = self.api.get_price(self.symbol)
                    self.close_position(price, "程序退出")
                break
            
            except Exception as e:
                logger.error(f"主循环错误: {e}")
                time.sleep(5)


def main():
    """入口"""
    # 确认模式
    if CONFIG["MODE"] != "LIVE":
        logger.warning(f"⚠️ 当前模式为 {CONFIG['MODE']}，切换到LIVE模式请输入 'LIVE':")
        confirm = input().strip()
        if confirm != "LIVE":
            logger.info("取消启动")
            return
    
    trader = V12LiveTrader()
    trader.run()


if __name__ == "__main__":
    main()