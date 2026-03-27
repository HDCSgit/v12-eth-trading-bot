"""
市场环境可视化模块
提供实时和历史市场状态的可视化展示
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime

# 可视化依赖（可选）
try:
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    from matplotlib.patches import Rectangle
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False


class RegimeVisualizer:
    """市场环境可视化器"""
    
    # 环境类型颜色映射
    REGIME_COLORS = {
        'SIDEWAYS': '#808080',        # 灰色
        'TRENDING_UP': '#00FF00',     # 绿色
        'TRENDING_DOWN': '#FF0000',   # 红色
        'WEAK_TREND_UP': '#90EE90',   # 浅绿
        'WEAK_TREND_DOWN': '#FFB6C1', # 浅红
        'BREAKOUT': '#FFD700',        # 金色
        'BREAKDOWN': '#FF4500',       # 橙红
        'PUMP': '#FF69B4',            # 粉红
        'HIGH_VOL': '#FFA500',        # 橙色
        'REVERSAL_TOP': '#800080',    # 紫色
        'REVERSAL_BOTTOM': '#4169E1', # 蓝色
        'UNKNOWN': '#CCCCCC',         # 浅灰
    }
    
    def __init__(self, style: str = 'matplotlib'):
        self.style = style
        self.history: List[Dict] = []
        
    def add_point(self, timestamp: datetime, regime: str, 
                  confidence: float, price: float,
                  probabilities: Optional[Dict] = None):
        """添加可视化数据点"""
        self.history.append({
            'timestamp': timestamp,
            'regime': regime,
            'confidence': confidence,
            'price': price,
            'probabilities': probabilities or {},
        })
    
    def plot_regime_timeline(self, df: pd.DataFrame, 
                             regime_col: str = 'regime_pred',
                             save_path: Optional[str] = None):
        """
        绘制市场环境时间线
        
        Args:
            df: 包含价格和预测结果的DataFrame
            regime_col: 环境预测列名
            save_path: 保存路径
        """
        if not MATPLOTLIB_AVAILABLE:
            print("Matplotlib not installed, cannot plot")
            return
        
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(15, 12), 
                                            gridspec_kw={'height_ratios': [3, 1, 1]})
        
        # 1. 价格图 + 环境背景色
        ax1.plot(df.index, df['close'], color='black', linewidth=1, label='Price')
        
        # 添加环境背景色
        current_regime = None
        start_idx = 0
        
        for i, regime in enumerate(df[regime_col]):
            if regime != current_regime:
                if current_regime is not None:
                    color = self.REGIME_COLORS.get(current_regime, '#CCCCCC')
                    ax1.axvspan(df.index[start_idx], df.index[i], 
                               alpha=0.2, color=color)
                current_regime = regime
                start_idx = i
        
        # 最后一个区间
        if current_regime is not None:
            color = self.REGIME_COLORS.get(current_regime, '#CCCCCC')
            ax1.axvspan(df.index[start_idx], df.index[-1], 
                       alpha=0.2, color=color)
        
        ax1.set_ylabel('Price')
        ax1.set_title('Market Regime Timeline')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # 2. 置信度图
        if 'regime_confidence' in df.columns:
            ax2.plot(df.index, df['regime_confidence'], 
                    color='blue', linewidth=1, label='Confidence')
            ax2.axhline(y=0.7, color='red', linestyle='--', 
                       alpha=0.5, label='Threshold')
            ax2.fill_between(df.index, df['regime_confidence'], 
                            alpha=0.3, color='blue')
            ax2.set_ylabel('Confidence')
            ax2.set_ylim(0, 1)
            ax2.legend()
            ax2.grid(True, alpha=0.3)
        
        # 3. 环境类型图
        regime_encoded = df[regime_col].map({
            r: i for i, r in enumerate(self.REGIME_COLORS.keys())
        }).fillna(0)
        
        scatter_colors = [self.REGIME_COLORS.get(r, '#CCCCCC') 
                         for r in df[regime_col]]
        ax3.scatter(df.index, regime_encoded, 
                   c=scatter_colors, s=10, alpha=0.7)
        ax3.set_ylabel('Regime Type')
        ax3.set_yticks(range(len(self.REGIME_COLORS)))
        ax3.set_yticklabels(list(self.REGIME_COLORS.keys()), fontsize=8)
        ax3.grid(True, alpha=0.3)
        
        # 图例
        legend_elements = [mpatches.Patch(color=color, label=regime, alpha=0.5)
                          for regime, color in self.REGIME_COLORS.items()]
        ax1.legend(handles=legend_elements, loc='upper left', 
                  fontsize=8, ncol=3)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
            print(f"Saved to {save_path}")
        else:
            plt.show()
    
    def plot_probability_heatmap(self, df: pd.DataFrame,
                                 save_path: Optional[str] = None):
        """
        绘制环境概率热力图
        
        显示每个时间点各类别的概率分布
        """
        if not MATPLOTLIB_AVAILABLE:
            print("Matplotlib not installed, cannot plot")
            return
        
        # 需要概率列
        prob_cols = [c for c in df.columns if c.startswith('prob_')]
        if len(prob_cols) == 0:
            print("No probability columns found")
            return
        
        fig, ax = plt.subplots(figsize=(15, 8))
        
        # 构建概率矩阵
        prob_matrix = df[prob_cols].values.T
        
        im = ax.imshow(prob_matrix, aspect='auto', cmap='RdYlGn',
                       interpolation='nearest', vmin=0, vmax=1)
        
        ax.set_yticks(range(len(prob_cols)))
        ax.set_yticklabels([c.replace('prob_', '') for c in prob_cols])
        ax.set_xlabel('Time')
        ax.set_title('Market Regime Probability Heatmap')
        
        plt.colorbar(im, ax=ax, label='Probability')
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
        else:
            plt.show()
    
    def plot_feature_importance(self, importance_dict: Dict[str, float],
                                 top_n: int = 15,
                                 save_path: Optional[str] = None):
        """
        绘制特征重要性图
        
        Args:
            importance_dict: {特征名: 重要性}
            top_n: 显示前N个特征
        """
        if not MATPLOTLIB_AVAILABLE:
            print("Matplotlib not installed, cannot plot")
            return
        
        # 排序
        sorted_items = sorted(importance_dict.items(), 
                             key=lambda x: x[1], reverse=True)[:top_n]
        
        features, values = zip(*sorted_items)
        
        fig, ax = plt.subplots(figsize=(10, 8))
        
        y_pos = np.arange(len(features))
        ax.barh(y_pos, values, align='center')
        ax.set_yticks(y_pos)
        ax.set_yticklabels(features)
        ax.invert_yaxis()
        ax.set_xlabel('Importance')
        ax.set_title(f'Top {top_n} Feature Importance')
        ax.grid(True, alpha=0.3, axis='x')
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
        else:
            plt.show()
    
    def create_interactive_dashboard(self, df: pd.DataFrame,
                                      port: int = 8050):
        """
        创建交互式Dash应用（实时可视化）
        
        需要安装 dash: pip install dash
        """
        try:
            import dash
            from dash import dcc, html
            from dash.dependencies import Input, Output
        except ImportError:
            print("Dash not installed. Run: pip install dash")
            return
        
        app = dash.Dash(__name__)
        
        app.layout = html.Div([
            html.H1("Market Regime Monitor V2", style={'textAlign': 'center'}),
            
            dcc.Graph(id='price-regime-chart'),
            
            dcc.Graph(id='confidence-chart'),
            
            dcc.Interval(id='interval', interval=5000),  # 5秒刷新
        ])
        
        @app.callback(
            [Output('price-regime-chart', 'figure'),
             Output('confidence-chart', 'figure')],
            [Input('interval', 'n_intervals')]
        )
        def update_charts(n):
            # 价格+环境图
            fig1 = go.Figure()
            fig1.add_trace(go.Scatter(
                x=df.index, y=df['close'],
                mode='lines', name='Price'
            ))
            fig1.update_layout(title='Price & Regime')
            
            # 置信度图
            fig2 = go.Figure()
            if 'regime_confidence' in df.columns:
                fig2.add_trace(go.Scatter(
                    x=df.index, y=df['regime_confidence'],
                    mode='lines', name='Confidence',
                    fill='tozeroy'
                ))
            fig2.update_layout(title='Regime Confidence')
            
            return fig1, fig2
        
        app.run_server(debug=False, port=port)
    
    def generate_html_report(self, df: pd.DataFrame, 
                             output_path: str = 'regime_report.html'):
        """生成HTML报告"""
        
        # 统计信息
        regime_counts = df['regime_pred'].value_counts()
        avg_confidence = df.get('regime_confidence', pd.Series()).mean()
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Market Regime Analysis Report</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .header {{ background: #333; color: white; padding: 20px; }}
                .stats {{ display: flex; gap: 20px; margin: 20px 0; }}
                .stat-box {{ border: 1px solid #ddd; padding: 15px; border-radius: 5px; }}
                .regime-item {{ padding: 5px; margin: 2px; border-radius: 3px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>Market Regime Analysis Report</h1>
                <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            </div>
            
            <div class="stats">
                <div class="stat-box">
                    <h3>Total Samples</h3>
                    <p>{len(df)}</p>
                </div>
                <div class="stat-box">
                    <h3>Avg Confidence</h3>
                    <p>{avg_confidence:.2%}</p>
                </div>
                <div class="stat-box">
                    <h3>Unique Regimes</h3>
                    <p>{len(regime_counts)}</p>
                </div>
            </div>
            
            <h2>Regime Distribution</h2>
            <div>
                {''.join([
                    f'<div class="regime-item" style="background: {self.REGIME_COLORS.get(r, '#ccc')}">'
                    f'{r}: {c} ({c/len(df):.1%})</div>'
                    for r, c in regime_counts.items()
                ])}
            </div>
        </body>
        </html>
        """
        
        with open(output_path, 'w') as f:
            f.write(html_content)
        
        print(f"Report saved to {output_path}")


def create_simple_console_visualizer(result_dict: Dict) -> str:
    """
    简单的控制台可视化
    
    返回ASCII艺术字符串
    """
    regime = result_dict.get('regime', 'UNKNOWN')
    confidence = result_dict.get('confidence', 0)
    
    # 置信度条
    bar_len = int(confidence * 20)
    bar = '█' * bar_len + '░' * (20 - bar_len)
    
    lines = [
        "╔════════════════════════════════════╗",
        f"║  Market Regime: {regime:18} ║",
        "╠════════════════════════════════════╣",
        f"║  Confidence: [{bar}] {confidence:.1%}  ║",
        "╚════════════════════════════════════╝",
    ]
    
    return '\n'.join(lines)
