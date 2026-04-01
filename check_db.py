import sqlite3

conn = sqlite3.connect('v12_optimized.db')
cursor = conn.cursor()

# 检查表结构
print('=== 表结构 ===')
cursor.execute("PRAGMA table_info(positions)")
columns = cursor.fetchall()
print('positions 表列:')
for col in columns:
    print(f"  {col[1]} ({col[2]})")

print('\n=== 最新持仓状态 ===')
try:
    cursor.execute('''
        SELECT * FROM positions 
        ORDER BY timestamp DESC 
        LIMIT 3
    ''')
    positions = cursor.fetchall()
    if positions:
        for p in positions:
            print(p)
    else:
        print('无持仓记录')
except Exception as e:
    print(f'查询错误: {e}')

print('\n=== 最近交易记录 ===')
cursor.execute('''
    SELECT timestamp, side, entry_price, exit_price, 
           pnl_pct, pnl_usdt, result, reason 
    FROM trades 
    ORDER BY timestamp DESC 
    LIMIT 3
''')
trades = cursor.fetchall()
for t in trades:
    print(f"时间: {t[0]}")
    print(f"方向: {t[1]} 入场: {t[2]} 出场: {t[3]}")
    print(f"盈亏: {t[4]*100:.2f}% ${t[5]:.2f} 结果: {t[6]}")
    print(f"原因: {t[7]}")
    print('---')

conn.close()
