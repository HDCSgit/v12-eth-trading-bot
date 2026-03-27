#!/usr/bin/env python3
"""
V2市场环境检测 - 高级可视化

特性：
1. 历史K线（实色） vs 预测区间（虚线/半透明）
2. 市场环境背景色标注
3. 置信度热力图
4. 预测概率分布
5. 交互式时间轴

使用方法:
    python visualize_regime_v2_advanced.py --model models/regime_xgb_v1.pkl --data eth_usdt_15m_binance.csv
"""
import sys
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent))

try:
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    from matplotlib.patches import Rectangle
    from matplotlib.collections import LineCollection
    import matplotlib.dates as mdates
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    print("ERROR: matplotlib not installed. Run: pip install matplotlib")
    sys.exit(1)

from market_regime_v2 import MarketRegimeDetectorV2


class AdvancedRegimeVisualizer:
    """高级市场环境可视化器"""
    
    # 市场环境颜色映射
    REGIME_COLORS = {
        'SIDEWAYS': '#808080',      # 灰色
        'TREND_UP': '#00FF00',      # 绿色
        'TREND_DOWN': '#FF0000',    # 红色
        'BREAKOUT': '#FFD700',      # 金色
        'EXTREME': '#FF69B4',       # 粉红
    }
    
    # 预测区间样式
    PREDICTION_STYLE = {
        'color': '#1E90FF',         # 蓝色虚线
        'linestyle': '--',
        'linewidth': 1.5,
        'alpha': 0.7,
    }
    
    def __init__(self, lookforward=48):
        """
        Args:
            lookforward: 预测周期数（48个15分钟=12小时）
        """
        self.lookforward = lookforward
        self.lookforward_hours = lookforward * 15 / 60  # 转换为小时
        
    def plot_advanced_dashboard(self, df, result_df, output_path='regime_advanced.png'):
        """
        绘制高级可视化仪表盘
        
        Args:
            df: 原始OHLCV数据
            result_df: 包含预测结果的数据
            output_path: 输出图片路径
        """
        # 创建子图布局
        fig = plt.figure(figsize=(20, 14))
        gs = fig.add_gridspec(4, 2, height_ratios=[3, 1, 1, 1], hspace=0.05, wspace=0.05)
        
        # 1. 主K线图（含预测区间）
        ax1 = fig.add_subplot(gs[0, :])
        self._plot_price_with_prediction(ax1, df, result_df)
        
        # 2. 市场环境状态条
        ax2 = fig.add_subplot(gs[1, :], sharex=ax1)
        self._plot_regime_timeline(ax2, result_df)
        
        # 3. 置信度曲线
        ax3 = fig.add_subplot(gs[2, :], sharex=ax1)
        self._plot_confidence(ax3, result_df)
        
        # 4. 概率分布热力图（右侧）
        ax4 = fig.add_subplot(gs[3, :], sharex=ax1)
        self._plot_probability_heatmap(ax4, result_df)
        
        # 添加总标题
        fig.suptitle(
            f'V2 Market Regime Analysis - {datetime.now().strftime("%Y-%m-%d %H:%M")}\n'
            f'Prediction Horizon: {self.lookforward_hours}h ({self.lookforward} periods)',
            fontsize=16, fontweight='bold', y=0.995
        )
        
        # 保存
        plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
        print(f"\n✓ 高级可视化已保存: {output_path}")
        plt.close()
    
    def _plot_price_with_prediction(self, ax, df, result_df):
        """
        绘制价格K线，区分历史真实数据和预测区间
        """
        # 计算预测边界
        last_real_time = df['timestamp'].max()
        prediction_start = last_real_time
        prediction_end = last_real_time + timedelta(minutes=15 * self.lookforward)
        
        # 1. 绘制历史真实K线（实色）
        self._plot_candles(ax, df, is_prediction=False)
        
        # 2. 绘制预测区间（虚线/半透明）
        # 模拟未来价格走势（基于预测的环境趋势）
        future_df = self._generate_future_price(df, result_df)
        if future_df is not None:
            self._plot_candles(ax, future_df, is_prediction=True)
        
        # 3. 标记预测区间背景
        ax.axvspan(
            prediction_start, prediction_end,
            alpha=0.1, color='blue', label=f'Prediction Zone ({self.lookforward_hours}h)'
        )
        
        # 4. 添加垂直分界线
        ax.axvline(x=prediction_start, color='blue', linestyle='--', linewidth=2, alpha=0.7)
        ax.text(
            prediction_start, ax.get_ylim()[1] * 0.95,
            f'Now\n{prediction_start.strftime("%m-%d %H:%M")}',
            ha='center', va='top', fontsize=10, color='blue', fontweight='bold',
            bbox=dict(boxstyle='round', facecolor='white', alpha=0.8)
        )
        
        # 5. 添加图例
        ax.legend(loc='upper left', fontsize=10)
        ax.set_ylabel('Price (USDT)', fontsize=11)
        ax.set_title('Price Chart - Historical (Solid) vs Prediction (Dashed)', fontsize=12)
        ax.grid(True, alpha=0.3)
        
        # 格式化x轴
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=6))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
    
    def _plot_candles(self, ax, df, is_prediction=False):
        """绘制K线"""
        width = 0.6
        width2 = 0.05
        
        # 确定颜色
        if is_prediction:
            # 预测区间：蓝色半透明
            up_color = '#1E90FF'
            down_color = '#4169E1'
            alpha = 0.6
            edge_color = '#1E90FF'
        else:
            # 历史数据：传统红绿
            up_color = '#00FF00'
            down_color = '#FF0000'
            alpha = 1.0
            edge_color = 'black'
        
        for idx, row in df.iterrows():
            if row['close'] >= row['open']:
                color = up_color
            else:
                color = down_color
            
            # 实体
            height = abs(row['close'] - row['open'])
            bottom = min(row['close'], row['open'])
            rect = Rectangle(
                (mdates.date2num(row['timestamp']) - width/2, bottom),
                width, height,
                facecolor=color, edgecolor=edge_color, alpha=alpha, linewidth=0.5
            )
            ax.add_patch(rect)
            
            # 影线
            ax.plot(
                [mdates.date2num(row['timestamp']), mdates.date2num(row['timestamp'])],
                [row['low'], row['high']],
                color=color, alpha=alpha, linewidth=0.8
            )
    
    def _generate_future_price(self, df, result_df):
        """基于预测生成未来价格走势（示意）"""
        # 获取最新的预测结果
        latest_result = result_df.iloc[-1]
        regime = latest_result.get('regime_pred', 'SIDEWAYS')
        confidence = latest_result.get('regime_confidence', 0.5)
        
        # 基于环境类型生成趋势
        last_price = df['close'].iloc[-1]
        last_time = df['timestamp'].iloc[-1]
        
        # 根据预测环境设置趋势方向
        if regime == 'TREND_UP':
            trend = 0.002  # 上涨0.2%每周期
        elif regime == 'TREND_DOWN':
            trend = -0.002  # 下跌0.2%每周期
        elif regime == 'BREAKOUT':
            trend = 0.004  # 突破上涨0.4%
        else:
            trend = 0  # 震荡
        
        # 生成未来价格（简化模型）
        future_data = []
        current_price = last_price
        
        for i in range(min(self.lookforward, 20)):  # 最多显示20个周期
            # 添加随机波动
            volatility = 0.001
            change = trend + np.random.normal(0, volatility)
            
            open_p = current_price
            close_p = current_price * (1 + change)
            high_p = max(open_p, close_p) * (1 + abs(np.random.normal(0, 0.002)))
            low_p = min(open_p, close_p) * (1 - abs(np.random.normal(0, 0.002)))
            
            future_time = last_time + timedelta(minutes=15 * (i + 1))
            
            future_data.append({
                'timestamp': future_time,
                'open': open_p,
                'high': high_p,
                'low': low_p,
                'close': close_p,
            })
            
            current_price = close_p
        
        return pd.DataFrame(future_data)
    
    def _plot_regime_timeline(self, ax, result_df):
        """绘制市场环境时间线"""
        ax.set_ylabel('Regime', fontsize=10)
        ax.set_ylim(-0.5, 4.5)
        ax.set_yticks(range(5))
        ax.set_yticklabels(['SIDEWAYS', 'TREND_UP', 'TREND_DOWN', 'BREAKOUT', 'EXTREME'])
        
        # 绘制环境状态条
        regime_map = {r: i for i, r in enumerate(['SIDEWAYS', 'TREND_UP', 'TREND_DOWN', 'BREAKOUT', 'EXTREME'])}
        
        for idx, row in result_df.iterrows():
            regime = row.get('regime_pred', 'SIDEWAYS')
            y_pos = regime_map.get(regime, 0)
            color = self.REGIME_COLORS.get(regime, '#808080')
            
            ax.scatter(
                row['timestamp'], y_pos,
                c=color, s=50, alpha=0.7, edgecolors='none'
            )
        
        ax.set_title('Market Regime Timeline', fontsize=11)
        ax.grid(True, alpha=0.3, axis='y')
    
    def _plot_confidence(self, ax, result_df):
        """绘制置信度曲线"""
        ax.plot(
            result_df['timestamp'], result_df['regime_confidence'],
            color='blue', linewidth=1.5, alpha=0.8
        )
        ax.fill_between(
            result_df['timestamp'], result_df['regime_confidence'],
            alpha=0.3, color='blue'
        )
        ax.axhline(y=0.7, color='red', linestyle='--', linewidth=1, alpha=0.5, label='High Confidence')
        ax.axhline(y=0.5, color='orange', linestyle='--', linewidth=1, alpha=0.5, label='Medium')
        
        ax.set_ylabel('Confidence', fontsize=10)
        ax.set_ylim(0, 1)
        ax.set_title('Prediction Confidence', fontsize=11)
        ax.legend(loc='upper left', fontsize=8)
        ax.grid(True, alpha=0.3)
    
    def _plot_probability_heatmap(self, ax, result_df):
        """绘制概率分布热力图"""
        regimes = ['SIDEWAYS', 'TREND_UP', 'TREND_DOWN', 'BREAKOUT', 'EXTREME']
        
        # 构建概率矩阵
        prob_matrix = np.zeros((len(regimes), len(result_df)))
        
        for i, regime in enumerate(regimes):
            col_name = f'prob_{regime}'
            if col_name in result_df.columns:
                prob_matrix[i, :] = result_df[col_name].values
            else:
                # 如果没有详细概率，使用one-hot
                prob_matrix[i, :] = (result_df['regime_pred'] == regime).astype(float) * result_df['regime_confidence']
        
        im = ax.imshow(
            prob_matrix, aspect='auto', cmap='RdYlGn',
            interpolation='nearest', vmin=0, vmax=1
        )
        
        ax.set_yticks(range(len(regimes)))
        ax.set_yticklabels(regimes, fontsize=9)
        ax.set_ylabel('Regime Probability', fontsize=10)
        ax.set_title('Regime Probability Heatmap', fontsize=11)
        
        # 添加颜色条
        cbar = plt.colorbar(im, ax=ax, pad=0.01)
        cbar.set_label('Probability', fontsize=9)
        
        # 设置x轴标签
        n_ticks = min(10, len(result_df))
        tick_indices = np.linspace(0, len(result_df)-1, n_ticks, dtype=int)
        ax.set_xticks(tick_indices)
        ax.set_xticklabels(
            [result_df.iloc[i]['timestamp'].strftime('%m-%d %H:%M') for i in tick_indices],
            rotation=45, ha='right', fontsize=8
        )


