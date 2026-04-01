#!/usr/bin/env python3
"""ML监控摘要 - 修复编码问题"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from ml_self_diagnosis import MLSelfDiagnosis, ModelHealthStatus

d = MLSelfDiagnosis()
metrics = d.calculate_metrics()

if not metrics:
    print("数据不足")
    sys.exit(0)

status, issues = d.diagnose(metrics)

print("="*70)
print(f"ML模型监控摘要 - {metrics.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
print("="*70)

print(f"\n[健康状态] {status.value}")

if issues:
    print(f"\n[问题列表] {len(issues)}项")
    for issue in issues:
        level = "CRITICAL" if "CRITICAL" in issue else "WARNING"
        print(f"  [{level}] {issue}")

print("\n[核心指标]")
print(f"  胜率(10笔): {metrics.win_rate_10*100:.1f}%")
print(f"  胜率(20笔): {metrics.win_rate_20*100:.1f}%")
print(f"  胜率(50笔): {metrics.win_rate_50*100:.1f}%")
print(f"  平均盈亏: {metrics.avg_pnl*100:.2f}%")
print(f"  总盈亏: {metrics.total_pnl*100:.2f}%")
print(f"  最大回撤: {metrics.max_drawdown*100:.2f}%")
print(f"  盈亏比: {metrics.profit_factor:.2f}")

print("\n[ML信号质量]")
print(f"  平均置信度: {metrics.avg_confidence:.2f}")
print(f"  高置信度比例: {metrics.high_conf_ratio*100:.1f}%")
print(f"  信号频率: {metrics.signal_frequency:.1f}笔/小时")

print("\n[维护建议]")
if status == ModelHealthStatus.CRITICAL:
    print("  1. 建议立即暂停交易")
    print("  2. 检查模型逻辑和特征")
    print("  3. 收紧止损到1.5x ATR")
    print("  4. 降低仓位到50%")
elif status == ModelHealthStatus.WARNING:
    print("  1. 提高ML阈值到0.85+")
    print("  2. 收紧止损到1.8x ATR")
    print("  3. 密切观察胜率变化")
else:
    print("  模型运行正常，继续保持监控")

print("\n" + "="*70)

# 保存简要报告
with open(f"ml_summary_{metrics.timestamp.strftime('%Y%m%d_%H%M%S')}.txt", 'w', encoding='utf-8') as f:
    f.write(f"Status: {status.value}\n")
    f.write(f"WinRate(20): {metrics.win_rate_20*100:.1f}%\n")
    f.write(f"MaxDrawdown: {metrics.max_drawdown*100:.2f}%\n")
    f.write(f"ProfitFactor: {metrics.profit_factor:.2f}\n")
    f.write(f"Issues: {len(issues)}\n")

print(f"\n报告已保存到: ml_summary_*.txt")
