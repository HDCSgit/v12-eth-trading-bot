#!/usr/bin/env python3
"""
ML模型Web仪表盘
=================
基于Plotly Dash的交互式可视化界面

功能:
- 实时更新的图表
- 交互式数据探索
- 历史数据回放
- 模型性能分析

启动:
    python ml_dashboard.py
    
访问:
    http://127.0.0.1:8050
"""

import dash
from dash import dcc, html, Input, Output
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
import sqlite3
from datetime import datetime, timedelta
import threading
import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 初始化Dash应用
app = dash.Dash(__name__)
app.title = 'V12 ML Model Dashboard'

# 布局
app.layout = html.Div([
    html.H1('[V12 ML] Real-time Dashboard', style={'textAlign': 'center', 'color': '#00d4ff'}),
    
    html.Div([
        html.Div([
            html.H3('实时状态'),
            html.Div(id='status-cards', className='status-container')
        ], style={'width': '20%', 'display': 'inline-block', 'verticalAlign': 'top'}),
        
        html.Div([
            dcc.Graph(id='live-pnl-chart'),
        ], style={'width': '78%', 'display': 'inline-block'})
    ]),
    
    html.Div([
        html.Div([
            dcc.Graph(id='feature-importance'),
        ], style={'width': '32%', 'display': 'inline-block'}),
        
        html.Div([
            dcc.Graph(id='confidence-distribution'),
        ], style={'width': '32%', 'display': 'inline-block'}),
        
        html.Div([
            dcc.Graph(id='winrate-trend'),
        ], style={'width': '32%', 'display': 'inline-block'})
    ]),
    
    html.Div([
        html.Div([
            dcc.Graph(id='trade-history'),
        ], style={'width': '100%', 'display': 'inline-block'})
    ]),
    
    # 自动更新间隔
    dcc.Interval(id='interval-component', interval=5*1000, n_intervals=0)
], style={'backgroundColor': '#1a1a2e', 'color': 'white', 'padding': '20px'})


def load_data():
    """加载数据"""
    try:
        conn = sqlite3.connect('v12_optimized.db')
        
        trades = pd.read_sql_query("""
            SELECT * FROM trades 
            WHERE timestamp >= datetime('now', '-7 days')
            ORDER BY timestamp
        """, conn)
        
        signals = pd.read_sql_query("""
            SELECT * FROM signals 
            WHERE timestamp >= datetime('now', '-24 hours')
            ORDER BY timestamp
        """, conn)
        
        conn.close()
        
        if len(trades) > 0:
            trades['timestamp'] = pd.to_datetime(trades['timestamp'])
            trades['pnl_cumsum'] = trades['pnl_pct'].cumsum() * 100
            
        if len(signals) > 0:
            signals['timestamp'] = pd.to_datetime(signals['timestamp'])
            
        return trades, signals
    except Exception as e:
        logger.error(f"数据加载失败: {e}")
        return pd.DataFrame(), pd.DataFrame()


@app.callback(
    Output('status-cards', 'children'),
    Input('interval-component', 'n_intervals')
)
def update_status(n):
    """更新状态卡片"""
    trades, signals = load_data()
    
    if len(trades) == 0:
        return html.Div('暂无数据', style={'color': 'gray'})
    
    total_trades = len(trades)
    wins = len(trades[trades['result'] == 'WIN'])
    win_rate = wins / total_trades * 100
    total_pnl = trades['pnl_pct'].sum() * 100
    
    return html.Div([
        create_card('总交易数', total_trades, '#4ecdc4'),
        create_card('胜率', f'{win_rate:.1f}%', '#95e1d3' if win_rate >= 40 else '#ff6b6b'),
        create_card('总盈亏', f'{total_pnl:+.2f}%', '#4ecdc4' if total_pnl >= 0 else '#ff6b6b'),
        create_card('24h信号', len(signals), '#a8e6cf')
    ])


def create_card(title, value, color):
    """创建状态卡片"""
    return html.Div([
        html.H4(title, style={'margin': '5px', 'color': '#888'}),
        html.H2(str(value), style={'margin': '5px', 'color': color})
    ], style={
        'backgroundColor': '#2d2d44',
        'borderRadius': '10px',
        'padding': '15px',
        'margin': '10px 0',
        'textAlign': 'center'
    })


@app.callback(
    Output('live-pnl-chart', 'figure'),
    Input('interval-component', 'n_intervals')
)
def update_pnl_chart(n):
    """更新PnL图表"""
    trades, _ = load_data()
    
    if len(trades) == 0:
        return go.Figure().update_layout(title='暂无数据', paper_bgcolor='#1a1a2e', plot_bgcolor='#1a1a2e')
    
    fig = go.Figure()
    
    # PnL累积曲线
    fig.add_trace(go.Scatter(
        x=trades['timestamp'],
        y=trades['pnl_cumsum'],
        mode='lines',
        name='累积PnL',
        line=dict(color='#00d4ff', width=2),
        fill='tonexty',
        fillcolor='rgba(0, 212, 255, 0.2)'
    ))
    
    # 零线
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    
    # 买卖点标记
    for idx, row in trades.iterrows():
        color = '#00ff88' if row['result'] == 'WIN' else '#ff4444'
        symbol = 'triangle-up' if row['side'] in ['BUY', 'LONG'] else 'triangle-down'
        fig.add_trace(go.Scatter(
            x=[row['timestamp']],
            y=[row['pnl_cumsum']],
            mode='markers',
            marker=dict(color=color, size=12, symbol=symbol),
            name=f"{row['side']} {row['result']}",
            showlegend=False
        ))
    
    fig.update_layout(
        title='💰 PnL累积曲线',
        paper_bgcolor='#1a1a2e',
        plot_bgcolor='#2d2d44',
        font=dict(color='white'),
        xaxis=dict(gridcolor='#444'),
        yaxis=dict(gridcolor='#444', title='盈亏 (%)'),
        height=400
    )
    
    return fig


