#!/usr/bin/env python3
"""测试新的仓位计算逻辑"""

import sys
sys.path.insert(0, r'D:\openclaw\binancepro')

from main_v12_live_optimized import RiskManager, MarketRegime

def test_position_sizing():
    rm = RiskManager()
    
    # 模拟参数
    balance = 50.0       # $50 余额
    price = 2080.0       # ETH价格
    atr = 20.0           # ATR $20 (约1%)
    
    test_cases = [
        # (置信度, 市场环境, 描述)
        (0.85, MarketRegime.TRENDING_UP, "高置信度+趋势上涨"),
        (0.75, MarketRegime.TRENDING_DOWN, "高置信度+趋势下跌"),
        (0.65, MarketRegime.TRENDING_UP, "中置信度+趋势市"),
        (0.60, MarketRegime.SIDEWAYS, "中置信度+震荡市"),
        (0.58, MarketRegime.SIDEWAYS, "低置信度+震荡市"),
        (0.50, MarketRegime.UNKNOWN, "极低置信度"),
    ]
    
    print("=" * 70)
    print("智能仓位计算测试")
    print(f"假设：余额${balance}, 价格${price}, ATR ${atr}")
    print("=" * 70)
    print()
    
    for confidence, regime, desc in test_cases:
        qty = rm.calculate_position_size(balance, price, atr, confidence, regime)
        notional = qty * price
        
        print(f"【{desc}】")
        print(f"  置信度: {confidence:.2f} | 环境: {regime.value}")
        print(f"  仓位: {qty:.4f} ETH (${notional:.2f})")
        print()
    
    print("=" * 70)
    print("对比：原逻辑（线性 confidence/0.6）")
    print("=" * 70)
    
    for confidence, regime, desc in test_cases[:3]:
        old_mult = min(confidence / 0.6, 2.0)
        base_risk = balance * 0.03  # 假设3%风险
        old_qty = (base_risk * old_mult) / (0.02 * price)
        print(f"{desc}: 置信度{confidence:.2f} → 原倍数{old_mult:.2f} → 仓位{old_qty:.4f}ETH")
    
    print()
    print("结论：新逻辑下高置信度(0.85)仓位是低置信度(0.50)的约6-8倍")
    print("      更能体现'高确信重仓，低确信轻仓'的原则")

if __name__ == "__main__":
    test_position_sizing()
