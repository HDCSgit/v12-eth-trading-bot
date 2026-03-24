import logging
import time
import sys
import signal
import os
from datetime import datetime
from config import CONFIG, API_KEY, SECRET_KEY   # ← 关键修复
from binance_api import BinanceExpertAPI
from strategy import ExpertStrategy
from risk_execution import ExecutionEngine, start_prometheus, db
# ======================【全局日志配置（生产级）】======================
def setup_logging():
    """设置详细的日志系统"""
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    
    # 主日志文件
    main_handler = logging.FileHandler(
        f'{log_dir}/elite_production_{datetime.now():%Y%m%d}.log', 
        encoding='utf-8'
    )
    main_handler.setLevel(logging.INFO)
    
    # 错误日志单独记录
    error_handler = logging.FileHandler(
        f'{log_dir}/elite_errors_{datetime.now():%Y%m%d}.log',
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    
    # 交易日志单独记录
    trade_handler = logging.FileHandler(
        f'{log_dir}/elite_trades_{datetime.now():%Y%m%d}.log',
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
    return trade_logger

trade_logger = setup_logging()
logger = logging.getLogger(__name__)

# ======================【主生产系统】======================
class ProductionSystem:
    def __init__(self):
        self.api = BinanceExpertAPI()
        self.strategy = ExpertStrategy()
        self.executor = ExecutionEngine(self.api)
        self.running = True
        self.cycle_count = 0
        self.last_status_time = time.time()
        
        # 优雅退出处理
        signal.signal(signal.SIGINT, self._graceful_shutdown)
        signal.signal(signal.SIGTERM, self._graceful_shutdown)
        
        logger.info("=" * 70)
        logger.info("🏆 完整生产级专家量化系统已启动")
        logger.info(f"模式: {CONFIG['MODE']} | 交易对: {CONFIG['SYMBOLS']}")
        logger.info(f"杠杆: {CONFIG['LEVERAGE']}x | 最大风险: {CONFIG['MAX_RISK_PCT']*100}%")
        logger.info("=" * 70)
        
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
        # 最后一次同步并记录
        for symbol in CONFIG["SYMBOLS"]:
            self.executor.sync_position(symbol)
        db.conn.close()
        logger.info("✅ 所有日志已持久化，系统安全退出")
        sys.exit(0)

    def _log_status_report(self):
        """定期输出状态报告"""
        if time.time() - self.last_status_time < 300:  # 每5分钟
            return
        
        self.last_status_time = time.time()
        
        logger.info("=" * 70)
        logger.info("📊 系统状态报告")
        logger.info("=" * 70)
        
        balance = self.api.get_balance()
        logger.info(f"💰 当前余额: ${balance:.2f} USDT")
        
        for symbol in CONFIG["SYMBOLS"]:
            pos = self.executor.positions.get(symbol)
            price = self.api.price_cache.get(symbol, "N/A")
            
            if pos:
                entry = pos['entryPrice']
                qty = pos['qty']
                side = pos['side']
                leverage = CONFIG.get("LEVERAGE", 10)
                if price != "N/A":
                    # 计算杠杆后的盈亏
                    if side == "LONG":
                        price_change_pct = (price - entry) / entry
                    else:
                        price_change_pct = (entry - price) / entry
                    
                    leveraged_pnl_pct = price_change_pct * leverage * 100
                    notional_value = qty * entry
                    pnl_amount = notional_value * price_change_pct
                    
                    logger.info(f"📍 {symbol}: {side} {qty} @ ${entry:.2f} | 现价: ${price:.2f} | "
                               f"盈亏: ${pnl_amount:.2f} ({leveraged_pnl_pct:+.2f}%) | 杠杆: {leverage}x")
                else:
                    logger.info(f"📍 {symbol}: {side} {qty} @ ${entry:.2f} | 现价: N/A")
            else:
                logger.info(f"📍 {symbol}: 无持仓 | 现价: ${price if price != 'N/A' else 'N/A'}")
        
        logger.info("=" * 70)

    def run(self):
        start_prometheus()  # 启动监控指标（http://localhost:9091）
        
        logger.info(f"🚀 开始监控 {len(CONFIG['SYMBOLS'])} 个交易对: {CONFIG['SYMBOLS']}")
        logger.info(f"⏱️  轮询间隔: {CONFIG['POLL_INTERVAL']}秒")
        
        while self.running:
            try:
                self.cycle_count += 1
                
                for symbol in CONFIG["SYMBOLS"]:
                    # 获取最新 K 线
                    df = self.api.get_klines(symbol, limit=800)
                    if df is None or len(df) < 200:
                        logger.warning(f"[{symbol}] 数据不足，跳过")
                        continue
                    
                    # 计算特征
                    df = self.strategy.compute_features(df, symbol)
                    if df is None or len(df) < 2:
                        logger.warning(f"[{symbol}] 特征计算后数据不足，跳过")
                        continue
                    
                    # 获取当前持仓和价格
                    current_pos = self.executor.positions.get(symbol)
                    current_price = self.api.get_price(symbol)
                    
                    # 生成信号（传入持仓信息用于止盈止损检查）
                    signal = self.strategy.generate_signal(symbol, df, current_pos, current_price)
                    
                    # 记录详细信号信息
                    if signal['action'] != 'HOLD':
                        trade_logger.info(
                            f"SIGNAL | {symbol} | {signal['action']} | "
                            f"confidence={signal['confidence']:.2f} | "
                            f"reason={signal['reason']} | "
                            f"sl={signal.get('sl', 'N/A')} | tp={signal.get('tp', 'N/A')}"
                        )
                    
                    # 执行交易（含风控、日志、Telegram、Prometheus）
                    self.executor.execute_signal(signal)
                    
                    # 实时价格缓存日志（调试用）
                    price = self.api.price_cache.get(symbol, "N/A")
                    if self.cycle_count % 100 == 0:  # 每100个周期记录一次
                        logger.debug(
                            f"[{symbol}] price={price} | signal={signal['action']} | "
                            f"confidence={signal['confidence']:.2f}"
                        )
                
                # 定期状态报告
                self._log_status_report()
                
                # 每 0.8 秒轮询一次（配合 WebSocket 实时性）
                time.sleep(CONFIG["POLL_INTERVAL"])
                
            except Exception as e:
                logger.error(f"主循环异常: {e}", exc_info=True)
                time.sleep(5)  # 防止狂刷日志

if __name__ == "__main__":
    if not API_KEY or not SECRET_KEY:          # ← 修复后的检查
        logger.critical("❌ .env 文件中 BINANCE_API_KEY 或 SECRET_KEY 为空！")
        logger.critical("当前 .env 路径: " + os.path.abspath('.env'))
        sys.exit(1)
    
    system = ProductionSystem()
    system.run()