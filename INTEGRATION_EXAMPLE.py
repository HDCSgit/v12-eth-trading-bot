#!/usr/bin/env python3
"""
V12交易系统集成ML监控示例
===========================

展示了如何将ML自检系统完整集成到交易系统中
"""

# ========================================
# 1. 在 main_v12_live_optimized.py 中修改
# ========================================

"""
# 在文件顶部添加导入
from ml_monitor_integration import MLMonitorBridge

# ========================================
# 2. 在 V12OptimizedTrader.__init__ 中添加
# ========================================

class V12OptimizedTrader:
    def __init__(self):
        # ... 原有初始化代码 ...
        
        # ========== 新增: ML监控桥接器 ==========
        self.ml_monitor = MLMonitorBridge(self)
        self.ml_monitor.start()
        logger.info("✅ ML监控桥接器已启动")
        # ======================================
        
        # ... 其他初始化代码 ...

# ========================================
# 3. 在 generate_signal 方法中添加交易前检查
# ========================================

    def generate_signal(self, df, current_price, funding_rate, 
                       has_position=False, position_side=None, entry_price=0):
        """生成交易信号"""
        
        # ========== 新增: ML监控检查 ==========
        can_trade, reason = self.ml_monitor.can_trade()
        if not can_trade:
            logger.warning(f'[MLMonitor] 🛑 交易被阻止: {reason}')
            return TradingSignal(
                'HOLD', 0.5, SignalSource.TECHNICAL,
                f'ML监控阻止: {reason}',
                df['ATR'].iloc[-1] if 'ATR' in df.columns else 10.0,
                regime=MarketRegime.UNKNOWN,
                funding_rate=funding_rate
            )
        # ======================================
        
        # ... 原有信号生成逻辑 ...
        
        # 记录ML置信度供监控使用
        ml_result = self.signal_gen.ml_model.predict(df)
        self.last_ml_confidence = ml_result.get('confidence', 0.5)
        
        # ... 继续信号处理 ...

# ========================================
# 4. 在 run_cycle 方法中添加定期检查
# ========================================

    def run_cycle(self):
        """运行一个交易周期"""
        try:
            # ... 原有代码 ...
            
            # ========== 新增: ML监控定期检查 ==========
            self.ml_monitor.check_and_adjust()
            # =========================================
            
            # ... 原有代码继续 ...
            
        except Exception as e:
            logger.error(f"交易周期异常: {e}")

# ========================================
# 5. 添加监控状态查询命令
# ========================================

    def print_ml_status(self):
        """打印ML监控状态"""
        status = self.ml_monitor.get_status()
        
        print("="*60)
        print("ML监控状态")
        print("="*60)
        print(f"ML阈值: {status['maintenance_state']['ml_threshold']:.2f}")
        print(f"止损倍数: {status['maintenance_state']['stop_loss_mult']:.1f}x")
        print(f"仓位比例: {status['maintenance_state']['position_size_pct']*100:.0f}%")
        print(f"交易开关: {'开启' if status['maintenance_state']['trading_enabled'] else '关闭'}")
        print(f"检查周期: {status['cycle_count']}")
        print(f"最后更新: {status['maintenance_state']['last_update']}")
        if status['maintenance_state']['reason']:
            print(f"状态说明: {status['maintenance_state']['reason']}")
        print("="*60)

# ========================================
# 6. 添加手动控制命令（用于紧急情况）
# ========================================

    def ml_emergency_stop(self):
        """紧急停止交易"""
        self.ml_monitor.manual_override('trading_enabled', False)
        logger.critical("🛑 紧急停止交易！")
        
    def ml_resume_trading(self):
        """恢复交易"""
        self.ml_monitor.resume_trading()
        logger.info("✅ 恢复交易")
        
    def ml_set_threshold(self, value: float):
        """设置ML阈值"""
        self.ml_monitor.manual_override('ml_threshold', value)
        logger.info(f"ML阈值设置为 {value:.2f}")


# ========================================
# 7. 在日志中显示监控信息
# ========================================

# 在交易日志中添加ML监控信息
"""
示例日志输出:

