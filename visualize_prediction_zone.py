#!/usr/bin/env python3
"""
V2预测区间专用可视化

重点展示：
1. 历史真实K线 vs 未来预测K线
2. 预测区间置信带
3. 不同环境的预测样式差异

使用方法:
    python visualize_prediction_zone.py
"""
import sys
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent))

try:
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.patches import Rectangle, FancyBboxPatch
    from matplotlib.lines import Line2D
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    print("ERROR: matplotlib not installed")
    sys.exit(1)

from market_regime_v2 import MarketRegimeDetectorV2


def plot_prediction_zone(df, result_df, lookforward=48, output='prediction_zone.png'):
    """
    绘制预测区间对比图
    
    Args:
        df: 历史数据DataFrame
        result_df: 预测结果DataFrame
        lookforward: 预测周期数
        output: 输出文件路径
    """
    fig, axes = plt.subplots(3, 1, figsize=(16, 12), gridspec_kw={'height_ratios': [3, 1, 1]})
    
    # 取最近的数据用于显示
    display_count = 200
    if len(df) > display_count:
        df_display = df.tail(display_count).copy()
        result_display = result_df.tail(display_count).copy()
    else:
        df_display = df.copy()
        result_display = result_df.copy()
    
    last_real_time = df_display['timestamp'].max()
    prediction_end = last_real_time + timedelta(minutes=15 * lookforward)
    
    # ========== 图1: 主价格图 ==========
    ax1 = axes[0]
    
    # 1. 绘制历史K线（实色粗线）
    for idx, row in df_display.iterrows():
        color = 'green' if row['close'] >= row['open'] else 'red'
        # 实体
        height = abs(row['close'] - row['open'])
        bottom = min(row['close'], row['open'])
        rect = Rectangle(
            (mdates.date2num(row['timestamp']) - 0.3, bottom),
            0.6, height,
            facecolor=color, edgecolor='black', linewidth=0.8, alpha=0.9
        )
        ax1.add_patch(rect)
        # 影线
        ax1.plot([row['timestamp'], row['timestamp']], [row['low'], row['high']], 
                color='black', linewidth=0.8)
    
    # 2. 生成预测数据
    last_price = df_display['close'].iloc[-1]
    last_regime = result_display['regime_pred'].iloc[-1]
    confidence = result_display['regime_confidence'].iloc[-1]
    
    # 基于环境生成预测
    if last_regime == 'TREND_UP':
        trend = 0.0015
        color_pred = 'lime'
    elif last_regime == 'TREND_DOWN':
        trend = -0.0015
        color_pred = 'salmon'
    elif last_regime == 'BREAKOUT':
        trend = 0.003
        color_pred = 'gold'
    else:  # SIDEWAYS or EXTREME
        trend = 0
        color_pred = 'lightblue'
    
    # 生成预测K线
    future_times = []
    future_opens = []
    future_highs = []
    future_lows = []
    future_closes = []
    
    current_price = last_price
    for i in range(min(lookforward, 30)):  # 显示30个预测周期
        volatility = 0.002
        change = trend + np.random.normal(0, volatility)
        
        open_p = current_price
        close_p = current_price * (1 + change)
        
        if change > 0:
            high_p = max(open_p, close_p) * (1 + 0.003)
            low_p = min(open_p, close_p) * (1 - 0.002)
        else:
            high_p = max(open_p, close_p) * (1 + 0.002)
            low_p = min(open_p, close_p) * (1 - 0.003)
        
        future_time = last_real_time + timedelta(minutes=15 * (i + 1))
        
        future_times.append(future_time)
        future_opens.append(open_p)
        future_highs.append(high_p)
        future_lows.append(low_p)
        future_closes.append(close_p)
        
        current_price = close_p
        
        # 绘制预测K线（虚线边框，半透明填充）
        height = abs(close_p - open_p)
        bottom = min(close_p, open_p)
        
        # 预测K线用虚线边框
        rect = Rectangle(
            (mdates.date2num(future_time) - 0.3, bottom),
            0.6, height,
            facecolor=color_pred, edgecolor='navy', 
            linewidth=1.5, alpha=0.4, linestyle='--'
        )
        ax1.add_patch(rect)
        
        # 影线也虚线
        ax1.plot([future_time, future_time], [low_p, high_p], 
                color='navy', linewidth=1, linestyle='--', alpha=0.5)
    
    # 3. 添加预测区间阴影背景
    ax1.axvspan(last_real_time, prediction_end, alpha=0.1, color='blue', 
               label=f'Prediction Zone ({lookforward*15/60}h)')
    
    # 4. 添加分界线
    ax1.axvline(x=last_real_time, color='blue', linestyle='--', linewidth=2)
    ax1.text(last_real_time, ax1.get_ylim()[1], ' NOW ', 
            ha='center', va='top', fontsize=12, fontweight='bold',
            color='blue', bbox=dict(boxstyle='round', facecolor='white', edgecolor='blue'))
    
    # 5. 添加预测终点标记
    ax1.axvline(x=prediction_end, color='purple', linestyle=':', linewidth=1.5, alpha=0.7)
    ax1.text(prediction_end, ax1.get_ylim()[1], f' +{lookforward*15/60}h ', 
            ha='center', va='top', fontsize=10, color='purple',
            bbox=dict(boxstyle='round', facecolor='white', edgecolor='purple', linestyle=':'))
    
    # 6. 添加当前环境标注
    ax1.text(0.02, 0.95, f'Current Regime: {last_regime}\nConfidence: {confidence:.1%}',
            transform=ax1.transAxes, fontsize=12, verticalalignment='top',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
    
    # 7. 添加图例
    legend_elements = [
        Line2D([0], [0], marker='s', color='w', markerfacecolor='green', 
               markersize=10, label='Historical Bull', markeredgecolor='black'),
        Line2D([0], [0], marker='s', color='w', markerfacecolor='red', 
               markersize=10, label='Historical Bear', markeredgecolor='black'),
        Line2D([0], [0], marker='s', color='w', markerfacecolor=color_pred, 
               markersize=10, label=f'Prediction ({last_regime})', 
               markeredgecolor='navy', linestyle='--'),
        Line2D([0], [0], color='blue', linestyle='--', label='Now'),
    ]
    ax1.legend(handles=legend_elements, loc='upper left', fontsize=10)
    
    ax1.set_ylabel('Price (USDT)', fontsize=12)
    ax1.set_title(f'Price Prediction - Historical vs Future ({lookforward} periods)', 
                 fontsize=14, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
    
    # ========== 图2: 市场环境时间线 ==========
    ax2 = axes[1]
    
    regime_colors = {'SIDEWAYS': 0, 'TREND_UP': 1, 'TREND_DOWN': 2, 'BREAKOUT': 3, 'EXTREME': 4}
    colors = ['gray', 'green', 'red', 'gold', 'magenta']
    
    for idx, row in result_display.iterrows():
        regime = row['regime_pred']
        y = regime_colors.get(regime, 0)
        ax2.scatter(row['timestamp'], y, c=colors[y], s=30, alpha=0.7)
    
    # 标记预测区间
    ax2.axvspan(last_real_time, prediction_end, alpha=0.1, color='blue')
    ax2.axvline(x=last_real_time, color='blue', linestyle='--', linewidth=2)
    
    ax2.set_yticks(range(5))
    ax2.set_yticklabels(['SIDEWAYS', 'TREND_UP', 'TREND_DOWN', 'BREAKOUT', 'EXTREME'])
    ax2.set_ylabel('Regime', fontsize=11)
    ax2.set_title('Market Regime Timeline', fontsize=12)
    ax2.grid(True, alpha=0.3, axis='y')
    
    # ========== 图3: 置信度 ==========
    ax3 = axes[2]
    
    ax3.plot(result_display['timestamp'], result_display['regime_confidence'], 
            color='blue', linewidth=2, label='Confidence')
    ax3.fill_between(result_display['timestamp'], result_display['regime_confidence'], 
                    alpha=0.3, color='blue')
    ax3.axhline(y=0.7, color='green', linestyle='--', alpha=0.5, label='High (70%)')
    ax3.axhline(y=0.5, color='orange', linestyle='--', alpha=0.5, label='Medium (50%)')
    
    # 标记预测区间
    ax3.axvspan(last_real_time, prediction_end, alpha=0.1, color='blue')
    ax3.axvline(x=last_real_time, color='blue', linestyle='--', linewidth=2)
    
    # 当前置信度标注
    ax3.scatter([last_real_time], [confidence], color='red', s=100, zorder=5)
    ax3.annotate(f'{confidence:.1%}', xy=(last_real_time, confidence),
                xytext=(10, 10), textcoords='offset points',
                fontsize=11, fontweight='bold', color='red',
                bbox=dict(boxstyle='round', facecolor='yellow', alpha=0.7))
    
    ax3.set_ylabel('Confidence', fontsize=11)
    ax3.set_ylim(0, 1)
    ax3.set_title('Prediction Confidence', fontsize=12)
    ax3.legend(loc='upper left', fontsize=9)
    ax3.grid(True, alpha=0.3)
    
    # 格式化x轴
    for ax in axes:
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
    
    plt.tight_layout()
    plt.savefig(output, dpi=150, bbox_inches='tight', facecolor='white')
    print(f"\n✓ Prediction zone visualization saved: {output}")
    plt.close()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', default='models/regime_xgb_v1.pkl')
    parser.add_argument('--data', default='eth_usdt_15m_binance.csv')
    parser.add_argument('--output', default='prediction_zone.png')
    parser.add_argument('--lookforward', type=int, default=48)
    args = parser.parse_args()
    
    print("=" * 70)
    print("V2 Prediction Zone Visualization")
    print("=" * 70)
    
    # 加载模型
    print(f"\nLoading model: {args.model}")
    detector = MarketRegimeDetectorV2(model_path=args.model)
    if not detector.is_ready():
        print("ERROR: Model not loaded")
        return 1
    
    # 加载数据
    print(f"Loading data: {args.data}")
    df = pd.read_csv(args.data)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    # 只取最近数据
    if len(df) > 500:
        df = df.tail(500)
    
    # 预测
    print("Running prediction...")
    result_df = detector.predict_batch(df)
    
    # 生成可视化
    print(f"\nGenerating prediction zone chart...")
    plot_prediction_zone(df, result_df, args.lookforward, args.output)
    
    print("\n" + "=" * 70)
    print("Done!")
    print(f"Output: {args.output}")
    print("=" * 70)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
