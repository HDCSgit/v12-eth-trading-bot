#!/usr/bin/env python3
import requests
import pandas as pd
from datetime import datetime, timedelta

CSV_FILE = 'eth_usdt_15m_binance.csv'
CSV_LAST = datetime(2026, 3, 27, 5, 30)
start = CSV_LAST - timedelta(hours=2)

print("=" * 60)
print("紧急修复：更新数据到最新")
print("=" * 60)

# 获取数据
url = 'https://fapi.binance.com/fapi/v1/klines'
params = {
    'symbol': 'ETHUSDT',
    'interval': '15m',
    'startTime': int(start.timestamp() * 1000),
    'limit': 100
}
resp = requests.get(url, params=params)
data = resp.json()

# 过滤新数据
csv_last_ts = CSV_LAST.timestamp() * 1000
new_data = [k for k in data if k[0] > csv_last_ts]

print(f"获取到 {len(data)} 条，新数据 {len(new_data)} 条")

if new_data:
    # 转换为DataFrame
    rows = []
    for k in new_data:
        rows.append({
            'timestamp': pd.to_datetime(k[0], unit='ms'),
            'open': float(k[1]),
            'high': float(k[2]),
            'low': float(k[3]),
            'close': float(k[4]),
            'volume': float(k[5]),
            'close_time': pd.to_datetime(k[6], unit='ms'),
        })
    df_new = pd.DataFrame(rows)
    
    # 读取旧数据
    df_old = pd.read_csv(CSV_FILE)
    df_old['timestamp'] = pd.to_datetime(df_old['timestamp'])
    
    # 合并
    df_combined = pd.concat([df_old, df_new])
    df_combined = df_combined.drop_duplicates(subset=['timestamp'])
    df_combined = df_combined.sort_values('timestamp')
    
    # 保存
    df_combined.to_csv(CSV_FILE, index=False)
    
    print("=" * 60)
    print("[OK] 更新完成!")
    print(f"  原数据: {len(df_old)} 条")
    print(f"  新数据: {len(new_data)} 条")
    print(f"  合并后: {len(df_combined)} 条")
    print(f"  时间范围: {df_combined['timestamp'].min()} ~ {df_combined['timestamp'].max()}")
    print(f"  最新数据距今: {(datetime.now() - df_combined['timestamp'].max()).total_seconds()/60:.1f} 分钟")
    print("=" * 60)
else:
    print("无新数据")
