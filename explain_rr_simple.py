#!/usr/bin/env python3
"""
盈亏比过滤 - 详细计算过程
"""

print("=" * 70)
print("盈亏比过滤计算方法")
print("=" * 70)
print()

print("【公式】")
print("  对于做空(SELL):")
print("    Risk  (风险) = 止损价 - 入场价")
print("    Reward(收益) = 入场价 - 止盈价")
print("    R:R 比率     = Reward / Risk")
print()
print("  对于做多(BUY):")
print("    Risk  (风险) = 入场价 - 止损价")
print("    Reward(收益) = 止盈价 - 入场价")
print("    R:R 比率     = Reward / Risk")
print()
print("  判断标准: R:R >= 2.0 才允许入场")
print()

print("=" * 70)
print("实际计算案例")
print("=" * 70)
print()

# 案例: 做空 ETH @ $2060
entry = 2060.00

# 固定盈亏比模式
stop_pct = 0.008    # 0.8%
tp_pct = 0.016      # 1.6%

sl = entry * (1 + stop_pct)  # 止损在上方
tp = entry * (1 - tp_pct)    # 止盈在下方

print(f"案例: 做空 ETH")
print(f"  入场价: ${entry:.2f}")
print(f"  止损设置: {stop_pct*100:.2f}%")
print(f"  止盈设置: {tp_pct*100:.2f}%")
print()
print(f"计算过程:")
print(f"  止损价 = {entry:.2f} × (1 + {stop_pct}) = {entry:.2f} × {1+stop_pct} = ${sl:.2f}")
print(f"  止盈价 = {entry:.2f} × (1 - {tp_pct}) = {entry:.2f} × {1-tp_pct} = ${tp:.2f}")
print()
print(f"风险计算:")
risk = sl - entry
print(f"  Risk = {sl:.2f} - {entry:.2f} = ${risk:.2f}")
print(f"       = {risk/entry*100:.2f}%")
print()
print(f"收益计算:")
reward = entry - tp
print(f"  Reward = {entry:.2f} - {tp:.2f} = ${reward:.2f}")
print(f"         = {reward/entry*100:.2f}%")
print()
print(f"盈亏比:")
rr = reward / risk
print(f"  R:R = {reward:.2f} / {risk:.2f} = {rr:.2f}")
print(f"      = 1:{rr:.2f}")
print()
print(f"判断: {'允许入场' if rr >= 2.0 else '阻止入场'} (要求 >= 1:2)")
print()

print("=" * 70)
print("对比: 旧模式 vs 新模式")
print("=" * 70)
print()

print("【旧模式】ATR动态计算:")
print("  假设 ATR = $20 (约0.97%)")
atr = 20
sl_mult = 1.5
tp_mult = 4.0

old_sl = entry + atr * sl_mult
old_tp = entry - atr * tp_mult
old_risk = old_sl - entry
old_reward = entry - old_tp
old_rr = old_reward / old_risk

print(f"  止损 = {entry:.2f} + {atr:.2f} × {sl_mult} = ${old_sl:.2f}")
print(f"  止盈 = {entry:.2f} - {atr:.2f} × {tp_mult} = ${old_tp:.2f}")
print(f"  风险 = ${old_risk:.2f} ({old_risk/entry*100:.2f}%)")
print(f"  收益 = ${old_reward:.2f} ({old_reward/entry*100:.2f}%)")
print(f"  R:R = 1:{old_rr:.2f}")
print()
print("  问题:")
print("    - 止损太宽(1.45%)，实际亏损往往更大")
print("    - 止盈太远(3.88%)，震荡市难以达到")
print("    - 实际盈亏比可能只有 1:1 甚至更低")
print()

print("【新模式】固定百分比:")
print(f"  止损 = ${sl:.2f} ({stop_pct*100:.2f}%)")
print(f"  止盈 = ${tp:.2f} ({tp_pct*100:.2f}%)")
print(f"  风险 = ${risk:.2f} ({risk/entry*100:.2f}%)")
print(f"  收益 = ${reward:.2f} ({reward/entry*100:.2f}%)")
print(f"  R:R = 1:{rr:.2f}")
print()
print("  优势:")
print("    - 止损明确(0.8%)，易于执行")
print("    - 止盈合理(1.6%)，容易达到")
print("    - 盈亏比固定1:2，可预期")
print()

print("=" * 70)
print("过滤逻辑流程图")
print("=" * 70)
print()
print("生成交易信号")
print("      ↓")
print("计算 SL/TP 价格")
print("      ↓")
print("计算 Risk = |entry - sl|")
print("      ↓")
print("计算 Reward = |tp - entry|")
print("      ↓")
print("计算 R:R = Reward / Risk")
print("      ↓")
print("R:R >= 2.0 ?")
print("   ↓      ↓")
print(" 是      否")
print("   ↓      ↓")
print("允许入场  阻止入场")
print("         记录原因: '盈亏比不足'")
print()

print("=" * 70)
print("代码实现")
print("=" * 70)
print()
print("```python")
print("def _check_rr_ratio(self, entry, sl, tp, action):")
print("    if action == 'BUY':")
print("        risk = entry - sl      # 入场价减止损价")
print("        reward = tp - entry    # 止盈价减入场价")
print("    else:  # SELL")
print("        risk = sl - entry      # 止损价减入场价")
print("        reward = entry - tp    # 入场价减止盈价")
print("    ")
print("    if risk <= 0:")
print("        return False, 0        # 止损设置错误")
print("    ")
print("    rr_ratio = reward / risk   # 盈亏比 = 收益 / 风险")
print("    min_rr = CONFIG.get('MIN_RR_RATIO', 2.0)  # 最小2.0")
print("    ")
print("    return rr_ratio >= min_rr, rr_ratio  # (是否满足, 实际值)")
print("```")
print()

print("=" * 70)
print("对今日交易的影响")
print("=" * 70)
print()

print("假设交易: SELL @ $2060")
print()
print("场景A: 旧模式 (ATR动态)")
print("  入场: $2060")
print("  止损: $2090 (ATR*1.5)")
print("  止盈: $1980 (ATR*4.0)")
print("  实际: 价格涨到$2120，亏损-$60 (被大止损)")
print()
print("场景B: 新模式 (固定+硬性止损)")
print("  入场: $2060")
print("  止损: $2076 (0.8%)")
print("  硬性止损检查: 0.8% < 1.5%，但...")
print("  如果价格波动到$2080:")
print("  实际亏损: $20 (0.97%)，触发硬性止损出场")
print("  结果: 亏损控制在-1.5%以内")
print()
print("场景C: 盈亏比过滤阻止")
print("  假设某信号: 入场$2060, SL$2080, TP$2040")
print("  Risk = $20, Reward = $20")
print("  R:R = 1:1 < 2.0")
print("  结果: 阻止入场，避免低质量交易")
