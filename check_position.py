#!/usr/bin/env python3
from binance_api import BinanceExpertAPI

api = BinanceExpertAPI()
pos = api.get_position('ETHUSDT')

print("=" * 60)
print("  币安实际持仓检查")
print("=" * 60)

if pos:
    print(f"\n方向: {pos['side']}")
    print(f"数量: {pos['qty']:.4f} ETH")
    print(f"开仓价: ${pos['entryPrice']:.2f}")
    print(f"名义价值: ${pos['notional']:.2f}")
    print(f"未实现盈亏: ${pos['unrealizedProfit']:.4f}")
    print(f"杠杆: {pos['leverage']}x")
    
    # 检查是否超仓
    balance = api.get_balance()
    position_pct = abs(pos['notional']) / balance * 100
    print(f"\n账户余额: ${balance:.2f}")
    print(f"仓位占用: {position_pct:.1f}%")
    
    if position_pct > 200:
        print("\n[WARNING] 仓位过重！建议减仓或检查系统逻辑")
else:
    print("\n当前无持仓")
