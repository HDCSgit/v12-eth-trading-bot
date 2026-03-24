import pandas as pd
import numpy as np
from config import CONFIG
import logging
import time
from datetime import datetime
from typing import Dict, Tuple, Optional

logger = logging.getLogger(__name__)


class ExpertStrategyV3:
    """
    研究员级策略 V3 - 专家级止盈止损优化
    1. ATR动态止损止盈
    2. 趋势/震荡市自适应参数
    3. 分阶段止盈（金字塔）
    4. 时间衰减止损
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
        self.min_trade_interval = 300  # 5分钟
        
        # 追踪止盈数据
        self.position_high_watermark = {}
        self.position_entry_time = {}
        
        # 市场状态检测
        self.market_regime = 'unknown'  # 'trending', 'ranging', 'unknown'
        self.volatility_regime = 'normal'  # 'high', 'normal', 'low'
        
    def reset_daily_stats(self):
        """每日重置统计"""
        self.consecutive_losses = 0
        self.daily_stop_loss_triggered = False
        
    def detect_market_regime(self, df: pd.DataFrame) -> str:
        """
        检测市场状态：趋势市 vs 震荡市
        使用ADX指标判断
        """
        if len(df) < 50:
            return 'unknown'
        
        # 计算ADX
        high = df['high']
        low = df['low']
        close = df['close']
        
        # +DM和-DM
        plus_dm = high.diff()
        minus_dm = low.diff().abs()
        
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0
        
        plus_dm[plus_dm <= minus_dm] = 0
        minus_dm[minus_dm <= plus_dm] = 0
        
        # TR
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        # ATR
        atr = tr.rolling(14).mean()
        
        # +DI和-DI
        plus_di = 100 * plus_dm.rolling(14).mean() / atr
        minus_di = 100 * minus_dm.rolling(14).mean() / atr
        
        # DX和ADX
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx.rolling(14).mean()
        
        current_adx = adx.iloc[-1]
        
        if pd.isna(current_adx):
            return 'unknown'
        elif current_adx > 25:
            return 'trending'  # 趋势市
        elif current_adx < 20:
            return 'ranging'   # 震荡市
        else:
            return 'mixed'     # 混合状态
    
    def detect_volatility_regime(self, df: pd.DataFrame) -> str:
        """
        检测波动率状态
        """
        if len(df) < 30:
            return 'normal'
        
        atr_pct = df['atr'].iloc[-1] / df['close'].iloc[-1] * 100
        
        if atr_pct > 3.0:
            return 'high'
        elif atr_pct < 1.0:
            return 'low'
        else:
            return 'normal'
    
    def get_dynamic_stop_loss(self, entry_price: float, side: str, 
                             atr: float, market_regime: str) -> float:
        """
        ATR动态止损
        趋势市：宽止损（2.5倍ATR）
        震荡市：紧止损（1.5倍ATR）
        """
        atr_distance = atr * 2.0  # 默认2倍ATR
        
        if market_regime == 'trending':
            atr_distance = atr * 2.5  # 趋势市给更多空间
        elif market_regime == 'ranging':
            atr_distance = atr * 1.5  # 震荡市更严格
        
        if side == 'LONG':
            return entry_price - atr_distance
        else:
            return entry_price + atr_distance
    
    def get_dynamic_take_profit(self, entry_price: float, side: str,
                               atr: float, market_regime: str) -> Tuple[float, float, float]:
        """
        分阶段动态止盈
        返回：第一目标、第二目标、第三目标
        """
        # 根据市场状态调整
        if market_regime == 'trending':
            multipliers = [2.0, 3.5, 5.0]  # 趋势市让利润奔跑
        elif market_regime == 'ranging':
            multipliers = [1.5, 2.5, 3.0]  # 震荡市及时落袋
        else:
            multipliers = [1.8, 3.0, 4.0]  # 默认
        
        if side == 'LONG':
            return (
                entry_price + atr * multipliers[0],
                entry_price + atr * multipliers[1],
                entry_price + atr * multipliers[2]
            )
        else:
            return (
                entry_price - atr * multipliers[0],
                entry_price - atr * multipliers[1],
                entry_price - atr * multipliers[2]
            )
    
    def check_trailing_stop(self, position: dict, current_price: float, 
                           atr: float) -> Optional[Dict]:
        """
        改进版追踪止盈
        使用3倍ATR作为回撤阈值
        """
        entry = position['entryPrice']
        side = position['side']
        
        # 计算当前盈亏
        if side == "LONG":
            price_change_pct = (current_price - entry) / entry
        else:
            price_change_pct = (entry - current_price) / entry
        
        leverage = CONFIG.get("LEVERAGE", 5)
        leveraged_pnl_pct = price_change_pct * leverage * 100
        
        # 更新最高盈利点
        pos_key = f"{position['symbol']}_{side}"
        if pos_key not in self.position_high_watermark:
            self.position_high_watermark[pos_key] = leveraged_pnl_pct
        elif leveraged_pnl_pct > self.position_high_watermark[pos_key]:
            self.position_high_watermark[pos_key] = leveraged_pnl_pct
        
        max_profit = self.position_high_watermark[pos_key]
        
        # 动态回撤阈值：3倍ATR
        atr_pct = atr / entry * 100 * leverage
        trailing_threshold = max(3.0, atr_pct * 3)  # 至少3%，或3倍ATR
        
        # 启动条件：盈利超过5%
        if max_profit >= 5.0:
            # 从最高点回撤超过阈值
            if max_profit - leveraged_pnl_pct >= trailing_threshold:
                return {
                    'action': 'CLOSE',
                    'reason': f'Trailing Stop: Max {max_profit:.2f}%, '
                             f'Current {leveraged_pnl_pct:.2f}%, '
                             f'Threshold {trailing_threshold:.2f}%',
                    'pnl_pct': leveraged_pnl_pct
                }
        
        return None
    
    def check_time_stop(self, position: dict, current_time: float) -> Optional[Dict]:
        """
        时间止损：持仓超过4小时无盈利→平仓
        """
        pos_key = f"{position['symbol']}_{position['side']}"
        
        if pos_key not in self.position_entry_time:
            return None
        
        entry_time = self.position_entry_time[pos_key]
        hold_time = current_time - entry_time
        
        # 4小时 = 14400秒
        if hold_time > 14400:
            # 计算当前盈亏
            entry = position['entryPrice']
            current_price = position.get('markPrice', entry)
            
            if position['side'] == "LONG":
                pnl_pct = (current_price - entry) / entry * 100
            else:
                pnl_pct = (entry - current_price) / entry * 100
            
            # 如果盈利<2%，时间止损
            if pnl_pct < 2.0:
                return {
                    'action': 'CLOSE',
                    'reason': f'Time Stop: Held {hold_time/3600:.1f}h, PnL {pnl_pct:.2f}%'
                }
        
        return None
    
    def compute_features(self, df: pd.DataFrame, symbol: str, 
                        btc_df: pd.DataFrame = None) -> pd.DataFrame:
        """增强版特征工程"""
        df = df.copy()
        
        if len(df) < 50:
            return df
        
        # 原有特征
        df['ma20'] = df['close'].rolling(20, min_periods=1).mean()
        df['ma55'] = df['close'].rolling(55, min_periods=1).mean()
        df['ma200'] = df['close'].rolling(200, min_periods=1).mean()
        df['trend'] = np.where(df['ma55'] > df['ma200'], 1, -1)
        df['trend_short'] = np.where(df['ma20'] > df['ma55'], 1, -1)
        
        # RSI
        delta = df['close'].diff()
        gain = delta.clip(lower=0).rolling(14, min_periods=1).mean()
        loss = (-delta.clip(upper=0)).rolling(14, min_periods=1).mean()
        rs = gain / (loss + 1e-10)
        df['rsi'] = 100 - 100 / (1 + rs)
        
        # ATR（关键改进）
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
        
        # 市场状态检测
        df['market_regime'] = self.detect_market_regime(df)
        df['volatility_regime'] = self.detect_volatility_regime(df)
        
        return df
    
    def generate_signal(self, symbol: str, df: pd.DataFrame, 
                       position: dict = None, current_price: float = None,
                       api=None) -> dict:
        """V3信号生成 - 研究员级"""
        
        # 检查连续止损保护
        if self.daily_stop_loss_triggered:
            return self._make_signal(symbol, df, 'HOLD', 0, 'Daily stop loss limit reached')
        
        current_time = time.time()
        
        # 检查持仓退出（改进版）
        if position and current_price:
            row = df.iloc[-1]
            atr = row.get('atr', current_price * 0.02)
            
            # 1. 固定止损检查
            entry = position['entryPrice']
            side = position['side']
            
            # ATR动态止损
            sl_price = self.get_dynamic_stop_loss(entry, side, atr, 
                                                  row.get('market_regime', 'mixed'))
            
            if side == 'LONG' and current_price <= sl_price:
                self.consecutive_losses += 1
                return self._make_close_signal(symbol, current_price, 
                                              f'Stop Loss (ATR): {current_price:.2f} <= {sl_price:.2f}')
            
            if side == 'SHORT' and current_price >= sl_price:
                self.consecutive_losses += 1
                return self._make_close_signal(symbol, current_price,
                                              f'Stop Loss (ATR): {current_price:.2f} >= {sl_price:.2f}')
            
            # 2. 追踪止盈检查
            trailing_signal = self.check_trailing_stop(position, current_price, atr)
            if trailing_signal:
                self.consecutive_losses = 0
                return self._make_close_signal(symbol, current_price, trailing_signal['reason'])
            
            # 3. 时间止损检查
            time_signal = self.check_time_stop(position, current_time)
            if time_signal:
                return self._make_close_signal(symbol, current_price, time_signal['reason'])
            
            # 4. 分阶段止盈检查
            tp1, tp2, tp3 = self.get_dynamic_take_profit(entry, side, atr,
                                                         row.get('market_regime', 'mixed'))
            
            # 第一目标：止盈50%仓位
            if side == 'LONG' and current_price >= tp1:
                # 这里需要配合执行引擎实现部分平仓
                pass
        
        # 开仓信号逻辑（简化版，继承V2）
        if df is None or len(df) < 10:
            return self._make_signal(symbol, df, 'HOLD', 0, 'Insufficient data')
        
        row = df.iloc[-1]
        
        # 检测市场状态
        market_regime = row.get('market_regime', 'mixed')
        volatility_regime = row.get('volatility_regime', 'normal')
        
        # 根据市场状态调整信号阈值
        if market_regime == 'trending':
            rsi_long_threshold = 40  # 趋势市放宽
            rsi_short_threshold = 60
        elif market_regime == 'ranging':
            rsi_long_threshold = 30  # 震荡市更严格
            rsi_short_threshold = 70
        else:
            rsi_long_threshold = 35
            rsi_short_threshold = 65
        
        # 简化信号生成（实际需要完整实现）
        # ... 信号生成逻辑 ...
        
        return self._make_signal(symbol, df, 'HOLD', 0, 
                                 f'Market: {market_regime}, Vol: {volatility_regime}')
    
    def _make_signal(self, symbol, df, action, confidence, reason, 
                     sl=None, tp=None, sl_price=None, tp_prices=None):
        """构造信号字典（V3增强版）"""
        if df is not None and len(df) > 0:
            row = df.iloc[-1]
            return {
                'action': action,
                'confidence': confidence,
                'sl': sl,  # 百分比
                'tp': tp,
                'sl_price': sl_price,  # 绝对价格
                'tp_prices': tp_prices,  # [tp1, tp2, tp3]
                'reason': reason,
                'symbol': symbol,
                'atr': row.get('atr'),
                'rsi': row.get('rsi'),
                'market_regime': row.get('market_regime'),
                'consecutive_losses': self.consecutive_losses,
                'daily_stopped': self.daily_stop_loss_triggered
            }
        return {
            'action': action,
            'confidence': confidence,
            'sl': sl,
            'tp': tp,
            'sl_price': sl_price,
            'tp_prices': tp_prices,
            'reason': reason,
            'symbol': symbol
        }
    
    def _make_close_signal(self, symbol, price, reason):
        """构造平仓信号"""
        return {
            'action': 'CLOSE',
            'confidence': 1.0,
            'reason': reason,
            'symbol': symbol,
            'price': price
        }