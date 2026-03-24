import pandas as pd
import numpy as np
from config import CONFIG
import logging
import time
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class GridLevel:
    """网格层级数据类"""
    price: float
    side: str  # 'LONG' or 'SHORT'
    qty: float
    filled: bool = False
    order_id: str = ""
    pnl: float = 0.0


@dataclass
class PositionGroup:
    """仓位组（用于网格+补仓管理）"""
    symbol: str
    side: str
    entry_price: float
    total_qty: float = 0.0
    grid_levels: List[GridLevel] = field(default_factory=list)
    dca_levels: List[Dict] = field(default_factory=list)  # 补仓记录
    max_profit: float = 0.0
    entry_time: float = 0.0
    is_active: bool = True
    
    def get_average_price(self) -> float:
        """计算加权平均成本"""
        if not self.dca_levels:
            return self.entry_price
        
        total_cost = sum(level['price'] * level['qty'] for level in self.dca_levels)
        total_qty = sum(level['qty'] for level in self.dca_levels)
        return total_cost / total_qty if total_qty > 0 else self.entry_price
    
    def get_total_pnl_pct(self, current_price: float, leverage: int = 5) -> float:
        """计算整体盈亏百分比（杠杆后）"""
        avg_price = self.get_average_price()
        if self.side == 'LONG':
            price_change = (current_price - avg_price) / avg_price
        else:
            price_change = (avg_price - current_price) / avg_price
        return price_change * leverage * 100


