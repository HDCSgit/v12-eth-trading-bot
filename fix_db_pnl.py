#!/usr/bin/env python3
"""
修复数据库中已有交易记录的盈亏数据
重新计算扣除手续费后的真实净盈亏
"""

import sqlite3
from datetime import datetime

# 配置
DB_PATH = 'v12_optimized.db'
LEVERAGE = 5
TAKER_FEE_RATE = 0.0005  # 0.05%

# 颜色输出
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"


def fix_trade_pnl():
    """修复所有交易的PnL数据"""
    print(f"{CYAN}{'='*80}{RESET}")
    print(f"{CYAN}  数据库PnL修复工具{RESET}")
    print(f"{CYAN}{'='*80}{RESET}")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 获取所有交易记录
    cursor.execute('''
        SELECT id, timestamp, side, entry_price, exit_price, qty, pnl_pct, pnl_usdt
        FROM trades
        ORDER BY timestamp
    ''')
    trades = cursor.fetchall()
    
    print(f"\n找到 {len(trades)} 笔交易记录")
    print(f"参数: 杠杆={LEVERAGE}x, Taker费率={TAKER_FEE_RATE*100}%")
    print(f"\n开始修复...")
    
    fixed_count = 0
    total_old_pnl = 0
    total_new_pnl = 0
    total_fees = 0
    
    print(f"\n{'ID':<6} {'时间':<20} {'方向':<6} {'入场价':<10} {'出场价':<10} {'数量':<8} "
          f"{'原盈亏':<12} {'新盈亏':<12} {'手续费':<10}")
    print("-" * 100)
    
    for trade in trades:
        id_, timestamp, side, entry_price, exit_price, qty, old_pnl_pct, old_pnl_usdt = trade
        
        # 跳过无效数据
        if not all([entry_price, exit_price, qty]) or entry_price <= 0 or qty <= 0:
            continue
        
        # 计算名义价值
        notional_value = qty * entry_price
        
        # 计算价格变动
        if side in ['BUY', 'LONG']:
            # 做多：低买高卖
            price_change_pct = (exit_price - entry_price) / entry_price
        else:
            # 做空：高卖低买
            price_change_pct = (entry_price - exit_price) / entry_price
        
        # 计算毛盈亏（不含杠杆）
        gross_pnl_usdt = notional_value * price_change_pct
        
        # 计算手续费（开仓 + 平仓）
        open_fee = notional_value * TAKER_FEE_RATE
        close_fee = qty * exit_price * TAKER_FEE_RATE
        total_fee = open_fee + close_fee
        
        # 计算净盈亏（扣除手续费）
        new_pnl_usdt = gross_pnl_usdt - total_fee
        
        # 计算净收益率（包含杠杆）
        new_pnl_pct = (new_pnl_usdt / notional_value) * LEVERAGE
        
        # 更新数据库
        cursor.execute('''
            UPDATE trades
            SET pnl_pct = ?, pnl_usdt = ?
            WHERE id = ?
        ''', (new_pnl_pct, new_pnl_usdt, id_))
        
        fixed_count += 1
        total_old_pnl += old_pnl_usdt or 0
        total_new_pnl += new_pnl_usdt
        total_fees += total_fee
        
        # 显示部分记录
        if fixed_count <= 10 or fixed_count > len(trades) - 5:
            ts_short = timestamp[11:19] if len(timestamp) > 19 else timestamp
            old_pnl_str = f"{old_pnl_usdt:+.4f}" if old_pnl_usdt else "N/A"
            color = GREEN if new_pnl_usdt >= 0 else RED
            print(f"{id_:<6} {ts_short:<20} {side:<6} ${entry_price:<9.2f} ${exit_price:<9.2f} {qty:<8.4f} "
                  f"{old_pnl_str:<12} {color}{new_pnl_usdt:+.4f}{RESET} ${total_fee:<9.4f}")
        elif fixed_count == 11:
            print("...")
    
    conn.commit()
    conn.close()
    
    print("-" * 100)
    print(f"\n{CYAN}修复完成!{RESET}")
    print(f"  修复记录数: {fixed_count}")
    print(f"\n{YELLOW}盈亏对比:{RESET}")
    print(f"  原总盈亏(虚高): {GREEN if total_old_pnl >= 0 else RED}{total_old_pnl:+.4f}{RESET} USDT")
    print(f"  新总盈亏(真实): {GREEN if total_new_pnl >= 0 else RED}{total_new_pnl:+.4f}{RESET} USDT")
    print(f"  总手续费: {RED}{total_fees:.4f}{RESET} USDT")
    print(f"  差异: {RED}{total_old_pnl - total_new_pnl:+.4f}{RESET} USDT")
    
    # 计算修正后的胜率
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute('''
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN pnl_usdt > 0 THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN pnl_usdt <= 0 THEN 1 ELSE 0 END) as losses
        FROM trades
    ''')
    row = cursor.fetchone()
    conn.close()
    
    if row and row[0] > 0:
        total, wins, losses = row
        win_rate = wins / total * 100 if total > 0 else 0
        print(f"\n{CYAN}修正后统计:{RESET}")
        print(f"  总交易: {total}")
        print(f"  盈利: {GREEN}{wins}{RESET}")
        print(f"  亏损: {RED}{losses}{RESET}")
        print(f"  胜率: {GREEN if win_rate >= 50 else RED}{win_rate:.1f}%{RESET}")


