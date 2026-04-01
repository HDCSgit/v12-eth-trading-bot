#!/usr/bin/env python3
"""
V2市场环境检测 - 轻量级Web仪表盘 (Flask + 自动刷新)

使用方法:
    python regime_dashboard_simple.py
    然后访问 http://localhost:8050
"""
import sys
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from flask import Flask, render_template_string
import plotly.graph_objects as go
from plotly.utils import PlotlyJSONEncoder
import json
import threading
import time

sys.path.insert(0, str(Path(__file__).parent))
from market_regime_v2 import MarketRegimeDetectorV2

app = Flask(__name__)

# 全局数据缓存
cache = {
    'df': None,
    'result_df': None,
    'last_update': None
}

detector = None
data_file = 'eth_usdt_15m_binance.csv'
lookforward = 48

REGIME_COLORS = {
    'SIDEWAYS': '#808080',
    'TREND_UP': '#00AA00',
    'TREND_DOWN': '#FF0000',
    'BREAKOUT': '#FFD700',
    'EXTREME': '#FF00FF',
}

def load_and_predict():
    """加载数据并预测"""
    global cache
    
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Loading data...")
    df = pd.read_csv(data_file)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    if len(df) > 100:
        df = df.tail(100).copy()  # 减少到100条，提高加载速度
    
    df['timestamp'] = df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
    
    result_df = detector.predict_batch(df)
    
    cache['df'] = df
    cache['result_df'] = result_df
    cache['last_update'] = datetime.now()
    
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Data updated: {len(df)} samples, Regime: {result_df['regime_pred'].iloc[-1]}")

def generate_future_candles(df, result_df):
    """生成未来预测K线"""
    last_price = df['close'].iloc[-1]
    last_time_str = df['timestamp'].iloc[-1]
    last_time = pd.to_datetime(last_time_str)
    
    latest_regime = result_df['regime_pred'].iloc[-1]
    confidence = result_df['regime_confidence'].iloc[-1]
    
    if latest_regime == 'TREND_UP':
        trend = 0.001 * confidence
    elif latest_regime == 'TREND_DOWN':
        trend = -0.001 * confidence
    elif latest_regime == 'BREAKOUT':
        trend = 0.002 * confidence
    else:
        trend = 0
    
    future_data = []
    current_price = last_price
    
    for i in range(min(lookforward, 20)):
        volatility = 0.002 * (1 - confidence * 0.5)
        change = trend + np.random.normal(0, volatility)
        
        open_p = current_price
        close_p = current_price * (1 + change)
        
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

def create_main_chart():
    """创建主K线图"""
    df = cache['df']
    result_df = cache['result_df']
    
    fig = go.Figure()
    
    # 历史K线
    fig.add_trace(go.Candlestick(
        x=df['timestamp'],
        open=df['open'],
        high=df['high'],
        low=df['low'],
        close=df['close'],
        name='Historical',
        increasing_line_color='green',
        decreasing_line_color='red',
    ))
    
    # 预测K线
    future_df = generate_future_candles(df, result_df)
    fig.add_trace(go.Candlestick(
        x=future_df['timestamp'],
        open=future_df['open'],
        high=future_df['high'],
        low=future_df['low'],
        close=future_df['close'],
        name='Prediction (12h)',
        increasing_line_color='blue',
        decreasing_line_color='navy',
        increasing_fillcolor='rgba(30, 144, 255, 0.3)',
        decreasing_fillcolor='rgba(65, 105, 225, 0.3)',
    ))
    
    # 当前时间线
    last_time = df['timestamp'].iloc[-1]
    fig.add_vline(x=last_time, line_dash="dash", line_color="blue", line_width=2,
                  annotation_text="Now", annotation_position="top")
    
    fig.update_layout(
        title='ETH/USDT 15m - Price Chart with Prediction Zone',
        yaxis_title='Price (USDT)',
        xaxis_rangeslider_visible=False,
        height=600,
        hovermode='x unified',
        template='plotly_white',
    )
    
    return fig.to_json()

def create_regime_timeline():
    """创建市场环境时间线"""
    result_df = cache['result_df']
    
    fig = go.Figure()
    
    regimes = ['SIDEWAYS', 'TREND_UP', 'TREND_DOWN', 'BREAKOUT', 'EXTREME']
    y_map = {r: i for i, r in enumerate(regimes)}
    
    for regime in regimes:
        mask = result_df['regime_pred'] == regime
        if mask.any():
            fig.add_trace(go.Scatter(
                x=result_df.loc[mask, 'timestamp'].tolist(),
                y=[y_map[regime]] * mask.sum(),
                mode='markers',
                name=regime,
                marker=dict(color=REGIME_COLORS[regime], size=8, symbol='square'),
            ))
    
    fig.update_layout(
        title='Market Regime Timeline',
        yaxis=dict(tickmode='array', tickvals=list(range(len(regimes))), ticktext=regimes, range=[-0.5, 4.5]),
        height=200,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        template='plotly_white',
        margin=dict(l=50, r=50, t=80, b=50),
    )
    
    return fig.to_json()

