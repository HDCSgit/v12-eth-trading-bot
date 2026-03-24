#!/usr/bin/env python3
"""测试仓位占比控制参数效果"""

import sys
sys.path.insert(0, r'D:\openclaw\binancepro')

# 修改配置进行测试
import config
config.CONFIG["POSITION_SIZE_PCT_MIN"] = 0.30  # 最小30%
config.CONFIG["POSITION_SIZE_PCT_MAX"] = 0.70  # 最大70%
config.CONFIG["MAX_RISK_PCT"] = 0.03           # 3%基础风险
config.CONFIG["LEVERAGE"] = 5

from main_v12_live_optimized import RiskManager, MarketRegime

def test_position_control():
    rm = RiskManager()
    
    balance = 100.0      # $100 余额
    price = 2000.0       # ETH $2000
    atr = 20.0           # ATR $20
    
    print("=" * 80)
    print("仓位占比控制参数测试")
    print("=" * 80)
    print(f"假设：余额${balance}, ETH价格${price}, ATR ${atr}")
    print(f"配置：POSITION_SIZE_PCT_MIN={config.CONFIG['POSITION_SIZE_PCT_MIN']*100:.0f}%, "
          f"POSITION_SIZE_PCT_MAX={config.CONFIG['POSITION_SIZE_PCT_MAX']*100:.0f}%")
    print(f"      MAX_RISK_PCT={config.CONFIG['MAX_RISK_PCT']*100:.1f}%")
    print("=" * 80)
    print()
    
    test_cases = [
        (0.85, MarketRegime.TRENDING_UP, "极高置信度+趋势上涨"),
        (0.75, MarketRegime.TRENDING_DOWN, "高置信度+趋势下跌"),
        (0.65, MarketRegime.TRENDING_UP, "中置信度+趋势市"),
        (0.60, MarketRegime.SIDEWAYS, "中置信度+震荡市"),
        (0.58, MarketRegime.SIDEWAYS, "低置信度+震荡市"),
        (0.50, MarketRegime.UNKNOWN, "极低置信度"),
    ]
    
    print(f"{'场景':<20} {'置信度':>8} {'理论占比':>10} {'限制后':>10} {'仓位(ETH)':>12} {'名义价值':>12}")
    print("-" * 80)
    
    for confidence, regime, desc in test_cases:
        # 手动计算理论值
        base_risk = balance * config.CONFIG["MAX_RISK_PCT"]
        
        # 置信度倍数
        if confidence >= 0.80:
            conf_mult = 3.0
        elif confidence >= 0.70:
            conf_mult = 2.0
        elif confidence >= 0.60:
            conf_mult = 1.2
        elif confidence >= 0.55:
            conf_mult = 0.6
        else:
            conf_mult = 0.3
        
        # 环境倍数
        if regime in [MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN]:
            reg_mult = 1.3 if confidence >= 0.65 else 0.9
        elif regime == MarketRegime.SIDEWAYS:
            reg_mult = 0.7 if confidence < 0.70 else 1.0
        else:
            reg_mult = 1.0
        
        total_mult = conf_mult * reg_mult
        
        # ATR倍数
        if confidence >= 0.75:
            atr_mult = 2.5
        elif confidence >= 0.60:
            atr_mult = 2.0
        else:
            atr_mult = 1.5
        
        stop_loss_pct = max(atr_mult * atr / price, 0.008)
        
        # 理论占比
        base_pct = (config.CONFIG["MAX_RISK_PCT"] * total_mult) / stop_loss_pct
        
        # 限制后
        pos_min = config.CONFIG["POSITION_SIZE_PCT_MIN"]
        pos_max = config.CONFIG["POSITION_SIZE_PCT_MAX"]
        final_pct = max(pos_min, min(pos_max, base_pct))
        
        qty = (balance * final_pct) / price
        notional = qty * price
        
        marker = ""
        if base_pct < pos_min:
            marker = "↑提至最小"
        elif base_pct > pos_max:
            marker = "↓压至最大"
        
        print(f"{desc:<18} {confidence:>8.2f} {base_pct*100:>9.1f}% {final_pct*100:>9.1f}% "
              f"{qty:>11.4f} ${notional:>11.0f} {marker}")
    
    print()
    print("=" * 80)
    print("说明：")
    print("  理论占比 = MAX_RISK_PCT × 置信度倍数 × 环境倍数 / 止损距离")
    print("  限制后   = 理论占比 限制在 [MIN, MAX] 范围内")
    print("  ↑提至最小 = 理论值低于MIN，被提升至最小仓位")
    print("  ↓压至最大 = 理论值高于MAX，被压制至最大仓位")
    print("=" * 80)

if __name__ == "__main__":
    test_position_control()
