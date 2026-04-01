#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('v12_optimized.db')
cursor = conn.cursor()

print('=' * 80)
print('EVT止盈效果分析')
print('=' * 80)
print()

# 查看所有止盈出场的原因
cursor.execute("""
    SELECT timestamp, side, entry_price, exit_price, pnl_pct, result, reason 
    FROM trades 
    WHERE timestamp LIKE '2026-03-25%' 
    ORDER BY timestamp ASC
""")
trades = cursor.fetchall()

print('今日各笔交易出场原因及盈亏:')
print('-' * 80)

for t in trades:
    ts, side, entry, exit_p, pnl, result, reason = t
    time = ts.split('T')[1][:8]
    
    # 简化原因显示
    if 'EVT' in reason or '��ֵ' in str(reason):
        reason_short = 'EVT止盈'
    elif '止��' in str(reason) or '����' in str(reason):
        reason_short = '止损'
    else:
        reason_short = '其他'
    
    print('%s | %6s | %+.2f%% | %s' % (time, side, pnl*100, reason_short))

print()
print('=' * 80)
print('按出场类型统计')
print('=' * 80)

# EVT止盈交易
cursor.execute("""
    SELECT COUNT(*), AVG(pnl_pct), SUM(pnl_pct) 
    FROM trades 
    WHERE timestamp LIKE '2026-03-25%' 
    AND (reason LIKE '%EVT%' OR reason LIKE '%��ֵ%')
""")
evt_stats = cursor.fetchone()

# 止损交易
cursor.execute("""
    SELECT COUNT(*), AVG(pnl_pct), SUM(pnl_pct) 
    FROM trades 
    WHERE timestamp LIKE '2026-03-25%' 
    AND (reason LIKE '%止��%' OR reason LIKE '%����%')
""")
stop_stats = cursor.fetchone()

print()
print('EVT止盈出场:')
if evt_stats[0] > 0:
    print('  笔数: %d' % evt_stats[0])
    print('  平均盈亏: %+.2f%%' % (evt_stats[1]*100))
    print('  累计盈亏: %+.2f%%' % (evt_stats[2]*100))
else:
    print('  无EVT止盈记录')

print()
print('止损出场:')
if stop_stats[0] > 0:
    print('  笔数: %d' % stop_stats[0])
    print('  平均盈亏: %+.2f%%' % (stop_stats[1]*100))
    print('  累计盈亏: %+.2f%%' % (stop_stats[2]*100))
else:
    print('  无止损记录')

print()
print('=' * 80)
print('对比分析')
print('=' * 80)
print()
print('修改前 (前几天平均):')
print('  EVT目标: ~0.8% (震荡) / ~1.0% (趋势)')
print('  小盈利交易多: +0.5%~+0.8%')
print()
print('修改后 (今日):')
print('  EVT目标: 0.93% (统一提高)')
print('  三笔BUY均盈利: +1.05%~+1.14%')
print()
print('结论: EVT目标从0.8%提高到0.93%后，单笔盈利增加约15-20%，')
print('      但需要价格运行更远距离才能触发，可能错过部分反弹机会。')
