#!/usr/bin/env python3
"""
V2市场环境检测 - 高级交互式仪表盘

特性：
- 历史K线 vs 预测K线（不同颜色/样式）
- 预测区间高亮显示
- 实时置信度监控
- 预测概率分布
- 交互式时间轴缩放

使用方法:
    python start_regime_dashboard_v2.py
    然后访问 http://localhost:8050
"""
import sys
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent))

try:
    import dash
    from dash import dcc, html
    from dash.dependencies import Input, Output
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    import plotly.express as px
    DASH_AVAILABLE = True
except ImportError:
    DASH_AVAILABLE = False
    print("ERROR: Dash/Plotly not installed. Run: pip install dash plotly")
    sys.exit(1)

from market_regime_v2 import MarketRegimeDetectorV2


class RegimeDashboardV2:
    """V2高级交互式仪表盘"""
    
    REGIME_COLORS = {
        'SIDEWAYS': 'gray',
        'TREND_UP': 'green',
        'TREND_DOWN': 'red',
        'BREAKOUT': 'gold',
        'EXTREME': 'magenta',
    }
    
    def __init__(self, model_path, data_file, lookforward=48):
        self.detector = MarketRegimeDetectorV2(model_path=model_path)
        self.data_file = data_file
        self.lookforward = lookforward
        self.lookforward_hours = lookforward * 15 / 60
        
        self.app = dash.Dash(__name__)
        self._setup_layout()
        self._setup_callbacks()
        
        # 缓存数据
        self.df = None
        self.result_df = None
        self._load_data()
    
    def _load_data(self):
        """加载和预测数据"""
        print("Loading data...")
        df = pd.read_csv(self.data_file)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # 只取最近500条用于显示
        if len(df) > 500:
            self.df = df.tail(500).copy()
        else:
            self.df = df.copy()
        
        # 确保timestamp是字符串格式（Plotly兼容性）
        self.df['timestamp'] = self.df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
        
        print("Running prediction...")
        self.result_df = self.detector.predict_batch(self.df)
        
        print(f"Data loaded: {len(self.df)} samples")
        print(f"Latest regime: {self.result_df['regime_pred'].iloc[-1]}")
    
    def _setup_layout(self):
        """设置Dash布局"""
        self.app.layout = html.Div([
            html.H1("V2 Market Regime Dashboard", style={'textAlign': 'center'}),
            html.H3(f"Prediction Horizon: {self.lookforward_hours}h ({self.lookforward} periods)", 
                   style={'textAlign': 'center', 'color': 'gray'}),
            
            # 刷新控制
            html.Div([
                dcc.Interval(id='interval', interval=10000),  # 10秒刷新
                html.Button('Refresh Data', id='refresh-btn', n_clicks=0),
            ], style={'textAlign': 'center', 'padding': '10px'}),
            
            # 当前状态卡片
            html.Div(id='status-cards', style={
                'display': 'flex', 'justifyContent': 'space-around',
                'padding': '20px', 'backgroundColor': '#f0f0f0'
            }),
            
            # 主图表：K线 + 预测
            dcc.Graph(id='main-chart', style={'height': '600px'}),
            
            # 子图1：市场环境时间线
            dcc.Graph(id='regime-timeline', style={'height': '200px'}),
            
            # 子图2：置信度和概率
            html.Div([
                dcc.Graph(id='confidence-chart', style={'width': '50%', 'display': 'inline-block'}),
                dcc.Graph(id='probability-chart', style={'width': '50%', 'display': 'inline-block'}),
            ]),
            
            # 预测详情表格
            html.Div(id='prediction-details', style={'padding': '20px'}),
            
        ], style={'fontFamily': 'Arial, sans-serif'})
    
    def _setup_callbacks(self):
        """设置回调"""
        
        @self.app.callback(
            [Output('status-cards', 'children'),
             Output('main-chart', 'figure'),
             Output('regime-timeline', 'figure'),
             Output('confidence-chart', 'figure'),
             Output('probability-chart', 'figure')],
            [Input('interval', 'n_intervals'),
             Input('refresh-btn', 'n_clicks')]
        )
        def update_dashboard(n_intervals, n_clicks):
            # 重新加载最新数据
            self._load_data()
            
            # 生成图表
            status = self._create_status_cards()
            main_chart = self._create_main_chart()
            timeline = self._create_regime_timeline()
            confidence = self._create_confidence_chart()
            probability = self._create_probability_chart()
            
            return status, main_chart, timeline, confidence, probability
    
    def _create_status_cards(self):
        """创建状态卡片"""
        latest = self.result_df.iloc[-1]
        
        regime = latest['regime_pred']
        confidence = latest['regime_confidence']
        price = self.df['close'].iloc[-1]
        
        regime_colors = {
            'SIDEWAYS': '#808080',
            'TREND_UP': '#00FF00',
            'TREND_DOWN': '#FF0000',
            'BREAKOUT': '#FFD700',
            'EXTREME': '#FF69B4',
        }
        
        color = regime_colors.get(regime, 'gray')
        
        return html.Div([
            html.Div([
                html.H3("Current Regime"),
                html.H2(regime, style={'color': color}),
            ], style={'textAlign': 'center', 'padding': '20px', 'border': f'2px solid {color}', 'borderRadius': '10px'}),
            
            html.Div([
                html.H3("Confidence"),
                html.H2(f"{confidence:.1%}", style={'color': 'blue' if confidence > 0.7 else 'orange' if confidence > 0.5 else 'red'}),
            ], style={'textAlign': 'center', 'padding': '20px', 'border': '2px solid blue', 'borderRadius': '10px'}),
            
            html.Div([
                html.H3("Current Price"),
                html.H2(f"${price:.2f}"),
            ], style={'textAlign': 'center', 'padding': '20px', 'border': '2px solid green', 'borderRadius': '10px'}),
            
            html.Div([
                html.H3("Prediction"),
                html.H2(f"+{self.lookforward_hours}h"),
                html.P(f"Until {(datetime.now() + timedelta(hours=self.lookforward_hours)).strftime('%H:%M')}")
            ], style={'textAlign': 'center', 'padding': '20px', 'border': '2px dashed purple', 'borderRadius': '10px'}),
        ])
    
    def _create_main_chart(self):
        """创建主K线图（含预测）"""
        fig = go.Figure()
        
        # 1. 历史真实K线（实色）
        fig.add_trace(go.Candlestick(
            x=self.df['timestamp'],
            open=self.df['open'],
            high=self.df['high'],
            low=self.df['low'],
            close=self.df['close'],
            name='Historical',
            increasing_line_color='green',
            decreasing_line_color='red',
        ))
        
        # 2. 生成并绘制预测K线（虚线/蓝色）
        future_df = self._generate_future_candles()
        if future_df is not None:
            fig.add_trace(go.Candlestick(
                x=future_df['timestamp'],
                open=future_df['open'],
                high=future_df['high'],
                low=future_df['low'],
                close=future_df['close'],
                name=f'Prediction ({self.lookforward_hours}h)',
                increasing_line_color='blue',
                decreasing_line_color='navy',
                increasing_fillcolor='rgba(30, 144, 255, 0.3)',
                decreasing_fillcolor='rgba(65, 105, 225, 0.3)',
            ))
            
            # 添加预测区间阴影
            last_time = self.df['timestamp'].iloc[-1]
            future_end = future_df['timestamp'].iloc[-1]
            fig.add_vrect(
                x0=last_time, 
                x1=future_end,
                fillcolor="blue", opacity=0.05,
                layer="below", line_width=0,
            )
        
        # 3. 添加当前时间线
        fig.add_vline(
            x=last_time, line_dash="dash",
            line_color="blue", line_width=2,
            annotation_text="Now", annotation_position="top"
        )
        
        # 4. 添加市场环境标注
        for idx, row in self.result_df.iterrows():
            if idx % 20 == 0:  # 每20个点标注一次，避免太密
                regime = row['regime_pred']
                color = self.REGIME_COLORS.get(regime, 'gray')
                fig.add_annotation(
                    x=row['timestamp'],
                    y=self.df['high'].max(),
                    text=regime[:4],  # 缩写
                    showarrow=False,
                    font=dict(color=color, size=8),
                    bgcolor='rgba(255,255,255,0.7)'
                )
        
        fig.update_layout(
            title='Price Chart with Prediction Zone',
            yaxis_title='Price (USDT)',
            xaxis_rangeslider_visible=False,
            height=600,
            hovermode='x unified',
        )
        
        return fig
    
    def _generate_future_candles(self):
        """生成未来预测K线"""
        last_price = self.df['close'].iloc[-1]
        last_time_str = self.df['timestamp'].iloc[-1]
        # 将字符串时间转回datetime用于计算
        last_time = pd.to_datetime(last_time_str)
        
        latest_regime = self.result_df['regime_pred'].iloc[-1]
        confidence = self.result_df['regime_confidence'].iloc[-1]
        
        # 基于环境类型确定趋势
        if latest_regime == 'TREND_UP':
            trend = 0.001 * confidence  # 上涨
        elif latest_regime == 'TREND_DOWN':
            trend = -0.001 * confidence  # 下跌
        elif latest_regime == 'BREAKOUT':
            trend = 0.002 * confidence  # 突破
        else:
            trend = 0  # 震荡
        
        future_data = []
        current_price = last_price
        
        for i in range(min(self.lookforward, 20)):  # 最多显示20个预测周期
            # 添加随机波动
            volatility = 0.002 * (1 - confidence * 0.5)  # 置信度越高，波动越小
            change = trend + np.random.normal(0, volatility)
            
            open_p = current_price
            close_p = current_price * (1 + change)
            
            # 高低点基于趋势方向
            if change > 0:
                high_p = max(open_p, close_p) * (1 + abs(np.random.normal(0, 0.003)))
                low_p = min(open_p, close_p) * (1 - abs(np.random.normal(0, 0.002)))
            else:
                high_p = max(open_p, close_p) * (1 + abs(np.random.normal(0, 0.002)))
                low_p = min(open_p, close_p) * (1 - abs(np.random.normal(0, 0.003)))
            
            future_time = last_time + timedelta(minutes=15 * (i + 1))
            
            future_data.append({
                'timestamp': future_time.strftime('%Y-%m-%d %H:%M:%S'),
                'open': open_p,
                'high': high_p,
                'low': low_p,
                'close': close_p,
            })
            
            current_price = close_p
        
        return pd.DataFrame(future_data)
    
    def _create_regime_timeline(self):
        """创建市场环境时间线"""
        fig = go.Figure()
        
        regimes = ['SIDEWAYS', 'TREND_UP', 'TREND_DOWN', 'BREAKOUT', 'EXTREME']
        y_map = {r: i for i, r in enumerate(regimes)}
        
        for regime in regimes:
            mask = self.result_df['regime_pred'] == regime
            if mask.any():
                fig.add_trace(go.Scatter(
                    x=self.result_df.loc[mask, 'timestamp'],
                    y=[y_map[regime]] * mask.sum(),
                    mode='markers',
                    name=regime,
                    marker=dict(
                        color=self.REGIME_COLORS[regime],
                        size=8,
                        symbol='square',
                    ),
                ))
        
        fig.update_layout(
            title='Market Regime Timeline',
            yaxis=dict(
                tickmode='array',
                tickvals=list(range(len(regimes))),
                ticktext=regimes,
                range=[-0.5, 4.5]
            ),
            height=200,
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        
        return fig
    
    def _create_confidence_chart(self):
        """创建置信度图表"""
        fig = go.Figure()
        
        fig.add_trace(go.Scatter(
            x=self.result_df['timestamp'],
            y=self.result_df['regime_confidence'],
            mode='lines',
            name='Confidence',
            fill='tozeroy',
            line=dict(color='blue', width=2),
        ))
        
        fig.add_hline(y=0.7, line_dash="dash", line_color="green", annotation_text="High")
        fig.add_hline(y=0.5, line_dash="dash", line_color="orange", annotation_text="Medium")
        
        fig.update_layout(
            title='Prediction Confidence',
            yaxis=dict(range=[0, 1]),
            height=300,
            showlegend=False,
        )
        
        return fig
    
    def _create_probability_chart(self):
        """创建概率分布饼图"""
        # 统计最近的环境分布
        recent = self.result_df.tail(100)
        counts = recent['regime_pred'].value_counts()
        
        fig = go.Figure(data=[go.Pie(
            labels=counts.index,
            values=counts.values,
            marker_colors=[self.REGIME_COLORS.get(r, 'gray') for r in counts.index],
            hole=0.4,
        )])
        
        fig.update_layout(
            title='Recent 100 Periods Distribution',
            height=300,
            showlegend=True,
        )
        
        return fig
    
    def run(self, debug=False, port=8050):
        """启动仪表盘"""
        print(f"\n{'='*60}")
        print("V2 Advanced Dashboard Starting...")
        print(f"URL: http://localhost:{port}")
        print(f"Press Ctrl+C to stop")
        print(f"{'='*60}\n")
        self.app.run(debug=debug, port=port)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', default='models/regime_xgb_v1.pkl')
    parser.add_argument('--data', default='eth_usdt_15m_binance.csv')
    parser.add_argument('--port', type=int, default=8050)
    parser.add_argument('--lookforward', type=int, default=48)
    args = parser.parse_args()
    
    dashboard = RegimeDashboardV2(args.model, args.data, args.lookforward)
    dashboard.run(port=args.port)


if __name__ == "__main__":
    main()
