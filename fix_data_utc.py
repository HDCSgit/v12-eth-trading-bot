#!/usr/bin/env python3
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta
import time

CSV_FILE = 'eth_usdt_15m_binance.csv'

def get_csv_last():
    df = pd.read_csv(CSV_FILE)
    ts = pd.to_datetime(df['timestamp'].max())
    # 转为UTC timestamp
    return ts.tz_localize('Asia/Shanghai').tz_convert('UTC').replace(tzinfo=None)

def fetch_all_new_data(start_time, csv_last_ts):
    all_new = []
    current_start = int(start_time.timestamp() * 1000)
    end_ms = int(datetime.now().timestamp() * 1000)
    
    for i in range(50):
        url = 'https://fapi.binance.com/fapi/v1/klines'
        params = {
            'symbol': 'ETHUSDT',
            'interval': '15m',
            'startTime': current_start,
            'limit': 1000
        }
        resp = requests.get(url, params=params)
        data = resp.json()
        
        if not data:
            break
        
        new_batch = [k for k in data if k[0] > csv_last_ts]
        if new_batch:
            all_new.extend(new_batch)
            print(f"  Batch {i+1}: +{len(new_batch)} = {len(all_new)} total")
        
        last_ts = data[-1][0]
        if last_ts >= end_ms or last_ts <= current_start:
            break
        current_start = last_ts + 1
        time.sleep(0.3)
    
    return all_new

print("="*60)
print("Fix data with UTC timezone")
print("="*60)

csv_last = get_csv_last()
print(f"CSV last (UTC): {csv_last}")
print(f"CSV ts ms: {int(csv_last.timestamp()*1000)}")

start = csv_last - timedelta(hours=2)
csv_last_ts = int(csv_last.timestamp() * 1000)

print(f"Fetching from: {start} (UTC)")
new_data = fetch_all_new_data(start, csv_last_ts)

print(f"\nTotal new records: {len(new_data)}")

if new_data:
    rows = []
    for k in new_data:
        # API返回UTC时间，转为本地时间存储
        utc_ts = pd.to_datetime(k[0], unit='ms', utc=True)
        local_ts = utc_ts.tz_convert('Asia/Shanghai').tz_localize(None)
        rows.append({
            'timestamp': local_ts,
            'open': float(k[1]),
            'high': float(k[2]),
            'low': float(k[3]),
            'close': float(k[4]),
            'volume': float(k[5]),
            'close_time': pd.to_datetime(k[6], unit='ms'),
        })
    df_new = pd.DataFrame(rows)
    
    df_old = pd.read_csv(CSV_FILE)
    df_old['timestamp'] = pd.to_datetime(df_old['timestamp'])
    
    df_combined = pd.concat([df_old, df_new])
    df_combined = df_combined.drop_duplicates(subset=['timestamp'])
    df_combined = df_combined.sort_values('timestamp')
    df_combined.to_csv(CSV_FILE, index=False)
    
    print("="*60)
    print("[SUCCESS]")
    print(f"  Old: {len(df_old)}")
    print(f"  New: {len(df_new)}")
    print(f"  Total: {len(df_combined)}")
    print(f"  Range: {df_combined['timestamp'].min()} ~ {df_combined['timestamp'].max()}")
    delay = (datetime.now() + timedelta(hours=8) - df_combined['timestamp'].max()).total_seconds()/60
    print(f"  Delay: {delay:.1f} min (local time)")
    print("="*60)
    print("\nNow run: python quick_retrain_v2.py")
