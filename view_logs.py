#!/usr/bin/env python3
"""
交易日志查看工具 - 实时查看交易状态和历史记录
"""
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import sys
import os

def connect_db():
    """连接数据库"""
    if not os.path.exists('elite_trades.db'):
        print("❌ 数据库文件不存在，请先运行交易系统")
        sys.exit(1)
    return sqlite3.connect('elite_trades.db')

def show_recent_trades(limit=10):
    """显示最近的交易记录"""
    conn = connect_db()
    df = pd.read_sql_query(f"""
        SELECT 
            timestamp, symbol, action, qty, price, pnl, pnl_pct, reason, confidence, mode
        FROM trades 
        ORDER BY timestamp DESC 
        LIMIT {limit}
    """, conn)
    conn.close()
    
    if df.empty:
        print("📭 暂无交易记录")
        return
    
    print("\n" + "="*100)
    print(f"📊 最近 {len(df)} 笔交易记录")
    print("="*100)
    print(df.to_string(index=False))
    print("="*100)

def show_positions():
    """显示当前持仓"""
    conn = connect_db()
    df = pd.read_sql_query("""
        SELECT 
            timestamp, symbol, side, qty, entry_price, current_price, 
            unrealized_pnl, unrealized_pnl_pct, leverage
        FROM positions 
        WHERE timestamp = (
            SELECT MAX(timestamp) FROM positions p2 
            WHERE p2.symbol = positions.symbol
        )
        ORDER BY timestamp DESC
    """, conn)
    conn.close()
    
    if df.empty:
        print("📭 暂无持仓记录")
        return
    
    print("\n" + "="*100)
    print("📍 当前持仓状态")
    print("="*100)
    print(df.to_string(index=False))
    print("="*100)

def show_today_summary():
    """显示今日汇总"""
    conn = connect_db()
    today = datetime.now().strftime('%Y-%m-%d')
    
    # 今日盈亏
    pnl_df = pd.read_sql_query(f"""
        SELECT 
            COUNT(*) as total_trades,
            SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losses,
            SUM(pnl) as total_pnl,
            AVG(pnl) as avg_pnl,
            SUM(qty * price) as total_volume
        FROM trades 
        WHERE timestamp LIKE '{today}%'
    """, conn)
    
    # 今日信号
    signal_df = pd.read_sql_query(f"""
        SELECT 
            COUNT(*) as total_signals,
            SUM(CASE WHEN executed = 1 THEN 1 ELSE 0 END) as executed_signals,
            SUM(CASE WHEN action = 'BUY' THEN 1 ELSE 0 END) as buy_signals,
            SUM(CASE WHEN action = 'SELL' THEN 1 ELSE 0 END) as sell_signals
        FROM signals 
        WHERE timestamp LIKE '{today}%'
    """, conn)
    
    conn.close()
    
    print("\n" + "="*100)
    print(f"📈 今日交易汇总 ({today})")
    print("="*100)
    
    if not pnl_df.empty and pnl_df['total_trades'].iloc[0] > 0:
        row = pnl_df.iloc[0]
        win_rate = (row['wins'] / row['total_trades'] * 100) if row['total_trades'] > 0 else 0
        
        print(f"交易次数: {row['total_trades']}")
        print(f"盈利次数: {row['wins']}")
        print(f"亏损次数: {row['losses']}")
        print(f"胜率: {win_rate:.1f}%")
        print(f"总盈亏: ${row['total_pnl']:.2f}")
        print(f"平均盈亏: ${row['avg_pnl']:.2f}")
        print(f"交易金额: ${row['total_volume']:.2f}")
    else:
        print("今日暂无交易")
    
    print("\n" + "-"*100)
    print("信号统计:")
    
    if not signal_df.empty:
        row = signal_df.iloc[0]
        print(f"总信号数: {row['total_signals']}")
        print(f"已执行: {row['executed_signals']}")
        print(f"买入信号: {row['buy_signals']}")
        print(f"卖出信号: {row['sell_signals']}")
    
    print("="*100)

