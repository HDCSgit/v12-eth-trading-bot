#!/usr/bin/env python3
"""
市场环境检测V2模型训练脚本

使用方法:
    python train_regime_v2.py --data data/eth_1h.csv --output models/regime_xgb_v1.pkl
    
    # 使用配置
    python train_regime_v2.py --config config.json
    
    # 交叉验证
    python train_regime_v2.py --data data/eth_1h.csv --cv 5
"""
import argparse
import sys
import pandas as pd
from pathlib import Path

# 添加当前目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from market_regime_v2 import MarketRegimeTrainer, RegimeFeatureExtractor


def load_data(filepath: str) -> pd.DataFrame:
    """加载OHLCV数据"""
    df = pd.read_csv(filepath)
    
    # 确保必要的列存在
    required_cols = ['open', 'high', 'low', 'close', 'volume']
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")
    
    # 设置时间索引
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)
    elif 'datetime' in df.columns:
        df['datetime'] = pd.to_datetime(df['datetime'])
        df.set_index('datetime', inplace=True)
    
    print(f"Loaded {len(df)} rows from {filepath}")
    print(f"Date range: {df.index[0]} to {df.index[-1]}")
    
    return df


def main():
    parser = argparse.ArgumentParser(description='Train Market Regime V2 Model')
    parser.add_argument('--data', type=str, default='data/historical_data.csv',
                       help='Path to OHLCV CSV file')
    parser.add_argument('--output', type=str, default='models/regime_xgb_v1.pkl',
                       help='Output model path')
    parser.add_argument('--lookforward', type=int, default=12,
                       help='Lookforward periods for label generation')
    parser.add_argument('--cv', type=int, default=0,
                       help='Number of cross-validation folds (0=disable)')
    parser.add_argument('--test-size', type=float, default=0.2,
                       help='Test set ratio')
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("Market Regime V2 Model Training")
    print("=" * 70)
    
    # 检查XGBoost
    try:
        import xgboost
        print(f"XGBoost version: {xgboost.__version__}")
    except ImportError:
        print("ERROR: XGBoost not installed!")
        print("Install: pip install xgboost")
        return 1
    
    # 加载数据
    print(f"\n[1] Loading data from {args.data}")
    try:
        df = load_data(args.data)
    except Exception as e:
        print(f"Error loading data: {e}")
        return 1
    
    # 准备训练器
    config = {
        'LOOKFORWARD_PERIODS': args.lookforward,
        'TEST_SIZE': args.test_size,
    }
    
    trainer = MarketRegimeTrainer(config)
    
    # 准备数据集
    print(f"\n[2] Preparing dataset...")
    X, y = trainer.prepare_dataset(df)
    
    if len(X) < 1000:
        print(f"WARNING: Dataset too small ({len(X)} samples)")
    
    # 交叉验证
    if args.cv > 0:
        print(f"\n[3] Running {args.cv}-fold cross-validation...")
        cv_results = trainer.cross_validate(X, y, n_splits=args.cv)
        print(f"\nCross-validation results:")
        print(f"  Mean accuracy: {cv_results['mean']:.4f}")
        print(f"  Std accuracy: {cv_results['std']:.4f}")
    
    # 训练最终模型
    print(f"\n[4] Training final model...")
    train_results = trainer.train(X, y, verbose=True)
    
    # 保存模型
    print(f"\n[5] Saving model to {args.output}...")
    trainer.save(args.output)
    
    # 统计信息
    print("\n" + "=" * 70)
    print("Training Summary")
    print("=" * 70)
    print(f"Training samples: {len(X)}")
    print(f"Features: {len(X.columns)}")
    print(f"Classes: {len(y.unique())}")
    print(f"Train accuracy: {train_results['train_accuracy']:.4f}")
    print(f"Val accuracy: {train_results['val_accuracy']:.4f}")
    print(f"Model saved: {args.output}")
    
    # 使用说明
    print("\n" + "=" * 70)
    print("Next Steps:")
    print("=" * 70)
    print(f"1. Update config.py:")
    print(f"   ML_REGIME_VERSION = 'v2'")
    print(f"   ML_REGIME_V2_MODEL_PATH = '{args.output}'")
    print(f"")
    print(f"2. Test the model:")
    print(f"   python test_regime_v2.py --model {args.output} --data {args.data}")
    print(f"")
    print(f"3. Run backtest:")
    print(f"   python backtest_regime_v2.py --model {args.output}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
