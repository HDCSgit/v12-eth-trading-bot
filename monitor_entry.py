#!/usr/bin/env python3
"""监控开仓条件"""
import sqlite3
import time
from datetime import datetime

def check_entry_conditions():
    conn = sqlite3.connect('v12_optimized.db')
    cursor = conn.cursor()
    
    # 获取最新信号
    print('=== 最新市场状态 ===')
    cursor.execute('''
        SELECT timestamp, action, source, reason, regime, confidence
        FROM signals 
        ORDER BY timestamp DESC 
        LIMIT 3
    ''')
    signals = cursor.fetchall()
    
    for s in signals:
        ts, action, source, reason, regime, conf = s
        print(f"时间: {ts}")
        print(f"信号: {action} | 来源: {source} | 置信度: {conf:.2f}")
        print(f"原因: {reason[:60]}")
        print(f"环境: {regime}")
        print('---')
    
    # 检查是否有持仓
    print('\n=== 持仓状态 ===')
    cursor.execute('''
        SELECT side, entry_price, current_price, unrealized_pnl_pct
        FROM positions 
        ORDER BY timestamp DESC 
        LIMIT 1
    ''')
    pos = cursor.fetchone()
    
    if pos:
        side, entry, current, pnl = pos
        print(f"当前持仓: {side}")
        print(f"入场价: ${entry:.2f} | 当前: ${current:.2f}")
        print(f"盈亏: {pnl*100:+.2f}%")
        print("\n[!] 有持仓，不会开仓，等待止盈/止损")
    else:
        print("[✓] 无持仓，等待开仓信号...")
        print("\n=== 开仓等待条件 ===")
        print("1. ML看多 + 置信度>0.56 + 趋势上涨 → BUY")
        print("2. ML看空 + 置信度>0.56 + 趋势下跌 → SELL")
        print("3. 技术指标确认 + 环境匹配 → BUY/SELL")
    
    conn.close()

if __name__ == '__main__':
    check_entry_conditions()
