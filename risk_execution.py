import logging
import time
import sqlite3
import math
from datetime import datetime
from config import CONFIG
from binance_api import BinanceExpertAPI
import requests  # 用于 Telegram 报警（比完整 bot 更轻量）

logger = logging.getLogger(__name__)

# ======================【增强型 SQLite 永久交易日志】======================
class TradeDB:
    def __init__(self):
        self.conn = sqlite3.connect('elite_trades.db', check_same_thread=False)
        self._init_tables()
        logger.info("✅ SQLite 交易数据库已就绪")
    
    def _init_tables(self):
        """初始化数据库表结构"""
        # 交易记录表
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                symbol TEXT,
                action TEXT,
                qty REAL,
                price REAL,
                pnl REAL,
                pnl_pct REAL,
                reason TEXT,
                order_id TEXT,
                confidence REAL,
                sl REAL,
                tp REAL,
                mode TEXT
            )
        ''')
        
        # 持仓记录表
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                symbol TEXT,
                side TEXT,
                qty REAL,
                entry_price REAL,
                current_price REAL,
                unrealized_pnl REAL,
                unrealized_pnl_pct REAL,
                leverage INTEGER
            )
        ''')
        
        # 余额记录表
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS balance_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                total_balance REAL,
                available_balance REAL,
                unrealized_pnl REAL,
                drawdown_pct REAL
            )
        ''')
        
        # 迁移：检查并添加缺失的列
        self._migrate_trades_table()
        
        # 信号记录表
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                symbol TEXT,
                action TEXT,
                confidence REAL,
                reason TEXT,
                price REAL,
                rsi REAL,
                macd REAL,
                executed BOOLEAN
            )
        ''')
        
        self.conn.commit()

    def _migrate_trades_table(self):
        """迁移 trades 表，添加缺失的列"""
        try:
            # 检查 trades 表是否存在
            cursor = self.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='trades'")
            if cursor.fetchone():
                # 获取现有列
                cursor = self.conn.execute("PRAGMA table_info(trades)")
                existing_columns = {row[1] for row in cursor.fetchall()}
                
                # 需要添加的列
                columns_to_add = {
                    'pnl_pct': 'REAL',
                    'order_id': 'TEXT',
                    'confidence': 'REAL',
                    'sl': 'REAL',
                    'tp': 'REAL',
                    'mode': 'TEXT'
                }
                
                for col_name, col_type in columns_to_add.items():
                    if col_name not in existing_columns:
                        self.conn.execute(f"ALTER TABLE trades ADD COLUMN {col_name} {col_type}")
                        logger.info(f"✅ 数据库迁移: 添加列 {col_name} 到 trades 表")
                
                self.conn.commit()
        except Exception as e:
            logger.warning(f"数据库迁移警告: {e}")

    def log_trade(self, symbol: str, action: str, qty: float, price: float, 
                  pnl: float = 0.0, pnl_pct: float = 0.0, reason: str = "", 
                  order_id: str = "", confidence: float = 0.0, sl: float = None, 
                  tp: float = None, mode: str = CONFIG["MODE"]):
        """记录交易"""
        self.conn.execute(
            """INSERT INTO trades 
                (timestamp, symbol, action, qty, price, pnl, pnl_pct, reason, order_id, confidence, sl, tp, mode) 
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (datetime.now().isoformat(), symbol, action, qty, price, pnl, pnl_pct, 
             reason, order_id, confidence, sl, tp, mode)
        )
        self.conn.commit()
        
        # 同时记录到logger
        trade_logger = logging.getLogger("trade")
        trade_logger.info(
            f"TRADE | {symbol} | {action} | qty={qty:.4f} | price=${price:.2f} | "
            f"pnl=${pnl:.2f} | reason={reason} | order_id={order_id}"
        )

    def log_position(self, symbol: str, side: str, qty: float, entry_price: float,
                     current_price: float, unrealized_pnl: float, unrealized_pnl_pct: float,
                     leverage: int = 5):
        """记录持仓状态"""
        self.conn.execute(
            """INSERT INTO positions 
                (timestamp, symbol, side, qty, entry_price, current_price, unrealized_pnl, unrealized_pnl_pct, leverage) 
                VALUES (?,?,?,?,?,?,?,?,?)""",
            (datetime.now().isoformat(), symbol, side, qty, entry_price, current_price,
             unrealized_pnl, unrealized_pnl_pct, leverage)
        )
        self.conn.commit()

    def log_balance(self, total_balance: float, available_balance: float, 
                    unrealized_pnl: float, drawdown_pct: float):
        """记录余额历史"""
        self.conn.execute(
            """INSERT INTO balance_history 
                (timestamp, total_balance, available_balance, unrealized_pnl, drawdown_pct) 
                VALUES (?,?,?,?,?)""",
            (datetime.now().isoformat(), total_balance, available_balance, 
             unrealized_pnl, drawdown_pct)
        )
        self.conn.commit()

    def log_signal(self, symbol: str, action: str, confidence: float, reason: str,
                   price: float, rsi: float = None, macd: float = None, executed: bool = False):
        """记录信号"""
        self.conn.execute(
            """INSERT INTO signals 
                (timestamp, symbol, action, confidence, reason, price, rsi, macd, executed) 
                VALUES (?,?,?,?,?,?,?,?,?)""",
            (datetime.now().isoformat(), symbol, action, confidence, reason, price, rsi, macd, executed)
        )
        self.conn.commit()

    def get_recent_trades(self, limit: int = 10):
        """获取最近的交易记录"""
        cursor = self.conn.execute(
            "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        )
        return cursor.fetchall()

    def get_today_pnl(self):
        """获取今日盈亏"""
        today = datetime.now().strftime('%Y-%m-%d')
        cursor = self.conn.execute(
            "SELECT SUM(pnl) FROM trades WHERE timestamp LIKE ?",
            (f"{today}%",)
        )
        result = cursor.fetchone()[0]
        return result if result else 0.0

    def get_trade_stats(self):
        """获取交易统计"""
        cursor = self.conn.execute("""
            SELECT 
                COUNT(*) as total_trades,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
                SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losing_trades,
                SUM(pnl) as total_pnl,
                AVG(pnl) as avg_pnl
            FROM trades
        """)
        return cursor.fetchone()

db = TradeDB()

# ======================【顶级风控引擎】======================
class EliteRiskManager:
    def __init__(self):
        self.max_risk_pct = CONFIG["MAX_RISK_PCT"]
        self.max_dd_limit = CONFIG["MAX_DD_LIMIT"]
        self.start_balance = None
        self.peak_balance = None
        self.today_trades = 0
        self.max_daily_trades = 999  # 每日最大交易次数（设为999，几乎无限制）

    def update_start_balance(self, balance: float):
        if self.start_balance is None:
            self.start_balance = balance
            self.peak_balance = balance
            logger.info(f"💰 初始余额: ${balance:.2f} USDT")
        
        # 更新峰值
        if balance > self.peak_balance:
            self.peak_balance = balance

    def calculate_position_size(self, balance: float, atr: float, price: float, confidence: float) -> float:
        """Kelly + ATR + 置信度 动态仓位（适配小资金）"""
        if price <= 0 or atr <= 0:
            return 0.0
        
        # 基础风险金额
        risk_amount = balance * self.max_risk_pct
        
        # 根据置信度调整仓位
        confidence_multiplier = min(confidence / 0.6, 2.0)  # 置信度越高，仓位越大
        
        # ATR止损距离
        stop_loss_pct = 2.0 * atr / price
        if stop_loss_pct < 0.01:  # 最小1%止损
            stop_loss_pct = 0.01
        
        # 计算数量
        qty = (risk_amount * confidence_multiplier) / (stop_loss_pct * price)
        
        # 限制最大仓位（使用90%资金，适应小资金）
        max_qty = balance * 0.9 / price
        
        final_qty = min(qty, max_qty)
        
        # 币安最小名义价值要求：20 USDT（加5%缓冲确保通过）
        min_notional = 21.0  # 提高到$21确保满足$20要求
        min_qty = min_notional / price
        min_qty = math.ceil(min_qty * 1000) / 1000  # 向上取整
        
        # 确保满足最小名义价值
        if final_qty < min_qty:
            logger.warning(f"仓位计算{final_qty:.4f}ETH(${final_qty*price:.2f})小于最小名义价值要求，调整为{min_qty:.4f}ETH")
            final_qty = min_qty
        
        # 向上取整到3位小数
        final_qty = math.ceil(final_qty * 1000) / 1000
        
        logger.info(
            f"Position sizing | balance=${balance:.2f} | atr={atr:.2f} | price=${price:.2f} | "
            f"confidence={confidence:.2f} | qty={final_qty}"
        )
        
        return final_qty

    def check_drawdown(self, current_balance: float) -> bool:
        """最大回撤熔断"""
        if self.start_balance is None or self.peak_balance is None:
            return False
        
        # 计算从峰值回撤
        dd_from_peak = (current_balance - self.peak_balance) / self.peak_balance
        
        # 计算从起始回撤
        dd_from_start = (current_balance - self.start_balance) / self.start_balance
        
        if dd_from_peak < -self.max_dd_limit:
            logger.critical(
                f"🚨 最大回撤触发！从峰值回撤: {dd_from_peak*100:.2f}% | "
                f"从起始回撤: {dd_from_start*100:.2f}%"
            )
            return True
        
        return False
    
    def check_daily_limit(self) -> bool:
        """检查每日交易次数限制"""
        if self.today_trades >= self.max_daily_trades:
            logger.warning(f"⚠️  今日交易次数已达上限: {self.max_daily_trades}")
            return True
        return False
    
    def increment_trade_count(self):
        """增加交易计数"""
        self.today_trades += 1

# ======================【执行引擎（生产核心）】======================
class ExecutionEngine:
    def __init__(self, api: BinanceExpertAPI):
        self.api = api
        self.risk = EliteRiskManager()
        self.positions = {}  # symbol -> 当前仓位信息
        self.telegram_enabled = bool(CONFIG.get("TELEGRAM_TOKEN") and CONFIG.get("TELEGRAM_CHAT_ID"))
        self.trade_history = []  # 最近交易历史

    def _send_telegram(self, message: str):
        if not self.telegram_enabled:
            return
        try:
            url = f"https://api.telegram.org/bot{CONFIG.get('TELEGRAM_TOKEN')}/sendMessage"
            requests.post(url, json={"chat_id": CONFIG.get("TELEGRAM_CHAT_ID"), "text": message, "parse_mode": "HTML"})
        except Exception as e:
            logger.error(f"Telegram 发送失败: {e}")

    def sync_position(self, symbol: str):
        """同步仓位并记录（考虑杠杆）"""
        pos = self.api.get_position(symbol)
        if pos:
            self.positions[symbol] = pos
            
            # 获取当前价格计算盈亏
            current_price = self.api.get_price(symbol)
            if current_price:
                entry = pos['entryPrice']
                qty = pos['qty']
                side = pos['side']
                leverage = CONFIG.get("LEVERAGE", 10)
                
                # 计算名义价值
                notional_value = qty * entry
                
                # 计算盈亏（考虑杠杆）
                if side == "LONG":
                    price_change_pct = (current_price - entry) / entry
                    unrealized_pnl = notional_value * price_change_pct  # 名义盈亏
                    unrealized_pnl_pct = price_change_pct * leverage * 100  # 杠杆后收益率
                else:
                    price_change_pct = (entry - current_price) / entry
                    unrealized_pnl = notional_value * price_change_pct
                    unrealized_pnl_pct = price_change_pct * leverage * 100
                
                # 记录到数据库
                db.log_position(symbol, side, qty, entry, current_price, 
                               unrealized_pnl, unrealized_pnl_pct, leverage)
                
                logger.info(
                    f"[{symbol}] Position | {side} {qty} @ ${entry:.2f} | "
                    f"Current: ${current_price:.2f} | PnL: ${unrealized_pnl:.2f} ({unrealized_pnl_pct:+.2f}%) | "
                    f"Leverage: {leverage}x"
                )
        else:
            if symbol in self.positions and self.positions[symbol]:
                logger.info(f"[{symbol}] 仓位已平仓")
            self.positions[symbol] = None

    def execute_signal(self, signal: dict):
        """执行交易信号"""
        symbol = signal['symbol']
        action = signal['action']
        confidence = signal.get('confidence', 0)
        
        # 获取当前价格用于日志
        current_price = self.api.get_price(symbol)
        
        # 记录所有信号（包括HOLD）到日志
        if action != 'HOLD':
            logger.info(
                f"[{symbol}] SIGNAL | {action} | Confidence:{confidence:.2f} | "
                f"Reason:{signal.get('reason', 'N/A')} | Price:${(current_price if current_price else 0):.2f}"
            )
        
        # 处理CLOSE信号（止盈止损）
        if action == 'CLOSE':
            self._execute_close(symbol, signal, current_price)
            return
        
        # 检查置信度阈值（对于OPEN信号）
        if action not in ['HOLD', 'CLOSE'] and confidence < CONFIG["CONFIDENCE_THRESHOLD"]:
            logger.info(f"[{symbol}] Signal confidence {confidence:.2f} below threshold {CONFIG['CONFIDENCE_THRESHOLD']}, ignored")
            return
        
        if action == 'HOLD':
            return
        
        # 获取账户信息
        balance = self.api.get_balance()
        self.risk.update_start_balance(balance)
        current_price = self.api.get_price(symbol) or signal.get('price', 0)
        
        # 记录信号到数据库
        db.log_signal(
            symbol, action, signal['confidence'], signal['reason'],
            current_price, signal.get('rsi'), signal.get('macd'), executed=False
        )
        
        # 风控检查1: 最大回撤
        if self.risk.check_drawdown(balance):
            self._emergency_close_all()
            return
        
        # 风控检查2: 每日交易次数
        if self.risk.check_daily_limit():
            return
        
        # 同步当前仓位
        self.sync_position(symbol)
        current_pos = self.positions.get(symbol)
        
        # 平反向仓
        if current_pos and ((action == 'BUY' and current_pos['side'] == 'SHORT') or 
                           (action == 'SELL' and current_pos['side'] == 'LONG')):
            side = 'SELL' if current_pos['side'] == 'LONG' else 'BUY'
            
            # 计算平仓盈亏
            entry = current_pos['entryPrice']
            qty = current_pos['qty']
            if current_pos['side'] == "LONG":
                pnl = (current_price - entry) * qty
                pnl_pct = (current_price - entry) / entry * 100
            else:
                pnl = (entry - current_price) * qty
                pnl_pct = (entry - current_price) / entry * 100
            
            order = self.api.place_order(symbol, side, current_pos['qty'], reduce_only=True)
            order_id = order.get('orderId', 'paper') if order else 'failed'
            
            db.log_trade(symbol, f"CLOSE_{side}", current_pos['qty'], current_price, 
                        pnl, pnl_pct, "平反向仓", order_id, signal['confidence'])
            
            msg = f"🔄 <b>平反向仓</b>\n{symbol} {side} {current_pos['qty']}\n盈亏: ${pnl:.2f} ({pnl_pct:+.2f}%)"
            logger.info(msg)
            self._send_telegram(msg)
            self.positions[symbol] = None
            self.risk.increment_trade_count()
        
        # 开新仓（仅当无仓位时）
        if not current_pos or abs(current_pos.get('qty', 0)) < 0.0001:
            # 从signal中获取ATR
            atr = signal.get('atr', 0.022 * current_price)  # 默认2.2%波动
            qty = self.risk.calculate_position_size(balance, atr, current_price, signal['confidence'])
            
            logger.info(f"[{symbol}] Position size calculated: {qty} (balance=${balance:.2f}, atr={atr:.2f})")
            
            if qty >= 0.001:
                side = action
                order = self.api.place_order(symbol, side, qty)
                order_id = order.get('orderId', 'paper') if order else 'failed'
                
                # 记录交易（只有成功下单才记录）
                if order and order.get('orderId') and order.get('orderId') != 'failed':
                    db.log_trade(
                        symbol, side, qty, current_price, 
                        pnl=0.0, pnl_pct=0.0, reason=signal['reason'], 
                        order_id=order_id, confidence=signal['confidence'],
                        sl=signal.get('sl'), tp=signal.get('tp')
                    )
                    logger.info(f"[{symbol}] 交易已记录到数据库: {order_id}")
                else:
                    logger.warning(f"[{symbol}] 下单失败，不记录到数据库")
                    return  # 下单失败，直接返回不执行后续操作
                
                # 更新信号为已执行
                db.conn.execute(
                    "UPDATE signals SET executed = 1 WHERE timestamp = (SELECT MAX(timestamp) FROM signals WHERE symbol = ?)",
                    (symbol,)
                )
                db.conn.commit()
                
                msg = (
                    f"✅ <b>{CONFIG['MODE']} 下单成功</b>\n"
                    f"{symbol} {side} {qty}\n"
                    f"价格: ${current_price:.2f}\n"
                    f"止损: ${signal.get('sl', 'N/A')}\n"
                    f"止盈: ${signal.get('tp', 'N/A')}\n"
                    f"理由: {signal['reason']}\n"
                    f"置信度: {signal['confidence']:.2f}"
                )
                logger.info(msg)
                self._send_telegram(msg)
                
                self.risk.increment_trade_count()
                self.sync_position(symbol)
            else:
                logger.warning(f"[{symbol}] 计算仓位为0，跳过下单")

    def _execute_close(self, symbol: str, signal: dict, current_price: float):
        """执行平仓（止盈止损，考虑杠杆）"""
        current_pos = self.positions.get(symbol)
        if not current_pos:
            logger.warning(f"[{symbol}] Close signal but no position")
            return
        
        side = 'SELL' if current_pos['side'] == 'LONG' else 'BUY'
        qty = current_pos['qty']
        leverage = CONFIG.get("LEVERAGE", 10)
        
        # 计算盈亏（考虑杠杆）
        entry = current_pos['entryPrice']
        notional_value = qty * entry
        
        if current_pos['side'] == "LONG":
            price_change_pct = (current_price - entry) / entry
            pnl = notional_value * price_change_pct  # 名义盈亏
            pnl_pct = price_change_pct * leverage * 100  # 杠杆后收益率
        else:
            price_change_pct = (entry - current_price) / entry
            pnl = notional_value * price_change_pct
            pnl_pct = price_change_pct * leverage * 100
        
        logger.info(f"[{symbol}] EXECUTING CLOSE | {side} {qty} | PnL: ${pnl:.2f} ({pnl_pct:.2f}%) | Leverage: {leverage}x")
        
        # 执行平仓
        order = self.api.place_order(symbol, side, qty, reduce_only=True)
        order_id = order.get('orderId', 'paper') if order else 'failed'
        
        # 记录到数据库
        db.log_trade(
            symbol, f"CLOSE_{side}", qty, current_price, 
            pnl, pnl_pct, signal['reason'], order_id, 
            confidence=1.0
        )
        
        # 发送通知
        msg = f"🔒 <b>Position Closed</b>\n{symbol} {side} {qty}\nPnL: ${pnl:.2f} ({pnl_pct:+.2f}%)\nReason: {signal['reason']}"
        logger.info(msg)
        self._send_telegram(msg)
        
        # 更新持仓
        self.positions[symbol] = None
        self.risk.increment_trade_count()
        
        if not order or order.get('orderId') == 'failed':
            logger.error(f"[{symbol}] 平仓 API 调用失败，强制本地清除持仓记录")
            self.positions[symbol] = None   # ← 新增这行

    def _emergency_close_all(self):
        """紧急全部平仓"""
        logger.critical("🔥 触发紧急平仓！")
        
        for symbol in list(self.positions.keys()):
            pos = self.positions.get(symbol)
            if pos and pos.get('qty', 0) > 0.001:
                side = 'SELL' if pos['side'] == 'LONG' else 'BUY'
                current_price = self.api.get_price(symbol) or 0
                
                order = self.api.place_order(symbol, side, pos['qty'], reduce_only=True)
                order_id = order.get('orderId', 'paper') if order else 'failed'
                
                # 计算盈亏
                entry = pos['entryPrice']
                qty = pos['qty']
                if pos['side'] == "LONG":
                    pnl = (current_price - entry) * qty
                else:
                    pnl = (entry - current_price) * qty
                
                db.log_trade(symbol, f"EMERGENCY_CLOSE_{side}", pos['qty'], current_price, 
                            pnl, 0, "最大回撤熔断", order_id)
                
                msg = f"🚨 <b>紧急平仓</b>\n{symbol} {side} {pos['qty']}\n盈亏: ${pnl:.2f}"
                logger.critical(msg)
                self._send_telegram(msg)
        
        logger.critical("🔥 所有仓位已紧急平仓！系统暂停")

# ======================【Prometheus 监控指标（可选接入 Grafana）】======================
try:
    from prometheus_client import Gauge, start_http_server, Counter
    
    BALANCE_GAUGE = Gauge('trading_balance_usdt', '当前 USDT 余额')
    DD_GAUGE = Gauge('trading_drawdown_pct', '当前回撤百分比')
    TRADES_TOTAL = Counter('trading_total_trades', '总交易次数')
    PNL_GAUGE = Gauge('trading_daily_pnl', '今日盈亏')
    POSITION_GAUGE = Gauge('trading_position_size', '当前持仓数量', ['symbol', 'side'])
    
    prometheus_started = False
except ImportError:
    prometheus_started = False
    logger.warning("Prometheus 客户端未安装，监控功能禁用")

def start_prometheus():
    global prometheus_started
    if not prometheus_started:
        try:
            start_http_server(9091)  # 访问 http://localhost:9091
            logger.info("📊 Prometheus 监控已启动 (端口 9091)")
            prometheus_started = True
        except Exception as e:
            logger.error(f"Prometheus 启动失败: {e}")
