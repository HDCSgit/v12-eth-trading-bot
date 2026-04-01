#!/usr/bin/env python3
"""同步CSV数据到SQLite"""
import pandas as pd
import sqlite3
from datetime import datetime

print('='*60)
print('数据同步工具: CSV -> SQLite')
print('='*60)

# 读取CSV
df = pd.read_csv('eth_usdt_15m_binance.csv')
print(f'CSV数据: {len(df)} 条')
print(f'最新时间: {df["timestamp"].iloc[-1]}')
print()

# 写入SQLite
conn = sqlite3.connect('historical_data.db')
df.to_sql('klines', conn, if_exists='replace', index=False)
conn.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON klines(timestamp)')
conn.commit()

# 验证
cur = conn.cursor()
cur.execute('SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM klines')
count, min_ts, max_ts = cur.fetchone()

print(f'SQLite同步完成: {count} 条')
print(f'时间范围: {min_ts} ~ {max_ts}')
conn.close()

print()
print('✅ 同步成功！现在可以重新训练模型了')
print()
print('下一步建议:')
print('  python auto_ml_trainer.py --once')
print('='*60)
