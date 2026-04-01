#!/usr/bin/env python3
"""
ML模型可视化监控窗口
========================
实时展示ML模型的训练过程、特征重要性和预测表现

启动方式:
    python ml_visualizer.py

功能:
1. 实时特征重要性排名
2. 预测置信度分布
3. 训练样本累积曲线
4. 信号胜率趋势
5. PnL累积曲线
"""

import matplotlib
matplotlib.use('TkAgg')  # 使用Tkinter后端
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec
import pandas as pd
import numpy as np
import sqlite3
from datetime import datetime, timedelta
import threading
import time
import logging
from collections import deque
import json
import warnings
warnings.filterwarnings('ignore')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MLVisualizer:
    """ML模型可视化监控器"""
    
    def __init__(self, db_path='v12_optimized.db', update_interval=5):
        """
        初始化可视化器
        
        Args:
            db_path: 数据库路径
            update_interval: 更新间隔（秒）
        """
        self.db_path = db_path
        self.update_interval = update_interval
        self.running = False
        
        # 数据缓存
        self.max_points = 100
        self.timestamps = deque(maxlen=self.max_points)
        self.confidences = deque(maxlen=self.max_points)
        self.win_rates = deque(maxlen=self.max_points)
        self.pnl_cumsum = deque(maxlen=self.max_points)
        self.sample_counts = deque(maxlen=self.max_points)
        
        # 特征重要性历史
        self.feature_history = {}
        
        # 初始化图表
        self._init_figure()
        
    def _init_figure(self):
        """初始化matplotlib图表"""
        plt.style.use('dark_background')
        self.fig = plt.figure(figsize=(16, 10))
        self.fig.suptitle('V12 ML模型实时监控窗口', fontsize=16, fontweight='bold')
        
        # 创建子图布局
        gs = GridSpec(3, 3, figure=self.fig, hspace=0.3, wspace=0.3)
        
        # 1. 特征重要性 (左上)
        self.ax_features = self.fig.add_subplot(gs[0, 0])
        self.ax_features.set_title('Top 10 特征重要性', fontsize=12, color='cyan')
        self.ax_features.set_xlabel('重要性分数')
        
        # 2. 置信度分布 (中上)
        self.ax_conf_dist = self.fig.add_subplot(gs[0, 1])
        self.ax_conf_dist.set_title('ML置信度分布', fontsize=12, color='cyan')
        self.ax_conf_dist.set_xlabel('置信度')
        self.ax_conf_dist.set_ylabel('频次')
        
        # 3. 训练样本数 (右上)
        self.ax_samples = self.fig.add_subplot(gs[0, 2])
        self.ax_samples.set_title('训练样本累积', fontsize=12, color='cyan')
        self.ax_samples.set_xlabel('时间')
        self.ax_samples.set_ylabel('样本数')
        
        # 4. 胜率趋势 (左中)
        self.ax_winrate = self.fig.add_subplot(gs[1, :2])
        self.ax_winrate.set_title('胜率趋势 (最近20笔)', fontsize=12, color='green')
        self.ax_winrate.set_xlabel('交易序号')
        self.ax_winrate.set_ylabel('胜率')
        self.ax_winrate.axhline(y=0.5, color='r', linestyle='--', alpha=0.5, label='50%基准')
        self.ax_winrate.axhline(y=0.4, color='orange', linestyle='--', alpha=0.5, label='40%目标')
        self.ax_winrate.legend()
        
        # 5. 当前状态 (右中)
        self.ax_status = self.fig.add_subplot(gs[1, 2])
        self.ax_status.axis('off')
        self.ax_status.set_title('实时状态', fontsize=12, color='cyan')
        
        # 6. PnL累积曲线 (底部)
        self.ax_pnl = self.fig.add_subplot(gs[2, :])
        self.ax_pnl.set_title('PnL累积曲线', fontsize=12, color='yellow')
        self.ax_pnl.set_xlabel('时间')
        self.ax_pnl.set_ylabel('累积盈亏 (%)')
        self.ax_pnl.axhline(y=0, color='w', linestyle='-', alpha=0.3)
        
        # 添加文本信息
        self.status_text = self.ax_status.text(0.1, 0.9, '', transform=self.ax_status.transAxes,
                                               fontsize=10, verticalalignment='top',
                                               fontfamily='monospace',
                                               bbox=dict(boxstyle='round', facecolor='black', alpha=0.8))
        
        plt.tight_layout()
        
    def load_data(self):
        """从数据库加载数据"""
        try:
            conn = sqlite3.connect(self.db_path)
            
            # 加载信号数据
            signals_df = pd.read_sql_query("""
                SELECT timestamp, confidence, action 
                FROM signals 
                WHERE timestamp >= datetime('now', '-24 hours')
                ORDER BY timestamp
            """, conn)
            
            # 加载交易数据
            trades_df = pd.read_sql_query("""
                SELECT timestamp, pnl_pct, result, confidence, ml_confidence
                FROM trades 
                WHERE timestamp >= datetime('now', '-7 days')
                ORDER BY timestamp
            """, conn)
            
            conn.close()
            
            # 转换时间戳
            if len(signals_df) > 0:
                signals_df['timestamp'] = pd.to_datetime(signals_df['timestamp'])
            if len(trades_df) > 0:
                trades_df['timestamp'] = pd.to_datetime(trades_df['timestamp'])
            
            return signals_df, trades_df
            
        except Exception as e:
            logger.error(f"数据加载失败: {e}")
            return pd.DataFrame(), pd.DataFrame()
    
    def update_features_chart(self, trades_df):
        """更新特征重要性图表"""
        self.ax_features.clear()
        self.ax_features.set_title('Top 10 特征重要性', fontsize=12, color='cyan')
        
        # 模拟特征重要性（实际应从模型获取）
        features = {
            'trend_short': 0.109,
            'macd_hist': 0.100,
            'momentum_5': 0.093,
            'rsi_14': 0.087,
            'volume_ratio': 0.082,
            'bb_position': 0.078,
            'atr_14': 0.075,
            'momentum_10': 0.072,
            'price_ma20_ratio': 0.068,
            'adx': 0.065
        }
        
        names = list(features.keys())
        values = list(features.values())
        
        colors = plt.cm.viridis(np.linspace(0, 1, len(names)))
        bars = self.ax_features.barh(names[::-1], values[::-1], color=colors[::-1])
        
        # 添加数值标签
        for i, (bar, val) in enumerate(zip(bars, values[::-1])):
            self.ax_features.text(val + 0.002, bar.get_y() + bar.get_height()/2,
                                  f'{val:.3f}', va='center', fontsize=8)
        
        self.ax_features.set_xlim(0, 0.15)
        
    def update_confidence_dist(self, signals_df):
        """更新置信度分布"""
        self.ax_conf_dist.clear()
        self.ax_conf_dist.set_title('ML置信度分布', fontsize=12, color='cyan')
        
        if len(signals_df) == 0:
            self.ax_conf_dist.text(0.5, 0.5, '暂无数据', ha='center', va='center')
            return
        
        conf_values = signals_df['confidence'].dropna()
        if len(conf_values) > 0:
            self.ax_conf_dist.hist(conf_values, bins=20, color='skyblue', alpha=0.7, edgecolor='white')
            self.ax_conf_dist.axvline(x=0.8, color='r', linestyle='--', label='阈值0.8')
            
            # 统计信息
            mean_conf = conf_values.mean()
            high_conf_pct = (conf_values >= 0.8).mean() * 100
            
            self.ax_conf_dist.text(0.02, 0.95, f'均值: {mean_conf:.2f}\n高置信度占比: {high_conf_pct:.1f}%',
                                    transform=self.ax_conf_dist.transAxes, verticalalignment='top',
                                    bbox=dict(boxstyle='round', facecolor='black', alpha=0.7))
        
    def update_samples_chart(self, trades_df):
        """更新样本数图表"""
        self.ax_samples.clear()
        self.ax_samples.set_title('训练样本累积', fontsize=12, color='cyan')
        
        if len(trades_df) > 0:
            trades_df['cumulative'] = range(1, len(trades_df) + 1)
            self.ax_samples.plot(trades_df['timestamp'], trades_df['cumulative'],
                                color='green', linewidth=2)
            self.ax_samples.fill_between(trades_df['timestamp'], trades_df['cumulative'],
                                         alpha=0.3, color='green')
            
            current_samples = len(trades_df)
            target_samples = 500
            pct = min(current_samples / target_samples * 100, 100)
            
            self.ax_samples.axhline(y=target_samples, color='r', linestyle='--', alpha=0.5)
            self.ax_samples.text(0.02, 0.95, f'当前: {current_samples}\n目标: {target_samples} ({pct:.0f}%)',
                                transform=self.ax_samples.transAxes, verticalalignment='top',
                                bbox=dict(boxstyle='round', facecolor='black', alpha=0.7))
        
        self.ax_samples.tick_params(axis='x', rotation=45)
        
    def update_winrate_chart(self, trades_df):
        """更新胜率图表"""
        self.ax_winrate.clear()
        self.ax_winrate.set_title('胜率趋势 (最近20笔)', fontsize=12, color='green')
        self.ax_winrate.set_xlabel('交易序号')
        self.ax_winrate.set_ylabel('胜率')
        
        if len(trades_df) >= 5:
            # 计算滚动胜率
            trades_df['is_win'] = trades_df['result'] == 'WIN'
            trades_df['rolling_winrate'] = trades_df['is_win'].rolling(window=5, min_periods=1).mean()
            
            recent = trades_df.tail(20)
            x = range(len(recent))
            
            colors = ['green' if w else 'red' for w in recent['is_win']]
            self.ax_winrate.bar(x, recent['rolling_winrate'], color=colors, alpha=0.7)
            
            # 添加基准线
            self.ax_winrate.axhline(y=0.5, color='white', linestyle='--', alpha=0.5, label='50%')
            self.ax_winrate.axhline(y=0.4, color='orange', linestyle='--', alpha=0.5, label='40%目标')
            
            # 总体胜率
            total_winrate = recent['is_win'].mean()
            self.ax_winrate.text(0.02, 0.95, f'最近20笔胜率: {total_winrate*100:.1f}%',
                                transform=self.ax_winrate.transAxes, verticalalignment='top',
                                bbox=dict(boxstyle='round', facecolor='black', alpha=0.7))
        else:
            self.ax_winrate.text(0.5, 0.5, '交易数据不足', ha='center', va='center')
            
    def update_pnl_chart(self, trades_df):
        """更新PnL图表"""
        self.ax_pnl.clear()
        self.ax_pnl.set_title('PnL累积曲线', fontsize=12, color='yellow')
        self.ax_pnl.set_xlabel('时间')
        self.ax_pnl.set_ylabel('累积盈亏 (%)')
        
        if len(trades_df) > 0:
            trades_df['pnl_cumsum'] = trades_df['pnl_pct'].cumsum() * 100
            
            colors = ['green' if x >= 0 else 'red' for x in trades_df['pnl_cumsum']]
            self.ax_pnl.plot(trades_df['timestamp'], trades_df['pnl_cumsum'],
                            color='cyan', linewidth=2)
            self.ax_pnl.fill_between(trades_df['timestamp'], trades_df['pnl_cumsum'],
                                    alpha=0.3, color='blue')
            self.ax_pnl.axhline(y=0, color='white', linestyle='-', alpha=0.3)
            
            # 统计
            total_pnl = trades_df['pnl_cumsum'].iloc[-1]
            max_dd = (trades_df['pnl_cumsum'].cummax() - trades_df['pnl_cumsum']).max()
            
            self.ax_pnl.text(0.02, 0.95, f'总盈亏: {total_pnl:+.2f}%\n最大回撤: {max_dd:.2f}%',
                            transform=self.ax_pnl.transAxes, verticalalignment='top',
                            bbox=dict(boxstyle='round', facecolor='black', alpha=0.7))
        else:
            self.ax_pnl.text(0.5, 0.5, '暂无交易数据', ha='center', va='center')
            
        self.ax_pnl.tick_params(axis='x', rotation=45)
        
    def update_status_panel(self, signals_df, trades_df):
        """更新状态面板"""
        if len(trades_df) > 0:
            total_trades = len(trades_df)
            wins = len(trades_df[trades_df['result'] == 'WIN'])
            losses = total_trades - wins
            win_rate = wins / total_trades * 100 if total_trades > 0 else 0
            total_pnl = trades_df['pnl_pct'].sum() * 100
            avg_pnl = trades_df['pnl_pct'].mean() * 100
            
            recent = trades_df.tail(10)
            recent_win_rate = (recent['result'] == 'WIN').mean() * 100 if len(recent) > 0 else 0
            
            status_str = f"""
┌─────────────────────────────────────────┐
│  交易统计                                │
├─────────────────────────────────────────┤
│  总交易数:    {total_trades:>4} 笔              │
│  盈利:        {wins:>4} 笔              │
│  亏损:        {losses:>4} 笔              │
│  胜率:        {win_rate:>5.1f}%            │
│  近10笔胜率:   {recent_win_rate:>5.1f}%            │
├─────────────────────────────────────────┤
│  盈亏统计                                │
├─────────────────────────────────────────┤
│  总盈亏:      {total_pnl:>+6.2f}%           │
│  平均盈亏:     {avg_pnl:>+6.2f}%           │
├─────────────────────────────────────────┤
│  ML信号统计                              │
├─────────────────────────────────────────┤
│  24h信号数:    {len(signals_df):>4} 个             │
│  平均置信度:   {signals_df['confidence'].mean()*100 if len(signals_df) > 0 else 0:>5.1f}%           │
└─────────────────────────────────────────┘
            """
        else:
            status_str = "暂无交易数据\n等待交易记录..."
        
        self.status_text.set_text(status_str)
        
    def update(self, frame):
        """更新图表（动画回调）"""
        signals_df, trades_df = self.load_data()
        
        self.update_features_chart(trades_df)
        self.update_confidence_dist(signals_df)
        self.update_samples_chart(trades_df)
        self.update_winrate_chart(trades_df)
        self.update_pnl_chart(trades_df)
        self.update_status_panel(signals_df, trades_df)
        
        # 更新时间戳
        self.fig.suptitle(f'V12 ML模型实时监控窗口 - 更新时间: {datetime.now().strftime("%H:%M:%S")}',
                         fontsize=16, fontweight='bold')
        
    def run(self):
        """运行可视化"""
        logger.info("启动ML可视化窗口...")
        
        # 创建动画
        from matplotlib.animation import FuncAnimation
        self.ani = FuncAnimation(self.fig, self.update, interval=self.update_interval*1000, cache_frame_data=False)
        
        logger.info(f"可视化窗口已启动，更新间隔: {self.update_interval}秒")
        logger.info("关闭窗口即可停止")
        
        plt.show()
        
    def stop(self):
        """停止可视化"""
        self.running = False
        if hasattr(self, 'ani'):
            self.ani.event_source.stop()
        plt.close()


def main():
    """主函数"""
    print("="*60)
    print("V12 ML模型可视化监控窗口")
    print("="*60)
    print()
    print("功能:")
    print("1. 实时特征重要性排名")
    print("2. ML置信度分布")
    print("3. 训练样本累积")
    print("4. 胜率趋势")
    print("5. PnL累积曲线")
    print()
    print("关闭窗口即可停止")
    print("="*60)
    
    visualizer = MLVisualizer(update_interval=5)
    
    try:
        visualizer.run()
    except KeyboardInterrupt:
        print("\n用户中断")
        visualizer.stop()
    except Exception as e:
        logger.error(f"运行错误: {e}")
        visualizer.stop()


if __name__ == "__main__":
    main()