2026-03-24 19:00:00 | INFO | ✅ ML模型训练完成 | 样本数: 200
2026-03-24 19:00:05 | INFO | [MLMonitor] 模型状态: 健康, 胜率: 42.0%, 回撤: 5.2%
2026-03-24 19:30:00 | INFO | [MLMonitor] 模型状态: 警告, 胜率: 32.0%, 回撤: 12.0%
2026-03-24 19:30:00 | WARNING | [MLMonitor] 提高ML阈值至0.82
2026-03-24 19:30:00 | WARNING | [MLMonitor] 收紧止损至1.8x ATR
2026-03-24 20:00:00 | INFO | [MLMonitor] 模型状态: 危险, 胜率: 18.0%, 回撤: 22.0%
2026-03-24 20:00:00 | CRITICAL | [MLMonitor] ⚠️ 暂停所有新交易！
2026-03-24 20:00:00 | CRITICAL | [MLMonitor] 降低仓位至50%
"""


# ========================================
# 8. 外部控制接口（用于远程管理）
# ========================================

def control_ml_monitor(command: str, param: str = None, value=None):
    """
    外部控制ML监控
    
    可以通过API、命令行或Web界面调用
    
    命令:
        - status: 查看状态
        - stop: 停止交易
        - resume: 恢复交易
        - set_threshold: 设置阈值
        - set_stop_loss: 设置止损倍数
    """
    from main_v12_live_optimized import V12OptimizedTrader
    
    # 假设可以访问全局实例
    trader = V12OptimizedTrader.instance  # 需要实现单例模式
    
    if command == 'status':
        trader.print_ml_status()
        
    elif command == 'stop':
        trader.ml_emergency_stop()
        
    elif command == 'resume':
        trader.ml_resume_trading()
        
    elif command == 'set_threshold' and value is not None:
        trader.ml_set_threshold(float(value))
        
    elif command == 'set_stop_loss' and value is not None:
        trader.ml_monitor.manual_override('stop_loss_mult', float(value))
        
    else:
        print(f"未知命令: {command}")


# ========================================
# 9. 启动脚本中添加监控选项
# ========================================

"""
在 start_v12_optimized.bat 中添加:

@echo off
...
echo [M] 启动交易+ML监控
echo [T] 仅启动交易
echo [V] 查看ML监控状态
echo ...

set /p choice="请选择: "

if "%choice%"=="M" goto trade_with_monitor
if "%choice%"=="T" goto trade_only
if "%choice%"=="V" goto view_monitor
...

:view_monitor
python -c "from main_v12_live_optimized import V12OptimizedTrader; t = V12OptimizedTrader(); t.print_ml_status()"
pause
goto end
"""


# ========================================
# 10. 定期生成监控报告
# ========================================

import schedule
import time

def daily_ml_report():
    """每日ML监控报告"""
    from ml_self_diagnosis import MLSelfDiagnosis
    
    diagnosis = MLSelfDiagnosis()
    report = diagnosis.generate_report()
    
    # 保存报告
    filename = f"ml_daily_report_{datetime.now().strftime('%Y%m%d')}.txt"
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(report)
    
    # 发送通知（如果有配置）
    print(report)

# 每天上午9点生成报告
schedule.every().day.at("09:00").do(daily_ml_report)

# 在主循环中
def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    print("="*70)
    print("V12 ML监控集成示例")
    print("="*70)
    print()
    print("本文件展示了如何将ML自检系统集成到交易系统中")
    print()
    print("主要修改点:")
    print("1. 导入 MLMonitorBridge")
    print("2. 在 __init__ 中初始化监控")
    print("3. 在 generate_signal 中添加交易前检查")
    print("4. 在 run_cycle 中添加定期检查")
    print("5. 添加手动控制接口")
    print()
    print("详细文档: ML_MONITOR_GUIDE.md")
    print("="*70)
