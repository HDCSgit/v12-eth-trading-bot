#!/usr/bin/env python3
import sqlite3
import pandas as pd
from datetime import datetime, timedelta

conn = sqlite3.connect('v12_optimized.db')
now = datetime.now()
yesterday_23h = now.replace(hour=23, minute=0, second=0, microsecond=0) - timedelta(days=1)

query = '''
SELECT timestamp, side, pnl_pct, pnl_usdt, result, regime, signal_source
FROM trades WHERE timestamp >= ? ORDER BY timestamp
'''

df = pd.read_sql_query(query, conn, params=(yesterday_23h.isoformat(),))

print('=== ETHUSDT 交易分析报告 ===')
print('时间:', yesterday_23h.strftime('%m-%d %H:%M'), '至', now.strftime('%m-%d %H:%M'))
print('总交易:', len(df), '笔')

if len(df) == 0:
    print('无交易记录')
    conn.close()
    exit()

wins = len(df[df['result'] == 'WIN'])
losses = len(df[df['result'] == 'LOSS'])
print('胜负:', wins, '胜 /', losses, '负')
print('胜率:', round(wins/len(df)*100, 1), '%')
print('总盈亏:', round(df['pnl_usdt'].sum(), 2), 'USDT')
print('总盈亏:', round(df['pnl_pct'].sum()*100, 2), '%')

avg_win = df[df['result'] == 'WIN']['pnl_pct'].mean() * 100 if wins > 0 else 0
avg_loss = df[df['result'] == 'LOSS']['pnl_pct'].mean() * 100 if losses > 0 else 0
print('平均盈利:', round(avg_win, 2), '%')
print('平均亏损:', round(avg_loss, 2), '%')

pf = abs(avg_win * wins / (avg_loss * losses)) if avg_loss != 0 and losses > 0 else 0
print('盈亏比:', round(pf, 2))

print()
print('=== 市场环境分析 ===')
for regime in df['regime'].unique():
    subset = df[df['regime'] == regime]
    w = len(subset[subset['result'] == 'WIN'])
    wr = w / len(subset) * 100
    pnl = subset['pnl_pct'].sum() * 100
    print(regime + ':', len(subset), '笔, 胜率' + str(round(wr, 1)) + '%, 盈亏' + str(round(pnl, 2)) + '%')

print()
print('=== 多空分析 ===')
longs = df[df['side'].isin(['BUY', 'LONG'])]
shorts = df[df['side'].isin(['SELL', 'SHORT'])]
if len(longs) > 0:
    lw = len(longs[longs['result'] == 'WIN'])
    print('做多:', len(longs), '笔, 胜率' + str(round(lw/len(longs)*100, 1)) + '%, 盈亏' + str(round(longs['pnl_pct'].sum()*100, 2)) + '%')
if len(shorts) > 0:
    sw = len(shorts[shorts['result'] == 'WIN'])
    print('做空:', len(shorts), '笔, 胜率' + str(round(sw/len(shorts)*100, 1)) + '%, 盈亏' + str(round(shorts['pnl_pct'].sum()*100, 2)) + '%')

print()
print('=== 最近5笔 ===')
for _, row in df.tail(5).iterrows():
    ts = pd.to_datetime(row['timestamp']).strftime('%m-%d %H:%M')
    print(ts, '|', row['side'][:4], '|', row['result'], '|', str(round(row['pnl_pct']*100, 2)) + '%', '|', row['regime'])

conn.close()
