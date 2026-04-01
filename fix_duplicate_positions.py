#!/usr/bin/env python3
"""
修复重复持仓问题 - 平掉多余的仓位
保留最早的一单，平掉后面的重复单
"""

from binance_api import BinanceExpertAPI
from config import CONFIG

print("=" * 70)
print("  修复重复持仓")
print("=" * 70)

api = BinanceExpertAPI()
symbol = "ETHUSDT"

# 获取当前持仓
position = api.get_position(symbol)

if not position or position.get('qty', 0) <= 0.0001:
    print("\n当前无持仓，无需修复")
    exit(0)

current_qty = position['qty']
current_side = position['side']  # LONG or SHORT
entry_price = position['entryPrice']

print(f"\n当前持仓:")
print(f"  方向: {current_side}")
print(f"  数量: {current_qty:.4f} ETH")
print(f"  开仓价: ${entry_price:.2f}")
print(f"  名义价值: ${position['notional']:.2f}")

# 计算期望的仓位大小（基于配置）
leverage = CONFIG.get("LEVERAGE", 5)
expected_qty_per_trade = 0.018  # 从日志看每单约0.018ETH

num_trades = round(current_qty / expected_qty_per_trade)
print(f"\n分析:")
print(f"  每单期望: ~{expected_qty_per_trade:.4f} ETH")
print(f"  估计单数: {num_trades}单")

if num_trades <= 1:
    print("\n持仓正常，无需修复")
    exit(0)

# 建议保留1单，平掉多余
qty_to_close = round(current_qty - expected_qty_per_trade, 3)

print(f"\n建议操作:")
print(f"  保留: {expected_qty_per_trade:.4f} ETH")
print(f"  平仓: {qty_to_close:.4f} ETH")

close_side = 'SELL' if current_side == 'LONG' else 'BUY'

print(f"\n执行平仓: {close_side} {qty_to_close} ETH (reduceOnly=True)")

confirm = input("\n确认执行? (y/n): ").strip().lower()

if confirm == 'y':
    try:
        order = api.place_order(symbol, close_side, qty_to_close, reduce_only=True)
        if order and order.get('orderId'):
            print(f"✅ 平仓成功: orderId={order.get('orderId')}")
            
            # 验证新持仓
            new_pos = api.get_position(symbol)
            if new_pos:
                print(f"\n新持仓: {new_pos['side']} {new_pos['qty']:.4f} ETH")
            else:
                print("\n持仓已清空")
        else:
            print(f"❌ 平仓失败: {order}")
    except Exception as e:
        print(f"❌ 异常: {e}")
else:
    print("已取消")
