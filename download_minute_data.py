#!/usr/bin/env python3
"""
下载ETHUSDT 5分钟数据（2年）
币安API限制：单请求最多1000条，需要分批下载
"""

import requests
import pandas as pd
import time
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

def download_eth_5m(start_date='2024-01-01', end_date='2026-03-20'):
    """
    下载ETHUSDT 5分钟K线数据
    """
    symbol = 'ETHUSDT'
    interval = '5m'  # 5分钟
    base_url = 'https://fapi.binance.com/fapi/v1/klines'
    
    # 转换为时间戳（毫秒）
    start_ts = int(pd.Timestamp(start_date).timestamp() * 1000)
    end_ts = int(pd.Timestamp(end_date).timestamp() * 1000)
    
    all_data = []
    current_ts = start_ts
    
    logger.info(f"开始下载 {symbol} {interval} 数据")
    logger.info(f"时间范围: {start_date} 至 {end_date}")
    
    batch_num = 0
    
    while current_ts < end_ts:
        batch_num += 1
        
        # 计算批次结束时间（1000条5分钟 = 约3.5天）
        batch_end = min(current_ts + 1000 * 5 * 60 * 1000, end_ts)
        
        params = {
            'symbol': symbol,
            'interval': interval,
            'startTime': current_ts,
            'endTime': batch_end,
            'limit': 1000
        }
        
        try:
            response = requests.get(base_url, params=params, timeout=30)
            data = response.json()
            
            if not data:
                logger.warning(f"批次 {batch_num}: 无数据")
                break
            
            all_data.extend(data)
            logger.info(f"批次 {batch_num}: 获取 {len(data)} 条，累计 {len(all_data)} 条")
            
            # 更新起始时间
            current_ts = data[-1][0] + 1
            
            # 避免限流
            time.sleep(0.5)
            
        except Exception as e:
            logger.error(f"下载出错: {e}")
            time.sleep(2)
            continue
    
    # 转换为DataFrame
    if all_data:
        df = pd.DataFrame(all_data, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'trades', 'taker_buy_base',
            'taker_buy_quote', 'ignore'
        ])
        
        # 转换类型
        numeric_cols = ['open', 'high', 'low', 'close', 'volume', 
                       'quote_volume', 'taker_buy_base', 'taker_buy_quote']
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        
        # 保存
        filename = f'eth_usdt_5m_{start_date[:4]}_{end_date[:4]}.csv'
        df.to_csv(filename, index=False)
        
        logger.info(f"\n下载完成！")
        logger.info(f"总条数: {len(df)}")
        logger.info(f"时间范围: {df['timestamp'].min()} 至 {df['timestamp'].max()}")
        logger.info(f"文件保存: {filename}")
        
        return df
    
    return None

if __name__ == "__main__":
    # 下载2年数据
    df = download_eth_5m('2024-01-01', '2026-03-20')