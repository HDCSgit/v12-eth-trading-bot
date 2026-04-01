#!/usr/bin/env python3
"""检查 EVT 止盈状态 """

import sqlite3
import numpy as np
import pandas as pd

# 模拟 EVT 计算
try:
    from evt_take_profit import get_evt_engine
    
    print("=== EVT 引擎状态检查 ===")
    engine = get_evt_engine()
    
    print(f"安全折扣: {engine.safety_factor}")
    print(f"窗口大小: {engine.window_size}")
    print(f"阈值分位数: {engine.threshold_quantile}")
    print(f"参数已计算: {engine._params is not None}")
    
    if engine._params:
        print("\n=== 正负极值参数 ===")
        pos_params = engine._params.get('positive', {})
        neg_params = engine._params.get('negative', {})
        
        print("正极值 (LONG方向):")
        for k, v in pos_params.items():
            print(f"  {k}: {v}")
            
        print("\n负极值 (SHORT方向):")
        for k, v in neg_params.items():
            print(f"  {k}: {v}")
        
        # 计算不同方向的目标
        print("\n=== 理论止盈目标 ===")
        
        # LONG 方向
        tp_long, info_long = engine.calculate_tp_level('LONG', regime='TRENDING_UP')
        print(f"LONG @ TRENDING_UP: {tp_long*100:.2f}%")
        print(f"  形状参数ξ: {info_long.get('shape', 0):.3f}")
        print(f"  置信度: {info_long.get('confidence', 0)}")
        print(f"  市场环境倍数: {info_long.get('regime_multiplier', 1.0)}")
        
        # SHORT 方向  
        tp_short, info_short = engine.calculate_tp_level('SHORT', regime='TRENDING_UP')
        print(f"\nSHORT @ TRENDING_UP: {tp_short*100:.2f}%")
        print(f"  形状参数ξ: {info_short.get('shape', 0):.3f}")
        
        # 震荡市
        tp_sw, info_sw = engine.calculate_tp_level('LONG', regime='SIDEWAYS')
        print(f"\nLONG @ SIDEWAYS: {tp_sw*100:.2f}%")
        print(f"  市场环境倍数: {info_sw.get('regime_multiplier', 1.0)}")
        
    else:
        print("\n[!] EVT 参数尚未计算，需要价格数据")
        
except Exception as e:
    print(f"错误: {e}")
    import traceback
    traceback.print_exc()
