#!/usr/bin/env python3
import sqlite3
from datetime import datetime

conn = sqlite3.connect('v12_optimized.db')
cursor = conn.cursor()

print('=' * 80)
print('2026-03-25 交易战报')
print('=' * 80)
print()

# 1. 总体统计
cursor.execute("""
    SELECT COUNT(*), 
           SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END),
           SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END),
           SUM(pnl_pct),
           AVG(pnl_pct)
    FROM trades 
    WHERE timestamp LIKE '2026-03-25%'
""")
total, wins, losses, total_pnl, avg_pnl = cursor.fetchone()

print('[一、总体统计]')
print('总交易: %d笔' % total)
print('盈利: %d笔 (%.0f%%)' % (wins, wins*100/total if total else 0))
print('亏损: %d笔 (%.0f%%)' % (losses, losses*100/total if total else 0))
print('总盈亏: %+.2f%%' % (total_pnl*100 if total_pnl else 0))
print('平均单笔: %+.2f%%' % (avg_pnl*100 if avg_pnl else 0))
print()

# 2. 详细交易记录
cursor.execute("""
    SELECT timestamp, side, entry_price, exit_price, pnl_pct, result, reason
    FROM trades 
    WHERE timestamp LIKE '2026-03-25%'
    ORDER BY timestamp ASC
""")
trades = cursor.fetchall()

print('[二、交易明细]')
print('-' * 80)
for t in trades:
    ts, side, entry, exit, pnl, result, reason = t
    time = ts.split('T')[1][:8]
    
    # 简化原因
    if 'EVT' in reason:
        reason_short = 'EVT止盈'
    elif '止损' in reason or 'stop' in reason.lower():
        reason_short = '止损'
    elif '回撤' in reason:
        reason_short = '回撤止盈'
    else:
        reason_short = reason[:20]
    
    print('%s | %6s | %.2f->%.2f | %s %+.2f%% | %s' % (
        time, side, entry, exit, result, pnl*100, reason_short
    ))
print('-' * 80)
print()

# 3. 按出场原因分组统计
print('[三、止盈止损分析]')
cursor.execute("""
    SELECT 
        CASE 
            WHEN reason LIKE '%EVT%' THEN 'EVT止盈'
            WHEN reason LIKE '%止损%' OR reason LIKE '%stop%' THEN '止损'
            WHEN reason LIKE '%回撤%' THEN '回撤止盈'
            ELSE '其他'
        END as exit_type,
        COUNT(*),
        SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END),
        SUM(pnl_pct),
        AVG(pnl_pct)
    FROM trades 
    WHERE timestamp LIKE '2026-03-25%'
    GROUP BY exit_type
""")

for row in cursor.fetchall():
    exit_type, count, wins, total_pnl, avg_pnl = row
    print('%s: %d笔 (胜%d) | 总盈亏%+.2f%% | 平均%+.2f%%' % (
        exit_type, count, wins, total_pnl*100, avg_pnl*100
    ))
print()

# 4. 大额盈亏分析
print('[四、大额盈亏分析]')
cursor.execute("""
    SELECT timestamp, side, pnl_pct, result
    FROM trades 
    WHERE timestamp LIKE '2026-03-25%' AND ABS(pnl_pct) > 0.03
    ORDER BY pnl_pct DESC
""")
big_trades = cursor.fetchall()

if big_trades:
    for t in big_trades:
        ts, side, pnl, result = t
        time = ts.split('T')[1][:8]
        print('  %s | %s | %+.2f%% | %s' % (time, side, pnl*100, result))
else:
    print('  无大额盈亏(>3%)交易')
print()

# 5. 时间分布分析
print('[五、时段分析]')
cursor.execute("""
    SELECT 
        CASE 
            WHEN CAST(SUBSTR(timestamp, 12, 2) AS INTEGER) < 12 THEN '上午(00-12)'
            WHEN CAST(SUBSTR(timestamp, 12, 2) AS INTEGER) < 18 THEN '下午(12-18)'
            ELSE '晚上(18-24)'
        END as period,
        COUNT(*),
        SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END),
        SUM(pnl_pct)
    FROM trades 
    WHERE timestamp LIKE '2026-03-25%'
    GROUP BY period
""")

for row in cursor.fetchall():
    period, count, wins, pnl = row
    print('%s: %d笔 (胜%d) | 盈亏%+.2f%%' % (period, count, wins, pnl*100))
print()

# 6. 当前持仓
print('[六、当前持仓状态]')
cursor.execute("""
    SELECT timestamp, side, entry_price, exit_price, pnl_pct, result
    FROM trades 
    ORDER BY timestamp DESC
    LIMIT 1
""")
last_trade = cursor.fetchone()

if last_trade:
    ts, side, entry, exit_p, pnl, result = last_trade
    # 检查是否是今天的未平仓交易（exit_price为0或result为空）
    if '2026-03-25' in ts and (exit_p == 0 or exit_p is None or result not in ['WIN', 'LOSS']):
        print('  持有仓位: %s @ %.2f' % (side, entry))
        print('  开仓时间: %s' % ts.split('T')[1][:8])
    else:
        print('  当前无持仓')
else:
    print('  无交易记录')
print()

print('=' * 80)
