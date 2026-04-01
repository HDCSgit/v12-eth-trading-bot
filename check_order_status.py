#!/usr/bin/env python3
"""
检查指定订单的实际状态
"""

from binance_api import BinanceExpertAPI
from datetime import datetime

api = BinanceExpertAPI()
symbol = "ETHUSDT"

print("=" * 70)
print("  币安订单状态查询")
print("=" * 70)

# 查询最近的所有订单（包括已成交和未成交）
print("\n1. 查询最近订单...")
orders = api._request(
    'GET', '/fapi/v1/allOrders',
    {'symbol': symbol, 'limit': 10},
    signed=True
)

if orders and isinstance(orders, list):
    print(f"\n最近{len(orders)}笔订单:")
    print(f"{'订单ID':<20} {'类型':<8} {'方向':<6} {'价格':<12} {'数量':<8} {'状态':<10} {'时间'}")
    print("-" * 90)
    
    for order in orders:
        order_id = order.get('orderId')
        order_type = order.get('type')
        side = order.get('side')
        price = float(order.get('price', 0))
        qty = float(order.get('qty', 0))
        status = order.get('status')
        time_ms = order.get('time', 0)
        
        # 检查是否是Maker
        is_maker = order.get('isMaker', False)
        
        dt = datetime.fromtimestamp(time_ms/1000).strftime('%H:%M:%S')
        
        maker_mark = "[M]" if is_maker else "[T]"
        
        print(f"{order_id:<20} {order_type:<8} {side:<6} ${price:<11.2f} {qty:<8.4f} {status:<10} {dt} {maker_mark}")

# 查询成交记录
print("\n" + "=" * 70)
print("  成交记录 (User Trades)")
print("=" * 70)

trades = api._request(
    'GET', '/fapi/v1/userTrades',
    {'symbol': symbol, 'limit': 10},
    signed=True
)

if trades and isinstance(trades, list):
    print(f"\n最近{len(trades)}笔成交:")
    print(f"{'时间':<12} {'方向':<6} {'价格':<12} {'数量':<8} {'Maker/Taker':<12} {'手续费'}")
    print("-" * 70)
    
    total_maker_fee = 0
    total_taker_fee = 0
    
    for trade in trades:
        ts = datetime.fromtimestamp(trade['time']/1000).strftime('%H:%M:%S')
        side = trade['side']
        price = float(trade['price'])
        qty = float(trade['qty'])
        commission = float(trade['commission'])
        is_maker = trade.get('maker', False)
        
        role = "Maker" if is_maker else "Taker"
        
        print(f"{ts:<12} {side:<6} ${price:<11.2f} {qty:<8.4f} {role:<12} ${commission:.6f}")
        
        # 计算费率
        notional = qty * price
        fee_rate = commission / notional if notional > 0 else 0
        
        if is_maker:
            total_maker_fee += commission
        else:
            total_taker_fee += commission
    
    print("-" * 70)
    print(f"\nMaker手续费总计: ${total_maker_fee:.6f}")
    print(f"Taker手续费总计: ${total_taker_fee:.6f}")

# 对比系统记录
print("\n" + "=" * 70)
print("  系统数据库记录")
print("=" * 70)

import sqlite3
conn = sqlite3.connect('v12_optimized.db')
cursor = conn.execute('''
    SELECT timestamp, side, entry_price, qty, order_type, pnl_usdt
    FROM trades
    ORDER BY timestamp DESC
    LIMIT 5
''')

rows = cursor.fetchall()
if rows:
    print(f"\n最近5笔:")
    print(f"{'时间':<20} {'方向':<6} {'价格':<10} {'数量':<8} {'系统记录':<10} {'盈亏'}")
    print("-" * 70)
    for row in rows:
        ts, side, price, qty, order_type, pnl = row
        ts_short = ts[11:19] if len(ts) > 19 else ts
        ot = order_type or 'TAKER'
        print(f"{ts_short:<20} {side:<6} ${price:<9.2f} {qty:<8.4f} {ot:<10} {pnl:+.4f}")

conn.close()

print("\n" + "=" * 70)
print("  [提示] 对比系统记录 vs 币安实际成交，检查是否一致")
print("=" * 70)
