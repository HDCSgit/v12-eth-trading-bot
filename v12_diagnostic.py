#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V12优化版 实时诊断工具
查看ML学习状态、交易表现、系统健康度
"""

import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import time
import os
import sys

# 设置编码
sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)

# ANSI颜色
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    RESET = '\033[0m'

def color(text, color):
    return f"{color}{text}{Colors.RESET}"

def clear():
    os.system('cls' if os.name == 'nt' else 'clear')

def get_db():
    try:
        return sqlite3.connect('v12_optimized.db', check_same_thread=False)
    except:
        return None

def check_ml_status(conn):
    """检查ML训练状态"""
    print(color("\n【ML模型学习状态】", Colors.CYAN + Colors.BOLD))
    
    try:
        # 检查信号表中是否有ML信号
        cursor = conn.execute("""
            SELECT 
                COUNT(*) as total_signals,
                SUM(CASE WHEN source = '机器学习' THEN 1 ELSE 0 END) as ml_signals,
                MAX(timestamp) as last_signal_time,
                AVG(CASE WHEN source = '机器学习' THEN confidence END) as avg_ml_confidence
            FROM signals
            WHERE timestamp > datetime('now', '-1 hour')
        """)
        row = cursor.fetchone()
        
        if row and row[0] > 0:
            total = row[0]
            ml_count = row[1] or 0
            last_time = row[2]
            avg_conf = row[3] or 0
            
            ml_ratio = (ml_count / total * 100) if total > 0 else 0
            
            print(f"  近1小时信号总数: {total}")
            print(f"  ML信号数量: {color(ml_count, Colors.GREEN if ml_count > 0 else Colors.YELLOW)}")
            print(f"  ML占比: {color(f'{ml_ratio:.1f}%', Colors.GREEN if ml_ratio > 30 else Colors.YELLOW)}")
            print(f"  平均置信度: {color(f'{avg_conf:.2f}', Colors.GREEN if avg_conf > 0.6 else Colors.YELLOW)}")
            print(f"  最新信号: {last_time}")
            
            if ml_count == 0:
                print(color("  [警告] 近1小时没有ML信号，可能模型未训练或置信度不足", Colors.YELLOW))
            elif ml_ratio > 50:
                print(color("  [OK] ML模型正常工作，信号占比高", Colors.GREEN))
            else:
                print(color("  [INFO] ML模型偶尔参与，技术指标主导", Colors.BLUE))
        else:
            print(color("  [警告] 数据库无近期信号记录", Colors.YELLOW))
            
    except Exception as e:
        print(color(f"  ❌ 查询失败: {e}", Colors.RED))

def check_trading_performance(conn):
    """检查交易表现"""
    print(color("\n【交易表现 (今日)】", Colors.CYAN + Colors.BOLD))
    
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        cursor = conn.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN result = 'WIN' THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN result = 'LOSS' THEN 1 ELSE 0 END) as losses,
                SUM(pnl_usdt) as total_pnl,
                AVG(pnl_pct) as avg_pnl_pct,
                MAX(pnl_pct) as best_trade,
                MIN(pnl_pct) as worst_trade
            FROM trades
            WHERE timestamp LIKE ?
        """, (f'{today}%',))
        
        row = cursor.fetchone()
        
        if row and row[0] > 0:
            total, wins, losses, pnl, avg_pnl, best, worst = row
            win_rate = (wins / total * 100) if total > 0 else 0
            pnl = pnl or 0
            
            pnl_color = Colors.GREEN if pnl >= 0 else Colors.RED
            
            print(f"  总交易: {total} 笔")
            print(f"  盈利: {color(wins, Colors.GREEN)} | 亏损: {color(losses, Colors.RED)}")
            print(f"  胜率: {color(f'{win_rate:.1f}%', Colors.GREEN if win_rate >= 50 else Colors.RED)}")
            print(f"  总盈亏: {color(f'${pnl:+.2f}', pnl_color)}")
            print(f"  平均盈亏: {color(f'{avg_pnl*100:.2f}%', Colors.BLUE) if avg_pnl else 'N/A'}")
            print(f"  最佳: {color(f'{best*100:.2f}%', Colors.GREEN) if best else 'N/A'}")
            print(f"  最差: {color(f'{worst*100:.2f}%', Colors.RED) if worst else 'N/A'}")
            
            if pnl > 0:
                print(color("  [OK] 今日盈利，继续保持！", Colors.GREEN))
            elif pnl < 0:
                print(color("  [警告] 今日亏损，注意风控", Colors.YELLOW))
        else:
            print(color("  [INFO] 今日暂无交易", Colors.BLUE))
            
    except Exception as e:
        print(color(f"  ❌ 查询失败: {e}", Colors.RED))

def check_recent_trades(conn):
    """查看最新交易"""
    print(color("\n【最近5笔交易】", Colors.CYAN + Colors.BOLD))
    
    try:
        df = pd.read_sql_query("""
            SELECT 
                timestamp, side, entry_price, exit_price, 
                pnl_pct, pnl_usdt, result, signal_source
            FROM trades
            ORDER BY timestamp DESC
            LIMIT 5
        """, conn)
        
        if len(df) > 0:
            for _, row in df.iterrows():
                result_color = Colors.GREEN if row['result'] == 'WIN' else Colors.RED
                side_icon = '[多]' if row['side'] == 'BUY' else '[空]'
                print(f"  {side_icon} {color(row['result'], result_color):4} | "
                      f"{row['pnl_pct']*100:+6.2f}% | "
                      f"${row['pnl_usdt']:+7.2f} | "
                      f"{row['signal_source'][:6]:6} | "
                      f"{row['timestamp'][11:16]}")
        else:
            print(color("  ℹ️ 暂无交易记录", Colors.BLUE))
            
    except Exception as e:
        print(color(f"  ❌ 查询失败: {e}", Colors.RED))

