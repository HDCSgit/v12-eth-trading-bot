#!/usr/bin/env python3
"""
简化版增量数据更新
直接使用API获取最新数据并追加到CSV
"""
import pandas as pd
import requests
import time
from datetime import datetime, timedelta
import os

CSV_FILE = 'eth_usdt_15m_binance.csv'
SYMBOL = 'ETHUSDT'
INTERVAL = '15m'

def get_latest_from_csv():
    """获取CSV文件最后时间"""
    if not os.path.exists(CSV_FILE):
        return None
    df = pd.read_csv(CSV_FILE)
    if 'timestamp' in df.columns and not df.empty:
        return pd.to_datetime(df['timestamp'].max())
    return None

def fetch_recent_klines(symbol, interval, start_time, limit=1000):
    """获取K线数据"""
    url = 'https://fapi.binance.com/fapi/v1/klines'
    params = {
        'symbol': symbol,
        'interval': interval,
        'startTime': int(start_time.timestamp() * 1000),
        'limit': limit
    }
    
    resp = requests.get(url, params=params)
    if resp.status_code == 200:
        return resp.json()
    print(f"API错误: {resp.status_code}")
    return []

def main():
    print("=" * 60)
    print("简化版增量数据更新")
    print("=" * 60)
    
    # 1. 获取CSV最后时间
    csv_last = get_latest_from_csv()
    if csv_last:
        print(f"CSV最后时间: {csv_last}")
    else:
        print("CSV不存在或为空")
        return 1
    
    # 2. 计算需要下载的时间（从最后时间往前2小时，防止空缺）
    start_time = csv_last - timedelta(hours=2)
    print(f"下载起始: {start_time}")
    
    # 3. 获取数据（多批次）
    all_klines = []
    current_start = start_time
    max_batches = 20  # 最多20批次
    
    for batch in range(max_batches):
        print(f"\n批次 {batch+1}: {current_start}")
        klines = fetch_recent_klines(SYMBOL, INTERVAL, current_start)
        
        if not klines:
            print("无数据返回")
            break
        
        # 过滤掉CSV中已有的数据（使用timestamp比较，避免时区问题）
        new_klines = []
        csv_last_ts = csv_last.timestamp() * 1000  # 转为毫秒
        for k in klines:
            if k[0] > csv_last_ts:  # 直接比较毫秒时间戳
                new_klines.append(k)
        
        if new_klines:
            all_klines.extend(new_klines)
            print(f"  新数据: {len(new_klines)} 条")
            
            # 更新起始时间为最后一条数据的时间
            last_time = pd.to_datetime(new_klines[-1][0], unit='ms')
            current_start = last_time + timedelta(minutes=15)
            
            # 如果最后一条数据距离现在很近，停止
            if datetime.now() - last_time < timedelta(minutes=30):
                print("  已接近当前时间，停止")
                break
        else:
            print("  无新数据")
            break
        
        time.sleep(0.5)  # 避免限流
    
    if not all_klines:
        print("\n没有新数据需要下载")
        return 0
    
    # 4. 转换为DataFrame
    new_data = []
    for k in all_klines:
        new_data.append({
            'timestamp': pd.to_datetime(k[0], unit='ms'),
            'open': float(k[1]),
            'high': float(k[2]),
            'low': float(k[3]),
            'close': float(k[4]),
            'volume': float(k[5]),
            'close_time': pd.to_datetime(k[6], unit='ms'),
        })
    
    df_new = pd.DataFrame(new_data)
    
    # 5. 读取旧数据并合并
    df_old = pd.read_csv(CSV_FILE)
    df_old['timestamp'] = pd.to_datetime(df_old['timestamp'])
    
    # 去重（基于timestamp）
    df_combined = pd.concat([df_old, df_new])
    df_combined = df_combined.drop_duplicates(subset=['timestamp'])
    df_combined = df_combined.sort_values('timestamp')
    
    # 6. 保存
    df_combined.to_csv(CSV_FILE, index=False)
    
    print("\n" + "=" * 60)
    print("✓ 增量更新完成!")
    print(f"  原数据: {len(df_old)} 条")
    print(f"  新数据: {len(df_new)} 条")
    print(f"  合并后: {len(df_combined)} 条")
    print(f"  时间范围: {df_combined['timestamp'].min()} ~ {df_combined['timestamp'].max()}")
    print(f"  最新数据距今: {(datetime.now() - df_combined['timestamp'].max()).total_seconds()/60:.1f} 分钟")
    print("=" * 60)
    
    return 0

if __name__ == "__main__":
    exit(main())
