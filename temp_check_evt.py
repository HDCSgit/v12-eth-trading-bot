#!/usr/bin/env python3
from take_profit_manager import get_tp_manager, TPSignalType

tp_manager = get_tp_manager()

# 获取统计
print('=== 止盈策略绩效报告 ===')
print()

# 检查是否有EVT记录
evt_records = [r for r in tp_manager.records if r.signal_type == TPSignalType.EVT_EXTREME]
print('内存中EVT记录数:', len(evt_records))

if evt_records:
    print()
    print('最近3条EVT记录:')
    for r in evt_records[-3:]:
        time_str = r.timestamp.strftime('%H:%M:%S')
        pnl = r.pnl_pct * 100
        shape = r.evt_shape
        target = r.evt_expected_return * 100 if r.evt_expected_return else 0
        print('  %s | %s | %+.2f%% | shape=%.3f | target=%.2f%%' % (time_str, r.side, pnl, shape, target))

print()
print('各策略统计:')
df = tp_manager.get_strategy_performance()
if not df.empty:
    print(df.to_string(index=False))
else:
    print('  暂无数据（需要重启后重新记录）')
