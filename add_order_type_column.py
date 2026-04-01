#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('v12_optimized.db')
cursor = conn.execute('PRAGMA table_info(trades)')
cols = [c[1] for c in cursor.fetchall()]
print('当前trades表字段:', cols)

if 'order_type' not in cols:
    conn.execute("ALTER TABLE trades ADD COLUMN order_type TEXT DEFAULT 'MARKET'")
    conn.commit()
    print('[OK] 已添加order_type字段')
else:
    print('[OK] order_type字段已存在')

conn.close()
