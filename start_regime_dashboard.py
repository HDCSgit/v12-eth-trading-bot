#!/usr/bin/env python3
"""
V2市场环境实时仪表盘
在浏览器中实时显示市场状态

安装依赖:
    pip install dash plotly

使用方法:
    python start_regime_dashboard.py
    然后访问 http://localhost:8050
"""
import sys
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
import threading
import time

sys.path.insert(0, str(Path(__file__).parent))

try:
    import dash
    from dash import dcc, html
    from dash.dependencies import Input, Output
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    DASH_AVAILABLE = True
except ImportError:
    DASH_AVAILABLE = False
    print("ERROR: Dash not installed. Run: pip install dash plotly")
    sys.exit(1)

from market_regime_v2 import MarketRegimeDetectorV2


class RegimeDashboard:
    """V2市场环境实时仪表盘"""
    
    def __init__(self, model_path: str, data_file: str):
        self.detector = MarketRegimeDetectorV2(model_path=model_path)
        self.data_file = data_file
        self.history = []
        self.max_history = 500
        
        self.app = dash.Dash(__name__)
        self._setup_layout()
        self._setup_callbacks()
    
    def _setup_layout(self):
        """设置Dash布局"""
        self.app.layout = html.Div([
            html.H1("V2市场环境检测仪表盘", style={'textAlign': 'center'}),
            
            # 刷新间隔
            dcc.Interval(id='interval', interval=5000),  # 5秒刷新
            
            # 当前状态卡片
            html.Div(id='current-status', style={
                'padding': '20px',
                'margin': '10px',
                'border': '1px solid #ddd',
                'borderRadius': '5px'
            }),
            
            # 图表区域
            html.Div([
                # 价格和状态时间线
                dcc.Graph(id='price-regime-chart', style={'height': '500px'}),
                
                # 置信度历史
                dcc.Graph(id='confidence-chart', style={'height': '300px'}),
                
                # 概率分布热力图
                dcc.Graph(id='probability-heatmap', style={'height': '300px'}),
            ]),
            
            # 统计信息
            html.Div(id='statistics', style={
                'padding': '20px',
                'margin': '10px',
                'backgroundColor': '#f5f5f5'
            }),
            
        ])
    
    def _setup_callbacks(self):
        """设置回调函数"""
        
        @self.app.callback(
            [Output('current-status', 'children'),
             Output('price-regime-chart', 'figure'),
             Output('confidence-chart', 'figure'),
             Output('statistics', 'children')],
            [Input('interval', 'n_intervals')]
        )
        def update_dashboard(n):
            # 读取最新数据
            df = pd.read_csv(self.data_file)
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                df.set_index('timestamp', inplace=True)
            
            # 只取最近500条
            df = df.tail(500)
            
            # 预测
            result = self.detector.predict(df)
            
            # 更新历史
            self.history.append({
                'timestamp': datetime.now(),
                'regime': result.regime.value,
                'confidence': result.confidence,
                'price': df['close'].iloc[-1],
                'probabilities': result.probabilities
            })
            if len(self.history) > self.max_history:
                self.history = self.history[-self.max_history:]
            
            # 生成状态卡片
            status_card = self._create_status_card(result)
            
            # 生成图表
            price_chart = self._create_price_chart(df)
            confidence_chart = self._create_confidence_chart()
            statistics = self._create_statistics()
            
            return status_card, price_chart, confidence_chart, statistics
    
    def _create_status_card(self, result):
        """创建当前状态卡片"""
        regime_colors = {
            'SIDEWAYS': '#808080',
            'TREND_UP': '#00FF00',
            'TREND_DOWN': '#FF0000',
            'BREAKOUT': '#FFD700',
            'EXTREME': '#FF69B4',
        }
        
        color = regime_colors.get(result.regime.value, '#CCCCCC')
        
        return html.Div([
            html.H2(f"当前市场环境: {result.regime.value}", 
                   style={'color': color}),
            html.H3(f"置信度: {result.confidence:.1%}"),
            html.P(f"建议操作: {result.recommended_action}"),
            html.P(f"仓位倍数: {result.position_size_mult}x"),
            html.P(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"),
        ])
    
    def _create_price_chart(self, df):
        """创建价格和状态图表"""
        fig = make_subplots(rows=2, cols=1, 
                           shared_xaxes=True,
                           vertical_spacing=0.1,
                           row_heights=[0.7, 0.3])
        
        # 价格线
        fig.add_trace(
            go.Scatter(x=df.index, y=df['close'], 
                      mode='lines', name='Price',
                      line=dict(color='black')),
            row=1, col=1
        )
        
        # 如果有历史数据，添加状态背景
        if len(self.history) > 10:
            hist_df = pd.DataFrame(self.history)
            
            regime_colors = {
                'SIDEWAYS': 'gray',
                'TREND_UP': 'green',
                'TREND_DOWN': 'red',
                'BREAKOUT': 'gold',
                'EXTREME': 'purple',
            }
            
            for regime in hist_df['regime'].unique():
                mask = hist_df['regime'] == regime
                fig.add_trace(
                    go.Scatter(
                        x=hist_df[mask]['timestamp'],
                        y=hist_df[mask]['price'],
                        mode='markers',
                        name=regime,
                        marker=dict(color=regime_colors.get(regime, 'blue'), size=8)
                    ),
                    row=1, col=1
                )
        
        fig.update_layout(title='价格与市场环境', height=500)
        return fig
    
    def _create_confidence_chart(self):
        """创建置信度历史图表"""
        if len(self.history) < 2:
            return go.Figure()
        
        hist_df = pd.DataFrame(self.history)
        
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=hist_df['timestamp'],
            y=hist_df['confidence'],
            mode='lines',
            name='Confidence',
            fill='tozeroy'
        ))
        
        fig.add_hline(y=0.7, line_dash="dash", line_color="red",
                     annotation_text="High Confidence")
        
        fig.update_layout(
            title='置信度历史',
            yaxis=dict(range=[0, 1]),
            height=300
        )
        return fig
    
    def _create_statistics(self):
        """创建统计信息"""
        if len(self.history) < 10:
            return html.Div("收集数据中...")
        
        hist_df = pd.DataFrame(self.history)
        
        regime_counts = hist_df['regime'].value_counts()
        avg_confidence = hist_df['confidence'].mean()
        
        return html.Div([
            html.H4("统计信息"),
            html.P(f"平均置信度: {avg_confidence:.1%}"),
            html.P(f"数据点: {len(hist_df)}"),
            html.H5("环境分布:"),
            html.Ul([html.Li(f"{r}: {c} ({c/len(hist_df):.1%})") 
                    for r, c in regime_counts.items()])
        ])
    
    def run(self, debug=False, port=8050):
        """启动仪表盘"""
        print(f"\n🚀 启动V2市场环境仪表盘")
        print(f"   访问地址: http://localhost:{port}")
        print(f"   按 Ctrl+C 停止\n")
        self.app.run_server(debug=debug, port=port)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', default='models/regime_xgb_v1.pkl')
    parser.add_argument('--data', default='eth_usdt_15m_binance.csv')
    parser.add_argument('--port', type=int, default=8050)
    args = parser.parse_args()
    
    dashboard = RegimeDashboard(args.model, args.data)
    dashboard.run(port=args.port)


if __name__ == "__main__":
    main()
