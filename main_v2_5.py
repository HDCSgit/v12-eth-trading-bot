#!/usr/bin/env python3
"""
V2.5-Hybrid 主程序
结合V2双信号 + 轻量网格 + 斐波那契补仓 + 三层智能止盈
"""

import logging
import time
import sys
import signal
import os
from datetime import datetime
from config import CONFIG, API_KEY, SECRET_KEY
from binance_api import BinanceExpertAPI
from strategy_v2_5_hybrid import ExpertStrategyV2_5_Hybrid
from risk_execution_v2_5 import ExecutionEngineV2_5


# ======================【全局日志配置】======================
def setup_logging():
    """设置详细的日志系统"""
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    
    # 主日志文件
    main_handler = logging.FileHandler(
        f'{log_dir}/v2_5_production_{datetime.now():%Y%m%d}.log', 
        encoding='utf-8'
    )
    main_handler.setLevel(logging.INFO)
    
    # 错误日志单独记录
    error_handler = logging.FileHandler(
        f'{log_dir}/v2_5_errors_{datetime.now():%Y%m%d}.log',
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    
    # 交易日志单独记录
    trade_handler = logging.FileHandler(
        f'{log_dir}/v2_5_trades_{datetime.now():%Y%m%d}.log',
        encoding='utf-8'
    )
    trade_handler.setLevel(logging.INFO)
    
    # 控制台输出
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # 格式化
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)-15s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    for handler in [main_handler, error_handler, trade_handler, console_handler]:
        handler.setFormatter(formatter)
    
    # 根日志配置
    logging.basicConfig(
        level=logging.INFO,
        handlers=[main_handler, error_handler, console_handler]
    )
    
    # 交易专用logger
    trade_logger = logging.getLogger("trade")
    trade_logger.addHandler(trade_handler)
    return trade_logger

trade_logger = setup_logging()
logger = logging.getLogger(__name__)