def create_confidence_chart():
    """创建置信度图表"""
    result_df = cache['result_df']
    
    fig = go.Figure()
    
    fig.add_trace(go.Scatter(
        x=result_df['timestamp'].tolist(),
        y=result_df['regime_confidence'].tolist(),
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
        template='plotly_white',
        margin=dict(l=50, r=50, t=50, b=50),
    )
    
    return fig.to_json()

def create_probability_pie():
    """创建概率分布饼图"""
    result_df = cache['result_df']
    
    recent = result_df.tail(100)
    counts = recent['regime_pred'].value_counts()
    
    fig = go.Figure(data=[go.Pie(
        labels=counts.index.tolist(),
        values=counts.values.tolist(),
        marker_colors=[REGIME_COLORS.get(r, 'gray') for r in counts.index],
        hole=0.4,
    )])
    
    fig.update_layout(
        title='Recent 100 Periods Distribution',
        height=300,
        showlegend=True,
        template='plotly_white',
        margin=dict(l=50, r=50, t=50, b=50),
    )
    
    return fig.to_json()

def create_status_cards():
    """创建状态卡片HTML"""
    latest = cache['result_df'].iloc[-1]
    regime = latest['regime_pred']
    confidence = latest['regime_confidence']
    price = cache['df']['close'].iloc[-1]
    
    regime_color = REGIME_COLORS.get(regime, 'gray')
    
    return f"""
    <div class="card" style="border-color: {regime_color};">
        <h3>Current Regime</h3>
        <h2 style="color: {regime_color};">{regime}</h2>
        <p>Confidence: {confidence:.1%}</p>
    </div>
    <div class="card" style="border-color: #0066CC;">
        <h3>Current Price</h3>
        <h2 style="color: #0066CC;">${price:.2f}</h2>
        <p>ETH/USDT 15m</p>
    </div>
    <div class="card" style="border-color: purple;">
        <h3>Prediction</h3>
        <h2 style="color: purple;">+{lookforward * 15 / 60:.0f}h</h2>
        <p>Until {(datetime.now() + timedelta(hours=lookforward * 15 / 60)).strftime('%H:%M')}</p>
    </div>
    """

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>V2 Market Regime Dashboard</title>
    <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
    <style>
        body { font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }
        h1 { text-align: center; color: #333; }
        .header { text-align: center; color: #666; margin-bottom: 20px; }
        .cards-container { display: flex; justify-content: space-around; margin-bottom: 20px; }
        .card { background: white; padding: 20px; border-radius: 10px; border: 3px solid; text-align: center; min-width: 150px; }
        .card h3 { margin: 0 0 10px 0; color: #666; font-size: 14px; }
        .card h2 { margin: 0; font-size: 24px; }
        .card p { margin: 10px 0 0 0; color: #999; font-size: 12px; }
        .chart-container { background: white; padding: 10px; margin-bottom: 20px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .row { display: flex; gap: 20px; }
        .col { flex: 1; }
        .update-info { text-align: center; color: #999; font-size: 12px; margin-top: 10px; }
    </style>
</head>
<body>
    <h1>V2 Market Regime Dashboard</h1>
    <div class="header">Prediction Horizon: {{lookforward_hours}}h ({{lookforward}} periods)</div>
    
    <div class="cards-container">
        {{status_cards|safe}}
    </div>
    
    <div class="chart-container">
        <div id="main-chart"></div>
    </div>
    
    <div class="chart-container">
        <div id="timeline-chart"></div>
    </div>
    
    <div class="row">
        <div class="col">
            <div class="chart-container">
                <div id="confidence-chart"></div>
            </div>
        </div>
        <div class="col">
            <div class="chart-container">
                <div id="probability-chart"></div>
            </div>
        </div>
    </div>
    
    <div class="update-info">Last updated: {{last_update}} | Auto-refresh: 10s</div>
    
    <script>
        // Render charts
        Plotly.newPlot('main-chart', {{main_chart|safe}}, {responsive: true});
        Plotly.newPlot('timeline-chart', {{timeline|safe}}, {responsive: true});
        Plotly.newPlot('confidence-chart', {{confidence|safe}}, {responsive: true});
        Plotly.newPlot('probability-chart', {{probability|safe}}, {responsive: true});
        
        // Auto-refresh
        setTimeout(function() {
            location.reload();
        }, 10000);
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    """主页"""
    if cache['df'] is None:
        load_and_predict()
    
    return render_template_string(
        HTML_TEMPLATE,
        lookforward_hours=lookforward * 15 / 60,
        lookforward=lookforward,
        status_cards=create_status_cards(),
        main_chart=create_main_chart(),
        timeline=create_regime_timeline(),
        confidence=create_confidence_chart(),
        probability=create_probability_pie(),
        last_update=cache['last_update'].strftime('%Y-%m-%d %H:%M:%S') if cache['last_update'] else 'Never'
    )

def background_update():
    """后台更新数据"""
    while True:
        time.sleep(10)
        try:
            load_and_predict()
        except Exception as e:
            print(f"Update error: {e}")

def main():
    global detector, data_file, lookforward
    
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', default='models/regime_xgb_v1.pkl')
    parser.add_argument('--data', default='eth_usdt_15m_binance.csv')
    parser.add_argument('--port', type=int, default=8050)
    parser.add_argument('--lookforward', type=int, default=48)
    args = parser.parse_args()
    
    detector = MarketRegimeDetectorV2(model_path=args.model)
    data_file = args.data
    lookforward = args.lookforward
    
    # 初始加载
    load_and_predict()
    
    # 启动后台更新线程
    update_thread = threading.Thread(target=background_update, daemon=True)
    update_thread.start()
    
    print(f"\n{'='*60}")
    print("V2 Simple Dashboard Starting...")
    print(f"URL: http://localhost:{args.port}")
    print(f"Press Ctrl+C to stop")
    print(f"{'='*60}\n")
    
    app.run(host='0.0.0.0', port=args.port, debug=False, threaded=True)

if __name__ == '__main__':
    main()
