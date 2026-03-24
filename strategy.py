import pandas as pd
import numpy as np
from config import CONFIG
import logging
import time

logger = logging.getLogger(__name__)

class ExpertStrategy:
    def __init__(self):
        self.rsi_period = 14
        self.atr_period = 14
        self.bb_period = 20
        self.confidence_threshold = CONFIG["CONFIDENCE_THRESHOLD"]

    def compute_features(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """研究员级特征工程（趋势 + RSI + MACD + BB + ATR + 量能）"""
        df = df.copy()
        
        # 确保数据足够
        if len(df) < 50:
            logger.warning(f"[{symbol}] Data too short: {len(df)} rows")
            return df
        
        # 趋势
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
        
        # ATR（止损止盈核心）
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['atr'] = tr.rolling(self.atr_period, min_periods=1).mean()
        df['atr_pct'] = df['atr'] / df['close'] * 100
        
        # Bollinger Bands
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
        
        # 量能
        df['volume_ma'] = df['volume'].rolling(30, min_periods=1).mean()
        df['volume_spike'] = df['volume'] > df['volume_ma'] * 1.6
        df['volume_ratio'] = df['volume'] / (df['volume_ma'] + 1e-10)
        
        # 价格变化
        df['price_change_1m'] = df['close'].pct_change(1) * 100
        df['price_change_5m'] = df['close'].pct_change(5) * 100
        df['price_change_30m'] = df['close'].pct_change(30) * 100
        
        return df

    def check_position_exit(self, position: dict, current_price: float, symbol: str) -> dict:
        """检查是否需要平仓（止盈止损，考虑杠杆）"""
        if not position:
            return None
        
        entry = position['entryPrice']
        qty = position['qty']
        side = position['side']
        leverage = CONFIG.get("LEVERAGE", 10)
        
        # 计算价格变动百分比
        if side == "LONG":
            price_change_pct = (current_price - entry) / entry
        else:  # SHORT
            price_change_pct = (entry - current_price) / entry
        
        # 计算杠杆后收益率
        leveraged_pnl_pct = price_change_pct * leverage * 100
        
        # 计算名义盈亏金额
        notional_value = qty * entry
        pnl_amount = notional_value * price_change_pct
        
        # 止损 -5% (杠杆后)
        if leveraged_pnl_pct <= -5.0:
            return {
                'action': 'CLOSE',
                'confidence': 1.0,
                'reason': f'Stop Loss: {leveraged_pnl_pct:.2f}% (Leveraged {leverage}x)',
                'symbol': symbol,
                'price': current_price,
                'pnl_pct': leveraged_pnl_pct,
                'pnl_amount': pnl_amount
            }
        
        # 止盈 +10% (杠杆后)
        if leveraged_pnl_pct >= 10.0:
            return {
                'action': 'CLOSE',
                'confidence': 1.0,
                'reason': f'Take Profit: {leveraged_pnl_pct:.2f}% (Leveraged {leverage}x)',
                'symbol': symbol,
                'price': current_price,
                'pnl_pct': leveraged_pnl_pct,
                'pnl_amount': pnl_amount
            }
        
        return None

    def generate_signal(self, symbol: str, df: pd.DataFrame, position: dict = None, current_price: float = None) -> dict:
        """生成专家级交易信号（多层级策略）"""
        
        # 首先检查是否需要平仓（止盈止损）
        if position and current_price:
            exit_signal = self.check_position_exit(position, current_price, symbol)
            if exit_signal:
                logger.info(f"[{symbol}] EXIT SIGNAL: {exit_signal['reason']}")
                return exit_signal
        
        # 检查数据
        if df is None or len(df) < 10:
            return self._make_signal(symbol, df, 'HOLD', 0, 'Insufficient data')
        
        row = df.iloc[-1]
        
        # 检查必要字段是否存在
        required_fields = ['close', 'rsi', 'macd', 'macd_signal', 'trend', 'volume_ratio']
        for field in required_fields:
            if field not in row or pd.isna(row[field]):
                return self._make_signal(symbol, df, 'HOLD', 0, f'Missing field: {field}')
        
        prev = df.iloc[-2] if len(df) > 1 else row
        
        # 提取指标
        close = row['close']
        trend = row['trend']
        trend_short = row.get('trend_short', trend)
        rsi = row['rsi']
        macd = row['macd']
        macd_signal = row['macd_signal']
        macd_hist = row.get('macd_hist', macd - macd_signal)
        
        # MACD交叉检测
        macd_cross_up = (macd > macd_signal) and (prev.get('macd', macd) <= prev.get('macd_signal', macd_signal))
        macd_cross_down = (macd < macd_signal) and (prev.get('macd', macd) >= prev.get('macd_signal', macd_signal))
        
        volume_spike = row.get('volume_spike', False)
        volume_ratio = row.get('volume_ratio', 1.0)
        bb_width = row.get('bb_width', 0.05)
        bb_position = row.get('bb_position', 0.5)
        atr = row.get('atr', close * 0.02)
        price_change_5m = row.get('price_change_5m', 0)
        
        # 记录市场状态（每30秒）
        current_time = time.time()
        if not hasattr(self, '_last_log_time'):
            self._last_log_time = {}
        if symbol not in self._last_log_time or current_time - self._last_log_time.get(symbol, 0) > 30:
            logger.info(
                f"[{symbol}] Market | Price:${close:.2f} | Trend:{trend}/{trend_short} | "
                f"RSI:{rsi:.1f} | MACD:{macd:.4f} | Vol:{volume_ratio:.2f}x | "
                f"BB:{bb_position:.2f} | 5m:{price_change_5m:.2f}%"
            )
            self._last_log_time[symbol] = current_time
        
        # ========== 信号1: 完美多头共振 ==========
        if (trend == 1 and rsi < 40 and macd_cross_up and volume_spike and bb_width < 0.02):
            return self._make_signal(
                symbol, df, 'BUY', 0.90, 
                'Perfect Long (Trend+RSI+MACD+Volume+BB)',
                sl=close * 0.95, tp=close * 1.10
            )
        
        # ========== 信号2: 完美空头共振 ==========
        if (trend == -1 and rsi > 60 and macd_cross_down and volume_spike and bb_width < 0.02):
            return self._make_signal(
                symbol, df, 'SELL', 0.88,
                'Perfect Short (Trend+RSI+MACD+Volume+BB)',
                sl=close * 1.05, tp=close * 0.90
            )
        
        # ========== 信号3: 趋势跟随+RSI反转 (多头) ==========
        if (trend == 1 and rsi < 35 and macd > macd_signal and price_change_5m > -1):
            return self._make_signal(
                symbol, df, 'BUY', 0.75,
                'Trend Follow Long (Trend+RSI+MACD)',
                sl=close * 0.96, tp=close * 1.08
            )
        
        # ========== 信号4: 趋势跟随+RSI反转 (空头) ==========
        if (trend == -1 and rsi > 65 and macd < macd_signal and price_change_5m < 1):
            return self._make_signal(
                symbol, df, 'SELL', 0.73,
                'Trend Follow Short (Trend+RSI+MACD)',
                sl=close * 1.04, tp=close * 0.92
            )
        
        # ========== 信号5: MACD金叉+量能 (多头) ==========
        if (macd_cross_up and volume_ratio > 1.3 and rsi < 55 and trend_short == 1):
            return self._make_signal(
                symbol, df, 'BUY', 0.70,
                'MACD Cross Long (MACD+Volume+RSI)',
                sl=close * 0.97, tp=close * 1.06
            )
        
        # ========== 信号6: MACD死叉+量能 (空头) ==========
        if (macd_cross_down and volume_ratio > 1.3 and rsi > 45 and trend_short == -1):
            return self._make_signal(
                symbol, df, 'SELL', 0.68,
                'MACD Cross Short (MACD+Volume+RSI)',
                sl=close * 1.03, tp=close * 0.94
            )
        
        # ========== 信号7: 布林带反弹 (多头) ==========
        if (bb_position < 0.1 and rsi < 45 and macd_hist > 0 and trend == 1):
            return self._make_signal(
                symbol, df, 'BUY', 0.65,
                'BB Bounce Long (BB+RSI+MACD)',
                sl=close * 0.96, tp=close * 1.05
            )
        
        # ========== 信号8: 布林带回落 (空头) ==========
        if (bb_position > 0.9 and rsi > 55 and macd_hist < 0 and trend == -1):
            return self._make_signal(
                symbol, df, 'SELL', 0.63,
                'BB Reject Short (BB+RSI+MACD)',
                sl=close * 1.04, tp=close * 0.95
            )
        
        # ========== 信号9: 超卖反弹 (多头) ==========
        if (rsi < 30 and macd_hist > -0.5 and price_change_5m < -2):
            return self._make_signal(
                symbol, df, 'BUY', 0.60,
                'Oversold Bounce (RSI<30+MACD)',
                sl=close * 0.97, tp=close * 1.04
            )
        
        # ========== 信号10: 超买回落 (空头) ==========
        if (rsi > 70 and macd_hist < 0.5 and price_change_5m > 2):
            return self._make_signal(
                symbol, df, 'SELL', 0.58,
                'Overbought Drop (RSI>70+MACD)',
                sl=close * 1.03, tp=close * 0.96
            )
        
        # 无信号
        return self._make_signal(symbol, df, 'HOLD', 0, 'No matching conditions')
    
    def _make_signal(self, symbol, df, action, confidence, reason, sl=None, tp=None):
        """构造信号字典"""
        if df is not None and len(df) > 0:
            row = df.iloc[-1]
            return {
                'action': action,
                'confidence': confidence,
                'sl': sl,
                'tp': tp,
                'reason': reason,
                'symbol': symbol,
                'atr': row.get('atr'),
                'rsi': row.get('rsi'),
                'macd': row.get('macd'),
                'price': row.get('close'),
                'trend': row.get('trend'),
                'bb_position': row.get('bb_position')
            }
        return {
            'action': action,
            'confidence': confidence,
            'sl': sl,
            'tp': tp,
            'reason': reason,
            'symbol': symbol,
            'atr': None,
            'rsi': None,
            'macd': None,
            'price': None,
            'trend': None,
            'bb_position': None
        }
