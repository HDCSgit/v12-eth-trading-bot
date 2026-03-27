#!/usr/bin/env python3
"""
V2快速重训练脚本（6小时周期专用）
轻量级：只增量更新数据，快速训练

使用方式:
    python quick_retrain_v2.py
    
预计耗时:
    - 数据更新: 30-60秒
    - 模型训练: 2-3分钟
    - 总计: 3-4分钟
"""
import sys
import os
import subprocess
import shutil
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def main():
    print("=" * 70)
    print("V2快速重训练 (6小时周期)")
    print("=" * 70)
    start_time = datetime.now()
    
    data_file = "eth_usdt_15m_binance.csv"
    model_file = "models/regime_xgb_v1.pkl"
    
    # 1. 快速增量更新数据（只下载缺失的）
    log("[1/4] 增量更新数据...")
    result = subprocess.run(
        ["python", "update_data_incremental.py"],
        capture_output=True, text=True
    )
    if "数据已是最新" in result.stdout:
        log("   ✓ 数据已是最新")
    elif result.returncode == 0:
        log("   ✓ 数据更新完成")
    else:
        log(f"   ⚠ 更新失败，使用现有数据")
    
    # 2. 备份旧模型
    log("[2/4] 备份旧模型...")
    if os.path.exists(model_file):
        backup_name = f"models/regime_xgb_{datetime.now().strftime('%m%d_%H%M')}.pkl"
        shutil.copy(model_file, backup_name)
        log(f"   ✓ 备份: {backup_name}")
    
    # 3. 快速训练（减少树数量，加快速度）
    log("[3/4] 快速训练模型...")
    log("   参数: lookforward=48, 简化特征")
    
    # 使用环境变量传递快速模式
    os.environ["V2_QUICK_TRAIN"] = "1"
    
    result = subprocess.run([
        "python", "train_regime_v2.py",
        "--data", data_file,
        "--output", model_file,
        "--lookforward", "48",
        "--test-size", "0.1"  # 减少验证集比例
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        log(f"   ✗ 训练失败")
        print(result.stderr[-500:])  # 显示最后500字符错误
        return 1
    
    # 提取关键信息
    for line in result.stdout.split('\n'):
        if 'Validation accuracy' in line:
            log(f"   ✓ {line.strip()}")
    
    # 4. 验证模型
    log("[4/4] 验证模型...")
    try:
        from market_regime_v2 import MarketRegimeDetectorV2
        import pandas as pd
        
        detector = MarketRegimeDetectorV2(model_path=model_file)
        if detector.is_ready():
            # 快速测试
            df = pd.read_csv(data_file).tail(50)
            result = detector.predict(df)
            log(f"   ✓ 模型正常: {result.regime.value} @ {result.confidence:.0%}")
        else:
            log("   ✗ 模型加载失败")
            return 1
    except Exception as e:
        log(f"   ✗ 验证失败: {e}")
        return 1
    
    # 完成
    elapsed = (datetime.now() - start_time).total_seconds()
    print("=" * 70)
    print(f"✅ 快速重训练完成! 耗时: {elapsed:.0f}秒")
    print(f"   新模型已生效，交易程序将在60秒内自动加载")
    print("=" * 70)
    
    # 记录时间戳
    with open("models/regime_v2_last_training.txt", 'w') as f:
        f.write(f"Last training: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Next training: +6 hours\n")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
