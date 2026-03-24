#!/usr/bin/env python3
"""
分析昨天23点到目前的交易情况
"""
import sqlite3
import pandas as pd
from datetime import datetime, timedelta

# 连接数据库
conn = sqlite3.connect('v12_optimized.db')

# 获取昨天23点和今天的时间范围
now = datetime.now()
yesterday_23h = now.replace(hour=23, minute=0, second=0, microsecond=0) - timedelta(days=1)

print("=" * 80)
print(f"ETHUSDT 交易分析报告")
print(f"时间范围: {yesterday_23h.strftime('%Y-%m-%d %H:%M')} 至 {now.strftime('%Y-%m-%d %H:%M')}")
print("=" * 80)

# 查询交易数据
query = """
SELECT 
    timestamp, symbol, side, entry_price, exit_price, qty, 
    pnl_pct, pnl_usdt, result, reason, signal_source, confidence, regime
FROM trades
WHERE timestamp >= ?
ORDER BY timestamp
"""

df = pd.read_sql_query(query, conn, params=(yesterday_23h.isoformat(),))

if len(df) == 0:
    print("\n⚠️ 该时间段内没有交易记录")
    conn.close()
    exit()

# 基础统计
print(f"\n【一、基础统计】")
print(f"总交易笔数: {len(df)}")
print(f"总盈亏(USDT): ${df['pnl_usdt'].sum():+.2f}")
print(f"总盈亏(%): {df['pnl_pct'].sum()*100:+.2f}%")

wins = len(df[df['result'] == 'WIN'])
losses = len(df[df['result'] == 'LOSS'])
win_rate = wins / len(df) * 100 if len(df) > 0 else 0

print(f"\n胜场: {wins} | 负场: {losses}")
print(f"胜率: {win_rate:.1f}%")

# 盈亏分析
avg_win = df[df['result'] == 'WIN']['pnl_pct'].mean() * 100 if wins > 0 else 0
avg_loss = df[df['result'] == 'LOSS']['pnl_pct'].mean() * 100 if losses > 0 else 0
profit_factor = abs(avg_win * wins / (avg_loss * losses)) if avg_loss != 0 and losses > 0 else 0

print(f"\n平均盈利: {avg_win:+.2f}%")
print(f"平均亏损: {avg_loss:+.2f}%")
print(f"盈亏比: {profit_factor:.2f}")

# 按市场环境分析
print(f"\n【二、市场环境分析】")
print("-" * 80)
regime_stats = df.groupby('regime').agg({
    'pnl_pct': ['count', 'mean', 'sum'],
    'result': lambda x: (x == 'WIN').sum()
}).round(4)

for regime in df['regime'].unique():
    subset = df[df['regime'] == regime]
    total = len(subset)
    wins_regime = len(subset[subset['result'] == 'WIN'])
    wr = wins_regime / total * 100 if total > 0 else 0
    total_pnl = subset['pnl_pct'].sum() * 100
    avg_pnl = subset['pnl_pct'].mean() * 100
    
    print(f"\n{regime}:")
    print(f"  交易笔数: {total}")
    print(f"  胜率: {wr:.1f}%")
    print(f"  总盈亏: {total_pnl:+.2f}%")
    print(f"  平均盈亏: {avg_pnl:+.2f}%")

# 按信号来源分析
print(f"\n【三、信号来源分析】")
print("-" * 80)
source_stats = df.groupby('signal_source').agg({
    'pnl_pct': ['count', 'mean', 'sum'],
    'result': lambda x: (x == 'WIN').sum()
})
print(source_stats)

# 按方向分析
print(f"\n【四、多空方向分析】")
print("-" * 80)
longs = df[df['side'].isin(['BUY', 'LONG'])]
shorts = df[df['side'].isin(['SELL', 'SHORT'])]

print(f"\n做多交易: {len(longs)}笔")
if len(longs) > 0:
    long_wins = len(longs[longs['result'] == 'WIN'])
    print(f"  胜率: {long_wins/len(longs)*100:.1f}%")
    print(f"  总盈亏: {longs['pnl_pct'].sum()*100:+.2f}%")

