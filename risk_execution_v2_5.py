import logging
import time
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional
from config import CONFIG
from binance_api import BinanceExpertAPI
from strategy_v2_5_hybrid import ExpertStrategyV2_5_Hybrid, PositionGroup, GridLevel

logger = logging.getLogger(__name__)


class ExecutionEngineV2_5:
    """
    V2.5-Hybrid 专用执行引擎
    支持：网格交易、斐波那契补仓、三层止盈
    """
    
    def __init__(self, api: BinanceExpertAPI, strategy: ExpertStrategyV2_5_Hybrid):
        self.api = api
        self.strategy = strategy
        self.positions = {}  # symbol -> 当前持仓信息
        self.db = TradeDBV2_5()
        
        logger.info("✅ V2.5-Hybrid 执行引擎初始化完成")
    
    def sync_position(self, symbol: str):
        """同步币安仓位到本地"""
        pos = self.api.get_position(symbol)
        if pos:
            self.positions[symbol] = pos
            
            # 如果策略中没有这个仓位组，创建一个
            if symbol not in self.strategy.position_groups:
                pg = PositionGroup(
                    symbol=symbol,
                    side=pos['side'],
                    entry_price=pos['entryPrice'],
                    total_qty=pos['qty'],
                    entry_time=time.time()
                )
                self.strategy.position_groups[symbol] = pg
        else:
            self.positions[symbol] = None
    
    def execute_signal(self, signal: Dict):
        """执行交易信号"""
        symbol = signal['symbol']
        action = signal['action']
        
        if action == 'HOLD':
            return
        
        # 处理新开仓
        if action in ['BUY', 'SELL']:
            self._open_position(symbol, signal)
        
        # 处理补仓
        elif action == 'DCA':
            self._execute_dca(symbol, signal)
        
        # 处理平仓
        elif action in ['CLOSE_ALL', 'STOP_LOSS']:
            self._close_all(symbol, signal)
        
        elif action == 'CLOSE_GRID':
            self._close_grid_level(symbol, signal)
    
    def _open_position(self, symbol: str, signal: Dict):
        """开新仓（带网格初始化）"""
        # 获取账户信息
        balance = self.api.get_balance()
        
        # 计算仓位大小（单笔风险0.8%）
        risk_amount = balance * CONFIG.get("MAX_RISK_PCT", 0.008)
        entry_price = self.api.get_price(symbol) or signal.get('atr', 0) * 50
        
        if entry_price <= 0:
            logger.error(f"[{symbol}] 无法获取有效价格")
            return
        
        # ATR动态止损距离
        atr = signal.get('atr', entry_price * 0.02)
        stop_distance = atr * 2.0  # 2倍ATR
        
        qty = risk_amount / stop_distance
        max_qty = balance * 0.3 / entry_price  # 最大30%资金
        qty = min(qty, max_qty)
        
        if qty < 0.001:
            logger.warning(f"[{symbol}] 计算仓位太小: {qty}")
            return
        
        side = signal['action']
        
        # 下单
        order = self.api.place_order(symbol, side, qty)
        
        if order and order.get('orderId'):
            order_id = order.get('orderId')
            
            # 创建仓位组
            pg = PositionGroup(
                symbol=symbol,
                side='LONG' if side == 'BUY' else 'SHORT',
                entry_price=entry_price,
                total_qty=qty,
                entry_time=time.time()
            )
            
            # 初始化网格
            grid_levels = self.strategy.create_grid_levels(entry_price, pg.side, atr, qty)
            pg.grid_levels = grid_levels
            
            # 记录首单
            pg.dca_levels.append({
                'price': entry_price,
                'qty': qty,
                'order_id': order_id,
                'timestamp': datetime.now().isoformat(),
                'dca_index': 0
            })
            
            self.strategy.position_groups[symbol] = pg
            
            # 记录到数据库
            self.db.log_trade(
                symbol=symbol,
                action=side,
                qty=qty,
                price=entry_price,
                reason=signal['reason'],
                order_id=order_id,
                confidence=signal['confidence'],
                sl=signal.get('sl'),
                tp=signal.get('tp'),
                trade_type='OPEN'
            )
            
            # 记录网格层级
            for i, level in enumerate(grid_levels):
                self.db.log_grid_level(
                    symbol=symbol,
                    level_index=i,
                    target_price=level.price,
                    qty=level.qty,
                    side=level.side
                )
            
            logger.info(
                f"✅ [{symbol}] 开仓成功 | {side} {qty:.4f} @ ${entry_price:.2f} | "
                f"网格层级: {len(grid_levels)} | 订单ID: {order_id}"
            )
    
    def _execute_dca(self, symbol: str, signal: Dict):
        """执行斐波那契补仓"""
        if symbol not in self.strategy.position_groups:
            logger.warning(f"[{symbol}] 无持仓组，无法补仓")
            return
        
        pg = self.strategy.position_groups[symbol]
        
        # 计算补仓数量（斐波那契递增）
        dca_index = signal['dca_index'] - 1  # 转换为0-based
        fib_multiplier = signal.get('fib_multiplier', 1.618)
        
        # 基础补仓量 = 首单 × 斐波那契系数
        base_qty = pg.dca_levels[0]['qty'] if pg.dca_levels else 0.01
        dca_qty = base_qty * fib_multiplier
        
        # 检查最大补仓次数
        if len(pg.dca_levels) >= 3:
            logger.warning(f"[{symbol}] 已达最大补仓次数")
            return
        
        # 下单
        side = 'BUY' if pg.side == 'LONG' else 'SELL'
        order = self.api.place_order(symbol, side, dca_qty)
        
        if order and order.get('orderId'):
            current_price = self.api.get_price(symbol) or signal.get('trigger_price', 0)
            
            # 记录补仓
            pg.dca_levels.append({
                'price': current_price,
                'qty': dca_qty,
                'order_id': order.get('orderId'),
                'timestamp': datetime.now().isoformat(),
                'dca_index': dca_index,
                'fib_multiplier': fib_multiplier
            })
            
            pg.total_qty += dca_qty
            
            # 更新数据库
            self.db.log_trade(
                symbol=symbol,
                action=f"DCA_{side}",
                qty=dca_qty,
                price=current_price,
                reason=f"Fib DCA #{dca_index+1} x{fib_multiplier:.2f}",
                order_id=order.get('orderId'),
                trade_type='DCA'
            )
            
            logger.info(
                f"🔄 [{symbol}] 补仓成功 | #{dca_index+1} {dca_qty:.4f} @ ${current_price:.2f} | "
                f"Fib: {fib_multiplier:.2f} | 总持仓: {pg.total_qty:.4f}"
            )
    
    def _close_grid_level(self, symbol: str, signal: Dict):
        """平网格层级（尾单止盈）"""
        grid_level = signal.get('grid_level')
        if not grid_level:
            return
        
        pg = self.strategy.position_groups.get(symbol)
        if not pg:
            return
        
        # 平部分仓位
        close_qty = min(grid_level.qty, pg.total_qty * 0.5)  # 最多平50%
        
        side = 'SELL' if pg.side == 'LONG' else 'BUY'
        order = self.api.place_order(symbol, side, close_qty, reduce_only=True)
        
        if order and order.get('orderId'):
            grid_level.filled = True
            grid_level.order_id = order.get('orderId')
            
            # 计算盈亏
            pnl = self._calculate_grid_pnl(pg, grid_level)
            
            self.db.log_trade(
                symbol=symbol,
                action=f"GRID_CLOSE_{side}",
                qty=close_qty,
                price=self.api.get_price(symbol),
                pnl=pnl,
                reason=signal['reason'],
                order_id=order.get('orderId'),
                trade_type='GRID_TP'
            )
            
            logger.info(
                f"🎯 [{symbol}] 网格止盈 | Level ${grid_level.price:.2f} | "
                f"Qty: {close_qty:.4f} | PnL: ${pnl:.2f}"
            )
    
    def _close_all(self, symbol: str, signal: Dict):
        """全平（整组止盈/止损/追踪止盈）"""
        pg = self.strategy.position_groups.get(symbol)
        if not pg or not pg.is_active:
            return
        
        pos = self.positions.get(symbol)
        if not pos or pos.get('qty', 0) < 0.001:
            logger.warning(f"[{symbol}] 无持仓可平")
            return
        
        side = 'SELL' if pos['side'] == 'LONG' else 'BUY'
        qty = pos['qty']
        
        order = self.api.place_order(symbol, side, qty, reduce_only=True)
        
        if order and order.get('orderId'):
            # 计算总盈亏
            entry = pg.get_average_price()
            current_price = self.api.get_price(symbol) or entry
            
            if pg.side == "LONG":
                pnl_amount = (current_price - entry) * qty
                pnl_pct = (current_price - entry) / entry * 100 * CONFIG.get("LEVERAGE", 5)
            else:
                pnl_amount = (entry - current_price) * qty
                pnl_pct = (entry - current_price) / entry * 100 * CONFIG.get("LEVERAGE", 5)
            
            # 标记仓位组为不活跃
            pg.is_active = False
            
            # 如果是止损，增加连续止损计数
            if signal['action'] == 'STOP_LOSS':
                self.strategy.consecutive_losses += 1
            
            # 记录交易
            self.db.log_trade(
                symbol=symbol,
                action=f"CLOSE_ALL_{side}",
                qty=qty,
                price=current_price,
                pnl=pnl_amount,
                pnl_pct=pnl_pct,
                reason=signal['reason'],
                order_id=order.get('orderId'),
                trade_type='EXIT'
            )
            
            logger.info(
                f"🔒 [{symbol}] 全平成功 | {signal['reason']} | "
                f"Qty: {qty:.4f} | PnL: ${pnl_amount:.2f} ({pnl_pct:+.2f}%)"
            )
    
    def _calculate_grid_pnl(self, pg: PositionGroup, level: GridLevel) -> float:
        """计算网格层级盈亏"""
        if not pg.dca_levels:
            return 0.0
        
        avg_price = pg.get_average_price()
        qty = level.qty
        
        if pg.side == 'LONG':
            return (level.price - avg_price) * qty
        else:
            return (avg_price - level.price) * qty