# ======================【V2.5-Hybrid 生产系统】======================
class ProductionSystemV2_5:
    def __init__(self):
        self.api = BinanceExpertAPI()
        self.strategy = ExpertStrategyV2_5_Hybrid()
        self.executor = ExecutionEngineV2_5(self.api, self.strategy)
        self.running = True
        self.cycle_count = 0
        self.last_status_time = time.time()
        self.last_daily_reset = datetime.now().day
        
        # 优雅退出处理
        signal.signal(signal.SIGINT, self._graceful_shutdown)
        signal.signal(signal.SIGTERM, self._graceful_shutdown)
        
        logger.info("=" * 80)
        logger.info("🏆 V2.5-Hybrid 混合策略系统已启动")
        logger.info("模式: {} | 交易对: {}".format(CONFIG['MODE'], CONFIG['SYMBOLS']))
        logger.info("杠杆: {}x | 最大风险: {}%".format(
            CONFIG.get('LEVERAGE', 5), 
            CONFIG.get('MAX_RISK_PCT', 0.008) * 100
        ))
        logger.info("核心特性:")
        logger.info("  • V2双信号叠加（置信度≥0.60）")
        logger.info("  • 轻量双向网格（ATR×1.4）")
        logger.info("  • 斐波那契动态补仓（最多3次）")
        logger.info("  • 三层智能止盈（网格+追踪+整组）")
        logger.info("=" * 80)
        
        # 初始化时同步所有仓位
        self._initial_sync()

    def _initial_sync(self):
        """初始化时同步所有仓位"""
        logger.info("📡 初始化仓位同步...")
        for symbol in CONFIG["SYMBOLS"]:
            self.executor.sync_position(symbol)
        logger.info("✅ 仓位同步完成")

    def _graceful_shutdown(self, signum=None, frame=None):
        logger.info("👋 接收到退出信号，正在优雅关闭...")
        self.running = False
        for symbol in CONFIG["SYMBOLS"]:
            self.executor.sync_position(symbol)
        logger.info("✅ 所有日志已持久化，系统安全退出")
        sys.exit(0)

    def _check_daily_reset(self):
        """每日重置策略统计"""
        current_day = datetime.now().day
        if current_day != self.last_daily_reset:
            self.last_daily_reset = current_day
            self.strategy.reset_daily_stats()
            logger.info("🌅 新的一天，重置策略统计")

    def _log_status_report(self):
        """定期输出状态报告"""
        if time.time() - self.last_status_time < 300:  # 每5分钟
            return
        
        self.last_status_time = time.time()
        
        logger.info("=" * 80)
        logger.info("📊 V2.5-Hybrid 系统状态报告")
        logger.info("=" * 80)
        
        balance = self.api.get_balance()
        logger.info(f"💰 当前余额: ${balance:.2f} USDT")
        logger.info(f"📉 连续止损次数: {self.strategy.consecutive_losses}")
        logger.info(f"🛑 今日暂停状态: {self.strategy.daily_stop_loss_triggered}")
        logger.info(f"🔄 交易间隔: {self.strategy.min_trade_interval/60:.0f}分钟")
        
        # 显示仓位组状态
        for symbol, pg in self.strategy.position_groups.items():
            if pg.is_active:
                current_price = self.api.get_price(symbol) or pg.entry_price
                avg_price = pg.get_average_price()
                pnl_pct = pg.get_total_pnl_pct(current_price, CONFIG.get('LEVERAGE', 5))
                
                logger.info(
                    f"📍 {symbol}: {pg.side} | "
                    f"均价: ${avg_price:.2f} | "
                    f"现价: ${current_price:.2f} | "
                    f"盈亏: {pnl_pct:+.2f}% | "
                    f"补仓: {len(pg.dca_levels)}/3 | "
                    f"网格: {len([l for l in pg.grid_levels if not l.filled])}个活跃"
                )
            else:
                logger.info(f"📍 {symbol}: 无活跃持仓")
        
        logger.info("=" * 80)

    def run(self):
        """主循环"""
        logger.info(f"🚀 开始监控 {len(CONFIG['SYMBOLS'])} 个交易对: {CONFIG['SYMBOLS']}")
        logger.info(f"⏱️ 轮询间隔: {CONFIG['POLL_INTERVAL']}秒")
        
        while self.running:
            try:
                self.cycle_count += 1
                
                # 检查每日重置
                self._check_daily_reset()
                
                for symbol in CONFIG["SYMBOLS"]:
                    # 获取K线
                    df = self.api.get_klines(symbol, limit=800)
                    if df is None or len(df) < 200:
                        logger.warning(f"[{symbol}] 数据不足，跳过")
                        continue
                    
                    # 计算特征
                    df = self.strategy.compute_features(df, symbol)
                    if df is None or len(df) < 2:
                        continue
                    
                    # 获取当前价格
                    current_price = self.api.get_price(symbol)
                    
                    # 生成信号
                    signal = self.strategy.generate_signal(
                        symbol, df, current_price, self.api
                    )
                    
                    # 记录详细信号信息
                    if signal['action'] != 'HOLD':
                        trade_logger.info(
                            f"SIGNAL | {symbol} | {signal['action']} | "
                            f"confidence={signal['confidence']:.2f} | "
                            f"reason={signal['reason']} | "
                            f"losses={signal.get('consecutive_losses', 0)}"
                        )
                        
                        # 如果是新开仓，显示网格信息
                        if signal['action'] in ['BUY', 'SELL'] and 'grid_levels' in signal:
                            grid_info = ", ".join([
                                f"${l.price:.0f}" for l in signal['grid_levels']
                            ])
                            logger.info(f"  └─ 网格层级: {grid_info}")
                    
                    # 执行交易
                    self.executor.execute_signal(signal)
                    
                    # 调试日志
                    if self.cycle_count % 100 == 0:
                        logger.debug(
                            f"[{symbol}] price={current_price} | "
                            f"signal={signal['action']} | "
                            f"confidence={signal['confidence']:.2f}"
                        )
                
                # 定期状态报告
                self._log_status_report()
                
                time.sleep(CONFIG["POLL_INTERVAL"])
                
            except Exception as e:
                logger.error(f"主循环异常: {e}", exc_info=True)
                time.sleep(5)


if __name__ == "__main__":
    if not API_KEY or not SECRET_KEY:
        logger.critical("❌ .env 文件中 API Key 未配置！")
        sys.exit(1)
    
    system = ProductionSystemV2_5()
    system.run()