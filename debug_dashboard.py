#!/usr/bin/env python3
"""调试Dashboard数据流"""
import pandas as pd
from market_regime_v2 import MarketRegimeDetectorV2
import plotly.graph_objects as go

# 加载数据
df = pd.read_csv('eth_usdt_15m_binance.csv')
df['timestamp'] = pd.to_datetime(df['timestamp'])
df = df.tail(500).copy()
df['timestamp'] = df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')

print('=== Data Check ===')
print(f'Data shape: {df.shape}')
print(f'Timestamp range: {df["timestamp"].iloc[0]} to {df["timestamp"].iloc[-1]}')
print(f'Price range: {df["low"].min():.2f} - {df["high"].max():.2f}')
print()
print('OHLC sample:')
print(df[['timestamp', 'open', 'high', 'low', 'close']].head(3).to_string())
print()

# 检查是否有NaN
print('=== NaN Check ===')
print('NaN counts:')
print(df[['open', 'high', 'low', 'close']].isna().sum())
print()

# 创建简单图表测试
fig = go.Figure()
fig.add_trace(go.Candlestick(
    x=df['timestamp'],
    open=df['open'],
    high=df['high'],
    low=df['low'],
    close=df['close'],
    name='Historical',
))

# 检查图表数据
print('=== Figure Data ===')
traces = fig.to_dict()['data']
print(f'Number of traces: {len(traces)}')
if traces:
    trace = traces[0]
    print(f'Trace type: {trace["type"]}')
    print(f'X count: {len(trace["x"])}')
    print(f'Open count: {len(trace["open"])}')
    print(f'First X: {trace["x"][0]}')
    print(f'Last X: {trace["x"][-1]}')
    print()
    print('First OHLC values:')
    print(f'  Open: {trace["open"][0]}')
    print(f'  High: {trace["high"][0]}')
    print(f'  Low: {trace["low"][0]}')
    print(f'  Close: {trace["close"][0]}')

# 保存HTML测试
fig.update_layout(title='Test Chart', yaxis_title='Price')
fig.write_html('test_chart.html')
print()
print('Saved test_chart.html - open in browser to verify')
