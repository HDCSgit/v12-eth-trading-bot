#!/usr/bin/env python3
"""
V2模型自动训练脚本（含实时数据更新）

使用方式:
    python train_regime_v2_auto.py
    
流程:
    1. 下载最新数据（最近90天）
    2. 训练V2模型
    3. 自动替换旧模型
    4. 记录训练时间戳
"""
import sys
import os
import subprocess
import argparse
from datetime import datetime
from pathlib import Path

def run_command(cmd, description):
    """运行命令并输出结果"""
    print(f"\n[>] {description}...")
    print(f"   命令: {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"   ✗ 失败: {result.stderr}")
        return False
    print(f"   ✓ 成功")
    return True

def main():
    parser = argparse.ArgumentParser(description='V2 Auto Training with Fresh Data')
    parser.add_argument('--days', type=int, default=90, help='下载最近N天数据')
    parser.add_argument('--interval', type=str, default='15m', help='时间周期')
    parser.add_argument('--lookforward', type=int, default=48, help='预测周期')
    parser.add_argument('--auto-replace', action='store_true', help='自动替换旧模型')
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("V2模型自动训练（含实时数据更新）")
    print("=" * 70)
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    data_file = f"eth_usdt_{args.interval}_binance.csv"
    model_backup = f"models/regime_xgb_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.pkl"
    model_target = "models/regime_xgb_v1.pkl"
    
    # 步骤1: 备份旧模型
    if os.path.exists(model_target):
        print(f"\n[1/5] 备份旧模型 -> {model_backup}")
        import shutil
        shutil.copy(model_target, model_backup)
        print(f"   ✓ 备份完成")
    
    # 步骤2: 下载最新数据
    print(f"\n[2/5] 下载最新数据（最近{args.days}天）...")
    download_cmd = f"python download_binance_data.py --symbol ETHUSDT --interval {args.interval} --days {args.days}"
    if not run_command(download_cmd, "下载数据"):
        print("✗ 数据下载失败，使用现有数据继续训练")
    
    # 步骤3: 检查数据文件
    if not os.path.exists(data_file):
        # 尝试查找数据目录
        data_dir = "data"
        if os.path.exists(data_dir):
            import glob
            pattern = f"{data_dir}/ethusdt_{args.interval}_*.csv"
            files = glob.glob(pattern)
            if files:
                # 取最新的文件
                data_file = max(files, key=os.path.getmtime)
                print(f"\n[3/5] 使用数据文件: {data_file}")
            else:
                print(f"✗ 找不到数据文件")
                return 1
        else:
            print(f"✗ 找不到数据文件: {data_file}")
            return 1
    else:
        print(f"\n[3/5] 使用数据文件: {data_file}")
    
    # 显示数据时间范围
    try:
        import pandas as pd
        df = pd.read_csv(data_file)
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            print(f"   数据范围: {df['timestamp'].min()} ~ {df['timestamp'].max()}")
            print(f"   数据条数: {len(df)}")
    except Exception as e:
        print(f"   警告: 无法读取数据时间范围: {e}")
    
    # 步骤4: 训练模型
    print(f"\n[4/5] 开始训练V2模型...")
    train_cmd = f"python train_regime_v2.py --data {data_file} --output {model_target} --lookforward {args.lookforward}"
    
    if not run_command(train_cmd, "训练模型"):
        print("✗ 训练失败")
        # 恢复备份
        if os.path.exists(model_backup):
            print(f"   恢复旧模型: {model_backup} -> {model_target}")
            shutil.copy(model_backup, model_target)
        return 1
    
    # 步骤5: 验证模型
    print(f"\n[5/5] 验证模型...")
    try:
        from market_regime_v2 import MarketRegimeDetectorV2
        detector = MarketRegimeDetectorV2(model_path=model_target)
        if detector.is_ready():
            print(f"   ✓ 模型加载成功")
            # 快速测试
            import pandas as pd
            df = pd.read_csv(data_file).tail(100)
            result = detector.predict(df)
            print(f"   ✓ 预测测试: {result.regime.value} @ {result.confidence:.1%}")
        else:
            print(f"   ✗ 模型加载失败")
            return 1
    except Exception as e:
        print(f"   ✗ 验证失败: {e}")
        return 1
    
    # 记录训练时间戳
    timestamp_file = "models/regime_v2_last_training.txt"
    with open(timestamp_file, 'w') as f:
        f.write(f"Last training: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Data range: {df['timestamp'].min()} ~ {df['timestamp'].max()}\n")
        f.write(f"Model: {model_target}\n")
    
    print("\n" + "=" * 70)
    print("✅ V2模型自动训练完成!")
    print("=" * 70)
    print(f"模型文件: {model_target}")
    print(f"备份文件: {model_backup}")
    print(f"时间戳: {timestamp_file}")
    print(f"\n下次运行:")
    print(f"   python train_regime_v2_auto.py")
    print("=" * 70)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
