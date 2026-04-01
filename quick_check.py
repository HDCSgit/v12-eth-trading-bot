#!/usr/bin/env python3
"""快速检查最近交易"""
import sqlite3
from datetime import datetime

conn = sqlite3.connect('v12_optimized.db')

print("=" * 70)
print("  最近交易检查")
print("=" * 70)

# 检查最近的开仓记录
cursor = conn.execute('''
    SELECT timestamp, side, entry_price, qty, order_type, pnl_pct, pnl_usdt
    FROM trades 
    ORDER BY timestamp DESC 
    LIMIT 5
''')

rows = cursor.fetchall()

print(f"\n最近5笔交易:")
print(f"{'时间':<20} {'方向':<6} {'价格':<10} {'数量':<8} {'类型':<8} {'盈亏':<12}")
print("-" * 70)

for row in rows:
    ts, side, price, qty, order_type, pnl_pct, pnl_usdt = row
    ts_short = ts[11:19] if len(ts) > 19 else ts
    ot = order_type or 'TAKER'
    print(f"{ts_short:<20} {side:<6} ${price:<9.2f} {qty:<8.4f} {ot:<8} {pnl_usdt:>+10.4f}")

# 统计今天的Maker/Taker比例
cursor = conn.execute('''
    SELECT 
        order_type,
        COUNT(*) as count,
        SUM(qty) as total_qty,
        SUM(CASE WHEN order_type='MAKER' THEN qty * entry_price * 0.0004 
                 WHEN order_type='HYBRID' THEN qty * entry_price * 0.00035
                 ELSE qty * entry_price * 0.001 END) as estimated_fee
    FROM trades 
    WHERE timestamp LIKE ?
    GROUP BY order_type
''', (f"{datetime.now().strftime('%Y-%m-%d')}%",))

print("\n" + "=" * 70)
print("  今日订单类型统计")
print("=" * 70)

total_qty = 0
saved = 0

for row in cursor.fetchall():
    ot, count, qty, fee = row
    ot_str = ot or 'TAKER'
    total_qty += qty
    print(f"{ot_str:<10}: {count}笔, 总量{qty:.4f}ETH, 预估手续费${fee:.4f}")
    
    # 计算节省
    if ot_str == 'MAKER':
        saved += qty * 2000 * 0.0006  # 节省0.06% (0.1% - 0.04%)

print(f"\n总持仓量: {total_qty:.4f}ETH")
if saved > 0:
    print(f"今日预估节省: ${saved:.4f}")

conn.close()
