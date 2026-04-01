#!/usr/bin/env python3
"""
ML模型自检与自动维护系统
============================
功能:
1. 实时监控模型性能指标
2. 自动检测模型退化
3. 触发重训练机制
4. 参数自适应调整
5. 生成维护报告

Author: AI Assistant
Version: 1.0.0
Date: 2026-03-24
"""

import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum
import json
import logging
import threading
import time

logger = logging.getLogger(__name__)


class ModelHealthStatus(Enum):
    """模型健康状态"""
    HEALTHY = "健康"           # 所有指标正常
    WARNING = "警告"           # 部分指标异常
    CRITICAL = "危险"          # 严重退化，需立即处理
    UNKNOWN = "未知"           # 数据不足


@dataclass
class ModelMetrics:
    """模型性能指标"""
    timestamp: datetime
    
    # 核心指标
    win_rate_10: float         # 最近10笔胜率
    win_rate_20: float         # 最近20笔胜率
    win_rate_50: float         # 最近50笔胜率
    
    # 盈亏指标
    avg_pnl: float             # 平均盈亏
    total_pnl: float           # 总盈亏
    max_drawdown: float        # 最大回撤
    profit_factor: float       # 盈亏比
    
    # 信号质量
    avg_confidence: float      # 平均置信度
    high_conf_ratio: float     # 高置信度比例
    signal_frequency: float    # 信号频率(笔/小时)
    
    # 预测准确度
    prediction_accuracy: float # 预测方向准确率
    calibration_error: float   # 校准误差
    
    # 模型稳定性
    feature_stability: float   # 特征稳定性
    prediction_entropy: float  # 预测熵(多样性)


