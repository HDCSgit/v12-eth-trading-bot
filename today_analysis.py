#!/usr/bin/env python3
trades = [
    {'time': '08:22:49', 'side': 'SELL', 'result': 'WIN', 'pnl_pct': 0.64, 'pnl_usd': 0.05, 'exit': 'EVT_TP'},
    {'time': '09:13:22', 'side': 'SELL', 'result': 'LOSS', 'pnl_pct': -2.96, 'pnl_usd': -0.22, 'exit': 'Program_Exit'},
    {'time': '11:05:29', 'side': 'SELL', 'result': 'WIN', 'pnl_pct': 0.53, 'pnl_usd': 0.04, 'exit': 'EVT_TP'},
    {'time': '11:42:12', 'side': 'BUY', 'result': 'LOSS', 'pnl_pct': -0.64, 'pnl_usd': -0.05, 'exit': 'Program_Exit'},
    {'time': '13:15:16', 'side': 'SELL', 'result': 'LOSS', 'pnl_pct': -2.93, 'pnl_usd': -0.22, 'exit': 'Dynamic_SL'},
    {'time': '13:21:20', 'side': 'SELL', 'result': 'WIN', 'pnl_pct': 0.41, 'pnl_usd': 0.03, 'exit': 'EVT_TP'},
    {'time': '13:25:43', 'side': 'SELL', 'result': 'WIN', 'pnl_pct': 0.41, 'pnl_usd': 0.03, 'exit': 'EVT_TP'},
    {'time': '15:13:26', 'side': 'SELL', 'result': 'LOSS', 'pnl_pct': -3.01, 'pnl_usd': -0.22, 'exit': 'Dynamic_SL'},
    {'time': '15:40:38', 'side': 'SELL', 'result': 'WIN', 'pnl_pct': 0.40, 'pnl_usd': 0.03, 'exit': 'EVT_TP'},
    {'time': '16:27:16', 'side': 'BUY', 'result': 'LOSS', 'pnl_pct': -3.21, 'pnl_usd': -0.24, 'exit': 'Dynamic_SL'},
]

total = len(trades)
wins = [t for t in trades if t['result'] == 'WIN']
losses = [t for t in trades if t['result'] == 'LOSS']
win_pnl = sum(t['pnl_pct'] for t in wins)
loss_pnl = sum(t['pnl_pct'] for t in losses)
total_pnl = win_pnl + loss_pnl
total_usd = sum(t['pnl_usd'] for t in trades)

print('='*60)
print('2026-03-27 Trading Analysis')
print('='*60)
print()
print('[Summary]')
print(f'  Total Trades: {total}')
print(f'  Wins: {len(wins)} | Losses: {len(losses)}')
print(f'  Win Rate: {len(wins)/total*100:.1f}%')
print(f'  Total PnL: {total_pnl:+.2f}% (${total_usd:+.2f})')
print()
print('[Avg Stats]')
avg_win = win_pnl/len(wins)
avg_loss = loss_pnl/len(losses)
print(f'  Avg Win: +{avg_win:.2f}%')
print(f'  Avg Loss: {avg_loss:.2f}%')
pf = abs(win_pnl/loss_pnl) if loss_pnl != 0 else 0
print(f'  Profit Factor: {pf:.2f}')
print()
print('[By Exit Type]')
evt = [t for t in trades if 'EVT' in t['exit']]
sl = [t for t in trades if 'SL' in t['exit']]
prog = [t for t in trades if 'Program' in t['exit']]
evt_pnl = sum(t['pnl_pct'] for t in evt)
sl_pnl = sum(t['pnl_pct'] for t in sl)
prog_pnl = sum(t['pnl_pct'] for t in prog)
print(f'  EVT TP: {len(evt)} trades, PnL: {evt_pnl:+.2f}%')
print(f'  Dynamic SL: {len(sl)} trades, PnL: {sl_pnl:+.2f}%')
print(f'  Program Exit: {len(prog)} trades, PnL: {prog_pnl:+.2f}%')
print()
print('[Trades]')
for t in trades:
    status = 'WIN ' if t['result'] == 'WIN' else 'LOSS'
    print(f"  {t['time']} | {status} | {t['side']:4} | {t['pnl_pct']:+6.2f}% | {t['exit']}")
print()
print('='*60)
print('[Key Findings]')
print(f'  1. Losses ({abs(avg_loss):.2f}%) are 5x larger than wins ({avg_win:.2f}%)')
print(f'  2. Dynamic SL caused {len(sl)} losses totaling {sl_pnl:+.2f}%')
print(f'  3. Program exits also problematic: {prog_pnl:+.2f}%')
print(f'  4. Only EVT TP working well: +{evt_pnl:.2f}%')
print('='*60)
