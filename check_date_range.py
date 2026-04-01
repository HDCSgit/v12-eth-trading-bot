#!/usr/bin/env python3
"""检查数据日期范围"""
import pandas as pd
import sqlite3
from datetime import datetime, timedelta

print('='*60)
print('数据日期范围检查')
print('='*60)
print(f'当前时间: {datetime.now()}')
print()

# 检查CSV
df = pd.read_csv('eth_usdt_15m_binance.csv')
df['timestamp'] = pd.to_datetime(df['timestamp'])

print(f'CSV总条数: {len(df)}')
print(f'最早日期: {df["timestamp"].min()}')
print(f'最新日期: {df["timestamp"].max()}')

# 计算9个月前的日期
nine_months_ago = datetime.now() - timedelta(days=9*30)
print(f'\n9个月前: {nine_months_ago}')

# 检查最近9个月的数据有多少条
recent_data = df[df['timestamp'] >= nine_months_ago]
print(f'最近9个月数据条数: {len(recent_data)}')

# 计算期望的条数（9个月 * 30天 * 24小时 * 4条/小时）
expected_bars = 9 * 30 * 24 * 4
print(f'期望条数(9个月): {expected_bars}')

if len(recent_data) < expected_bars * 0.8:  # 允许20%缺失
    print(f'\n⚠️ 警告: 最近9个月数据不足 ({len(recent_data)} < {expected_bars} * 0.8)')
    print(f'   数据最早只有: {df["timestamp"].min()}')
else:
    print(f'\n✓ 最近9个月数据充足: {len(recent_data)} 条')

# 检查数据连续性
print('\n数据连续性检查:')
df_recent = df.tail(100)
time_diffs = df_recent['timestamp'].diff().dt.total_seconds() / 60  # 分钟
expected_diff = 15  # 15分钟间隔
gaps = time_diffs[time_diffs > expected_diff * 2]
if len(gaps) > 0:
    print(f'   发现 {len(gaps)} 个时间间隔异常')
else:
    print('   最近100条数据连续')

print()
print('='*60)