def show_balance_history():
    """显示余额历史"""
    conn = connect_db()
    df = pd.read_sql_query("""
        SELECT 
            timestamp, total_balance, available_balance, unrealized_pnl, drawdown_pct
        FROM balance_history 
        ORDER BY timestamp DESC
        LIMIT 20
    """, conn)
    conn.close()
    
    if df.empty:
        print("📭 暂无余额记录")
        return
    
    print("\n" + "="*100)
    print("💰 余额历史 (最近20条)")
    print("="*100)
    print(df.to_string(index=False))
    print("="*100)

def show_stats():
    """显示总体统计"""
    conn = connect_db()
    
    # 总体统计
    stats_df = pd.read_sql_query("""
        SELECT 
            COUNT(*) as total_trades,
            SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losses,
            SUM(pnl) as total_pnl,
            AVG(pnl) as avg_pnl,
            MAX(pnl) as max_win,
            MIN(pnl) as max_loss,
            AVG(CASE WHEN pnl > 0 THEN pnl END) as avg_win,
            AVG(CASE WHEN pnl < 0 THEN pnl END) as avg_loss
        FROM trades
    """, conn)
    
    # 按币种统计
    symbol_df = pd.read_sql_query("""
        SELECT 
            symbol,
            COUNT(*) as trades,
            SUM(pnl) as total_pnl,
            AVG(pnl) as avg_pnl
        FROM trades
        GROUP BY symbol
        ORDER BY total_pnl DESC
    """, conn)
    
    conn.close()
    
    print("\n" + "="*100)
    print("📊 总体交易统计")
    print("="*100)
    
    if not stats_df.empty and stats_df['total_trades'].iloc[0] > 0:
        row = stats_df.iloc[0]
        win_rate = (row['wins'] / row['total_trades'] * 100)
        profit_factor = abs(row['avg_win'] / row['avg_loss']) if row['avg_loss'] != 0 else 0
        
        print(f"总交易次数: {row['total_trades']}")
        print(f"盈利次数: {row['wins']}")
        print(f"亏损次数: {row['losses']}")
        print(f"胜率: {win_rate:.1f}%")
        print(f"盈亏比: {profit_factor:.2f}")
        print(f"总盈亏: ${row['total_pnl']:.2f}")
        print(f"平均盈亏: ${row['avg_pnl']:.2f}")
        print(f"最大盈利: ${row['max_win']:.2f}")
        print(f"最大亏损: ${row['max_loss']:.2f}")
        print(f"平均盈利: ${row['avg_win']:.2f}")
        print(f"平均亏损: ${row['avg_loss']:.2f}")
    else:
        print("暂无交易数据")
    
    print("\n" + "-"*100)
    print("按币种统计:")
    print(symbol_df.to_string(index=False))
    print("="*100)

def watch_mode():
    """实时监控模式"""
    import time
    
    print("\n🔴 进入实时监控模式 (按 Ctrl+C 退出)")
    print("="*100)
    
    try:
        while True:
            os.system('cls' if os.name == 'nt' else 'clear')
            
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"\n⏰ {now}")
            print("="*100)
            
            show_today_summary()
            show_positions()
            show_recent_trades(5)
            
            time.sleep(5)  # 每5秒刷新
            
    except KeyboardInterrupt:
        print("\n\n👋 退出监控模式")

def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("""
交易日志查看工具

用法: python view_logs.py [命令]

命令:
    trades      - 显示最近交易记录
    positions   - 显示当前持仓
    today       - 显示今日汇总
    balance     - 显示余额历史
    stats       - 显示总体统计
    watch       - 实时监控模式
    all         - 显示所有信息
        """)
        sys.exit(0)
    
    command = sys.argv[1].lower()
    
    if command == 'trades':
        show_recent_trades()
    elif command == 'positions':
        show_positions()
    elif command == 'today':
        show_today_summary()
    elif command == 'balance':
        show_balance_history()
    elif command == 'stats':
        show_stats()
    elif command == 'watch':
        watch_mode()
    elif command == 'all':
        show_today_summary()
        show_positions()
        show_recent_trades()
        show_stats()
    else:
        print(f"❌ 未知命令: {command}")
        print("可用命令: trades, positions, today, balance, stats, watch, all")

if __name__ == '__main__':
    main()
