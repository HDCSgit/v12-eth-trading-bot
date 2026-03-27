#!/usr/bin/env python3
"""
市场环境检测V2测试脚本

使用方法:
    python test_regime_v2.py --model models/regime_xgb_v1.pkl --data data/eth_1h.csv
"""
import argparse
import sys
import pandas as pd
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from market_regime_v2 import MarketRegimeDetectorV2
from market_regime_v2.visualizer import create_simple_console_visualizer


def load_data(filepath: str, n_rows: int = 500) -> pd.DataFrame:
    """加载最近N行数据"""
    df = pd.read_csv(filepath)
    
    # 设置时间索引
    time_col = None
    for col in ['timestamp', 'datetime', 'time']:
        if col in df.columns:
            time_col = col
            break
    
    if time_col:
        df[time_col] = pd.to_datetime(df[time_col])
        df.set_index(time_col, inplace=True)
    
    # 只取最近N行
    if len(df) > n_rows:
        df = df.tail(n_rows)
    
    return df


def main():
    parser = argparse.ArgumentParser(description='Test Market Regime V2')
    parser.add_argument('--model', type=str, default='models/regime_xgb_v1.pkl',
                       help='Path to trained model')
    parser.add_argument('--data', type=str, default='data/historical_data.csv',
                       help='Path to test data')
    parser.add_argument('--live', action='store_true',
                       help='Run in live mode (continuous prediction)')
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("Market Regime V2 Test")
    print("=" * 70)
    
    # 加载模型
    print(f"\n[1] Loading model from {args.model}")
    detector = MarketRegimeDetectorV2(model_path=args.model)
    
    if not detector.is_ready():
        print("ERROR: Model not loaded!")
        return 1
    
    print("Model loaded successfully")
    
    # 加载测试数据
    print(f"\n[2] Loading test data from {args.data}")
    try:
        df = load_data(args.data)
        print(f"Loaded {len(df)} rows")
        print(f"Price range: {df['close'].min():.2f} - {df['close'].max():.2f}")
    except Exception as e:
        print(f"Error loading data: {e}")
        return 1
    
    # 运行预测
    print(f"\n[3] Running prediction...")
    result = detector.predict(df)
    
    # 显示结果
    print("\n" + "=" * 70)
    print("Prediction Result")
    print("=" * 70)
    
    result_dict = {
        'regime': result.regime.value,
        'confidence': result.confidence,
    }
    print(create_simple_console_visualizer(result_dict))
    
    print(f"\nUncertainty: {result.uncertainty:.2%}")
    print(f"Top-2 gap: {result.top_2_gap:.2%}")
    print(f"Recommendation: {result.recommended_action}")
    print(f"Position mult: {result.position_size_mult}")
    print(f"Use limit order: {result.use_limit_order}")
    
    # 概率分布
    print(f"\nProbability Distribution:")
    sorted_probs = sorted(result.probabilities.items(), 
                         key=lambda x: x[1], reverse=True)
    for regime, prob in sorted_probs[:5]:
        bar = '█' * int(prob * 20)
        print(f"  {regime:15} [{bar:<20}] {prob:.1%}")
    
    # 批量预测统计
    print(f"\n[4] Batch prediction statistics...")
    result_df = detector.predict_batch(df)
    
    print(f"\nRegime distribution:")
    regime_counts = result_df['regime_pred'].value_counts()
    for regime, count in regime_counts.items():
        pct = count / len(result_df) * 100
        print(f"  {regime:15}: {count:4d} ({pct:.1f}%)")
    
    avg_conf = result_df['regime_confidence'].mean()
    print(f"\nAverage confidence: {avg_conf:.2%}")
    
    print("\n" + "=" * 70)
    print("Test completed successfully!")
    print("=" * 70)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
