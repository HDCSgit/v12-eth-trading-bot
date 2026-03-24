#!/usr/bin/env python3
"""
快速测试修复后的交易系统
"""
import sys
import os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from binance_api import BinanceExpertAPI
from strategy import ExpertStrategy
from config import CONFIG

def test_system():
    print("="*80)
    print("Testing Fixed Trading System")
    print("="*80)
    
    api = BinanceExpertAPI()
    strategy = ExpertStrategy()
    
    symbol = "ETHUSDT"
    
    print(f"\n[1] Testing data fetch...")
    df = api.get_klines(symbol, limit=300)
    if df is None:
        print("ERROR: Failed to fetch data")
        return
    print(f"OK: Fetched {len(df)} rows")
    
    print(f"\n[2] Testing feature calculation...")
    df = strategy.compute_features(df, symbol)
    if df is None or len(df) < 10:
        print("ERROR: Feature calculation failed")
        return
    print(f"OK: Features calculated, {len(df)} rows")
    
    # 检查关键字段
    required = ['close', 'rsi', 'macd', 'trend', 'atr']
    missing = [f for f in required if f not in df.columns]
    if missing:
        print(f"ERROR: Missing fields: {missing}")
        return
    print(f"OK: All required fields present")
    
    print(f"\n[3] Testing position exit check...")
    # 模拟一个亏损持仓
    test_position = {
        'side': 'LONG',
        'qty': 0.023,
        'entryPrice': 2195.95
    }
    current_price = 2100.0  # 模拟下跌到2100
    
    exit_signal = strategy.check_position_exit(test_position, current_price, symbol)
    if exit_signal:
        print(f"OK: Exit signal generated!")
        print(f"   Action: {exit_signal['action']}")
        print(f"   Reason: {exit_signal['reason']}")
        print(f"   PnL%: {exit_signal['pnl_pct']:.2f}%")
    else:
        print("No exit signal (position not at SL/TP)")
    
    print(f"\n[4] Testing signal generation...")
    
    # 测试多次
    for i in range(3):
        df = api.get_klines(symbol, limit=300)
        df = strategy.compute_features(df, symbol)
        
        # 获取当前持仓
        pos = api.get_position(symbol)
        price = api.get_price(symbol)
        
        signal = strategy.generate_signal(symbol, df, pos, price)
        
        print(f"\n  Test {i+1}:")
        print(f"    Action: {signal['action']}")
        print(f"    Confidence: {signal['confidence']:.2f}")
        print(f"    Reason: {signal['reason']}")
        print(f"    Price: ${signal.get('price', 0):.2f}")
        print(f"    RSI: {signal.get('rsi', 0):.2f}")
        
        if signal['action'] not in ['HOLD', 'CLOSE']:
            print(f"    SL: ${signal.get('sl', 0):.2f}")
            print(f"    TP: ${signal.get('tp', 0):.2f}")
    
    print(f"\n[5] Checking current position...")
    pos = api.get_position(symbol)
    price = api.get_price(symbol)
    balance = api.get_balance()
    
    print(f"  Balance: ${balance:.2f} USDT")
    price_str = f"${price:.2f}" if price else "N/A"
    print(f"  Price: {price_str}")
    
    if pos:
        entry = pos['entryPrice']
        qty = pos['qty']
        pnl_pct = (price - entry) / entry * 100 if price else 0
        print(f"  Position: {pos['side']} {qty} @ ${entry:.2f}")
        print(f"  PnL: {pnl_pct:.2f}%")
        
        # 检查是否应该平仓
        if pnl_pct <= -5:
            print(f"  ALERT: Should CLOSE (Stop Loss at -5%)!")
        elif pnl_pct >= 10:
            print(f"  ALERT: Should CLOSE (Take Profit at +10%)!")
    else:
        print(f"  No position")
    
    print("\n" + "="*80)
    print("Test Complete")
    print("="*80)

if __name__ == '__main__':
    test_system()
