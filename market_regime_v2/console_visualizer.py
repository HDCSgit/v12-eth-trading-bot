"""
控制台实时可视化模块
在交易日志中显示V2市场环境状态
"""
from datetime import datetime
from typing import Optional, Dict


class ConsoleVisualizer:
    """控制台可视化器 - 轻量级实时显示"""
    
    # ANSI颜色代码
    COLORS = {
        'SIDEWAYS': '\033[90m',      # 灰色
        'TREND_UP': '\033[32m',      # 绿色
        'TREND_DOWN': '\033[31m',    # 红色
        'BREAKOUT': '\033[33m',      # 黄色
        'EXTREME': '\033[35m',       # 紫色
        'RESET': '\033[0m',
        'BOLD': '\033[1m',
    }
    
    def __init__(self, use_color: bool = True):
        self.use_color = use_color
        self.last_regime = None
        self.last_confidence = 0
        
    def format_regime_bar(self, regime: str, confidence: float, 
                          probabilities: Optional[Dict[str, float]] = None) -> str:
        """
        格式化市场环境状态条
        
        示例输出:
        [ML环境] 🟢 TREND_UP [████████░░] 78% | 趋势上涨，建议做多
        """
        # 简化的 regime 名称映射
        regime_emoji = {
            'SIDEWAYS': '⬜',
            'TREND_UP': '🟢',
            'TREND_DOWN': '🔴',
            'BREAKOUT': '🟡',
            'EXTREME': '🟣',
        }.get(regime, '⚪')
        
        # 置信度条
        bar_len = int(confidence * 10)
        bar = '█' * bar_len + '░' * (10 - bar_len)
        
        # 颜色
        color = self.COLORS.get(regime, '') if self.use_color else ''
        reset = self.COLORS['RESET'] if self.use_color else ''
        bold = self.COLORS['BOLD'] if self.use_color else ''
        
        # 主要输出
        lines = [
            f"{color}{bold}[ML-V2]{reset} {regime_emoji} {regime:12} [{bar}] {confidence:.0%}",
        ]
        
        # 如果概率分布详细且置信度不高，显示TOP3
        if probabilities and confidence < 0.7:
            top3 = sorted(probabilities.items(), key=lambda x: x[1], reverse=True)[:3]
            probs_str = " | ".join([f"{k}:{v:.0%}" for k, v in top3])
            lines.append(f"       └─ 概率分布: {probs_str}")
        
        return '\n'.join(lines)
    
    def format_compact(self, result_dict: Dict) -> str:
        """
        紧凑格式（适合单行显示）
        
        示例:
        [V2:TREND_UP@78%]
        """
        regime = result_dict.get('regime', 'UNKNOWN')
        confidence = result_dict.get('confidence', 0)
        
        return f"[V2:{regime}@{confidence:.0%}]"
    
    def print_state_change(self, current_regime: str, current_confidence: float,
                          previous_regime: str, previous_confidence: float):
        """打印环境变化警告"""
        if current_regime != previous_regime:
            color = self.COLORS.get(current_regime, '') if self.use_color else ''
            reset = self.COLORS['RESET'] if self.use_color else ''
            
            print(f"{color}⚠️  市场环境变化: {previous_regime} → {current_regime}{reset}")
            
            if current_regime in ['BREAKOUT', 'EXTREME']:
                print(f"{color}   💡 建议: 注意风险控制，减少仓位{reset}")
            elif current_regime == 'SIDEWAYS' and previous_regime in ['TREND_UP', 'TREND_DOWN']:
                print(f"{color}   💡 建议: 趋势可能结束，考虑止盈{reset}")


# 便捷函数
def print_regime_status(result, use_color: bool = True):
    """一键打印V2状态"""
    viz = ConsoleVisualizer(use_color=use_color)
    
    output = viz.format_regime_bar(
        regime=result.regime.value,
        confidence=result.confidence,
        probabilities=result.probabilities
    )
    print(output)


# 使用示例
if __name__ == "__main__":
    # 测试显示效果
    viz = ConsoleVisualizer(use_color=True)
    
    test_cases = [
        {'regime': 'TREND_UP', 'confidence': 0.78},
        {'regime': 'SIDEWAYS', 'confidence': 0.45},
        {'regime': 'BREAKOUT', 'confidence': 0.82},
        {'regime': 'EXTREME', 'confidence': 0.65},
    ]
    
    print("V2控制台可视化测试:\n")
    for case in test_cases:
        print(viz.format_regime_bar(case['regime'], case['confidence']))
        print()
