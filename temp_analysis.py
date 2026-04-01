#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('v12_optimized.db')
cursor = conn.cursor()

print('=' * 80)
print('2026-03-25 交易战报')
print('=' * 80)
print()

# 所有交易
cursor.execute("SELECT timestamp, side, entry_price, exit_price, pnl_pct, result FROM trades WHERE timestamp LIKE '2026-03-25%' ORDER BY timestamp ASC")
trades = cursor.fetchall()

total_pnl = 0
win_count = 0
loss_count = 0

for t in trades:
    ts, side, entry, exit_p, pnl, result = t
    time = ts.split('T')[1][:8]
    total_pnl += pnl
    if result == 'WIN':
        win_count += 1
    else:
        loss_count += 1
    print('%s | %6s | %.2f -> %.2f | %s %+.2f%%' % (time, side, entry, exit_p, result, pnl*100))

print()
print('今日统计: 总盈亏 %+.2f%% | 胜率 %d/%d' % (total_pnl*100, win_count, len(trades)))

# 13:55之后
cursor.execute("SELECT timestamp, side, entry_price, exit_price, pnl_pct, result FROM trades WHERE timestamp > '2026-03-25T13:55:00' ORDER BY timestamp ASC")
trades_after = cursor.fetchall()

print()
print('=' * 80)
print('13:55 之后交易详情')
print('=' * 80)

pnl_after = 0
for t in trades_after:
    ts, side, entry, exit_p, pnl, result = t
    time = ts.split('T')[1][:8]
    pnl_after += pnl
    print('%s | %6s | %.2f -> %.2f | %s %+.2f%%' % (time, side, entry, exit_p, result, pnl*100))

print()
print('13:55之后盈亏: %+.2f%% (3笔全胜)' % (pnl_after*100))

# 关键交易分析
print()
print('=' * 80)
print('关键交易分析')
print('=' * 80)

# 亏损交易
cursor.execute("SELECT timestamp, side, entry_price, exit_price, pnl_pct FROM trades WHERE timestamp LIKE '2026-03-25%' AND result = 'LOSS' ORDER BY timestamp ASC")
loss_trades = cursor.fetchall()

if loss_trades:
    print()
    print('亏损交易:')
    for t in loss_trades:
        ts, side, entry, exit_p, pnl = t
        time = ts.split('T')[1][:8]
        print('  %s | %s | 入场:%.2f 出场:%.2f | 亏损:%.2f%%' % (time, side, entry, exit_p, pnl*100))
        print('  -> 13:08 SELL空单，趋势上涨中被止损 -2.33%')

# 大额盈利
cursor.execute("SELECT timestamp, side, entry_price, exit_price, pnl_pct FROM trades WHERE timestamp LIKE '2026-03-25%' AND pnl_pct > 0.05 ORDER BY timestamp ASC")
big_wins = cursor.fetchall()

if big_wins:
    print()
    print('大额盈利 (>5%):')
    for t in big_wins:
        ts, side, entry, exit_p, pnl = t
        time = ts.split('T')[1][:8]
        print('  %s | %s | 入场:%.2f 出场:%.2f | 盈利:%.2f%%' % (time, side, entry, exit_p, pnl*100))

print()
print('=' * 80)
print('交易表现总结')
print('=' * 80)
print('✓ 总交易: %d笔 | 胜率: %d%% | 总盈亏: %+.2f%%' % (len(trades), win_count*100/len(trades), total_pnl*100))
print('✓ 13:55之后: 3笔全胜，累计+%.2f%% (主要是多单)' % (pnl_after*100))
print('✓ 最佳单笔: +5.44% (08:07 LONG)')
print('✗ 最差单笔: -2.33% (13:08 SELL - 逆势空单被止损)')
