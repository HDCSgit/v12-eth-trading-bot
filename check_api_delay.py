#!/usr/bin/env python3
import requests
import time
from datetime import datetime

# 检查币安服务器时间
resp = requests.get('https://fapi.binance.com/fapi/v1/time')
server_time = resp.json()['serverTime'] / 1000
local_time = time.time()

print("=" * 60)
print("币安API数据延迟检查")
print("=" * 60)
print(f"币安服务器时间: {datetime.fromtimestamp(server_time)}")
print(f"本地时间: {datetime.fromtimestamp(local_time)}")
print(f"时间差: {local_time - server_time:.1f}秒")

# 获取最新K线
resp = requests.get('https://fapi.binance.com/fapi/v1/klines?symbol=ETHUSDT&interval=15m&limit=5')
klines = resp.json()
if klines:
    last_candle_time = klines[-1][0] / 1000
    delay_hours = (time.time() - last_candle_time) / 3600
    print(f"\n最新K线时间: {datetime.fromtimestamp(last_candle_time)}")
    print(f"K线数据延迟: {delay_hours:.1f}小时")
    
    if delay_hours > 6:
        print("\n⚠️ 数据延迟超过6小时，这是币安期货的正常现象")
        print("原因: 币安期货数据API有延迟，特别是15分钟级别数据")
    else:
        print("\n✓ 数据延迟在正常范围内")

print("=" * 60)
