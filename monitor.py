#!/usr/bin/env python3
"""
交易系统诊断监控工具
实时监控交易系统的执行流程
"""
import sys
import os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import time
import logging
from datetime import datetime

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

from binance_api import BinanceExpertAPI
from strategy import ExpertStrategy
from risk_execution import ExecutionEngine, db
from config import CONFIG

def monitor_trading_system():
    """监控交易系统全流程"""
    print("="*80)
    print("Trading System Monitor - Diagnostic Mode")
    print("="*80)
    
    # 初始化组件
    api = BinanceExpertAPI()
    strategy = ExpertStrategy()
    executor = ExecutionEngine(api)
    
    print("\n[1] Checking Configuration...")
    print(f"  Mode: {CONFIG['MODE']}")
    print(f"  Symbols: {CONFIG['SYMBOLS']}")
    print(f"  Confidence Threshold: {CONFIG['CONFIDENCE_THRESHOLD']}")
    print(f"  Max Risk: {CONFIG['MAX_RISK_PCT']*100}%")
    print(f"  Leverage: {CONFIG['LEVERAGE']}x")
    
    print("\n[2] Checking Account...")
    balance = api.get_balance()
    print(f"  Available Balance: ${balance:.2f} USDT")
    
    if balance < 10:
        print(f"  WARNING: Balance too low! Need at least $10 to trade")
    
    print("\n[3] Checking Positions...")
    for symbol in CONFIG["SYMBOLS"]:
        pos = api.get_position(symbol)
        price = api.get_price(symbol)
        if pos:
            price_str = f"${price:.2f}" if price else "N/A"
            print(f"  {symbol}: {pos['side']} {pos['qty']} @ ${pos['entryPrice']:.2f} | Current: {price_str}")
        else:
            price_str = f"${price:.2f}" if price else "N/A"
            print(f"  {symbol}: No position | Price: {price_str}")
    
    print("\n[4] Testing Signal Generation (5 cycles)...")
    print("-"*80)
    
    for cycle in range(5):
        print(f"\n--- Cycle {cycle + 1} ---")
        
        for symbol in CONFIG["SYMBOLS"]:
            # 获取数据
            df = api.get_klines(symbol, limit=300)
            if df is None or len(df) < 200:
                print(f"[{symbol}] ERROR: Failed to get data")
                continue
            
            # 计算特征
            df = strategy.compute_features(df, symbol)
            if df is None:
                print(f"[{symbol}] ERROR: Feature calculation failed")
                continue
            
            # 生成信号
            signal = strategy.generate_signal(symbol, df)
            
            # 显示信号详情
            print(f"[{symbol}] Signal: {signal['action']} | Confidence: {signal['confidence']:.2f}")
            print(f"[{symbol}] Reason: {signal['reason']}")
            
            # 检查为什么会被过滤
            if signal['action'] != 'HOLD':
                print(f"[{symbol}] Checking execution conditions...")
                
                # 检查置信度
                if signal['confidence'] < CONFIG['CONFIDENCE_THRESHOLD']:
                    print(f"  [BLOCKED] Confidence {signal['confidence']:.2f} < threshold {CONFIG['CONFIDENCE_THRESHOLD']}")
                    continue
                
                # 检查余额
                balance = api.get_balance()
                if balance < 5:
                    print(f"  [BLOCKED] Balance ${balance:.2f} too low")
                    continue
                
                # 检查仓位
                current_pos = api.get_position(symbol)
                if current_pos:
                    print(f"  [INFO] Current position: {current_pos['side']} {current_pos['qty']}")
                    
                    # 检查是否应该平仓
                    entry = current_pos['entryPrice']
                    qty = current_pos['qty']
                    current_price = api.get_price(symbol) or signal.get('price', 0)
                    
                    if current_pos['side'] == "LONG":
                        pnl_pct = (current_price - entry) / entry * 100
                        
                        # 检查止损
                        if pnl_pct <= -5:
                            print(f"  [SHOULD CLOSE] Stop loss triggered: {pnl_pct:.2f}%")
                        
                        # 检查止盈
                        elif pnl_pct >= 10:
                            print(f"  [SHOULD CLOSE] Take profit triggered: {pnl_pct:.2f}%")
                        
                        # 检查反向信号
                        elif signal['action'] == 'SELL':
                            print(f"  [SHOULD CLOSE] Reverse signal: {signal['action']}")
                        
                        else:
                            print(f"  [HOLD] Position {pnl_pct:+.2f}%, no action needed")
                    
                    # 检查是否同向
                    elif signal['action'] == current_pos['side']:
                        print(f"  [BLOCKED] Same direction as current position")
                else:
                    print(f"  [READY TO OPEN] No position, can open {signal['action']}")
                    
                    # 计算仓位大小
                    atr = signal.get('atr', 0.022 * signal.get('price', 2000))
                    price = signal.get('price', 2000)
                    confidence = signal['confidence']
                    
                    risk_amount = balance * CONFIG['MAX_RISK_PCT']
                    confidence_multiplier = min(confidence / 0.7, 1.5)
                    stop_loss_pct = 2.0 * atr / price
                    qty = (risk_amount * confidence_multiplier) / (stop_loss_pct * price)
                    max_qty = balance * 0.25 / price
                    final_qty = round(min(qty, max_qty), 3)
                    
                    print(f"  [CALCULATION] Balance=${balance:.2f}, Risk={risk_amount:.2f}, Qty={final_qty}")
                    
                    if final_qty < 0.001:
                        print(f"  [BLOCKED] Calculated quantity {final_qty} too small")
                    else:
                        print(f"  [CAN TRADE] Would open {signal['action']} {final_qty} {symbol}")
        
        time.sleep(2)  # 等待2秒
    
    print("\n" + "="*80)
    print("Diagnostic Complete")
    print("="*80)
    print("\nCommon Issues:")
    print("1. Confidence threshold too high - Lower CONFIDENCE_THRESHOLD in config.py")
    print("2. Balance too low - Need at least $10 USDT")
    print("3. Strategy too strict - Check strategy.py conditions")
    print("4. No signals generated - Market conditions not met")
    print("\nTo fix: Edit config.py and lower CONFIDENCE_THRESHOLD to 0.55 or 0.50")

if __name__ == '__main__':
    monitor_trading_system()
