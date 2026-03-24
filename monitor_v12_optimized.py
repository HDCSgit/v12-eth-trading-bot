#!/usr/bin/env python3
"""
V12优化版实时监控面板
实时监控交易状态、盈亏、信号质量
"""

import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import time
import os
import sys

# ANSI颜色代码
COLORS = {
    'reset': '\033[0m',
    'bold': '\033[1m',
    'green': '\033[92m',
    'red': '\033[91m',
    'yellow': '\033[93m',
    'blue': '\033[94m',
    'cyan': '\033[96m',
    'white': '\033[97m',
    'bg_green': '\033[42m',
    'bg_red': '\033[41m'
}

def clear_screen():
    """清屏"""
    os.system('cls' if os.name == 'nt' else 'clear')

def color_text(text: str, color: str) -> str:
    """添加颜色"""
    return f"{COLORS.get(color, '')}{text}{COLORS['reset']}"

def get_db_connection():
    """获取数据库连接"""
    try:
        return sqlite3.connect('v12_optimized.db', check_same_thread=False)
    except:
        return None

def get_recent_trades(conn, limit: int = 10) -> pd.DataFrame:
    """获取最近交易"""
    try:
        df = pd.read_sql_query(f'''
            SELECT * FROM trades
            ORDER BY timestamp DESC
            LIMIT {limit}
        ''', conn)
        return df
    except:
        return pd.DataFrame()

def get_today_stats(conn) -> dict:
    """获取今日统计"""
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        cursor = conn.execute('''
            SELECT 
                COUNT(*) as total_trades,
                SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) as losses,
                SUM(pnl_usdt) as total_pnl,
                AVG(pnl_pct) as avg_pnl_pct,
                MAX(pnl_pct) as max_win,
                MIN(pnl_pct) as max_loss
            FROM trades
            WHERE timestamp LIKE ?
        ''', (f'{today}%',))
        
        row = cursor.fetchone()
        if row:
            total = row[0] or 0
            wins = row[1] or 0
            return {
                'total_trades': total,
                'wins': wins,
                'losses': row[2] or 0,
                'win_rate': (wins / total * 100) if total > 0 else 0,
                'total_pnl': row[3] or 0,
                'avg_pnl_pct': row[4] or 0,
                'max_win': row[5] or 0,
                'max_loss': row[6] or 0
            }
    except Exception as e:
        print(f"统计错误: {e}")
    
    return {'total_trades': 0, 'wins': 0, 'losses': 0, 'win_rate': 0, 'total_pnl': 0}

def get_signal_stats(conn, hours: int = 24) -> dict:
    """获取信号统计"""
    try:
        since = (datetime.now() - timedelta(hours=hours)).isoformat()
        cursor = conn.execute('''
            SELECT 
                source,
                COUNT(*) as count,
                SUM(CASE WHEN executed=1 THEN 1 ELSE 0 END) as executed,
                AVG(confidence) as avg_confidence
            FROM signals
            WHERE timestamp > ?
            GROUP BY source
        ''', (since,))
        
        stats = {}
        for row in cursor.fetchall():
            stats[row[0]] = {
                'count': row[1],
                'executed': row[2],
                'avg_confidence': row[3]
            }
        return stats
    except:
        return {}

def get_latest_signal(conn) -> dict:
    """获取最新信号"""
    try:
        cursor = conn.execute('''
            SELECT * FROM signals
            ORDER BY timestamp DESC
            LIMIT 1
        ''')
        row = cursor.fetchone()
        if row:
            return {
                'timestamp': row[1],
                'action': row[3],
                'confidence': row[4],
                'source': row[5],
                'reason': row[6],
                'price': row[7],
                'regime': row[9],
                'executed': row[10]
            }
    except:
        pass
    return None

def get_equity_curve(conn, hours: int = 24) -> list:
    """获取权益曲线数据"""
    try:
        since = (datetime.now() - timedelta(hours=hours)).isoformat()
        df = pd.read_sql_query('''
            SELECT timestamp, pnl_usdt FROM trades
            WHERE timestamp > ?
            ORDER BY timestamp
        ''', conn, params=(since,))
        
        if len(df) > 0:
            df['cumulative_pnl'] = df['pnl_usdt'].cumsum()
            return df['cumulative_pnl'].tolist()
    except:
        pass
    return []

def draw_sparkline(data: list, width: int = 40) -> str:
    """绘制迷你图"""
    if len(data) < 2:
        return "无数据"
    
    min_val = min(data)
    max_val = max(data)
    if max_val == min_val:
        return "-" * width
    
    chars = "▁▂▃▄▅▆▇█"
    result = ""
    step = len(data) / width
    
    for i in range(width):
        idx = int(i * step)
        if idx < len(data):
            val = data[idx]
            normalized = (val - min_val) / (max_val - min_val)
            char_idx = int(normalized * (len(chars) - 1))
            result += chars[char_idx]
    
    return result

