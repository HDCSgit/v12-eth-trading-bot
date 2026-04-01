# -*- coding: utf-8 -*-
import pickle
import sqlite3
import pandas as pd
import numpy as np
import sys

# Fix encoding
sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)

print("="*70)
print("ML模型诊断")
print("="*70)

# 1. 加载模型
with open('ml_model_trained.pkl', 'rb') as f:
    pkg = pickle.load(f)
    model = pkg.get('model')
    scaler = pkg.get('scaler')
    metrics = pkg.get('metrics', {})

print(f"[OK] 模型加载成功")
print(f"     训练样本: {metrics.get('train_samples', 'N/A')}")
print(f"     准确率: {metrics.get('accuracy', 'N/A')}")

# 2. 特征重要性
feature_cols = [
    'returns', 'log_returns', 'rsi_6', 'rsi_14', 'rsi_24',
    'macd', 'macd_signal', 'macd_hist', 'bb_width', 'bb_position',
    'trend_short', 'trend_mid', 'volume_ratio', 'taker_ratio',
    'momentum_5', 'momentum_10', 'momentum_20', 'atr_pct',
    'price_position', 'hour', 'day_of_week'
]

print()
print("-"*70)
print("特征重要性 TOP 10")
print("-"*70)

if hasattr(model, 'feature_importances_'):
    importance = list(zip(feature_cols, model.feature_importances_))
    importance.sort(key=lambda x: x[1], reverse=True)
    for feat, imp in importance[:10]:
        bar = "*" * int(imp * 50)
        print(f"  {feat:20s}: {imp:.4f} {bar}")

# 3. 获取最新数据
conn = sqlite3.connect('historical_data.db')
df = pd.read_sql_query(
    "SELECT * FROM klines ORDER BY timestamp DESC LIMIT 100", 
    conn
)
conn.close()

df = df.sort_values('timestamp')
close = df['close'].astype(float)

print()
print("-"*70)
print("当前市场数据")
print("-"*70)
print(f"  价格: ${close.iloc[-1]:.2f}")
print(f"  时间: {df.iloc[-1]['timestamp']}")

# 计算关键指标
delta = close.diff()
gain = delta.clip(lower=0).rolling(window=14).mean()
loss = (-delta.clip(upper=0)).rolling(window=14).mean()
rsi_14 = 100 - 100 / (1 + gain / (loss + 1e-10))

ema12 = close.ewm(span=12).mean()
ema26 = close.ewm(span=26).mean()
macd = ema12 - ema26
macd_signal = macd.ewm(span=9).mean()
macd_hist = macd - macd_signal

bb_mid = close.rolling(20).mean()
bb_std = close.rolling(20).std()
bb_width = (2 * bb_std) / bb_mid
bb_upper = bb_mid + 2 * bb_std
bb_lower = bb_mid - 2 * bb_std
bb_position = (close - bb_lower) / (bb_upper - bb_lower + 1e-10)

high = df['high'].astype(float)
low = df['low'].astype(float)
tr1 = high - low
tr2 = abs(high - close.shift())
tr3 = abs(low - close.shift())
atr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).rolling(14).mean()
atr_pct = atr / close

ma10 = close.rolling(10).mean()
ma20 = close.rolling(20).mean()
ma55 = close.rolling(55).mean()
trend_short = pd.Series(np.where(ma10 > ma20, 1, -1))
trend_mid = pd.Series(np.where(ma20 > ma55, 1, -1))

volume = df['volume'].astype(float)
volume_ma = volume.rolling(20).mean()
volume_ratio = volume / volume_ma

momentum_5 = close.pct_change(5)
momentum_10 = close.pct_change(10)
momentum_20 = close.pct_change(20)

returns = close.pct_change()
log_returns = np.log(close / close.shift(1))

high_20 = high.rolling(20).max()
low_20 = low.rolling(20).min()
price_position = (close - low_20) / (high_20 - low_20 + 1e-10)

# taker_ratio - 检查是否有这个字段
if 'taker_buy_base' in df.columns:
    taker_ratio = df['taker_buy_base'].astype(float) / volume
else:
    taker_ratio = pd.Series([0.5] * len(df))

# 时间特征
if 'timestamp' in df.columns:
    ts = pd.to_datetime(df['timestamp'])
    hour = ts.dt.hour
    day_of_week = ts.dt.dayofweek
else:
    from datetime import datetime
    now = datetime.now()
    hour = pd.Series([now.hour] * len(df))
    day_of_week = pd.Series([now.weekday()] * len(df))

