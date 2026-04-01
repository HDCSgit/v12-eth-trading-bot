#!/usr/bin/env python3
"""入场时机详细分析"""
import pandas as pd

# 今日交易数据
trades = [
    {'time': '08:22:49', 'side': 'SELL', 'entry_price': 2060.79, 'exit_price': None, 'pnl_pct': 0.64, 'exit_type': 'EVT_TP'},
    {'time': '09:13:22', 'side': 'SELL', 'entry_price': 2069.16, 'exit_price': None, 'pnl_pct': -2.96, 'exit_type': 'Program_Exit'},
    {'time': '11:05:29', 'side': 'SELL', 'entry_price': 2064.54, 'exit_price': None, 'pnl_pct': 0.53, 'exit_type': 'EVT_TP'},
    {'time': '11:42:12', 'side': 'BUY', 'entry_price': 2064.10, 'exit_price': None, 'pnl_pct': -0.64, 'exit_type': 'Program_Exit'},
    {'time': '13:15:16', 'side': 'SELL', 'entry_price': 2062.47, 'exit_price': None, 'pnl_pct': -2.93, 'exit_type': 'Dynamic_SL'},
    {'time': '13:21:20', 'side': 'SELL', 'entry_price': 2060.13, 'exit_price': None, 'pnl_pct': 0.41, 'exit_type': 'EVT_TP'},
    {'time': '13:25:43', 'side': 'SELL', 'entry_price': 2056.99, 'exit_price': None, 'pnl_pct': 0.41, 'exit_type': 'EVT_TP'},
    {'time': '15:13:26', 'side': 'SELL', 'entry_price': 2057.47, 'exit_price': None, 'pnl_pct': -3.01, 'exit_type': 'Dynamic_SL'},
    {'time': '15:40:38', 'side': 'SELL', 'entry_price': 2061.83, 'exit_price': None, 'pnl_pct': 0.40, 'exit_type': 'EVT_TP'},
    {'time': '16:27:16', 'side': 'BUY', 'entry_price': 2055.32, 'exit_price': None, 'pnl_pct': -3.21, 'exit_type': 'Dynamic_SL'},
]

# 计算理论盈亏（基于PnL推算出场价）
for t in trades:
    if t['side'] == 'SELL':
        # 做空：价格下跌盈利
        t['exit_price'] = t['entry_price'] * (1 + t['pnl_pct']/100)
    else:
        # 做多：价格上涨盈利
        t['exit_price'] = t['entry_price'] * (1 + t['pnl_pct']/100)

print('='*80)
print('2026-03-27 Entry Timing Analysis')
print('='*80)
print()

# 1. 入场准确性分析
print('[1] Entry Direction vs Market Movement')
print('-'*80)

winning_entries = [t for t in trades if t['pnl_pct'] > 0]
losing_entries = [t for t in trades if t['pnl_pct'] < 0]

print(f"Winning entries: {len(winning_entries)}")
for t in winning_entries:
    direction = "SHORT (SELL)" if t['side'] == 'SELL' else "LONG (BUY)"
    print(f"  {t['time']} | {direction:12} | Entry: ${t['entry_price']:.2f} -> Exit: ${t['exit_price']:.2f} | Profit: {t['pnl_pct']:+.2f}%")
    if t['side'] == 'SELL' and t['exit_price'] < t['entry_price']:
        print(f"    -> Correct: Price dropped after SHORT entry")
    elif t['side'] == 'BUY' and t['exit_price'] > t['entry_price']:
        print(f"    -> Correct: Price rose after LONG entry")

print()
print(f"Losing entries: {len(losing_entries)}")
for t in losing_entries:
    direction = "SHORT (SELL)" if t['side'] == 'SELL' else "LONG (BUY)"
    print(f"  {t['time']} | {direction:12} | Entry: ${t['entry_price']:.2f} -> Exit: ${t['exit_price']:.2f} | Loss: {t['pnl_pct']:.2f}%")
    if t['side'] == 'SELL' and t['exit_price'] > t['entry_price']:
        print(f"    -> Wrong: Price rose after SHORT entry (adverse move)")
    elif t['side'] == 'BUY' and t['exit_price'] < t['entry_price']:
        print(f"    -> Wrong: Price dropped after LONG entry (adverse move)")

# 2. 入场时机评估
print()
print('[2] Entry Timing Assessment')
print('-'*80)

# 加载K线数据看入场位置
df = pd.read_csv('eth_usdt_15m_binance.csv')
df['timestamp'] = pd.to_datetime(df['timestamp'])

# 获取今日数据
today_data = df[df['timestamp'] >= '2026-03-27'].copy()
if len(today_data) == 0:
    today_data = df.tail(100).copy()

today_high = today_data['high'].max()
today_low = today_data['low'].min()
today_range = today_high - today_low

print(f"Today's price range: ${today_low:.2f} - ${today_high:.2f} (Range: ${today_range:.2f})")
print()

for t in trades:
    entry = t['entry_price']
    # 计算入场位置在当日区间的百分比 (0% = low, 100% = high)
    position_pct = (entry - today_low) / today_range * 100
    
    if t['side'] == 'SELL':
        # 做空理想位置：高位 (接近100%)
        ideal = 'GOOD' if position_pct > 60 else 'FAIR' if position_pct > 40 else 'POOR'
        comment = 'Near high' if position_pct > 60 else 'Middle' if position_pct > 40 else 'Near low (bad for SHORT)'
    else:
        # 做多理想位置：低位 (接近0%)
        ideal = 'GOOD' if position_pct < 40 else 'FAIR' if position_pct < 60 else 'POOR'
        comment = 'Near low' if position_pct < 40 else 'Middle' if position_pct < 60 else 'Near high (bad for LONG)'
    
    result = 'WIN' if t['pnl_pct'] > 0 else 'LOSS'
    print(f"{t['time']} | {t['side']:4} | Entry: ${entry:.2f} | Position: {position_pct:5.1f}% | {ideal:5} | {comment} | {result}")

# 3. 关键问题识别
print()
print('[3] Key Findings')
print('-'*80)

# 大亏损交易分析
big_losses = [t for t in trades if t['pnl_pct'] < -2.0]
print(f"Big losses (< -2%): {len(big_losses)} trades")
for t in big_losses:
    print(f"  - {t['time']}: {t['side']} @ ${t['entry_price']:.2f}, loss {t['pnl_pct']:.2f}%, exit: {t['exit_type']}")

print()
print('Issues identified:')
print('  1. Entries are often in middle of range (40-60%) - not optimal')
print('  2. SELL entries when price is not near highs - catches falling knives')
print('  3. Dynamic SL triggered on 3 trades with large losses (-2.9% to -3.2%)')
print('  4. Only EVT TP saves profitable trades (small +0.4% to +0.6%)')

print()
print('[4] Recommendations')
print('-'*80)
print('  1. Improve entry timing: wait for better price levels')
print('  2. For SHORT: enter near daily highs (>70% of range)')
print('  3. For LONG: enter near daily lows (<30% of range)')
print('  4. Tighten dynamic SL to -1.5% max (currently allowing -3%+)')
print('  5. Increase position size on high-confidence entries')

print()
print('='*80)
