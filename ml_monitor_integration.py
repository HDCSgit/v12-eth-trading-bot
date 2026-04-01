#!/usr/bin/env python3
"""
ML监控集成模块
================
将ML自检系统集成到V12交易系统中

功能:
1. 实时监控ML模型性能
2. 自动调整交易参数
3. 异常时自动暂停交易
4. 生成维护报告

使用方法:
    在 main_v12_live_optimized.py 中:
    
    from ml_monitor_integration import MLMonitorBridge
    
    class V12OptimizedTrader:
        def __init__(self):
            ...
            self.ml_monitor = MLMonitorBridge(self)
            self.ml_monitor.start()
"""

import logging
from typing import Dict, Tuple
from datetime import datetime
import json
import os

logger = logging.getLogger(__name__)


class MLMonitorBridge:
    """
    ML监控桥接器
    
    连接ML自检系统和交易系统
    """
    
    def __init__(self, trader):
        """
        初始化
        
        Args:
            trader: V12OptimizedTrader实例
        """
        self.trader = trader
        self.config_file = 'ml_adaptive_config.json'
        self.last_check_time = None
        self.check_interval_minutes = 30
        self.cycle_count = 0
        
        # 维护状态
        self.maintenance_state = {
            'ml_threshold': 0.80,      # 当前ML阈值
            'stop_loss_mult': 2.0,     # 当前止损倍数
            'position_size_pct': 0.80, # 当前仓位比例
            'trading_enabled': True,   # 是否允许交易
            'last_update': None,
            'reason': None
        }
        
        # 加载历史配置
        self._load_config()
        
    def _load_config(self):
        """加载自适应配置"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    saved = json.load(f)
                    self.maintenance_state.update(saved)
                    logger.info(f"[MLMonitor] 加载自适应配置: {saved}")
            except Exception as e:
                logger.error(f"[MLMonitor] 加载配置失败: {e}")
    
    def _save_config(self):
        """保存自适应配置"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.maintenance_state, f, indent=2)
        except Exception as e:
            logger.error(f"[MLMonitor] 保存配置失败: {e}")
    
    def start(self):
        """启动监控"""
        logger.info("[MLMonitor] ML监控桥接器已启动")
        logger.info(f"[MLMonitor] 初始参数: ML阈值={self.maintenance_state['ml_threshold']}, "
                   f"止损={self.maintenance_state['stop_loss_mult']}x, "
                   f"仓位={self.maintenance_state['position_size_pct']*100:.0f}%")
    
    def check_and_adjust(self):
        """
        检查并调整参数
        
        在每个交易周期调用
        """
        self.cycle_count += 1
        
        # 每30个周期检查一次（约4-5分钟）
        if self.cycle_count % 30 != 0:
            return
        
        try:
            # 动态导入以避免循环依赖
            from ml_self_diagnosis import MLSelfDiagnosis, ModelHealthStatus
            
            diagnosis = MLSelfDiagnosis()
            metrics = diagnosis.calculate_metrics(lookback_hours=6)
            
            if not metrics:
                return
            
            status, issues = diagnosis.diagnose(metrics)
            
            # 记录状态
            logger.info(f"[MLMonitor] 模型状态: {status.value}, "
                       f"胜率(20笔): {metrics.win_rate_20*100:.1f}%, "
                       f"回撤: {metrics.max_drawdown*100:.1f}%")
            
            # 根据状态调整
            if status == ModelHealthStatus.CRITICAL:
                self._handle_critical(metrics, issues)
            elif status == ModelHealthStatus.WARNING:
                self._handle_warning(metrics, issues)
            elif status == ModelHealthStatus.HEALTHY:
                self._handle_healthy(metrics)
            
            self._save_config()
            
        except Exception as e:
            logger.error(f"[MLMonitor] 检查异常: {e}")
    
    def _handle_critical(self, metrics, issues):
        """处理危险状态"""
        logger.critical("[MLMonitor] ⚠️ 模型状态危险！触发紧急维护")
        
        old_state = self.maintenance_state.copy()
        
        # 1. 提高ML阈值到0.90，暂停低质量信号
        if metrics.win_rate_20 < 0.20:
            self.maintenance_state['ml_threshold'] = 0.90
            logger.critical("[MLMonitor] 提高ML阈值至0.90，暂停低质量信号")
        
        # 2. 收紧止损
        if metrics.max_drawdown > 0.20:
            self.maintenance_state['stop_loss_mult'] = 1.5
            logger.critical("[MLMonitor] 收紧止损至1.5x ATR")
        
        # 3. 降低仓位
        self.maintenance_state['position_size_pct'] = 0.50
        logger.critical("[MLMonitor] 降低仓位至50%")
        
        # 4. 如果胜率极低，完全暂停交易
        if metrics.win_rate_10 < 0.10:
            self.maintenance_state['trading_enabled'] = False
            self.maintenance_state['reason'] = f"胜率过低: {metrics.win_rate_10*100:.1f}%"
            logger.critical("[MLMonitor] 🛑 暂停所有新交易！")
        
        self.maintenance_state['last_update'] = datetime.now().isoformat()
        
        # 应用参数到交易系统
        self._apply_to_trader()
        
        # 生成报告
        self._generate_alert(old_state, self.maintenance_state, issues)
    
    def _handle_warning(self, metrics, issues):
        """处理警告状态"""
        logger.warning("[MLMonitor] 模型状态警告，执行自适应调整")
        
        old_state = self.maintenance_state.copy()
        adjusted = False
        
        # 胜率下降，提高阈值
        if metrics.win_rate_20 < 0.35 and self.maintenance_state['ml_threshold'] < 0.85:
            self.maintenance_state['ml_threshold'] = min(0.90, self.maintenance_state['ml_threshold'] + 0.02)
            logger.warning(f"[MLMonitor] 提高ML阈值至{self.maintenance_state['ml_threshold']:.2f}")
            adjusted = True
        
        # 回撤过大，收紧止损
        if metrics.max_drawdown > 0.10 and self.maintenance_state['stop_loss_mult'] > 1.5:
            self.maintenance_state['stop_loss_mult'] = max(1.5, self.maintenance_state['stop_loss_mult'] - 0.2)
            logger.warning(f"[MLMonitor] 收紧止损至{self.maintenance_state['stop_loss_mult']:.1f}x ATR")
            adjusted = True
        
        # 信号过少，略微降低阈值
        if metrics.signal_frequency < 2 and self.maintenance_state['ml_threshold'] > 0.75:
            self.maintenance_state['ml_threshold'] = max(0.75, self.maintenance_state['ml_threshold'] - 0.01)
            logger.warning(f"[MLMonitor] 略微降低ML阈值至{self.maintenance_state['ml_threshold']:.2f}以增加信号")
            adjusted = True
        
        if adjusted:
            self.maintenance_state['last_update'] = datetime.now().isoformat()
            self._apply_to_trader()
    
    def _handle_healthy(self, metrics):
        """处理健康状态 - 可以尝试恢复参数"""
        # 如果连续健康，逐步恢复正常参数
        if self.maintenance_state['ml_threshold'] > 0.80:
            self.maintenance_state['ml_threshold'] = max(0.80, self.maintenance_state['ml_threshold'] - 0.01)
            logger.info(f"[MLMonitor] 模型健康，逐步恢复ML阈值至{self.maintenance_state['ml_threshold']:.2f}")
            self.maintenance_state['last_update'] = datetime.now().isoformat()
            self._apply_to_trader()
        
        # 恢复交易权限
        if not self.maintenance_state['trading_enabled']:
            self.maintenance_state['trading_enabled'] = True
            self.maintenance_state['reason'] = None
            logger.info("[MLMonitor] ✅ 恢复交易权限")
            self._apply_to_trader()
    
    def _apply_to_trader(self):
        """应用参数到交易系统"""
        try:
            # 更新交易系统的CONFIG
            if hasattr(self.trader, 'config'):
                self.trader.config['ML_CONFIDENCE_THRESHOLD'] = self.maintenance_state['ml_threshold']
                self.trader.config['STOP_LOSS_ATR_MULT'] = self.maintenance_state['stop_loss_mult']
                self.trader.config['POSITION_SIZE_PCT'] = self.maintenance_state['position_size_pct']
            
            # 如果交易系统使用全局CONFIG
            from config import CONFIG
            CONFIG['ML_CONFIDENCE_THRESHOLD'] = self.maintenance_state['ml_threshold']
            CONFIG['STOP_LOSS_ATR_MULT'] = self.maintenance_state['stop_loss_mult']
            
            logger.info("[MLMonitor] 参数已应用到交易系统")
            
        except Exception as e:
            logger.error(f"[MLMonitor] 应用参数失败: {e}")
    
    def _generate_alert(self, old_state, new_state, issues):
        """生成警报报告"""
        alert = []
        alert.append("="*70)
        alert.append("⚠️ ML模型维护警报")
        alert.append(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        alert.append("="*70)
        
        alert.append("\n【参数变更】")
        for key in ['ml_threshold', 'stop_loss_mult', 'position_size_pct', 'trading_enabled']:
            if old_state.get(key) != new_state.get(key):
                alert.append(f"  {key}: {old_state.get(key)} → {new_state.get(key)}")
        
        alert.append("\n【触发原因】")
        for issue in issues:
            alert.append(f"  - {issue}")
        
        if not new_state['trading_enabled']:
            alert.append("\n🛑 交易已暂停！")
            alert.append(f"原因: {new_state.get('reason', '未知')}")
            alert.append("请检查模型状态并手动恢复")
        
        alert.append("\n" + "="*70)
        
        alert_text = "\n".join(alert)
        logger.critical(alert_text)
        
        # 保存到文件
        alert_file = f"ml_alert_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        try:
            with open(alert_file, 'w', encoding='utf-8') as f:
                f.write(alert_text)
        except Exception as e:
            logger.error(f"保存警报失败: {e}")
    
    def can_trade(self) -> Tuple[bool, str]:
        """
        检查是否允许交易
        
        在生成信号前调用
        
        Returns:
            (是否允许, 原因)
        """
        if not self.maintenance_state['trading_enabled']:
            return False, f"交易已暂停: {self.maintenance_state.get('reason', '模型维护')}"
        
        # 检查ML阈值
        signal_confidence = getattr(self.trader, 'last_ml_confidence', 0.5)
        if signal_confidence < self.maintenance_state['ml_threshold']:
            return False, f"ML置信度{signal_confidence:.2f}低于阈值{self.maintenance_state['ml_threshold']:.2f}"
        
        return True, "检查通过"
    
    def get_status(self) -> Dict:
        """获取当前状态"""
        return {
            'maintenance_state': self.maintenance_state,
            'cycle_count': self.cycle_count,
            'last_check': self.last_check_time
        }
    
    def manual_override(self, param: str, value):
        """手动覆盖参数"""
        if param in self.maintenance_state:
            old_value = self.maintenance_state[param]
            self.maintenance_state[param] = value
            self.maintenance_state['last_update'] = datetime.now().isoformat()
            self.maintenance_state['reason'] = f"手动覆盖: {param} {old_value}→{value}"
            self._apply_to_trader()
            self._save_config()
            logger.info(f"[MLMonitor] 手动覆盖参数: {param} = {value}")
        else:
            logger.error(f"[MLMonitor] 未知参数: {param}")
    
    def resume_trading(self):
        """手动恢复交易"""
        self.maintenance_state['trading_enabled'] = True
        self.maintenance_state['reason'] = None
        self.maintenance_state['last_update'] = datetime.now().isoformat()
        self._save_config()
        logger.info("[MLMonitor] 手动恢复交易")


# ==================== 使用示例 ====================

def example_usage():
    """使用示例"""
    print("="*70)
    print("MLMonitorBridge 使用示例")
    print("="*70)
    print()
    print("1. 在 V12OptimizedTrader 中添加:")
    print()
    print("   from ml_monitor_integration import MLMonitorBridge")
    print()
    print("   class V12OptimizedTrader:")
    print("       def __init__(self):")
    print("           ...")
    print("           # 启动ML监控")
    print("           self.ml_monitor = MLMonitorBridge(self)")
    print("           self.ml_monitor.start()")
    print()
    print("       def run_cycle(self):")
    print("           # 检查是否允许交易")
    print("           can_trade, reason = self.ml_monitor.can_trade()")
    print("           if not can_trade:")
    print("               logger.warning(f'交易被阻止: {reason}')")
    print("               return")
    print()
    print("           # 生成信号...")
    print()
    print("           # 定期检查和调整")
    print("           self.ml_monitor.check_and_adjust()")
    print()
    print("2. 查看当前状态:")
    print("   status = trader.ml_monitor.get_status()")
    print()
    print("3. 手动恢复交易:")
    print("   trader.ml_monitor.resume_trading()")
    print()
    print("4. 手动调整参数:")
    print("   trader.ml_monitor.manual_override('ml_threshold', 0.85)")
    print()
    print("="*70)


if __name__ == "__main__":
    example_usage()