class MLSelfDiagnosis:
    """ML模型自检系统"""
    
    # 健康阈值配置
    THRESHOLDS = {
        'win_rate_warning': 0.30,      # 胜率警告线
        'win_rate_critical': 0.20,     # 胜率危险线
        'drawdown_warning': 0.10,      # 回撤警告线
        'drawdown_critical': 0.20,     # 回撤危险线
        'profit_factor_min': 1.0,      # 盈亏比最小值
        'confidence_min': 0.70,        # 最小平均置信度
        'accuracy_min': 0.55,          # 最小预测准确率
    }
    
    def __init__(self, db_path: str = 'v12_optimized.db'):
        self.db_path = db_path
        self.metrics_history: List[ModelMetrics] = []
        self.max_history = 100
        self.current_status = ModelHealthStatus.UNKNOWN
        self.diagnosis_log: List[Dict] = []
        
    def calculate_metrics(self, lookback_hours: int = 24) -> Optional[ModelMetrics]:
        """计算当前模型指标"""
        try:
            conn = sqlite3.connect(self.db_path)
            
            # 加载交易数据
            trades_df = pd.read_sql_query(f"""
                SELECT * FROM trades 
                WHERE timestamp >= datetime('now', '-{lookback_hours} hours')
                ORDER BY timestamp
            """, conn)
            
            # 加载信号数据
            signals_df = pd.read_sql_query(f"""
                SELECT * FROM signals 
                WHERE timestamp >= datetime('now', '-{lookback_hours} hours')
                ORDER BY timestamp
            """, conn)
            
            conn.close()
            
            if len(trades_df) < 5:
                logger.warning(f"交易数据不足: {len(trades_df)} < 5")
                return None
            
            # 数据类型转换 - 处理可能的bytes类型
            for col in ['pnl_pct', 'pnl_usdt', 'entry_price', 'exit_price', 'qty']:
                if col in trades_df.columns:
                    trades_df[col] = pd.to_numeric(trades_df[col], errors='coerce')
            
            for col in ['confidence']:
                if col in signals_df.columns:
                    signals_df[col] = pd.to_numeric(signals_df[col], errors='coerce')
            
            # 转换时间戳
            trades_df['timestamp'] = pd.to_datetime(trades_df['timestamp'])
            
            # 计算胜率
            trades_df['is_win'] = trades_df['result'] == 'WIN'
            win_rate_10 = trades_df.tail(10)['is_win'].mean() if len(trades_df) >= 10 else 0
            win_rate_20 = trades_df.tail(20)['is_win'].mean() if len(trades_df) >= 20 else win_rate_10
            win_rate_50 = trades_df.tail(50)['is_win'].mean() if len(trades_df) >= 50 else win_rate_20
            
            # 盈亏指标
            avg_pnl = trades_df['pnl_pct'].mean()
            total_pnl = trades_df['pnl_pct'].sum()
            
            # 最大回撤
            trades_df['pnl_cumsum'] = trades_df['pnl_pct'].cumsum()
            trades_df['peak'] = trades_df['pnl_cumsum'].cummax()
            trades_df['drawdown'] = trades_df['peak'] - trades_df['pnl_cumsum']
            max_drawdown = trades_df['drawdown'].max()
            
            # 盈亏比
            wins = trades_df[trades_df['pnl_pct'] > 0]['pnl_pct'].sum()
            losses = abs(trades_df[trades_df['pnl_pct'] < 0]['pnl_pct'].sum())
            profit_factor = wins / losses if losses > 0 else float('inf')
            
            # 信号质量
            if len(signals_df) > 0:
                avg_confidence = signals_df['confidence'].mean()
                high_conf_ratio = (signals_df['confidence'] >= 0.8).mean()
                signal_frequency = len(signals_df) / lookback_hours
            else:
                avg_confidence = 0.5
                high_conf_ratio = 0
                signal_frequency = 0
            
            # 预测准确度（简化计算）
            prediction_accuracy = win_rate_20  # 用胜率作为代理
            
            # 校准误差
            calibration_error = abs(avg_confidence - prediction_accuracy)
            
            # 特征稳定性（需要历史数据）
            feature_stability = self._calculate_feature_stability()
            
            # 预测熵
            if len(signals_df) > 0:
                action_counts = signals_df['action'].value_counts(normalize=True)
                prediction_entropy = -sum(p * np.log2(p) for p in action_counts if p > 0)
            else:
                prediction_entropy = 0
            
            metrics = ModelMetrics(
                timestamp=datetime.now(),
                win_rate_10=win_rate_10,
                win_rate_20=win_rate_20,
                win_rate_50=win_rate_50,
                avg_pnl=avg_pnl,
                total_pnl=total_pnl,
                max_drawdown=max_drawdown,
                profit_factor=profit_factor,
                avg_confidence=avg_confidence,
                high_conf_ratio=high_conf_ratio,
                signal_frequency=signal_frequency,
                prediction_accuracy=prediction_accuracy,
                calibration_error=calibration_error,
                feature_stability=feature_stability,
                prediction_entropy=prediction_entropy
            )
            
            # 保存历史
            self.metrics_history.append(metrics)
            if len(self.metrics_history) > self.max_history:
                self.metrics_history.pop(0)
            
            return metrics
            
        except Exception as e:
            logger.error(f"计算指标失败: {e}")
            return None
    
    def _calculate_feature_stability(self) -> float:
        """计算特征稳定性（需要实现特征历史追踪）"""
        # TODO: 实现特征重要性历史对比
        return 0.8  # 默认值
    
    def diagnose(self, metrics: ModelMetrics) -> Tuple[ModelHealthStatus, List[str]]:
        """诊断模型健康状况"""
        issues = []
        
        # 检查胜率
        if metrics.win_rate_20 < self.THRESHOLDS['win_rate_critical']:
            issues.append(f"CRITICAL: 胜率{metrics.win_rate_20*100:.1f}%低于危险线{self.THRESHOLDS['win_rate_critical']*100:.0f}%")
        elif metrics.win_rate_20 < self.THRESHOLDS['win_rate_warning']:
            issues.append(f"WARNING: 胜率{metrics.win_rate_20*100:.1f}%低于警告线{self.THRESHOLDS['win_rate_warning']*100:.0f}%")
        
        # 检查回撤
        if metrics.max_drawdown > self.THRESHOLDS['drawdown_critical']:
            issues.append(f"CRITICAL: 最大回撤{metrics.max_drawdown*100:.1f}%超过危险线{self.THRESHOLDS['drawdown_critical']*100:.0f}%")
        elif metrics.max_drawdown > self.THRESHOLDS['drawdown_warning']:
            issues.append(f"WARNING: 最大回撤{metrics.max_drawdown*100:.1f}%超过警告线{self.THRESHOLDS['drawdown_warning']*100:.0f}%")
        
        # 检查盈亏比
        if metrics.profit_factor < self.THRESHOLDS['profit_factor_min']:
            issues.append(f"WARNING: 盈亏比{metrics.profit_factor:.2f}低于{self.THRESHOLDS['profit_factor_min']}")
        
        # 检查置信度
        if metrics.avg_confidence < self.THRESHOLDS['confidence_min']:
            issues.append(f"WARNING: 平均置信度{metrics.avg_confidence:.2f}低于{self.THRESHOLDS['confidence_min']}")
        
        # 检查预测准确率
        if metrics.prediction_accuracy < self.THRESHOLDS['accuracy_min']:
            issues.append(f"WARNING: 预测准确率{metrics.prediction_accuracy*100:.1f}%低于{self.THRESHOLDS['accuracy_min']*100:.0f}%")
        
        # 检查胜率下降趋势
        if len(self.metrics_history) >= 3:
            recent_wr = [m.win_rate_20 for m in self.metrics_history[-3:]]
            if all(recent_wr[i] > recent_wr[i+1] for i in range(len(recent_wr)-1)):
                issues.append("WARNING: 胜率连续下降，模型可能退化")
        
        # 确定状态
        if any('CRITICAL' in issue for issue in issues):
            status = ModelHealthStatus.CRITICAL
        elif any('WARNING' in issue for issue in issues):
            status = ModelHealthStatus.WARNING
        elif metrics.win_rate_20 >= 0.40:
            status = ModelHealthStatus.HEALTHY
        else:
            status = ModelHealthStatus.UNKNOWN
        
        # 记录日志
        self.diagnosis_log.append({
            'timestamp': datetime.now(),
            'status': status.value,
            'issues': issues,
            'metrics': metrics
        })
        
        self.current_status = status
        return status, issues
    
    def generate_report(self) -> str:
        """生成诊断报告"""
        metrics = self.calculate_metrics()
        if not metrics:
            return "数据不足，无法生成报告"
        
        status, issues = self.diagnose(metrics)
        
        report = []
        report.append("="*70)
        report.append(f"ML模型自检报告 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("="*70)
        
        report.append(f"\n【健康状态】 {status.value}")
        
        if issues:
            report.append(f"\n【发现问题】 {len(issues)}项")
            for issue in issues:
                report.append(f"  - {issue}")
        else:
            report.append("\n【发现问题】 无")
        
        report.append(f"\n【核心指标】")
        report.append(f"  胜率(10笔): {metrics.win_rate_10*100:.1f}%")
        report.append(f"  胜率(20笔): {metrics.win_rate_20*100:.1f}%")
        report.append(f"  胜率(50笔): {metrics.win_rate_50*100:.1f}%")
        report.append(f"  平均盈亏: {metrics.avg_pnl*100:.2f}%")
        report.append(f"  总盈亏: {metrics.total_pnl*100:.2f}%")
        report.append(f"  最大回撤: {metrics.max_drawdown*100:.2f}%")
        report.append(f"  盈亏比: {metrics.profit_factor:.2f}")
        
        report.append(f"\n【信号质量】")
        report.append(f"  平均置信度: {metrics.avg_confidence:.2f}")
        report.append(f"  高置信度比例: {metrics.high_conf_ratio*100:.1f}%")
        report.append(f"  信号频率: {metrics.signal_frequency:.1f}笔/小时")
        
        report.append(f"\n【预测性能】")
        report.append(f"  预测准确率: {metrics.prediction_accuracy*100:.1f}%")
        report.append(f"  校准误差: {metrics.calibration_error:.3f}")
        report.append(f"  预测熵: {metrics.prediction_entropy:.3f}")
        
        # 建议
        report.append(f"\n【维护建议】")
        suggestions = self._generate_suggestions(metrics, issues)
        for suggestion in suggestions:
            report.append(f"  - {suggestion}")
        
        report.append("\n" + "="*70)
        
        return "\n".join(report)
    
    def _generate_suggestions(self, metrics: ModelMetrics, issues: List[str]) -> List[str]:
        """生成维护建议"""
        suggestions = []
        
        if metrics.win_rate_20 < 0.30:
            suggestions.append("建议立即暂停交易，检查模型逻辑")
            suggestions.append("考虑增加训练样本，重新训练模型")
            suggestions.append("检查特征是否过时，更新特征工程")
        
        if metrics.max_drawdown > 0.15:
            suggestions.append("建议收紧止损，降低单笔风险")
            suggestions.append("考虑降低仓位大小")
        
        if metrics.avg_confidence < 0.70:
            suggestions.append("建议提高ML置信度阈值，过滤低质量信号")
        
        if metrics.profit_factor < 1.2:
            suggestions.append("建议优化止盈止损比例，提高盈亏比")
        
        if not suggestions:
            suggestions.append("模型运行正常，继续保持监控")
        
        return suggestions


class MLAutoMaintenance:
    """ML模型自动维护系统"""
    
    def __init__(self, diagnosis: MLSelfDiagnosis):
        self.diagnosis = diagnosis
        self.maintenance_log: List[Dict] = []
        self.is_running = False
        self.maintenance_thread = None
        
        # 自适应参数
        self.adaptive_params = {
            'ml_threshold': 0.80,
            'stop_loss_mult': 2.0,
            'position_size_pct': 0.80,
        }
    
    def start_monitoring(self, interval_minutes: int = 30):
        """启动自动监控"""
        self.is_running = True
        self.maintenance_thread = threading.Thread(
            target=self._monitoring_loop,
            args=(interval_minutes,),
            daemon=True
        )
        self.maintenance_thread.start()
        logger.info(f"自动监控已启动，间隔: {interval_minutes}分钟")
    
    def _monitoring_loop(self, interval_minutes: int):
        """监控循环"""
        while self.is_running:
            try:
                # 执行自检
                metrics = self.diagnosis.calculate_metrics()
                if metrics:
                    status, issues = self.diagnosis.diagnose(metrics)
                    
                    logger.info(f"模型状态: {status.value}, 胜率: {metrics.win_rate_20*100:.1f}%")
                    
                    # 根据状态执行维护
                    if status == ModelHealthStatus.CRITICAL:
                        self._emergency_maintenance(metrics, issues)
                    elif status == ModelHealthStatus.WARNING:
                        self._adaptive_adjustment(metrics, issues)
                    
                    # 生成报告
                    if len(self.diagnosis.metrics_history) % 10 == 0:
                        report = self.diagnosis.generate_report()
                        self._save_report(report)
                
            except Exception as e:
                logger.error(f"监控循环异常: {e}")
            
            time.sleep(interval_minutes * 60)
    
    def _emergency_maintenance(self, metrics: ModelMetrics, issues: List[str]):
        """紧急维护"""
        logger.critical("触发紧急维护！")
        
        actions = []
        
        # 1. 暂停新信号（通过提高阈值）
        if metrics.win_rate_20 < 0.20:
            self.adaptive_params['ml_threshold'] = 0.90
            actions.append("提高ML阈值至0.90，暂停低质量信号")
        
        # 2. 收紧止损
        if metrics.max_drawdown > 0.20:
            self.adaptive_params['stop_loss_mult'] = 1.5
            actions.append("收紧止损至1.5x ATR")
        
        # 3. 降低仓位
        self.adaptive_params['position_size_pct'] = 0.50
        actions.append("降低仓位至50%")
        
        # 记录
        self.maintenance_log.append({
            'timestamp': datetime.now(),
            'type': 'emergency',
            'metrics': metrics,
            'issues': issues,
            'actions': actions,
            'params': self.adaptive_params.copy()
        })
        
        logger.critical(f"紧急维护动作: {actions}")
    
    def _adaptive_adjustment(self, metrics: ModelMetrics, issues: List[str]):
        """自适应调整"""
        logger.warning("执行自适应调整")
        
        actions = []
        
        # 胜率下降时的调整
        if metrics.win_rate_20 < 0.35 and self.adaptive_params['ml_threshold'] < 0.85:
            self.adaptive_params['ml_threshold'] += 0.02
            actions.append(f"提高ML阈值至{self.adaptive_params['ml_threshold']:.2f}")
        
        # 回撤过大时的调整
        if metrics.max_drawdown > 0.10:
            self.adaptive_params['stop_loss_mult'] = max(1.5, self.adaptive_params['stop_loss_mult'] - 0.2)
            actions.append(f"收紧止损至{self.adaptive_params['stop_loss_mult']:.1f}x ATR")
        
        # 信号过少时的调整
        if metrics.signal_frequency < 2 and self.adaptive_params['ml_threshold'] > 0.75:
            self.adaptive_params['ml_threshold'] -= 0.01
            actions.append(f"略微降低ML阈值至{self.adaptive_params['ml_threshold']:.2f}以增加信号")
        
        if actions:
            self.maintenance_log.append({
                'timestamp': datetime.now(),
                'type': 'adaptive',
                'metrics': metrics,
                'issues': issues,
                'actions': actions,
                'params': self.adaptive_params.copy()
            })
            logger.warning(f"自适应调整: {actions}")
    
    def _save_report(self, report: str):
        """保存报告"""
        filename = f"ml_diagnosis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(report)
        logger.info(f"报告已保存: {filename}")
    
    def get_adaptive_params(self) -> Dict:
        """获取当前自适应参数"""
        return self.adaptive_params.copy()
    
    def stop(self):
        """停止监控"""
        self.is_running = False
        if self.maintenance_thread:
            self.maintenance_thread.join(timeout=5)
        logger.info("自动监控已停止")


# ==================== 集成到交易系统 ====================

class MLMonitorIntegration:
    """ML监控集成到交易系统"""
    
    def __init__(self, db_path: str = 'v12_optimized.db'):
        self.diagnosis = MLSelfDiagnosis(db_path)
        self.maintenance = MLAutoMaintenance(self.diagnosis)
        
    def start(self):
        """启动监控"""
        # 立即执行一次诊断
        report = self.diagnosis.generate_report()
        print(report)
        
        # 启动自动监控
        self.maintenance.start_monitoring(interval_minutes=30)
        
    def get_recommended_params(self) -> Dict:
        """获取推荐的参数"""
        return self.maintenance.get_adaptive_params()
    
    def check_before_trade(self) -> Tuple[bool, str]:
        """交易前检查"""
        metrics = self.diagnosis.calculate_metrics(lookback_hours=6)
        if not metrics:
            return True, "数据不足，允许交易"
        
        status, issues = self.diagnosis.diagnose(metrics)
        
        if status == ModelHealthStatus.CRITICAL:
            return False, f"模型状态危险，暂停交易: {issues[0]}"
        
        if status == ModelHealthStatus.WARNING and metrics.win_rate_10 < 0.25:
            return False, f"最近10笔胜率过低({metrics.win_rate_10*100:.1f}%)，建议暂停"
        
        return True, "检查通过"


def main():
    """测试运行"""
    print("="*70)
    print("ML模型自检系统测试")
    print("="*70)
    
    monitor = MLMonitorIntegration()
    
    # 生成报告
    report = monitor.diagnosis.generate_report()
    print(report)
    
    # 获取推荐参数
    params = monitor.get_recommended_params()
    print("\n【推荐参数】")
    for key, value in params.items():
        print(f"  {key}: {value}")
    
    # 检查是否允许交易
    allowed, msg = monitor.check_before_trade()
    print(f"\n【交易检查】 {'允许' if allowed else '阻止'}: {msg}")
    
    print("\n" + "="*70)
    print("启动自动监控 (按Ctrl+C停止)...")
    print("="*70)
    
    monitor.start()
    
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("\n停止监控...")
        monitor.maintenance.stop()


if __name__ == "__main__":
    main()