class ExpertStrategyV2_5_Hybrid:
    """
    V2.5-Hybrid 混合策略
    结合V2双信号 + 轻量网格 + 斐波那契补仓 + 三层智能止盈
    """
    
    def __init__(self):
        # 基础参数
        self.rsi_period = 14
        self.atr_period = 14
        self.bb_period = 20
        
        # 连续止损计数器
        self.consecutive_losses = 0
        self.max_consecutive_losses = 2
        self.daily_stop_loss_triggered = False
        
        # 交易记录
        self.last_trade_side = None
        self.last_trade_time = 0
        self.min_trade_interval = 240  # 4分钟（轻度激进调整）
        
        # 仓位组管理 {symbol: PositionGroup}
        self.position_groups = {}
        
        # 风控参数
        self.max_dca_count = 3  # 最大补仓次数
        self.dca_fib_sequence = [1.0, 1.618, 2.618]  # 斐波那契数列
        self.dca_accelerator = 1.2  # 第3次补仓加速系数
        
        # 止盈参数
        self.grid_profit_target = 0.008  # 单格止盈0.8%
        self.trailing_start = 0.06  # 追踪止盈启动
        self.trailing_stop = 0.03  # 追踪止盈回撤
        self.group_take_profit = 0.08  # 整组止盈8%
        
        # 网格参数
        self.grid_atr_multiplier = 1.4  # 网格间距ATR×1.4（轻度激进）
        self.grid_atr_dynamic = True    # 启用动态ATR倍数
        self.funding_rate_threshold = 0.00015  # Funding Rate过滤阈值 0.015%
        
        logger.info("✅ V2.5-Hybrid 策略初始化完成")
        
    def reset_daily_stats(self):
        """每日重置统计"""
        self.consecutive_losses = 0
        self.daily_stop_loss_triggered = False
        # 清空已平仓的仓位组
        self.position_groups = {k: v for k, v in self.position_groups.items() if v.is_active}
        
    def compute_features(self, df: pd.DataFrame, symbol: str, 
                        btc_df: pd.DataFrame = None) -> pd.DataFrame:
        """增强版特征工程"""
        df = df.copy()
        
        if len(df) < 50:
            return df
        
        # 原有特征计算（V2完整保留）
        df['ma20'] = df['close'].rolling(20, min_periods=1).mean()
        df['ma55'] = df['close'].rolling(55, min_periods=1).mean()
        df['ma200'] = df['close'].rolling(200, min_periods=1).mean()
        df['trend'] = np.where(df['ma55'] > df['ma200'], 1, -1)
        df['trend_short'] = np.where(df['ma20'] > df['ma55'], 1, -1)
        
        # RSI
        delta = df['close'].diff()
        gain = delta.clip(lower=0).rolling(self.rsi_period, min_periods=1).mean()
        loss = (-delta.clip(upper=0)).rolling(self.rsi_period, min_periods=1).mean()
        rs = gain / (loss + 1e-10)
        df['rsi'] = 100 - 100 / (1 + rs)
        
        # ATR（关键指标）
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['atr'] = tr.rolling(self.atr_period, min_periods=1).mean()
        df['atr_pct'] = df['atr'] / df['close'] * 100
        
        # 布林带
        df['bb_mid'] = df['close'].rolling(self.bb_period, min_periods=1).mean()
        df['bb_std'] = df['close'].rolling(self.bb_period, min_periods=1).std()
        df['bb_upper'] = df['bb_mid'] + 2 * df['bb_std']
        df['bb_lower'] = df['bb_mid'] - 2 * df['bb_std']
        df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_mid']
        df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'] + 1e-10)
        
        # MACD
        ema12 = df['close'].ewm(span=12, adjust=False, min_periods=1).mean()
        ema26 = df['close'].ewm(span=26, adjust=False, min_periods=1).mean()
        df['macd'] = ema12 - ema26
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False, min_periods=1).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']
        df['macd_expanding'] = df['macd_hist'] > df['macd_hist'].shift(1)
        
        # 量能
        df['volume_ma'] = df['volume'].rolling(30, min_periods=1).mean()
        df['volume_spike'] = df['volume'] > df['volume_ma'] * 1.5
        df['volume_ratio'] = df['volume'] / (df['volume_ma'] + 1e-10)
        
        # 价格变化
        df['price_change_1m'] = df['close'].pct_change(1) * 100
        df['price_change_5m'] = df['close'].pct_change(5) * 100
        df['price_change_15m'] = df['close'].pct_change(15) * 100
        
        return df

    def count_active_signals(self, row, prev) -> Tuple[int, int, List[str]]:
        """
        V2双信号统计（完整保留）
        返回: (多头信号数, 空头信号数, 信号详情列表)
        """
        long_signals = []
        short_signals = []
        
        close = row['close']
        trend = row['trend']
        trend_short = row.get('trend_short', trend)
        rsi = row['rsi']
        macd = row['macd']
        macd_signal = row['macd_signal']
        macd_hist = row.get('macd_hist', macd - macd_signal)
        macd_expanding = row.get('macd_expanding', False)
        
        # MACD交叉检测
        macd_cross_up = (macd > macd_signal) and (prev.get('macd', macd) <= prev.get('macd_signal', macd_signal))
        macd_cross_down = (macd < macd_signal) and (prev.get('macd', macd) >= prev.get('macd_signal', macd_signal))
        
        volume_spike = row.get('volume_spike', False)
        volume_ratio = row.get('volume_ratio', 1.0)
        bb_width = row.get('bb_width', 0.05)
        bb_position = row.get('bb_position', 0.5)
        price_change_5m = row.get('price_change_5m', 0)
        
        # ========== 多头信号 ==========
        if (trend == 1 and rsi < 45 and macd_cross_up and volume_spike and bb_width < 0.05):
            long_signals.append('Perfect Long (90%)')
        if (trend == 1 and rsi < 40 and macd > macd_signal and price_change_5m > -2):
            long_signals.append('Trend Follow Long (75%)')
        if (macd_cross_up and volume_ratio > 1.2 and rsi < 60 and trend_short == 1):
            long_signals.append('MACD Cross Long (70%)')
        if (bb_position < 0.15 and rsi < 50 and macd_hist > 0 and trend >= 0):
            long_signals.append('BB Bounce Long (65%)')
        if (rsi < 35 and (macd_hist > 0 or macd_expanding) and price_change_5m < -1.5):
            long_signals.append('Oversold Bounce (60%)')
        if (rsi < 40 and row.get('price_change_15m', 0) < -3 and macd_hist > -0.5):
            long_signals.append('Oversold 15m (58%)')
        
        # ========== 空头信号 ==========
        if (trend == -1 and rsi > 55 and macd_cross_down and volume_spike and bb_width < 0.05):
            short_signals.append('Perfect Short (88%)')
        if (trend == -1 and rsi > 60 and macd < macd_signal and price_change_5m < 2):
            short_signals.append('Trend Follow Short (73%)')
        if (macd_cross_down and volume_ratio > 1.2 and rsi > 40 and trend_short == -1):
            short_signals.append('MACD Cross Short (68%)')
        if (bb_position > 0.85 and rsi > 50 and macd_hist < 0 and trend <= 0):
            short_signals.append('BB Reject Short (63%)')
        if (rsi > 65 and (macd_hist < 0 or not macd_expanding) and price_change_5m > 1.5):
            short_signals.append('Overbought Drop (58%)')
        if (rsi > 60 and row.get('price_change_15m', 0) > 3 and macd_hist < 0.5):
            short_signals.append('Overbought 15m (56%)')
        
        return len(long_signals), len(short_signals), long_signals + short_signals

    def calculate_confidence(self, signal_count: int) -> float:
        """计算置信度"""
        # confidence = 0.45 + 0.15 × (信号数量 - 1)
        return 0.45 + 0.15 * (signal_count - 1)

    def should_open_position(self, long_count: int, short_count: int, 
                           signal_details: List[str]) -> Tuple[str, float, str]:
        """
        V2.5频率优化版 - 单/双信号混合（核心改造）
        1. Perfect信号（90%）单信号直接开仓
        2. Trend Follow / MACD Cross（75%）单信号可开仓
        3. 普通信号才要求2个以上
        """
        # === 1. Perfect信号（90%）单信号直接开仓 ===
        if long_count >= 1 and any('Perfect Long' in s for s in signal_details):
            return 'BUY', 0.88, 'Perfect Long (单信号豁免)'
        if short_count >= 1 and any('Perfect Short' in s for s in signal_details):
            return 'SELL', 0.86, 'Perfect Short (单信号豁免)'
        
        # === 2. Trend Follow / MACD Cross（75%）单信号可开仓 ===
        if long_count >= 1 and any('Trend Follow' in s or 'MACD Cross' in s for s in signal_details):
            return 'BUY', 0.72, 'Trend/MACD Single Signal (单信号豁免)'
        if short_count >= 1 and any('Trend Follow' in s or 'MACD Cross' in s for s in signal_details):
            return 'SELL', 0.70, 'Trend/MACD Single Signal (单信号豁免)'
        
        # === 3. 双信号（保守网）===
        if long_count >= 2:
            confidence = 0.55 + 0.10 * (long_count - 2)  # 阈值0.55，每多一个信号+0.10
            return 'BUY', min(confidence, 0.85), f'Multi-Signal Long ({long_count})'
        if short_count >= 2:
            confidence = 0.53 + 0.10 * (short_count - 2)
            return 'SELL', min(confidence, 0.83), f'Multi-Signal Short ({short_count})'
        
        return 'HOLD', 0.0, 'No valid signals'

    def get_dynamic_grid_multiplier(self, volume_ratio: float, atr_pct: float) -> float:
        """
        计算动态ATR网格倍数
        公式: 1.2 + 0.2 × volume_ratio（量能越大，网格越宽）
        
        Args:
            volume_ratio: 成交量比率 (当前量/30日均量)
            atr_pct: ATR百分比
        
        Returns:
            动态网格倍数
        """
        if not self.grid_atr_dynamic:
            return self.grid_atr_multiplier
        
        # 基础倍数 1.2，根据量能调整
        base_multiplier = 1.2
        
        # 量能调整: volume_ratio 0.5-2.0 映射到 -0.1 到 +0.3
        volume_adjustment = 0.2 * (volume_ratio - 1.0)
        volume_adjustment = max(-0.1, min(0.3, volume_adjustment))
        
        # ATR波动率调整: ATR% 1%-5% 映射到 -0.1 到 +0.2
        atr_adjustment = 0.075 * (atr_pct - 2.5)
        atr_adjustment = max(-0.1, min(0.2, atr_adjustment))
        
        dynamic_multiplier = base_multiplier + volume_adjustment + atr_adjustment
        
        # 限制范围 1.0 - 1.8
        return max(1.0, min(1.8, dynamic_multiplier))

    def create_grid_levels(self, entry_price: float, side: str, atr: float, 
                          qty: float, volume_ratio: float = 1.0, atr_pct: float = 2.0) -> List[GridLevel]:
        """
        创建轻量双向网格层级（支持动态ATR倍数）
        网格间距 = ATR × 动态倍数
        """
        # 使用动态倍数
        grid_multiplier = self.get_dynamic_grid_multiplier(volume_ratio, atr_pct)
        grid_spacing = atr * grid_multiplier
        
        logger.info(f"网格参数: ATR=${atr:.2f}, 倍数={grid_multiplier:.2f}, "
                   f"间距=${grid_spacing:.2f}, 量能比={volume_ratio:.2f}")
        
        levels = []
        
        # 创建3个网格层级（双向）
        for i in range(1, 4):
            if side == 'LONG':
                # 多头网格：在上方挂止盈单
                grid_price = entry_price + grid_spacing * i
            else:
                # 空头网格：在下方挂止盈单
                grid_price = entry_price - grid_spacing * i
            
            grid_qty = qty * (0.5 ** (i-1))  # 递减仓位
            
            level = GridLevel(
                price=grid_price,
                side=side,
                qty=grid_qty
            )
            levels.append(level)
        
        return levels

    def check_dca_condition(self, position_group: PositionGroup, 
                           current_price: float, atr: float) -> Optional[Dict]:
        """
        检查补仓条件（斐波那契动态补仓）
        延迟补单：需再跌1.2×ATR才触发
        """
        if len(position_group.dca_levels) >= self.max_dca_count:
            return None
        
        last_entry = position_group.dca_levels[-1]['price'] if position_group.dca_levels else position_group.entry_price
        dca_index = len(position_group.dca_levels)
        
        # 计算补仓触发距离（斐波那契 + 延迟）
        fib_multiplier = self.dca_fib_sequence[dca_index]
        if dca_index == 2:  # 第3次补仓加速
            fib_multiplier *= self.dca_accelerator
        
        trigger_distance = atr * 1.2 * fib_multiplier
        
        # 检查是否触发
        if position_group.side == 'LONG':
            if current_price <= last_entry - trigger_distance:
                return {
                    'trigger_price': last_entry - trigger_distance,
                    'fib_multiplier': fib_multiplier,
                    'dca_index': dca_index + 1
                }
        else:
            if current_price >= last_entry + trigger_distance:
                return {
                    'trigger_price': last_entry + trigger_distance,
                    'fib_multiplier': fib_multiplier,
                    'dca_index': dca_index + 1
                }
        
        return None

    def check_three_layer_exit(self, position_group: PositionGroup, 
                               current_price: float, leverage: int = 5) -> Optional[Dict]:
        """
        三层智能止盈检查
        1. 尾单止盈（单格达标）
        2. 追踪止盈（盈利>6%后回撤3%）
        3. 整组止盈（整体收益>=8%）
        """
        if not position_group.is_active:
            return None
        
        # 计算整体盈亏
        total_pnl_pct = position_group.get_total_pnl_pct(current_price, leverage)
        
        # 更新最高盈利
        if total_pnl_pct > position_group.max_profit:
            position_group.max_profit = total_pnl_pct
        
        # ===== 第3层：整组止盈 =====
        if total_pnl_pct >= self.group_take_profit * 100:  # 8%转为百分比
            return {
                'action': 'CLOSE_ALL',
                'reason': f'Group Take Profit: {total_pnl_pct:.2f}% >= {self.group_take_profit*100:.0f}%',
                'pnl_pct': total_pnl_pct
            }
        
        # ===== 第2层：追踪止盈 =====
        if position_group.max_profit >= self.trailing_start * 100:  # 6%
            drawdown = position_group.max_profit - total_pnl_pct
            if drawdown >= self.trailing_stop * 100:  # 3%
                return {
                    'action': 'CLOSE_ALL',
                    'reason': f'Trailing Stop: Max {position_group.max_profit:.2f}%, '
                             f'Current {total_pnl_pct:.2f}%, Drawdown {drawdown:.2f}%',
                    'pnl_pct': total_pnl_pct
                }
        
        # ===== 第1层：尾单止盈（检查网格层级） =====
        for level in position_group.grid_levels:
            if not level.filled:
                if position_group.side == 'LONG' and current_price >= level.price:
                    return {
                        'action': 'CLOSE_GRID',
                        'grid_level': level,
                        'reason': f'Grid Level Take Profit: ${level.price:.2f}',
                        'pnl_pct': (level.price - position_group.get_average_price()) / position_group.get_average_price() * leverage * 100
                    }
                elif position_group.side == 'SHORT' and current_price <= level.price:
                    return {
                        'action': 'CLOSE_GRID',
                        'grid_level': level,
                        'reason': f'Grid Level Take Profit: ${level.price:.2f}',
                        'pnl_pct': (position_group.get_average_price() - level.price) / position_group.get_average_price() * leverage * 100
                    }
        
        return None

    def check_stop_loss(self, position_group: PositionGroup, 
                       current_price: float, leverage: int = 5) -> Optional[Dict]:
        """
        止损检查（杠杆后-5%）
        """
        avg_price = position_group.get_average_price()
        
        if position_group.side == 'LONG':
            loss_pct = (current_price - avg_price) / avg_price * leverage
        else:
            loss_pct = (avg_price - current_price) / avg_price * leverage
        
        STOP_LOSS_PCT = -0.05  # -5%
        
        if loss_pct <= STOP_LOSS_PCT:
            self.consecutive_losses += 1
            if self.consecutive_losses >= self.max_consecutive_losses:
                self.daily_stop_loss_triggered = True
            
            return {
                'action': 'STOP_LOSS',
                'reason': f'Stop Loss: {loss_pct*100:.2f}% <= {STOP_LOSS_PCT*100:.0f}%',
                'pnl_pct': loss_pct * 100
            }
        
        return None

    def check_funding_rate(self, api, symbol: str, side: str) -> Tuple[bool, str]:
        """
        检查Funding Rate过滤
        资金费率 > 0.015% 时禁止开多，避免持仓成本
        
        Args:
            api: Binance API实例
            symbol: 交易对
            side: 开仓方向 ('LONG' or 'SHORT')
        
        Returns:
            (是否允许开仓, 原因)
        """
        if api is None:
            return True, "API not available"
        
        try:
            funding_rate = api.get_funding_rate(symbol)
            
            if funding_rate is None:
                return True, "Funding rate unavailable"
            
            # 多头过滤：正资金费率过高时不开多
            if side == 'LONG' and funding_rate > self.funding_rate_threshold:
                return False, f"Funding rate {funding_rate*100:.4f}% > {self.funding_rate_threshold*100:.4f}%, skip LONG"
            
            # 空头过滤：负资金费率过低时不开空（可选，视策略而定）
            # if side == 'SHORT' and funding_rate < -self.funding_rate_threshold:
            #     return False, f"Funding rate {funding_rate*100:.4f}% too negative, skip SHORT"
            
            return True, f"Funding rate OK: {funding_rate*100:.4f}%"
            
        except Exception as e:
            logger.warning(f"Funding rate check failed: {e}")
            return True, "Funding rate check failed, allow by default"

    def generate_signal(self, symbol: str, df: pd.DataFrame, 
                       current_price: float = None, api=None) -> Dict:
        """
        V2.5-Hybrid 主信号生成器（优化版）
        新增：强信号豁免 + 动态网格 + Funding Rate过滤
        """
        current_time = time.time()
        
        # 检查连续止损保护
        if self.daily_stop_loss_triggered:
            return self._make_signal(symbol, 'HOLD', 0, 'Daily stop loss limit reached')
        
        # 检查交易间隔
        if current_time - self.last_trade_time < self.min_trade_interval:
            return self._make_signal(symbol, 'HOLD', 0, 'Trade interval too short')
        
        # 数据检查
        if df is None or len(df) < 10:
            return self._make_signal(symbol, 'HOLD', 0, 'Insufficient data')
        
        row = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else row
        
        # 检查必要字段
        required = ['close', 'rsi', 'macd', 'macd_signal', 'trend', 'atr']
        for field in required:
            if field not in row or pd.isna(row[field]):
                return self._make_signal(symbol, 'HOLD', 0, f'Missing {field}')
        
        # ===== 1. 统计信号数量（V2核心）=====
        long_count, short_count, signal_details = self.count_active_signals(row, prev)
        
        # 记录市场状态
        self._log_market_status(symbol, row, long_count, short_count, signal_details)
        
        # ===== 2. 检查现有仓位组的平仓/补仓/网格=====
        if symbol in self.position_groups and self.position_groups[symbol].is_active:
            pg = self.position_groups[symbol]
            
            # 检查止损
            sl_signal = self.check_stop_loss(pg, current_price)
            if sl_signal:
                return self._make_exit_signal(symbol, sl_signal)
            
            # 检查三层止盈
            exit_signal = self.check_three_layer_exit(pg, current_price)
            if exit_signal:
                return self._make_exit_signal(symbol, exit_signal)
            
            # 检查补仓
            dca_signal = self.check_dca_condition(pg, current_price, row['atr'])
            if dca_signal:
                return self._make_dca_signal(symbol, pg.side, dca_signal, row['atr'])
            
            # 无操作，继续持有
            return self._make_signal(symbol, 'HOLD', 0, 'Holding position with grid active')
        
        # ===== 3. 新开仓判断（双信号+强信号豁免）=====
        action, confidence, reason = self.should_open_position(long_count, short_count, signal_details)
        
        if action != 'HOLD':
            side = 'LONG' if action == 'BUY' else 'SHORT'
            
            # === 新增：Funding Rate过滤 ===
            funding_allowed, funding_reason = self.check_funding_rate(api, symbol, side)
            if not funding_allowed:
                logger.info(f"[{symbol}] {funding_reason}")
                return self._make_signal(symbol, 'HOLD', 0, funding_reason)
            
            # 避免反向开仓后立即反手
            if self.last_trade_side and action != self.last_trade_side:
                pass
            
            self.last_trade_side = action
            self.last_trade_time = current_time
            
            # 计算止损止盈价格
            close = row['close']
            sl = close * 0.95 if action == 'BUY' else close * 1.05
            tp = close * 1.08 if action == 'BUY' else close * 0.92
            
            # === 新增：动态网格参数 ===
            atr = row['atr']
            volume_ratio = row.get('volume_ratio', 1.0)
            atr_pct = row.get('atr_pct', 2.0)
            qty = 0.0  # 由执行引擎计算
            
            # 使用动态网格
            grid_levels = self.create_grid_levels(
                close, side, atr, qty, 
                volume_ratio=volume_ratio, 
                atr_pct=atr_pct
            )
            
            return {
                'action': action,
                'confidence': confidence,
                'reason': reason,
                'symbol': symbol,
                'sl': sl,
                'tp': tp,
                'atr': atr,
                'rsi': row['rsi'],
                'grid_levels': grid_levels,
                'is_hybrid': True,
                'consecutive_losses': self.consecutive_losses,
                'funding_ok': True
            }
        
        # 无信号
        return self._make_signal(symbol, 'HOLD', 0, f'No signals (L:{long_count}/S:{short_count})')
    
    def _log_market_status(self, symbol, row, long_count, short_count, signal_details=None):
        """记录市场状态（优化版，显示信号详情）"""
        current_time = time.time()
        if not hasattr(self, '_last_log_time'):
            self._last_log_time = {}
        
        if symbol not in self._last_log_time or current_time - self._last_log_time.get(symbol, 0) > 30:
            # 基础信息
            msg = (
                f"[{symbol}] Market | Price:${row['close']:.2f} | "
                f"Trend:{row['trend']}/{row.get('trend_short', row['trend'])} | "
                f"RSI:{row['rsi']:.1f} | MACD:{row['macd']:.4f} | "
                f"ATR:{row['atr']:.2f} | VolRatio:{row.get('volume_ratio', 1.0):.2f} | "
                f"Signals: L{long_count}/S{short_count}"
            )
            
            # 如果有信号详情，显示最强的信号
            if signal_details and len(signal_details) > 0:
                # 找出Perfect信号
                perfect_signals = [s for s in signal_details if 'Perfect' in s]
                if perfect_signals:
                    msg += f" | ⚡ {perfect_signals[0]}"
                else:
                    msg += f" | 📊 {signal_details[0]}"
            
            logger.info(msg)
            self._last_log_time[symbol] = current_time
    
    def _make_signal(self, symbol, action, confidence, reason, **kwargs):
        """构造基础信号"""
        signal = {
            'action': action,
            'confidence': confidence,
            'reason': reason,
            'symbol': symbol,
            'consecutive_losses': self.consecutive_losses,
            'daily_stopped': self.daily_stop_loss_triggered
        }
        signal.update(kwargs)
        return signal
    
    def _make_exit_signal(self, symbol, exit_info):
        """构造平仓信号"""
        return {
            'action': exit_info['action'],
            'confidence': 1.0,
            'reason': exit_info['reason'],
            'symbol': symbol,
            'pnl_pct': exit_info.get('pnl_pct', 0),
            'is_exit': True
        }
    
    def _make_dca_signal(self, symbol, side, dca_info, atr):
        """构造补仓信号"""
        return {
            'action': 'DCA',
            'side': side,
            'confidence': 0.9,
            'reason': f"DCA #{dca_info['dca_index']} at Fib {dca_info['fib_multiplier']:.2f}",
            'symbol': symbol,
            'trigger_price': dca_info['trigger_price'],
            'dca_index': dca_info['dca_index'],
            'atr': atr,
            'is_dca': True
        }