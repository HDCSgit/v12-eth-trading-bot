#!/usr/bin/env python3
"""调试Dash回调"""
import sys
sys.path.insert(0, '.')

from start_regime_dashboard_v2 import RegimeDashboardV2
import json

# 创建dashboard实例
dashboard = RegimeDashboardV2(
    model_path='models/regime_xgb_v1.pkl',
    data_file='eth_usdt_15m_binance.csv',
    lookforward=48
)

# 手动调用回调函数
print('=== Testing Callback ===')
with dashboard.app.server.app_context():
    # 获取回调函数
    callbacks = dashboard.app.callback_map
    print(f'Number of callbacks: {len(callbacks)}')
    
    # 尝试手动生成图表
    print()
    print('=== Generating Charts ===')
    
    try:
        status = dashboard._create_status_cards()
        print('✓ Status cards created')
    except Exception as e:
        print(f'✗ Status cards error: {e}')
    
    try:
        main_chart = dashboard._create_main_chart()
        print(f'✓ Main chart created - traces: {len(main_chart.data)}')
        # 保存HTML
        main_chart.write_html('debug_main_chart.html')
        print('  Saved to debug_main_chart.html')
    except Exception as e:
        print(f'✗ Main chart error: {e}')
        import traceback
        traceback.print_exc()
    
    try:
        timeline = dashboard._create_regime_timeline()
        print(f'✓ Timeline created - traces: {len(timeline.data)}')
    except Exception as e:
        print(f'✗ Timeline error: {e}')
        
    try:
        confidence = dashboard._create_confidence_chart()
        print(f'✓ Confidence chart created - traces: {len(confidence.data)}')
    except Exception as e:
        print(f'✗ Confidence error: {e}')

print()
print('Done! Check debug_main_chart.html in browser.')