def show_daily_summary():
    """显示每日汇总"""
    print(f"\n{CYAN}{'='*80}{RESET}")
    print(f"{CYAN}  每日盈亏汇总 (修复后){RESET}")
    print(f"{CYAN}{'='*80}{RESET}")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute('''
        SELECT 
            SUBSTR(timestamp, 1, 10) as date,
            COUNT(*) as trades,
            SUM(CASE WHEN pnl_usdt > 0 THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN pnl_usdt <= 0 THEN 1 ELSE 0 END) as losses,
            SUM(pnl_usdt) as total_pnl,
            AVG(pnl_usdt) as avg_pnl
        FROM trades
        GROUP BY date
        ORDER BY date DESC
    ''')
    rows = cursor.fetchall()
    conn.close()
    
    print(f"\n{'日期':<12} {'交易数':<8} {'盈利':<6} {'亏损':<6} {'胜率':<8} {'总盈亏':<12} {'平均每笔'}")
    print("-" * 80)
    
    total_trades = 0
    total_pnl = 0
    
    for row in rows:
        date, trades, wins, losses, day_pnl, avg_pnl = row
        win_rate = wins / trades * 100 if trades > 0 else 0
        total_trades += trades
        total_pnl += day_pnl or 0
        
        pnl_color = GREEN if (day_pnl or 0) >= 0 else RED
        wr_color = GREEN if win_rate >= 50 else RED
        
        print(f"{date:<12} {trades:<8} {wins:<6} {losses:<6} "
              f"{wr_color}{win_rate:>6.1f}%{RESET} "
              f"{pnl_color}{day_pnl:>+10.4f}{RESET} "
              f"{avg_pnl:>+10.4f}")
    
    print("-" * 80)
    pnl_color = GREEN if total_pnl >= 0 else RED
    print(f"{'总计':<12} {total_trades:<8} {'':<6} {'':<6} {'':<8} "
          f"{pnl_color}{total_pnl:>+10.4f}{RESET}")


if __name__ == "__main__":
    # 先备份数据库
    import shutil
    backup_path = f'v12_optimized_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db'
    shutil.copy(DB_PATH, backup_path)
    print(f"数据库已备份到: {backup_path}")
    
    # 修复数据
    fix_trade_pnl()
    
    # 显示每日汇总
    show_daily_summary()
    
    print(f"\n{GREEN}修复完成! 数据库已更新。{RESET}")
