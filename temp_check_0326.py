#!/usr/bin/env python3
import sqlite3
from datetime import datetime

conn = sqlite3.connect('v12_optimized.db')
cursor = conn.cursor()

print('=' * 80)
print('2026-03-26 交易战报')
print('=' * 80)
print()

# 检查是否有3-26的交易
cursor.execute("""
    SELECT COUNT(*), 
           SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END),
           SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END),
           SUM(pnl_pct),
           AVG(pnl_pct)
    FROM trades 
    WHERE timestamp LIKE '2026-03-26%'
""")

total, wins, losses, total_pnl, avg_pnl = cursor.fetchone()

if not total:
    print('2026-03-26 暂无交易记录')
    print()
    
    # 查看最近的交易时间
    cursor.execute("""
        SELECT timestamp FROM trades 
        ORDER BY timestamp DESC LIMIT 1
    """)
    last_trade = cursor.fetchone()
    if last_trade:
        print('最近交易时间:', last_trade[0])
    print()
    
    # 查看今天的日期范围
    print('当前系统时间参考:', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    
else:
    print('[一、总体统计]')
    print('总交易: %d笔' % total)
    print('盈利: %d笔 (%.0f%%)' % (wins, wins*100/total))
    print('亏损: %d笔 (%.0f%%)' % (losses, losses*100/total))
    print('总盈亏: %+.2f%%' % (total_pnl*100 if total_pnl else 0))
    print('平均单笔: %+.2f%%' % (avg_pnl*100 if avg_pnl else 0))
    print()
    
    # 详细交易记录
    cursor.execute("""
        SELECT timestamp, side, entry_price, exit_price, pnl_pct, result, reason
        FROM trades 
        WHERE timestamp LIKE '2026-03-26%'
        ORDER BY timestamp ASC
    """)
    trades = cursor.fetchall()
    
    print('[二、交易明细]')
    print('-' * 80)
    for t in trades:
        ts, side, entry, exit, pnl, result, reason = t
        time = ts.split('T')[1][:8]
        print('%s | %6s | %.2f->%.2f | %s %+.2f%% | %s' % (
            time, side, entry, exit, result, pnl*100, reason[:30]
        ))
    print('-' * 80)

print('=' * 80)
