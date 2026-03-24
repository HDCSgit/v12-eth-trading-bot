#!/usr/bin/env python3
"""
V12实时监控面板
"""

import sqlite3
import time
from datetime import datetime, timedelta
from binance_api import BinanceExpertAPI
from config import CONFIG
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')
logger = logging.getLogger(__name__)


def show_live_status():
    """显示实时状态"""
    api = BinanceExpertAPI()
    symbol = CONFIG["SYMBOLS"][0]
    
    print("\n" + "=" * 70)
    print(" " * 20 + "📊 V12-LIVE 实时监控")
    print("=" * 70)
    
    # 账户信息
    balance = api.get_balance()
    print(f"\n💰 账户余额: ${balance:.2f} USDT")
    
    # 当前价格
    price = api.get_price(symbol)
    print(f"📈 {symbol} 价格: ${price:.2f}")
    
    # 持仓信息
    position = api.get_position(symbol)
    if position:
        side = position['side']
        entry = position['entryPrice']
        qty = position['qty']
        pnl = position['unrealizedProfit']
        notional = position['notional']
        liq_price = position['liquidationPrice']
        
        pnl_pct = pnl / notional * 100 if notional > 0 else 0
        
        print(f"\n📦 当前持仓:")
        print(f"   方向: {side}")
        print(f"   数量: {qty:.4f} ETH")
        print(f"   入场价: ${entry:.2f}")
        print(f"   浮动盈亏: ${pnl:+.2f} ({pnl_pct:+.2f}%)")
        print(f"   名义价值: ${notional:.2f}")
        print(f"   爆仓价: ${liq_price:.2f}")
    else:
        print(f"\n📦 当前持仓: 无")
    
    # 今日交易统计
    conn = sqlite3.connect('v12_trades.db')
    cursor = conn.cursor()
    
    today = datetime.now().strftime('%Y-%m-%d')
    cursor.execute('''
        SELECT COUNT(*), 
               SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) as losses,
               SUM(pnl_usdt) as total_pnl
        FROM trades 
        WHERE date(timestamp) = date(?)
    ''', (today,))
    
    total, wins, losses, pnl = cursor.fetchone()
    conn.close()
    
    if total and total > 0:
        win_rate = wins / total * 100
        print(f"\n📊 今日交易统计:")
        print(f"   总交易: {total} 笔")
        print(f"   盈利: {wins} 笔 | 亏损: {losses} 笔")
        print(f"   胜率: {win_rate:.1f}%")
        print(f"   总盈亏: ${pnl:+.2f}")
    
    # 资金费率
    funding_rate = api.get_funding_rate(symbol)
    next_funding = api.get_next_funding_time(symbol)
    time_to_funding = (next_funding - int(time.time() * 1000)) / 1000 / 60
    
    print(f"\n⏰ 资金费率:")
    print(f"   当前: {funding_rate:.4%}")
    print(f"   下次结算: {time_to_funding:.0f} 分钟后")
    
    print("=" * 70)


def monitor_loop():
    """监控循环"""
    logger.info("🚀 V12监控启动...")
    
    while True:
        try:
            show_live_status()
            time.sleep(30)  # 每30秒更新
            
        except KeyboardInterrupt:
            print("\n\n监控已停止")
            break
        except Exception as e:
            logger.error(f"监控错误: {e}")
            time.sleep(5)


if __name__ == "__main__":
    monitor_loop()