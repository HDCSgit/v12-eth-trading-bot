#!/usr/bin/env python3
"""
V12配置验证工具
检查config.py中所有参数是否正确
"""

import sys
sys.path.insert(0, r'D:\openclaw\binancepro')

from config import CONFIG

def verify_config():
    """验证配置完整性"""
    print("=" * 70)
    print("V12优化版 - 配置验证")
    print("=" * 70)
    print()
    
    errors = []
    warnings = []
    
    # 检查关键参数是否存在
    required_params = [
        "SYMBOLS", "LEVERAGE", "MODE", "MAX_RISK_PCT",
        "POSITION_SIZE_PCT_MIN", "POSITION_SIZE_PCT_MAX",
        "STOP_LOSS_ATR_MULT", "TP_SIDEWAYS_ATR_MULT",
        "ML_CONFIDENCE_THRESHOLD", "SPIKE_PRICE_CHANGE_THRESHOLD"
    ]
    
    for param in required_params:
        if param not in CONFIG:
            errors.append(f"缺少必需参数: {param}")
    
    # 检查参数合理性
    if CONFIG.get("LEVERAGE", 0) > 20:
        warnings.append(f"杠杆{CONFIG['LEVERAGE']}倍过高，建议5-10倍")
    
    if CONFIG.get("MAX_RISK_PCT", 0) > 0.1:
        warnings.append(f"单笔风险{CONFIG['MAX_RISK_PCT']*100}%过高，建议<5%")
    
    if CONFIG.get("POSITION_SIZE_PCT_MAX", 0) > 0.9:
        warnings.append(f"最大仓位{CONFIG['POSITION_SIZE_PCT_MAX']*100}%过高，建议<80%")
    
    if CONFIG.get("POSITION_SIZE_PCT_MIN", 0) > CONFIG.get("POSITION_SIZE_PCT_MAX", 1):
        errors.append("MIN仓位不能大于MAX仓位")
    
    # 显示配置摘要
    print("【基础配置】")
    print(f"  交易对: {CONFIG.get('SYMBOLS')}")
    print(f"  杠杆: {CONFIG.get('LEVERAGE')}x")
    print(f"  模式: {CONFIG.get('MODE')}")
    print()
    
    print("【风控配置】")
    print(f"  单笔风险: {CONFIG.get('MAX_RISK_PCT', 0)*100:.1f}%")
    print(f"  仓位范围: {CONFIG.get('POSITION_SIZE_PCT_MIN', 0)*100:.0f}% - {CONFIG.get('POSITION_SIZE_PCT_MAX', 0)*100:.0f}%")
    print(f"  日最大亏损: {CONFIG.get('MAX_DAILY_LOSS_PCT', 0)*100:.0f}%")
    print(f"  最大回撤: {CONFIG.get('MAX_DD_LIMIT', 0)*100:.0f}%")
    print()
    
    print("【止盈止损】")
    print(f"  止损倍数: {CONFIG.get('STOP_LOSS_ATR_MULT')}x ATR")
    print(f"  震荡市止盈: {CONFIG.get('TP_SIDEWAYS_ATR_MULT')}x ATR")
    print(f"  趋势市止盈: {CONFIG.get('TP_TRENDING_ATR_MULT')}x ATR")
    print(f"  移动止盈回撤: {CONFIG.get('TRAILING_STOP_DRAWBACK_PCT', 0)*100:.0f}%")
    print()
    
    print("【信号参数】")
    print(f"  ML门槛: {CONFIG.get('ML_CONFIDENCE_THRESHOLD')}")
    print(f"  RSI超卖/超买: {CONFIG.get('TECH_RSI_OVERSOLD')}/{CONFIG.get('TECH_RSI_OVERBOUGHT')}")
    print()
    
    print("【冷却期】")
    print(f"  高/中/低置信度: {CONFIG.get('COOLDOWN_HIGH_CONFIDENCE')}/{CONFIG.get('COOLDOWN_MID_CONFIDENCE')}/{CONFIG.get('COOLDOWN_LOW_CONFIDENCE')}秒")
    print()
    
    print("【插针保护】")
    print(f"  检测窗口: {CONFIG.get('SPIKE_DETECTION_WINDOW_SECONDS')}秒")
    print(f"  波动阈值: {CONFIG.get('SPIKE_PRICE_CHANGE_THRESHOLD', 0)*100:.1f}%")
    print(f"  熔断时间: {CONFIG.get('SPIKE_CIRCUIT_BREAKER_MINUTES')}分钟")
    print()
    
    # 显示警告和错误
    if warnings:
        print("【警告】")
        for w in warnings:
            print(f"  ⚠️  {w}")
        print()
    
    if errors:
        print("【错误】")
        for e in errors:
            print(f"  ❌  {e}")
        print()
        print("=" * 70)
        print("配置验证失败，请修复错误后重启")
        print("=" * 70)
        return False
    
    print("=" * 70)
    if warnings:
        print("✅ 配置验证通过（有警告，建议检查）")
    else:
        print("✅ 配置验证通过")
    print("=" * 70)
    return True

if __name__ == "__main__":
    success = verify_config()
    sys.exit(0 if success else 1)
