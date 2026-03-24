#!/usr/bin/env python3
"""
实时交易监控工具
监控下单和平仓动作
"""

import os
import time
import sqlite3
from datetime import datetime

# 颜色定义
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def print_header():
    """打印头部信息"""
    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"{BOLD}{CYAN}" + "="*80)
    print("🚀 Binance 量化交易实时监控")
    print("="*80 + f"{RESET}")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-"*80)


def get_recent_trades(db_path='elite_trades.db', limit=10):
    """获取最近的交易记录"""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            """SELECT timestamp, symbol, action, qty, price, pnl, pnl_pct, reason, order_id, mode 
               FROM trades 
               ORDER BY timestamp DESC LIMIT ?""",
            (limit,)
        )
        trades = cursor.fetchall()
        conn.close()
        return trades
    except Exception as e:
        print(f"{RED}数据库读取失败: {e}{RESET}")
        return []


def get_today_stats(db_path='elite_trades.db'):
    """获取今日统计"""
    try:
        conn = sqlite3.connect(db_path)
        today = datetime.now().strftime('%Y-%m-%d')
        
        # 今日交易次数
        cursor = conn.execute(
            "SELECT COUNT(*), SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) FROM trades WHERE timestamp LIKE ?",
            (f"{today}%",)
        )
        total, wins, losses = cursor.fetchone()
        total = total or 0
        wins = wins or 0
        losses = losses or 0
        
        # 今日盈亏
        cursor = conn.execute(
            "SELECT SUM(pnl) FROM trades WHERE timestamp LIKE ?",
            (f"{today}%",)
        )
        pnl = cursor.fetchone()[0] or 0
        
        conn.close()
        return {
            'total_trades': total,
            'wins': wins,
            'losses': losses,
            'pnl': pnl,
            'win_rate': (wins / total * 100) if total > 0 else 0
        }
    except Exception as e:
        return {'total_trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0, 'win_rate': 0}


def print_trades(trades):
    """打印交易记录"""
    if not trades:
        print(f"{YELLOW}暂无交易记录{RESET}")
        return
    
    print(f"\n{BOLD}最近 {len(trades)} 笔交易：{RESET}")
    print("-"*80)
    print(f"{'时间':<20} {'交易对':<10} {'动作':<12} {'数量':<8} {'价格':<12} {'盈亏':<12} {'模式'}")
    print("-"*80)
    
    for trade in trades:
        timestamp, symbol, action, qty, price, pnl, pnl_pct, reason, order_id, mode = trade
        
        # 格式化时间
        ts = timestamp.split('T')[1].split('.')[0] if 'T' in timestamp else timestamp[-8:]
        
        # 颜色处理
        if 'CLOSE' in action or 'SELL' in action:
            action_color = RED
        elif 'BUY' in action:
            action_color = GREEN
        else:
            action_color = RESET
            
        # 盈亏颜色
        if pnl and pnl > 0:
            pnl_str = f"{GREEN}+{pnl:.2f} ({pnl_pct:+.2f}%){RESET}"
        elif pnl and pnl < 0:
            pnl_str = f"{RED}{pnl:.2f} ({pnl_pct:+.2f}%){RESET}"
        else:
            pnl_str = f"{pnl:.2f}" if pnl else "0.00"
        
        mode_str = f"{YELLOW}[{mode}]{RESET}" if mode == 'PAPER' else f"{RED}[{mode}]{RESET}"
        
        print(f"{ts:<20} {symbol:<10} {action_color}{action:<12}{RESET} {qty:<8.4f} ${price:<10.2f} {pnl_str:<30} {mode_str}")


def print_stats(stats):
    """打印统计数据"""
    print(f"\n{BOLD}今日交易统计：{RESET}")
    print("-"*80)
    
    pnl_color = GREEN if stats['pnl'] > 0 else RED if stats['pnl'] < 0 else RESET
    win_rate_color = GREEN if stats['win_rate'] > 50 else RED
    
    print(f"总交易次数: {stats['total_trades']}")
    print(f"盈利次数: {GREEN}{stats['wins']}{RESET}")
    print(f"亏损次数: {RED}{stats['losses']}{RESET}")
    print(f"胜率: {win_rate_color}{stats['win_rate']:.1f}%{RESET}")
    print(f"今日盈亏: {pnl_color}{stats['pnl']:.2f} USDT{RESET}")
    print("-"*80)


def tail_log_file(log_file, lines=20):
    """实时查看日志文件末尾"""
    try:
        if not os.path.exists(log_file):
            return []
        
        with open(log_file, 'r', encoding='utf-8') as f:
            # 读取最后 N 行
            lines_list = f.readlines()
            return lines_list[-lines:]
    except Exception as e:
        return [f"读取日志失败: {e}"]


def print_live_logs():
    """打印实时日志"""
    log_files = [
        ('交易日志', 'logs/elite_trades_20260320.log'),
        ('主程序日志', 'logs/elite_production_20260320.log'),
        ('错误日志', 'logs/elite_errors_20260320.log')
    ]
    
    print(f"\n{BOLD}📋 实时日志预览：{RESET}")
    print("-"*80)
    
    for name, path in log_files:
        print(f"\n{CYAN}[{name}]{RESET}")
        lines = tail_log_file(path, 5)
        for line in lines:
            line = line.strip()
            if 'TRADE' in line or '下单' in line or '订单成功' in line:
                print(f"  {GREEN}{line}{RESET}")
            elif 'ERROR' in line or '错误' in line:
                print(f"  {RED}{line}{RESET}")
            elif 'SIGNAL' in line:
                print(f"  {YELLOW}{line}{RESET}")
            else:
                print(f"  {line}")


def main():
    """主函数"""
    try:
        while True:
            print_header()
            
            # 显示统计
            stats = get_today_stats()
            print_stats(stats)
            
            # 显示最近交易
            trades = get_recent_trades(limit=5)
            print_trades(trades)
            
            # 显示日志预览
            print_live_logs()
            
            print(f"\n{BOLD}刷新时间: {datetime.now().strftime('%H:%M:%S')} (每5秒自动刷新，按 Ctrl+C 退出){RESET}")
            time.sleep(5)
            
    except KeyboardInterrupt:
        print(f"\n\n{YELLOW}监控已停止{RESET}")


if __name__ == "__main__":
    main()