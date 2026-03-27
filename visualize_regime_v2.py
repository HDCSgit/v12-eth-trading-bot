#!/usr/bin/env python3
"""
V2市场环境可视化工具
生成静态图表和HTML报告
"""
import sys
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from market_regime_v2 import MarketRegimeDetectorV2
from market_regime_v2.visualizer import RegimeVisualizer


def main():
    import argparse
    parser = argparse.ArgumentParser(description='V2 Market Regime Visualization')
    parser.add_argument('--model', type=str, default='models/regime_xgb_v1.pkl',
                       help='Path to trained V2 model')
    parser.add_argument('--data', type=str, default='eth_usdt_15m_binance.csv',
                       help='Path to historical data')
    parser.add_argument('--output', type=str, default='regime_visualization',
                       help='Output directory for visualizations')
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("V2市场环境可视化工具")
    print("=" * 70)
    
    # 加载模型和数据
    print(f"\n[1/4] 加载模型: {args.model}")
    detector = MarketRegimeDetectorV2(model_path=args.model)
    if not detector.is_ready():
        print("ERROR: 模型加载失败")
        return 1
    
    print(f"[2/4] 加载数据: {args.data}")
    df = pd.read_csv(args.data)
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)
    
    # 只取最近5000条避免内存问题
    if len(df) > 5000:
        df = df.tail(5000)
    print(f"数据条数: {len(df)}")
    
    # 批量预测
    print(f"\n[3/4] 运行预测...")
    result_df = detector.predict_batch(df)
    
    # 创建输出目录
    import os
    os.makedirs(args.output, exist_ok=True)
    
    # 创建可视化器
    viz = RegimeVisualizer()
    
    print(f"\n[4/4] 生成可视化图表...")
    
    # 1. 时间线图
    print("  - 生成市场环境时间线...")
    try:
        viz.plot_regime_timeline(
            result_df, 
            save_path=f"{args.output}/regime_timeline.png"
        )
        print(f"    ✓ {args.output}/regime_timeline.png")
    except Exception as e:
        print(f"    ✗ 失败: {e}")
    
    # 2. 特征重要性（如果模型支持）
    print("  - 生成特征重要性图...")
    try:
        if hasattr(detector.model, 'feature_importances_'):
            importance = dict(zip(
                detector.feature_extractor.FEATURE_COLS,
                detector.model.feature_importances_
            ))
            viz.plot_feature_importance(
                importance,
                top_n=15,
                save_path=f"{args.output}/feature_importance.png"
            )
            print(f"    ✓ {args.output}/feature_importance.png")
    except Exception as e:
        print(f"    ✗ 失败: {e}")
    
    # 3. HTML报告
    print("  - 生成HTML报告...")
    try:
        viz.generate_html_report(
            result_df,
            output_path=f"{args.output}/report.html"
        )
        print(f"    ✓ {args.output}/report.html")
    except Exception as e:
        print(f"    ✗ 失败: {e}")
    
    # 4. 保存预测数据
    result_df.to_csv(f"{args.output}/predictions.csv")
    print(f"    ✓ {args.output}/predictions.csv")
    
    print("\n" + "=" * 70)
    print("可视化完成!")
    print(f"输出目录: {args.output}/")
    print("=" * 70)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
