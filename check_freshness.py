#!/usr/bin/env python3
"""检查数据和模型新鲜度"""
import pandas as pd
import sqlite3
from datetime import datetime
import os
import pickle

print('='*60)
print('数据与模型新鲜度检查报告')
print('='*60)
print()
print(f"检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# 1. SQLite数据库
print('[1] SQLite数据库 (historical_data.db)')
try:
    conn = sqlite3.connect('historical_data.db')
    df = pd.read_sql_query('SELECT timestamp FROM klines ORDER BY timestamp DESC LIMIT 3', conn)
    conn.close()
    print(f'    最新3条数据时间:')
    for i, ts in enumerate(df['timestamp'], 1):
        print(f'      {i}. {ts}')
except Exception as e:
    print(f'    错误: {e}')
print()

# 2. CSV文件
print('[2] CSV数据文件 (eth_usdt_15m_binance.csv)')
try:
    df_csv = pd.read_csv('eth_usdt_15m_binance.csv')
    latest = df_csv['timestamp'].iloc[-1]
    earliest = df_csv['timestamp'].iloc[0]
    print(f'    数据条数: {len(df_csv)}')
    print(f'    最早时间: {earliest}')
    print(f'    最新时间: {latest}')
except Exception as e:
    print(f'    错误: {e}')
print()

# 3. 交易信号模型
print('[3] 交易信号模型 (ml_model_trained.pkl)')
try:
    if os.path.exists('ml_model_trained.pkl'):
        mtime = os.path.getmtime('ml_model_trained.pkl')
        mtime_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
        print(f'    文件修改时间: {mtime_str}')
        with open('ml_model_trained.pkl', 'rb') as f:
            pkg = pickle.load(f)
            metrics = pkg.get('metrics', {})
            if 'training_time' in metrics:
                print(f'    训练时间: {metrics["training_time"]}')
            if 'train_samples' in metrics:
                print(f'    训练样本数: {metrics["train_samples"]}')
            if 'accuracy' in metrics:
                print(f'    准确率: {metrics["accuracy"]*100:.2f}%')
    else:
        print('    文件不存在')
except Exception as e:
    print(f'    错误: {e}')
print()

# 4. 市场环境模型
print('[4] 市场环境模型 (models/regime_xgb_v1.pkl)')
try:
    regime_path = 'models/regime_xgb_v1.pkl'
    if os.path.exists(regime_path):
        mtime = os.path.getmtime(regime_path)
        mtime_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
        print(f'    文件修改时间: {mtime_str}')
    else:
        print('    文件不存在 (当前使用V1规则，不依赖此模型)')
except Exception as e:
    print(f'    错误: {e}')
print()

# 5. 训练日志
print('[5] 自动训练日志 (ml_auto_training.log)')
try:
    if os.path.exists('ml_auto_training.log'):
        with open('ml_auto_training.log', 'r', encoding='utf-8') as f:
            lines = f.readlines()
            recent = [l.strip() for l in lines[-10:] if '训练' in l or '样本' in l or '准确率' in l or '完成' in l]
            print(f'    最近相关日志:')
            for line in recent[-5:]:
                print(f'      {line}')
    else:
        print('    日志文件不存在')
except Exception as e:
    print(f'    错误: {e}')

print()
print('='*60)