print(f"\n做空交易: {len(shorts)}笔")
if len(shorts) > 0:
    short_wins = len(shorts[shorts['result'] == 'WIN'])
    print(f"  胜率: {short_wins/len(shorts)*100:.1f}%")
    print(f"  总盈亏: {shorts['pnl_pct'].sum()*100:+.2f}%")

# 连续交易分析
print(f"\n【五、连续交易分析】")
print("-" * 80)
results = df['result'].tolist()
max_consecutive_wins = 0
max_consecutive_losses = 0
current_wins = 0
current_losses = 0

for r in results:
    if r == 'WIN':
        current_wins += 1
        current_losses = 0
        max_consecutive_wins = max(max_consecutive_wins, current_wins)
    else:
        current_losses += 1
        current_wins = 0
        max_consecutive_losses = max(max_consecutive_losses, current_losses)

print(f"最大连续盈利: {max_consecutive_wins}笔")
print(f"最大连续亏损: {max_consecutive_losses}笔")

# 交易时间分布
print(f"\n【六、交易时间分布】")
print("-" * 80)
df['hour'] = pd.to_datetime(df['timestamp']).dt.hour
hourly_stats = df.groupby('hour').size()
print("各时段交易笔数:")
for hour, count in hourly_stats.items():
    print(f"  {hour:02d}:00 - {count}笔")

# 最新交易详情
print(f"\n【七、最近5笔交易详情】")
print("-" * 80)
recent = df.tail(5)
for idx, row in recent.iterrows():
    ts = pd.to_datetime(row['timestamp']).strftime('%m-%d %H:%M')
    print(f"\n{ts} | {row['side']} | {row['result']}")
    print(f"  盈亏: {row['pnl_pct']*100:+.2f}% | ${row['pnl_usdt']:+.2f}")
    print(f"  环境: {row['regime']} | 来源: {row['signal_source']}")
    print(f"  置信度: {row['confidence']:.2f}")
    print(f"  原因: {row['reason'][:60]}...")

# 问题诊断
print(f"\n【八、问题诊断与建议】")
print("-" * 80)

issues = []

# 1. 趋势市胜率检查
trend_trades = df[df['regime'].isin(['趋势上涨', '趋势下跌'])]
if len(trend_trades) > 0:
    trend_wins = len(trend_trades[trend_trades['result'] == 'WIN'])
    trend_wr = trend_wins / len(trend_trades) * 100
    if trend_wr < 40:
        issues.append(f"⚠️ 趋势市胜率仅{trend_wr:.1f}%，顺势过滤可能仍需优化")
    else:
        print(f"✅ 趋势市胜率{trend_wr:.1f}%，顺势策略生效")

# 2. 震荡市胜率检查
sideways_trades = df[df['regime'].isin(['震荡市', '震荡上行', '震荡下行'])]
if len(sideways_trades) > 0:
    sw_wins = len(sideways_trades[sideways_trades['result'] == 'WIN'])
    sw_wr = sw_wins / len(sideways_trades) * 100
    if sw_wr < 50:
        issues.append(f"⚠️ 震荡市胜率仅{sw_wr:.1f}%，网格策略需优化")
    else:
        print(f"✅ 震荡市胜率{sw_wr:.1f}%，网格策略有效")

# 3. 连续亏损检查
if max_consecutive_losses >= 5:
    issues.append(f"🚨 出现{max_consecutive_losses}笔连续亏损，风控需关注")

# 4. 盈亏比检查
if profit_factor < 1.0:
    issues.append(f"⚠️ 盈亏比{profit_factor:.2f}<1，平均盈利小于平均亏损")

# 5. 极端亏损交易
big_losses = df[df['pnl_pct'] < -0.02]  # 亏损>2%
if len(big_losses) > 0:
    issues.append(f"⚠️ 有{len(big_losses)}笔亏损>2%的交易，止损是否过宽？")

if not issues:
    print("✅ 未发现明显问题")
else:
    for issue in issues:
        print(issue)

print("\n" + "=" * 80)
conn.close()
