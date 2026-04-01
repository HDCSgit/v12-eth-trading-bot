#!/usr/bin/env python3
"""
参数配置合理性分析
基于2026-03-25交易数据
"""

import sqlite3
import json

conn = sqlite3.connect('v12_optimized.db')
cursor = conn.cursor()

print('=' * 80)
print('V12交易系统参数合理性分析报告')
print('=' * 80)
print()

# 1. 分析胜率与交易频率
print('[一、交易频率分析]')
cursor.execute("""
    SELECT COUNT(*) as total, 
           SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) as wins,
           SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) as losses,
           AVG(pnl_pct) as avg_pnl,
           SUM(pnl_pct) as total_pnl
    FROM trades 
    WHERE timestamp LIKE '2026-03-25%'
""")
stats = cursor.fetchone()

total, wins, losses, avg_pnl, total_pnl = stats
print("今日交易: %d笔 | 胜率: %d/%d (%.0f%%)" % (total, wins, total, wins*100/total))
print("平均单笔: %+.2f%% | 总盈亏: %+.2f%%" % (avg_pnl*100, total_pnl*100))
print()

# 2. 分析亏损交易特征
print('[二、亏损交易分析]')
cursor.execute("""
    SELECT timestamp, side, entry_price, exit_price, pnl_pct, reason
    FROM trades 
    WHERE timestamp LIKE '2026-03-25%' AND result='LOSS'
    ORDER BY timestamp ASC
""")
losses = cursor.fetchall()

if losses:
    for loss in losses:
        ts, side, entry, exit_p, pnl, reason = loss
        time = ts.split('T')[1][:8]
        loss_pct = pnl * 100
        print("  %s %s | 入场:%.2f -> 出场:%.2f | 亏损:%.2f%%" % (time, side, entry, exit_p, loss_pct))
        print("    -> 原因: %s" % reason)
        
        # 分析原因
        if loss_pct < -2.0:
            print("    [WARNING] 单笔亏损过大! 止损设置可能过宽")
        if 'SELL' in side and loss_pct < 0:
            print("    [WARNING] 空单亏损 - 趋势判断错误")
print()

# 3. 分析盈利分布
print('[三、盈利分布分析]')
cursor.execute("""
    SELECT pnl_pct FROM trades 
    WHERE timestamp LIKE '2026-03-25%' AND result='WIN'
    ORDER BY pnl_pct DESC
""")
profits = cursor.fetchall()

if profits:
    big_wins = [p[0] for p in profits if p[0] > 0.05]
    mid_wins = [p[0] for p in profits if 0.01 <= p[0] <= 0.05]
    small_wins = [p[0] for p in profits if p[0] < 0.01]
    
    if big_wins:
        print("  大额盈利(>5%%): %d笔 | 平均: %.2f%%" % (len(big_wins), sum(big_wins)*100/len(big_wins)))
    else:
        print("  大额盈利(>5%%): 0笔")
        
    if mid_wins:
        print("  中等盈利(1-5%%): %d笔 | 平均: %.2f%%" % (len(mid_wins), sum(mid_wins)*100/len(mid_wins)))
    else:
        print("  中等盈利(1-5%%): 0笔")
        
    if small_wins:
        print("  小额盈利(<1%%): %d笔" % len(small_wins))
    else:
        print("  小额盈利(<1%%): 0笔")
print()

# 4. 参数问题诊断
print('[四、参数问题诊断]')
print()

# 问题1: 止损设置
print("1. 止损参数 (STOP_LOSS_ATR_MULT)")
print("   当前: 1.5x ATR")
print("   问题: 单笔亏损-2.33%%，说明止损太宽")
print("   建议: 降低到 1.0x ATR 或收紧到 1.2%% 固定值")
print()

# 问题2: 顺势阈值
print("2. ML顺势阈值 (ML_CONFIDENCE_THRESHOLD)")
print("   当前: 0.50")
print("   问题: 阈值过低，交易频率可能过高")
print("   建议: 提高到 0.55 或 0.58，过滤低质量信号")
print()

# 问题3: ADX趋势阈值
print("3. ADX趋势阈值 (TECH_ADX_TREND_THRESHOLD)")
print("   当前: 20")
print("   问题: 过于敏感，可能把震荡误判为趋势")
print("   建议: 恢复到 25 或提高到 22")
print()

# 问题4: EVT目标
print("4. EVT止盈目标 (min_return)")
print("   当前: 0.93%%")
print("   问题: 震荡市中可能难以达到，导致利润回吐")
print("   建议: 根据市场环境动态调整：趋势1.0%%，震荡0.7%%")
print()

# 问题5: 仓位计算
print("5. 仓位风险系数 (RISK_BASE_PCT)")
print("   当前: 3.0%%")
print("   问题: 理论仓位1125%%，说明风险参数激进")
print("   建议: 降低到 2.0%% 或 2.5%%，更稳健")
print()

# 问题6: 冷却期
print("6. 信号冷却期 (COOLDOWN_*)")
print("   当前: 10-45秒根据置信度")
print("   问题: 可能错过连续机会，但防止过度交易")
print("   建议: 保持当前，但亏损后延长到60秒")
print()

# 问题7: 逆势阈值
print("7. 逆势ML阈值 (COUNTER_TREND_ML_THRESHOLD)")
print("   当前: 0.95")
print("   问题: 虽然高，但代码逻辑曾有问题导致逆势交易")
print("   建议: 保持0.95，但确保代码逻辑正确执行")
print()

print('=' * 80)
print('[五、推荐调整清单]')
print('=' * 80)
print()
print("优先级 | 参数名 | 当前值 | 推荐值 | 原因")
print("-" * 80)
print("高 | STOP_LOSS_ATR_MULT | 1.5 | 1.0-1.2 | 减少单笔大亏损")
print("高 | ML_CONFIDENCE_THRESHOLD | 0.50 | 0.55-0.58 | 提高信号质量")
print("中 | TECH_ADX_TREND_THRESHOLD | 20 | 22-25 | 减少趋势误判")
print("中 | EVT_MIN_RETURN | 0.93%% | 动态调整 | 适应不同市场环境")
print("中 | RISK_BASE_PCT | 3.0%% | 2.0-2.5%% | 降低仓位风险")
print("低 | COOLDOWN_AFTER_LOSS | - | 60秒 | 防止连续亏损")
print()