print(f"  RSI(14): {rsi_14.iloc[-1]:.2f}")
print(f"  MACD Hist: {macd_hist.iloc[-1]:.6f}")
print(f"  BB Width: {bb_width.iloc[-1]:.4f}")
print(f"  BB Position: {bb_position.iloc[-1]:.4f}")
print(f"  ATR%: {atr_pct.iloc[-1]*100:.2f}%")
print(f"  Volume Ratio: {volume_ratio.iloc[-1]:.2f}")
print(f"  Trend Short: {trend_short.iloc[-1]}")
print(f"  Momentum(5): {momentum_5.iloc[-1]*100:.2f}%")
print(f"  Hour: {hour.iloc[-1]}, Day: {day_of_week.iloc[-1]}")

# 4. ML预测
print()
print("-"*70)
print("ML预测结果")
print("-"*70)

# 构造特征向量
X_data = {
    'returns': returns.iloc[-1],
    'log_returns': log_returns.iloc[-1],
    'rsi_6': 100 - 100 / (1 + delta.clip(lower=0).rolling(window=6).mean().iloc[-1] / ((-delta.clip(upper=0)).rolling(window=6).mean().iloc[-1] + 1e-10)),
    'rsi_14': rsi_14.iloc[-1],
    'rsi_24': 100 - 100 / (1 + delta.clip(lower=0).rolling(window=24).mean().iloc[-1] / ((-delta.clip(upper=0)).rolling(window=24).mean().iloc[-1] + 1e-10)),
    'macd': macd.iloc[-1],
    'macd_signal': macd_signal.iloc[-1],
    'macd_hist': macd_hist.iloc[-1],
    'bb_width': bb_width.iloc[-1],
    'bb_position': bb_position.iloc[-1],
    'trend_short': trend_short.iloc[-1],
    'trend_mid': trend_mid.iloc[-1],
    'volume_ratio': volume_ratio.iloc[-1],
    'taker_ratio': taker_ratio.iloc[-1],
    'momentum_5': momentum_5.iloc[-1],
    'momentum_10': momentum_10.iloc[-1],
    'momentum_20': momentum_20.iloc[-1],
    'atr_pct': atr_pct.iloc[-1],
    'price_position': price_position.iloc[-1],
    'hour': hour.iloc[-1],
    'day_of_week': day_of_week.iloc[-1]
}

X = pd.DataFrame([X_data])
X_scaled = scaler.transform(X)
proba = model.predict_proba(X_scaled)[0]

direction = 1 if proba[1] > proba[0] else -1
confidence = max(proba)

if direction == 1:
    direction_str = "看多 (BUY)"
elif direction == -1:
    direction_str = "看空 (SELL)"
else:
    direction_str = "观望"

print(f"  ML方向: {direction_str}")
print(f"  置信度: {confidence:.3f} ({confidence*100:.1f}%)")
print(f"  做空概率: {proba[0]:.3f}")
print(f"  做多概率: {proba[1]:.3f}")

# 阈值判断
print()
print("-"*70)
print("交易决策")
print("-"*70)

ml_threshold = 0.56
if confidence >= ml_threshold:
    action = "BUY" if direction == 1 else "SELL"
    print(f"  [信号有效] 置信度 {confidence:.3f} >= 阈值 {ml_threshold}")
    print(f"  建议: {action}")
else:
    print(f"  [信号无效] 置信度 {confidence:.3f} < 阈值 {ml_threshold}")
    print(f"  建议: HOLD (观望)")

# ADX计算
plus_dm = high.diff().clip(lower=0)
minus_dm = (-low.diff()).clip(lower=0)
tr = pd.concat([high - low, abs(high - close.shift()), abs(low - close.shift())], axis=1).max(axis=1)
atr_adx = tr.rolling(14).mean()
plus_di = 100 * plus_dm.rolling(14).mean() / atr_adx
minus_di = 100 * minus_dm.rolling(14).mean() / atr_adx
dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
adx = dx.rolling(14).mean()

print()
print("-"*70)
print("市场环境 (技术分析)")
print("-"*70)
print(f"  ADX: {adx.iloc[-1]:.2f} (阈值: 25)")
if adx.iloc[-1] > 25:
    print(f"    -> 有趋势")
else:
    print(f"    -> 无趋势/震荡")

bb_width_avg = bb_width.tail(15).mean()
print(f"  BB Width: {bb_width.iloc[-1]:.4f}")
print(f"  BB Avg(15): {bb_width_avg:.4f}")
print(f"  BB Threshold: 0.05")

if bb_width.iloc[-1] < 0.05 * 0.8 and bb_width.iloc[-1] < bb_width_avg * 0.7:
    print(f"    -> 盘整待破 (CONSOLIDATION) - 策略已禁用")
elif bb_width.iloc[-1] < 0.05:
    print(f"    -> 震荡市 (SIDEWAYS)")
else:
    print(f"    -> 波动较大")

print()
print("="*70)
print("诊断完成")
print("="*70)