class TradeDBV2_5:
    """V2.5专用数据库"""
    
    def __init__(self):
        self.conn = sqlite3.connect('elite_trades_v2_5.db', check_same_thread=False)
        self._init_tables()
        logger.info("✅ V2.5 数据库已就绪")
    
    def _init_tables(self):
        """初始化表结构"""
        # 交易记录表（增强版）
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
                trade_type TEXT,  -- OPEN/DCA/GRID_TP/EXIT
                dca_index INTEGER,
                fib_multiplier REAL
            )
        ''')
        
        # 网格层级表
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS grid_levels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                symbol TEXT,
                level_index INTEGER,
                target_price REAL,
                qty REAL,
                side TEXT,
                filled BOOLEAN DEFAULT 0,
                filled_time TEXT,
                pnl REAL
            )
        ''')
        
        # 仓位组表
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS position_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                side TEXT,
                entry_price REAL,
                total_qty REAL,
                dca_count INTEGER,
                avg_price REAL,
                max_profit REAL,
                is_active BOOLEAN,
                closed_time TEXT
            )
        ''')
        
        self.conn.commit()
    
    def log_trade(self, **kwargs):
        """记录交易"""
        fields = ['timestamp', 'symbol', 'action', 'qty', 'price', 'pnl', 'pnl_pct', 
                  'reason', 'order_id', 'confidence', 'sl', 'tp', 'trade_type', 
                  'dca_index', 'fib_multiplier']
        
        values = [datetime.now().isoformat()]
        for field in fields[1:]:
            values.append(kwargs.get(field))
        
        placeholders = ','.join(['?' for _ in fields])
        self.conn.execute(
            f"INSERT INTO trades ({','.join(fields)}) VALUES ({placeholders})",
            values
        )
        self.conn.commit()
    
    def log_grid_level(self, symbol: str, level_index: int, target_price: float,
                       qty: float, side: str):
        """记录网格层级"""
        self.conn.execute(
            """INSERT INTO grid_levels 
               (timestamp, symbol, level_index, target_price, qty, side)
               VALUES (?,?,?,?,?,?)""",
            (datetime.now().isoformat(), symbol, level_index, target_price, qty, side)
        )
        self.conn.commit()