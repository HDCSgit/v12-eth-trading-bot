# -*- coding: utf-8 -*-
import sys
sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)

import sqlite3
import pandas as pd
import numpy as np

conn = sqlite3.connect('historical_data.db')
df = pd.read_sql_query('SELECT * FROM klines ORDER BY timestamp DESC LIMIT 200', conn)
conn.close()

df = df.sort_values('timestamp')
close = df['close'].astype(float)
high = df['high'].astype(float)
low = df['low'].astype(float)

print('='*70)
print('趋势分析诊断')
print('='*70)

# 价格变化
print(f'\n价格统计 (最近200根K线):')
print(f'  起始: ${close.iloc[0]:.2f}')
print(f'  结束: ${close.iloc[-1]:.2f}')
print(f'  最高: ${close.max():.2f}')
print(f'  最低: ${close.min():.2f}')
print(f'  总变动: {(close.iloc[-1]/close.iloc[0]-1)*100:.2f}%')

# 计算ADX
plus_dm = high.diff().clip(lower=0)
minus_dm = (-low.diff()).clip(lower=0)
tr1 = high - low
tr2 = abs(high - close.shift())
tr3 = abs(low - close.shift())
tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
atr = tr.rolling(14).mean()
plus_di = 100 * plus_dm.rolling(14).mean() / atr
minus_di = 100 * minus_dm.rolling(14).mean() / atr
dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
adx = dx.rolling(14).mean()

print(f'\nADX (趋势强度):')
print(f'  当前: {adx.iloc[-1]:.2f}')
print(f'  阈值: 25 (ADX>25表示有趋势)')
print(f'  判断: {"有趋势" if adx.iloc[-1] > 25 else "无趋势/震荡"}')

# 均线
ma10 = close.rolling(10).mean()
ma20 = close.rolling(20).mean()
ma55 = close.rolling(55).mean()

print(f'\n均线系统:')
print(f'  MA10: {ma10.iloc[-1]:.2f}')
print(f'  MA20: {ma20.iloc[-1]:.2f}')
print(f'  MA55: {ma55.iloc[-1]:.2f}')

ma_bullish = ma10.iloc[-1] > ma20.iloc[-1] > ma55.iloc[-1]
ma_bearish = ma10.iloc[-1] < ma20.iloc[-1] < ma55.iloc[-1]

print(f'  多头排列: {ma_bullish}')
print(f'  空头排列: {ma_bearish}')

# 布林带
bb_mid = close.rolling(20).mean()
bb_std = close.rolling(20).std()
bb_width = (2 * bb_std) / bb_mid

print(f'\n布林带:')
print(f'  当前宽度: {bb_width.iloc[-1]:.4f}')
print(f'  阈值: 0.05')
print(f'  判断: {"收窄" if bb_width.iloc[-1] < 0.05 else "正常"}')

bb_width_avg = bb_width.tail(15).mean()
print(f'  15周期平均: {bb_width_avg:.4f}')

# 市场环境判断
print(f'\n市场环境判断逻辑:')
print(f'  1. ADX > 25: {adx.iloc[-1] > 25} (当前{adx.iloc[-1]:.2f})')
print(f'  2. 均线多头排列: {ma_bullish}')
print(f'  3. 均线空头排列: {ma_bearish}')
print(f'  4. BB宽度 < 0.04: {bb_width.iloc[-1] < 0.04}')
print(f'  5. BB收缩 < 0.7x平均: {bb_width.iloc[-1] < bb_width_avg * 0.7}')
print(f'  6. ADX < 20 (无趋势): {adx.iloc[-1] < 20}')

# 判断结果
if adx.iloc[-1] > 25:
    if ma_bullish:
        regime = '趋势上涨 (TRENDING_UP)'
    elif ma_bearish:
        regime = '趋势下跌 (TRENDING_DOWN)'
    else:
        regime = '趋势不明'
elif bb_width.iloc[-1] < 0.04 and bb_width.iloc[-1] < bb_width_avg * 0.7 and adx.iloc[-1] < 20:
    regime = '盘整待破 (CONSOLIDATION)'
elif bb_width.iloc[-1] < 0.05:
    regime = '震荡市 (SIDEWAYS)'
else:
    regime = '其他'

print(f'\n=> 判定结果: {regime}')

# 检查ML预测
print('\n' + '='*70)
print('ML预测检查')
print('='*70)

# 计算ML特征
from main_v12_live_optimized import V12MLModel
model = V12MLModel()
if model.load('ml_model_trained.pkl'):
    pred = model.predict(df)
    print(f'  ML方向: {pred["direction"]} (1=多, -1=空, 0=观望)')
    print(f'  ML置信度: {pred["confidence"]:.3f}')
    print(f'  做空概率: {pred["proba"][0]:.3f}')
    print(f'  做多概率: {pred["proba"][1]:.3f}')
    print(f'  顺势阈值: 0.56')
    print(f'  逆势阈值: 0.75')
    
    if pred['confidence'] >= 0.56:
        action = 'BUY' if pred['direction'] == 1 else 'SELL' if pred['direction'] == -1 else 'HOLD'
        print(f'\n  ML信号: {action} (置信度达标)')
        
        # 检查是否顺势
        if 'TRENDING_UP' in regime and action == 'BUY':
            print(f'  顺势交易: YES (趋势上涨 + ML看多)')
        elif 'TRENDING_DOWN' in regime and action == 'SELL':
            print(f'  顺势交易: YES (趋势下跌 + ML看空)')
        elif action != 'HOLD':
            is_counter = (('TRENDING_UP' in regime and action == 'SELL') or 
                         ('TRENDING_DOWN' in regime and action == 'BUY'))
            if is_counter:
                print(f'  逆势交易: 需要置信度>=0.75 (当前{pred["confidence"]:.3f})')
    else:
        print(f'\n  ML信号: 置信度不足 ({pred["confidence"]:.3f} < 0.56)')
else:
    print('  ML模型加载失败')
