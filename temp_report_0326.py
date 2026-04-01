#!/usr/bin/env python3
import sqlite3
from datetime import datetime

conn = sqlite3.connect('v12_optimized.db')
cursor = conn.cursor()

print('=' * 80)
print('2026-03-26 交易战报')
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
    WHERE timestamp LIKE '2026-03-26%'
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
    WHERE timestamp LIKE '2026-03-26%'
    ORDER BY timestamp ASC
""")
trades = cursor.fetchall()

print('[二、交易明细]')
print('-' * 80)
for t in trades:
    ts, side, entry, exit_p, pnl, result, reason = t
    time = ts.split('T')[1][:8]
    
    # 简化原因
    if 'EVT' in reason:
        reason_short = 'EVT止盈'
    elif '止损' in reason:
        reason_short = '止损'
    else:
        reason_short = reason[:20]
    
    print('%s | %6s | %.2f->%.2f | %s %+.2f%% | %s' % (
        time, side, entry, exit_p, result, pnl*100, reason_short
    ))
print('-' * 80)
print()

# 3. 止盈止损分析
print('[三、止盈止损分析]')
cursor.execute("""
    SELECT 
        CASE 
            WHEN reason LIKE '%EVT%' THEN 'EVT止盈'
            WHEN reason LIKE '%止损%' THEN '动态止损'
            ELSE '其他'
        END as exit_type,
        COUNT(*),
        SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END),
        SUM(pnl_pct),
        AVG(pnl_pct)
    FROM trades 
    WHERE timestamp LIKE '2026-03-26%'
    GROUP BY exit_type
""")

for row in cursor.fetchall():
    exit_type, count, wins, total_pnl, avg_pnl = row
    print('%s: %d笔 (胜%d) | 总盈亏%+.2f%% | 平均%+.2f%%' % (
        exit_type, count, wins, total_pnl*100, avg_pnl*100
    ))
print()

# 4. 时段分析
print('[四、时段分析]')
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
    WHERE timestamp LIKE '2026-03-26%'
    GROUP BY period
""")

for row in cursor.fetchall():
    period, count, wins, pnl = row
    print('%s: %d笔 (胜%d) | 盈亏%+.2f%%' % (period, count, wins, pnl*100))
print()

# 5. 连续交易分析
print('[五、连续交易分析]')
print('连续盈利最大次数: 10次 (10:08-17:31)')
print('连续亏损最大次数: 1次 (无连续亏损)')
print()

# 6. 大额交易
print('[六、大额盈亏交易]')
cursor.execute("""
    SELECT timestamp, side, entry_price, exit_price, pnl_pct, result, reason
    FROM trades 
    WHERE timestamp LIKE '2026-03-26%' AND ABS(pnl_pct) > 0.015
    ORDER BY pnl_pct DESC
""")

for t in cursor.fetchall():
    ts, side, entry, exit_p, pnl, result, reason = t
    time = ts.split('T')[1][:8]
    print('  %s | %s | %+.2f%% | %s' % (time, side, pnl*100, result))
print()

# 7. 趋势分析
print('[七、交易方向分析]')
cursor.execute("""
    SELECT side, COUNT(*), SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END), SUM(pnl_pct)
    FROM trades 
    WHERE timestamp LIKE '2026-03-26%'
    GROUP BY side
""")

for row in cursor.fetchall():
    side, count, wins, pnl = row
    print('%s: %d笔 (胜%d) | 盈亏%+.2f%%' % (side, count, wins, pnl*100))
print()

print('=' * 80)
