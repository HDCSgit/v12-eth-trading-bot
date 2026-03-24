#!/usr/bin/env python3
"""
市场诊断工具 - 检查当前市场状况和信号触发条件
"""
import sys
import os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from binance_api import BinanceExpertAPI
from strategy import ExpertStrategy
from config import CONFIG
import pandas as pd

def diagnose_market():
    """诊断市场状况"""
    print("="*80)
    print("Market Diagnostic Tool")
    print("="*80)
    
    api = BinanceExpertAPI()
    strategy = ExpertStrategy()
    
    for symbol in CONFIG["SYMBOLS"]:
        print(f"\n{'='*80}")
        print(f"交易对: {symbol}")
        print("="*80)
        
        # 获取K线数据
        df = api.get_klines(symbol, limit=300)
        if df is None or len(df) < 200:
            print(f"❌ 数据获取失败或不足")
            continue
        
        # 计算特征
        df = strategy.compute_features(df, symbol)
        if df is None or len(df) < 2:
            print(f"❌ 特征计算失败")
            continue
        
        # 获取最新数据
        row = df.iloc[-1]
        prev = df.iloc[-2]
        
        print(f"\n[Price] Current: ${row['close']:.2f}")
        print(f"[Price] 1min Change: {row['price_change_1m']:.2f}%")
        print(f"[Price] 5min Change: {row['price_change_5m']:.2f}%")
        print(f"[Price] 30min Change: {row['price_change_30m']:.2f}%")
        
        print(f"\n[Indicators]")
        print(f"  - Trend(Long/Short): {'UP' if row['trend'] == 1 else 'DOWN'} / {'UP' if row['trend_short'] == 1 else 'DOWN'}")
        print(f"  - RSI(14): {row['rsi']:.2f} {'(Oversold)' if row['rsi'] < 30 else '(Overbought)' if row['rsi'] > 70 else ''}")
        print(f"  - MACD: {row['macd']:.4f} (Signal: {row['macd_signal']:.4f})")
        print(f"  - MACD Hist: {row['macd_hist']:.4f}")
        print(f"  - ATR(14): {row['atr']:.2f} ({row['atr_pct']:.2f}%)")
        
        print(f"\n[Bollinger Bands]")
        print(f"  - Upper: ${row['bb_upper']:.2f}")
        print(f"  - Middle: ${row['bb_mid']:.2f}")
        print(f"  - Lower: ${row['bb_lower']:.2f}")
        print(f"  - Width: {row['bb_width']*100:.2f}% {'(Squeeze)' if row['bb_width'] < 0.02 else ''}")
        print(f"  - Position: {row['bb_position']*100:.1f}% {'(Near Lower)' if row['bb_position'] < 0.1 else '(Near Upper)' if row['bb_position'] > 0.9 else ''}")
        
        print(f"\n[Volume]")
        print(f"  - Current: {row['volume']:.2f}")
        print(f"  - 30min MA: {row['volume_ma']:.2f}")
        print(f"  - Ratio: {row['volume_ratio']:.2f}x {'(Spike)' if row['volume_ratio'] > 1.6 else ''}")
        
        # 生成信号
        signal = strategy.generate_signal(symbol, df)
        
        print(f"\n[Signal]")
        print(f"  - Action: {signal['action']}")
        print(f"  - Confidence: {signal['confidence']:.2f}")
        print(f"  - Reason: {signal['reason']}")
        
        if signal['action'] != 'HOLD':
            print(f"\n[Recommendation]")
            print(f"  - Stop Loss: ${signal['sl']:.2f}" if signal['sl'] else "  - Stop Loss: Not set")
            print(f"  - Take Profit: ${signal['tp']:.2f}" if signal['tp'] else "  - Take Profit: Not set")
            
            if signal['confidence'] >= CONFIG["CONFIDENCE_THRESHOLD"]:
                print(f"\n[Status] VALID SIGNAL (Confidence>{CONFIG['CONFIDENCE_THRESHOLD']})")
            else:
                print(f"\n[Status] SIGNAL TOO WEAK (Confidence<{CONFIG['CONFIDENCE_THRESHOLD']})")
        
        # 检查各项条件
        print(f"\n[Condition Check]")
        
        # 多头条件
        long_conditions = {
            "Trend UP": row['trend'] == 1,
            "RSI<40": row['rsi'] < 40,
            "MACD Cross Up": (row['macd'] > row['macd_signal']) and (prev['macd'] <= prev['macd_signal']),
            "Volume Spike": row['volume_spike'],
            "BB Squeeze": row['bb_width'] < 0.02,
            "RSI<30(Oversold)": row['rsi'] < 30,
            "Near BB Lower": row['bb_position'] < 0.1,
        }
        
        print(f"\n  Long Conditions:")
        for cond, met in long_conditions.items():
            status = "[OK]" if met else "[X]"
            print(f"    {status} {cond}")
        
        # 空头条件
        short_conditions = {
            "Trend DOWN": row['trend'] == -1,
            "RSI>60": row['rsi'] > 60,
            "MACD Cross Down": (row['macd'] < row['macd_signal']) and (prev['macd'] >= prev['macd_signal']),
            "Volume Spike": row['volume_spike'],
            "BB Squeeze": row['bb_width'] < 0.02,
            "RSI>70(Overbought)": row['rsi'] > 70,
            "Near BB Upper": row['bb_position'] > 0.9,
        }
        
        print(f"\n  Short Conditions:")
        for cond, met in short_conditions.items():
            status = "[OK]" if met else "[X]"
            print(f"    {status} {cond}")
    
    print(f"\n{'='*80}")
    print("Diagnostic Complete")
    print("="*80)

if __name__ == '__main__':
    diagnose_market()