def print_header():
    """打印头部"""
    print(color_text("=" * 80, 'bold'))
    print(color_text(" " * 25 + "📊 V12-OPTIMIZED 实时监控面板", 'cyan'))
    print(color_text("=" * 80, 'bold'))
    print(f"更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

def print_stats(stats: dict):
    """打印统计数据"""
    print(color_text("【今日交易统计】", 'yellow'))
    
    total = stats.get('total_trades', 0)
    wins = stats.get('wins', 0)
    losses = stats.get('losses', 0)
    win_rate = stats.get('win_rate', 0)
    total_pnl = stats.get('total_pnl', 0)
    
    # 颜色根据盈亏
    pnl_color = 'green' if total_pnl >= 0 else 'red'
    win_rate_color = 'green' if win_rate >= 50 else 'red'
    
    print(f"  总交易: {total} 笔")
    print(f"  盈利: {color_text(str(wins), 'green')} 笔 | 亏损: {color_text(str(losses), 'red')} 笔")
    print(f"  胜率: {color_text(f'{win_rate:.1f}%', win_rate_color)}")
    print(f"  总盈亏: {color_text(f'${total_pnl:+.2f}', pnl_color)}")
    
    if stats.get('max_win'):
        print(f"  最大盈利: {color_text(f'{stats['max_win']*100:.2f}%', 'green')}")
    if stats.get('max_loss'):
        print(f"  最大亏损: {color_text(f'{stats['max_loss']*100:.2f}%', 'red')}")
    print()

def print_latest_signal(signal: dict):
    """打印最新信号"""
    if not signal:
        return
    
    print(color_text("【最新信号】", 'yellow'))
    
    action = signal.get('action', 'HOLD')
    action_color = 'green' if action == 'BUY' else ('red' if action == 'SELL' else 'white')
    
    print(f"  时间: {signal.get('timestamp', 'N/A')[:19]}")
    print(f"  动作: {color_text(action, action_color)}")
    print(f"  置信度: {signal.get('confidence', 0):.2f}")
    print(f"  来源: {signal.get('source', 'N/A')}")
    print(f"  原因: {signal.get('reason', 'N/A')}")
    print(f"  价格: ${signal.get('price', 0):.2f}")
    print(f"  环境: {signal.get('regime', 'N/A')}")
    print(f"  已执行: {'是' if signal.get('executed') else '否'}")
    print()

def print_recent_trades(df: pd.DataFrame):
    """打印最近交易"""
    print(color_text("【最近5笔交易】", 'yellow'))
    
    if len(df) == 0:
        print("  暂无交易记录")
        print()
        return
    
    for _, row in df.head(5).iterrows():
        result = row.get('result', 'UNKNOWN')
        result_color = 'green' if result == 'WIN' else 'red'
        pnl_pct = row.get('pnl_pct', 0) * 100
        side = row.get('side', 'N/A')
        side_icon = '🔼' if side == 'BUY' else '🔽'
        
        print(f"  {side_icon} {color_text(result, result_color):4} | "
              f"{pnl_pct:+6.2f}% | "
              f"${row.get('pnl_usdt', 0):+8.2f} | "
              f"{row.get('timestamp', 'N/A')[:16]}")
    print()

def print_signal_stats(stats: dict):
    """打印信号统计"""
    print(color_text("【信号来源统计(24h)】", 'yellow'))
    
    if not stats:
        print("  无数据")
        print()
        return
    
    for source, data in stats.items():
        count = data.get('count', 0)
        executed = data.get('executed', 0)
        avg_conf = data.get('avg_confidence', 0)
        exec_rate = (executed / count * 100) if count > 0 else 0
        
        print(f"  {source:12} | 生成: {count:3} | 执行: {executed:3} ({exec_rate:5.1f}%) | 平均置信度: {avg_conf:.2f}")
    print()

def print_equity_curve(conn):
    """打印权益曲线"""
    print(color_text("【今日权益曲线】", 'yellow'))
    
    curve = get_equity_curve(conn, hours=24)
    if len(curve) > 0:
        sparkline = draw_sparkline(curve)
        start_val = curve[0]
        end_val = curve[-1]
        color = 'green' if end_val >= start_val else 'red'
        print(f"  {color_text(sparkline, color)}")
        print(f"  起始: ${start_val:.2f} → 当前: ${color_text(f'${end_val:.2f}', color)}")
    else:
        print("  暂无数据")
    print()

def print_system_status():
    """打印系统状态"""
    print(color_text("【系统状态】", 'yellow'))
    
    # 检查日志文件
    log_files = [
        f'logs/v12_live_opt_{datetime.now().strftime("%Y%m%d")}.log',
        f'logs/v12_trades_{datetime.now().strftime("%Y%m%d")}.log'
    ]
    
    for log_file in log_files:
        if os.path.exists(log_file):
            size = os.path.getsize(log_file) / 1024  # KB
            print(f"  ✓ {log_file} ({size:.1f} KB)")
        else:
            print(f"  ✗ {log_file} (不存在)")
    
    print()

def main():
    """主函数"""
    refresh_interval = 5  # 刷新间隔(秒)
    
    try:
        while True:
            clear_screen()
            
            conn = get_db_connection()
            if conn is None:
                print(color_text("❌ 无法连接数据库，请确保交易程序正在运行", 'red'))
                time.sleep(refresh_interval)
                continue
            
            try:
                print_header()
                
                # 今日统计
                stats = get_today_stats(conn)
                print_stats(stats)
                
                # 最新信号
                signal = get_latest_signal(conn)
                print_latest_signal(signal)
                
                # 最近交易
                trades_df = get_recent_trades(conn, 10)
                print_recent_trades(trades_df)
                
                # 信号统计
                signal_stats = get_signal_stats(conn, 24)
                print_signal_stats(signal_stats)
                
                # 权益曲线
                print_equity_curve(conn)
                
                # 系统状态
                print_system_status()
                
                # 快捷键提示
                print(color_text("-" * 80, 'bold'))
                print("按 Ctrl+C 退出监控 | 每5秒自动刷新")
                
            finally:
                conn.close()
            
            time.sleep(refresh_interval)
            
    except KeyboardInterrupt:
        print("\n\n监控已停止")
        sys.exit(0)

if __name__ == "__main__":
    main()
