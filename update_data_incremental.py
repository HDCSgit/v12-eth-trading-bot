#!/usr/bin/env python3
"""
增量数据更新脚本
只下载缺失的最新数据，而不是全部重新下载

使用方式:
    python update_data_incremental.py
"""
import sys
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import argparse

def get_last_timestamp(data_file):
    """获取数据文件的最后时间戳"""
    try:
        df = pd.read_csv(data_file)
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            return df['timestamp'].max()
        elif 'datetime' in df.columns:
            df['datetime'] = pd.to_datetime(df['datetime'])
            return df['datetime'].max()
    except Exception as e:
        print(f"无法读取现有数据: {e}")
    return None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--file', default='eth_usdt_15m_binance.csv')
    parser.add_argument('--symbol', default='ETHUSDT')
    parser.add_argument('--interval', default='15m')
    args = parser.parse_args()
    
    print("=" * 70)
    print("增量数据更新")
    print("=" * 70)
    
    # 检查现有数据
    last_time = get_last_timestamp(args.file)
    
    if last_time:
        time_diff = datetime.now() - last_time
        hours_missing = time_diff.total_seconds() / 3600
        
        print(f"\n现有数据: {args.file}")
        print(f"最后时间: {last_time}")
        print(f"当前时间: {datetime.now()}")
        print(f"缺失数据: {hours_missing:.1f} 小时 ({hours_missing/24:.1f} 天)")
        
        if hours_missing < 1:
            print("\n✓ 数据已是最新（<1小时），无需更新")
            return 0
        
        # 计算需要下载的天数
        days_needed = int(hours_missing / 24) + 1
        print(f"\n将下载最近 {days_needed} 天的数据...")
        
        # 下载新数据
        import subprocess
        # download_binance_data.py 使用 --update 参数，自动下载最新数据
        cmd = f"python download_binance_data.py --update --interval {args.interval}"
        print(f"\n执行: {cmd}")
        result = subprocess.run(cmd, shell=True)
        
        if result.returncode == 0:
            # 合并数据
            print("\n合并新旧数据...")
            try:
                # 读取新下载的数据（通常在data目录）
                import glob
                new_files = glob.glob(f"data/{args.symbol.lower()}_{args.interval}_*.csv")
                if new_files:
                    new_file = max(new_files, key=os.path.getmtime)
                    print(f"新数据文件: {new_file}")
                    
                    # 读取并合并
                    df_old = pd.read_csv(args.file)
                    df_new = pd.read_csv(new_file)
                    
                    # 合并并去重
                    df_combined = pd.concat([df_old, df_new])
                    if 'timestamp' in df_combined.columns:
                        df_combined['timestamp'] = pd.to_datetime(df_combined['timestamp'])
                        df_combined = df_combined.drop_duplicates(subset=['timestamp'])
                        df_combined = df_combined.sort_values('timestamp')
                    
                    # 保存
                    df_combined.to_csv(args.file, index=False)
                    print(f"✓ 合并完成: {len(df_combined)} 条数据")
                    print(f"  时间范围: {df_combined['timestamp'].min()} ~ {df_combined['timestamp'].max()}")
                else:
                    print("✗ 找不到新下载的数据文件")
            except Exception as e:
                print(f"✗ 合并失败: {e}")
                return 1
        else:
            print("✗ 下载失败")
            return 1
    else:
        print(f"✗ 找不到现有数据文件: {args.file}")
        print("将执行完整下载...")
        import subprocess
        subprocess.run(f"python download_binance_data.py --symbol {args.symbol} --interval {args.interval} --days 90", shell=True)
    
    return 0

if __name__ == "__main__":
    import os
    sys.exit(main())
