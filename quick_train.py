#!/usr/bin/env python3
"""
快速训练启动器 - 支持两种数据模式
================================
使用方式:
    python quick_train.py              # 默认滑动窗口(最新9个月)
    python quick_train.py --fixed      # 固定起点(2025-07-05之后所有)
    python quick_train.py --full       # 强制完整训练(非增量)
"""
import argparse
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def main():
    parser = argparse.ArgumentParser(description='快速训练ML模型')
    parser.add_argument('--fixed', action='store_true', help='使用固定起点模式(2025-07-05之后)')
    parser.add_argument('--full', action='store_true', help='强制完整训练(删除旧模型)')
    parser.add_argument('--months', type=int, default=9, help='滑动窗口月数(默认9)')
    args = parser.parse_args()
    
    print("="*60)
    print("ML模型快速训练")
    print("="*60)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # 设置环境变量控制训练模式
    if args.fixed:
        os.environ['TRAINING_DATA_MODE'] = 'fixed_start'
        print("[模式] 固定起点: 2025-07-05 之后所有数据")
    else:
        os.environ['TRAINING_DATA_MODE'] = 'sliding_window'
        os.environ['TRAINING_SLIDING_MONTHS'] = str(args.months)
        print(f"[模式] 滑动窗口: 最近{args.months}个月数据(最新鲜)")
    
    # 强制完整训练
    if args.full:
        print("[训练类型] 完整训练(删除旧模型重新训练)")
        if os.path.exists('ml_model_trained.pkl'):
            backup = f"ml_model_trained_{datetime.now().strftime('%m%d_%H%M')}.pkl.bak"
            import shutil
            shutil.move('ml_model_trained.pkl', backup)
            print(f"  旧模型已备份: {backup}")
    else:
        print("[训练类型] 增量训练(保留现有模型知识)")
    
    print()
    print("-"*60)
    
    # 执行训练
    try:
        from auto_ml_trainer import AutoMLTrainer
        trainer = AutoMLTrainer()
        
        # 覆盖配置
        if args.fixed:
            from config import CONFIG
            CONFIG['TRAINING_DATA_MODE'] = 'fixed_start'
        else:
            from config import CONFIG
            CONFIG['TRAINING_DATA_MODE'] = 'sliding_window'
            CONFIG['TRAINING_SLIDING_MONTHS'] = args.months
        
        success = trainer.run_training()
        
        if success:
            print()
            print("="*60)
            print("✅ 训练完成!")
            print("="*60)
            return 0
        else:
            print()
            print("[!] 训练被跳过或失败")
            return 1
            
    except Exception as e:
        print(f"\n✗ 训练失败: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