def check_signal_distribution(conn):
    """检查信号来源分布"""
    print(color("\n【信号来源分布 (近6小时)】", Colors.CYAN + Colors.BOLD))
    
    try:
        since = (datetime.now() - timedelta(hours=6)).isoformat()
        cursor = conn.execute("""
            SELECT 
                source,
                COUNT(*) as count,
                SUM(CASE WHEN executed = 1 THEN 1 ELSE 0 END) as executed,
                ROUND(AVG(confidence), 2) as avg_conf
            FROM signals
            WHERE timestamp > ?
            GROUP BY source
            ORDER BY count DESC
        """, (since,))
        
        rows = cursor.fetchall()
        
        if rows:
            for source, count, executed, conf in rows:
                exec_rate = (executed / count * 100) if count > 0 else 0
                source_emoji = "[ML]" if source == "机器学习" else ("[TECH]" if source == "技术指标" else "[GRID]")
                print(f"  {source_emoji} {source:10} | 生成:{count:3} | 执行:{executed:3}({exec_rate:4.0f}%) | 置信度:{conf}")
        else:
            print(color("  ℹ️ 无信号记录", Colors.BLUE))
            
    except Exception as e:
        print(color(f"  ❌ 查询失败: {e}", Colors.RED))

def check_system_health():
    """检查系统健康度"""
    print(color("\n【系统健康检查】", Colors.CYAN + Colors.BOLD))
    
    # 检查日志文件
    log_files = [
        f'logs/v12_live_opt_{datetime.now().strftime("%Y%m%d")}.log',
        f'logs/v12_trades_{datetime.now().strftime("%Y%m%d")}.log'
    ]
    
    for log_file in log_files:
        if os.path.exists(log_file):
            size = os.path.getsize(log_file) / 1024
            mtime = datetime.fromtimestamp(os.path.getmtime(log_file))
            age_seconds = (datetime.now() - mtime).total_seconds()
            
            status = color("[OK] 正常", Colors.GREEN) if age_seconds < 60 else color("[警告] 未更新", Colors.YELLOW)
            print(f"  {status} {log_file} ({size:.1f}KB, {age_seconds:.0f}秒前)")
        else:
            print(color(f"  [错误] 不存在: {log_file}", Colors.RED))
    
    # 检查数据库
    if os.path.exists('v12_optimized.db'):
        size = os.path.getsize('v12_optimized.db') / 1024
        print(color(f"  [OK] 数据库正常 (v12_optimized.db, {size:.1f}KB)", Colors.GREEN))
    else:
        print(color(f"  [错误] 数据库不存在", Colors.RED))

def check_position_status(conn):
    """检查当前持仓状态"""
    print(color("\n【当前持仓状态】", Colors.CYAN + Colors.BOLD))
    
    try:
        # 获取最新持仓记录
        cursor = conn.execute("""
            SELECT * FROM positions
            ORDER BY timestamp DESC
            LIMIT 1
        """)
        row = cursor.fetchone()
        
        if row:
            timestamp, symbol, side, qty, entry_price, current_price, pnl_pct, pnl_usdt = row[:8]
            
            pnl_color = Colors.GREEN if pnl_pct and pnl_pct >= 0 else Colors.RED
            side_color = Colors.GREEN if side == 'LONG' else Colors.RED
            
            print(f"  持仓方向: {color(side, side_color)}")
            print(f"  持仓数量: {qty} ETH")
            print(f"  入场价格: ${entry_price:.2f}")
            print(f"  当前价格: ${current_price:.2f}")
            print(f"  未实现盈亏: {color(f'{pnl_pct*100:+.2f}%', pnl_color) if pnl_pct else 'N/A'}")
            print(f"  未实现金额: {color(f'${pnl_usdt:+.2f}', pnl_color) if pnl_usdt else 'N/A'}")
            print(f"  更新时间: {timestamp}")
        else:
            print(color("  [INFO] 当前无持仓记录", Colors.BLUE))
            
    except Exception as e:
        print(color(f"  ❌ 查询失败: {e}", Colors.RED))

def main():
    """主函数"""
    clear()
    
    print(color("=" * 70, Colors.BOLD))
    print(color(" " * 20 + "[诊断] V12优化版 实时诊断工具", Colors.CYAN + Colors.BOLD))
    print(color("=" * 70, Colors.BOLD))
    print(f"诊断时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    conn = get_db()
    if conn is None:
        print(color("\n[错误] 无法连接数据库，请确保交易程序正在运行", Colors.RED))
        return
    
    try:
        check_ml_status(conn)
        check_position_status(conn)
        check_trading_performance(conn)
        check_recent_trades(conn)
        check_signal_distribution(conn)
        check_system_health()
        
        print(color("\n" + "=" * 70, Colors.BOLD))
        print(color("诊断完成! 按Ctrl+C退出，或按Enter刷新...", Colors.YELLOW))
        
    except Exception as e:
        print(color(f"\n[错误] 诊断异常: {e}", Colors.RED))
    finally:
        conn.close()

if __name__ == "__main__":
    while True:
        main()
        try:
            input()
        except KeyboardInterrupt:
            print("\n\n诊断工具已退出")
            break