def main():
    import argparse
    parser = argparse.ArgumentParser(description='V2 Advanced Visualization')
    parser.add_argument('--model', type=str, default='models/regime_xgb_v1.pkl')
    parser.add_argument('--data', type=str, default='eth_usdt_15m_binance.csv')
    parser.add_argument('--output', type=str, default='regime_advanced.png')
    parser.add_argument('--lookforward', type=int, default=48)
    parser.add_argument('--samples', type=int, default=500, help='显示最近N条数据')
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("V2市场环境检测 - 高级可视化")
    print("=" * 70)
    
    # 加载模型
    print(f"\n[1/3] 加载模型: {args.model}")
    detector = MarketRegimeDetectorV2(model_path=args.model)
    if not detector.is_ready():
        print("ERROR: 模型加载失败")
        return 1
    
    # 加载数据
    print(f"[2/3] 加载数据: {args.data}")
    df = pd.read_csv(args.data)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    # 只取最近N条
    if len(df) > args.samples:
        df = df.tail(args.samples)
    print(f"   数据条数: {len(df)}")
    print(f"   时间范围: {df['timestamp'].min()} ~ {df['timestamp'].max()}")
    
    # 预测
    print(f"\n[3/3] 运行预测...")
    result_df = detector.predict_batch(df)
    print(f"   最新环境: {result_df['regime_pred'].iloc[-1]}")
    print(f"   置信度: {result_df['regime_confidence'].iloc[-1]:.1%}")
    
    # 生成可视化
    print(f"\n生成高级可视化...")
    visualizer = AdvancedRegimeVisualizer(lookforward=args.lookforward)
    visualizer.plot_advanced_dashboard(df, result_df, output_path=args.output)
    
    print("\n" + "=" * 70)
    print("可视化完成!")
    print(f"输出文件: {args.output}")
    print("=" * 70)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
