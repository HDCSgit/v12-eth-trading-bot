#!/usr/bin/env python3
"""
杠杆和仓位对止盈止损的影响分析
"""

print("=" * 80)
print("杠杆与止盈止损关系分析")
print("=" * 80)
print()

# 假设参数
entry_price = 2200
atr = 15  # ATR值
leverage_options = [3, 5, 10]  # 不同杠杆

print("【一、杠杆对止损的影响】")
print("-" * 80)
print("止损公式: 止损百分比 = ATR倍数 × ATR / 入场价 × 杠杆")
print()

for lev in leverage_options:
    # 1.2x ATR止损
    sl_pct_raw = 1.2 * atr / entry_price  # 不含杠杆的价格变动
    sl_pct_lev = sl_pct_raw * lev  # 加杠杆后的账户盈亏
    
    sl_price = entry_price * (1 + sl_pct_raw)  # 止损价格（做多）
    sl_distance = abs(sl_price - entry_price)
    
    print(f"杠杆 {lev}x:")
    print(f"  价格变动: {sl_pct_raw*100:.2f}% ({sl_distance:.2f} USDT)")
    print(f"  账户亏损: {sl_pct_lev*100:.2f}%")
    print(f"  止损价格: {sl_price:.2f}")
    print()

print("【结论】")
print("✓ 止损价格（绝对值）与杠杆无关")
print("✓ 但账户亏损的百分比随杠杆线性增加")
print("  - 3x杠杆: 止损 ≈ 账户亏损2.45%")
print("  - 5x杠杆: 止损 ≈ 账户亏损4.09%")
print("  - 10x杠杆: 止损 ≈ 账户亏损8.18%")
print()

print("=" * 80)
print("【二、杠杆对止盈的影响】")
print("-" * 80)

# EVT止盈目标（以震荡市0.7%为例）
tp_target_raw = 0.007  # 0.7%价格变动

for lev in leverage_options:
    tp_pct_lev = tp_target_raw * lev  # 加杠杆后的账户盈利
    
    print(f"杠杆 {lev}x:")
    print(f"  EVT目标: {tp_target_raw*100:.2f}% 价格变动")
    print(f"  账户盈利: {tp_pct_lev*100:.2f}%")
    print()

print("【结论】")
print("✓ EVT止盈目标是固定的价格变动百分比（0.7%/1.0%/1.3%）")
print("✓ 与杠杆无关，但账户盈利随杠杆增加")
print("  - 3x杠杆: 止盈 ≈ 账户盈利2.1%")
print("  - 5x杠杆: 止盈 ≈ 账户盈利3.5%")
print("  - 10x杠杆: 止盈 ≈ 账户盈利7.0%")
print()

print("=" * 80)
print("【三、仓位大小对止盈止损的影响】")
print("-" * 80)
print()

balance = 100  # 100 USDT
position_sizes = [0.3, 0.5, 0.8]  # 仓位占比
lev = 5  # 5x杠杆

# 计算实际盈亏金额
tp_price_pct = 0.01  # 1%价格变动
tp_account_pct = tp_price_pct * lev  # 5%账户变动

print(f"假设: 5x杠杆，价格变动{tp_price_pct*100:.1f}%")
print()

for pos_pct in position_sizes:
    notional = balance * pos_pct  # 名义价值
    actual_position = notional * lev  # 实际仓位
    
    pnl_amount = actual_position * tp_price_pct  # 盈亏金额
    pnl_pct_of_balance = pnl_amount / balance  # 相对余额的盈亏
    
    print(f"仓位 {pos_pct*100:.0f}%:")
    print(f"  名义价值: {notional:.2f} USDT")
    print(f"  实际杠杆仓位: {actual_position:.2f} USDT")
    print(f"  价格变动{tp_price_pct*100:.1f}%的盈亏: {pnl_amount:.2f} USDT")
    print(f"  相对总余额: {pnl_pct_of_balance*100:.2f}%")
    print()

print("【结论】")
print("✓ 止盈止损的价格区间（入场价±X%）与仓位大小无关")
print("✓ 但盈亏金额与仓位大小成正比")
print("  - 30%仓位: 盈亏金额较小，风险可控")
print("  - 80%仓位: 盈亏金额较大，收益放大")
print()

print("=" * 80)
print("【四、关键认知】")
print("=" * 80)
print()
print("1. 止盈止损的价格区间是固定的：")
print("   - 止损: 入场价 ± (1.2 × ATR)")
print("   - 止盈: 入场价 ± (0.7%~1.3% 动态)")
print("   - 与杠杆、仓位都无关")
print()
print("2. 影响的是账户盈亏百分比：")
print("   - 高杠杆 → 同样价格变动，账户盈亏放大")
print("   - 大仓位 → 同样价格变动，盈亏金额增加")
print()
print("3. 风险控制的核心：")
print("   - 降低杠杆 → 减小单笔亏损对账户的冲击")
print("   - 降低仓位 → 减小单笔亏损金额")
print("   - 但止盈止损的价格区间不变")
print()
print("=" * 80)