@app.callback(
    Output('feature-importance', 'figure'),
    Input('interval-component', 'n_intervals')
)
def update_feature_importance(n):
    """更新特征重要性"""
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
    
    fig = go.Figure(go.Bar(
        x=list(features.values()),
        y=list(features.keys()),
        orientation='h',
        marker=dict(color=list(features.values()), colorscale='Viridis')
    ))
    
    fig.update_layout(
        title='🔍 Top 10 特征重要性',
        paper_bgcolor='#1a1a2e',
        plot_bgcolor='#2d2d44',
        font=dict(color='white'),
        xaxis=dict(gridcolor='#444', title='重要性'),
        yaxis=dict(gridcolor='#444'),
        height=350
    )
    
    return fig


@app.callback(
    Output('confidence-distribution', 'figure'),
    Input('interval-component', 'n_intervals')
)
def update_confidence_dist(n):
    """更新置信度分布"""
    _, signals = load_data()
    
    if len(signals) == 0:
        return go.Figure().update_layout(title='暂无数据', paper_bgcolor='#1a1a2e', plot_bgcolor='#1a1a2e')
    
    fig = go.Figure()
    
    fig.add_trace(go.Histogram(
        x=signals['confidence'],
        nbinsx=20,
        marker=dict(color='#00d4ff', line=dict(color='white', width=1)),
        name='置信度分布'
    ))
    
    # 阈值线
    fig.add_vline(x=0.8, line_dash="dash", line_color="red", annotation_text="阈值0.8")
    
    fig.update_layout(
        title='📊 ML置信度分布',
        paper_bgcolor='#1a1a2e',
        plot_bgcolor='#2d2d44',
        font=dict(color='white'),
        xaxis=dict(gridcolor='#444', title='置信度', range=[0.5, 1.0]),
        yaxis=dict(gridcolor='#444', title='频次'),
        height=350
    )
    
    return fig


@app.callback(
    Output('winrate-trend', 'figure'),
    Input('interval-component', 'n_intervals')
)
def update_winrate_trend(n):
    """更新胜率趋势"""
    trades, _ = load_data()
    
    if len(trades) < 5:
        return go.Figure().update_layout(title='数据不足', paper_bgcolor='#1a1a2e', plot_bgcolor='#1a1a2e')
    
    trades['is_win'] = trades['result'] == 'WIN'
    trades['rolling_winrate'] = trades['is_win'].rolling(window=5, min_periods=1).mean()
    
    recent = trades.tail(20)
    
    fig = go.Figure()
    
    colors = ['#00ff88' if w else '#ff4444' for w in recent['is_win']]
    
    fig.add_trace(go.Bar(
        x=list(range(len(recent))),
        y=recent['rolling_winrate'],
        marker=dict(color=colors, opacity=0.8),
        name='滚动胜率'
    ))
    
    fig.add_hline(y=0.5, line_dash="dash", line_color="white", annotation_text="50%")
    fig.add_hline(y=0.4, line_dash="dash", line_color="orange", annotation_text="40%目标")
    
    fig.update_layout(
        title='📈 胜率趋势 (最近20笔)',
        paper_bgcolor='#1a1a2e',
        plot_bgcolor='#2d2d44',
        font=dict(color='white'),
        xaxis=dict(gridcolor='#444', title='交易序号'),
        yaxis=dict(gridcolor='#444', title='胜率', range=[0, 1]),
        height=350
    )
    
    return fig


@app.callback(
    Output('trade-history', 'figure'),
    Input('interval-component', 'n_intervals')
)
def update_trade_history(n):
    """更新交易历史表格"""
    trades, _ = load_data()
    
    if len(trades) == 0:
        return go.Figure().update_layout(title='暂无交易', paper_bgcolor='#1a1a2e', plot_bgcolor='#1a1a2e')
    
    recent = trades.tail(20).sort_values('timestamp', ascending=False)
    
    colors = ['#00ff88' if r == 'WIN' else '#ff4444' for r in recent['result']]
    
    fig = go.Figure(data=[go.Table(
        header=dict(
            values=['时间', '方向', '入场价', '出场价', '盈亏%', '结果', '原因'],
            fill_color='#2d2d44',
            align='center',
            font=dict(color='white', size=12)
        ),
        cells=dict(
            values=[
                recent['timestamp'].dt.strftime('%H:%M:%S'),
                recent['side'],
                recent['entry_price'].round(2),
                recent['exit_price'].round(2),
                (recent['pnl_pct'] * 100).round(2),
                recent['result'],
                recent['reason'].str[:20]
            ],
            fill_color=[colors],
            align='center',
            font=dict(color='white', size=11),
            height=25
        )
    )])
    
    fig.update_layout(
        title='📜 最近交易记录',
        paper_bgcolor='#1a1a2e',
        font=dict(color='white'),
        height=400
    )
    
    return fig


def main():
    """主函数"""
    print("="*60)
    print("V12 ML Model Web Dashboard")
    print("="*60)
    print()
    print("启动中...")
    print()
    print("访问地址: http://127.0.0.1:8050")
    print()
    print("功能:")
    print("  - 实时PnL曲线")
    print("  - 特征重要性排名")
    print("  - 置信度分布")
    print("  - 胜率趋势")
    print("  - 交易历史")
    print()
    print("按 Ctrl+C 停止")
    print("="*60)
    
    app.run(debug=False, host='0.0.0.0', port=8050)


if __name__ == '__main__':
    main()
