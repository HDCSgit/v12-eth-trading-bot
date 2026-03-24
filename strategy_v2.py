import pandas as pd
import numpy as np
from config import CONFIG
import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)

class ExpertStrategyV2:
    """
    优化版策略 - 根据用户反馈改进
    1. 放宽信号条件，提高频率
    2. 信号叠加机制
    3. BTC趋势过滤
    4. 连续止损保护
    5. 追踪止盈
    """
    def __init__(self):
        self.rsi_period = 14
        self.atr_period = 14
        self.bb_period = 20
        self.confidence_threshold = CONFIG["CONFIDENCE_THRESHOLD"]
        
        # 连续止损计数器
        self.consecutive_losses = 0
        self.max_consecutive_losses = 2  # 连续2笔止损暂停当天交易
        self.daily_stop_loss_triggered = False
        
        # 记录今日已开单方向，避免频繁反手
        self.last_trade_side = None
        self.last_trade_time = 0
        self.min_trade_interval = 300  # 最少5分钟间隔
        
        # 追踪止盈数据
        self.position_high_watermark = {}  # 持仓最高盈利点
        
    def reset_daily_stats(self):
        """每日重置统计"""
        self.consecutive_losses = 0
        self.daily_stop_loss_triggered = False
        
    def compute_features(self, df: pd.DataFrame, symbol: str, btc_df: pd.DataFrame = None) -> pd.DataFrame:
        """增强版特征工程，增加BTC相关性"""
        df = df.copy()
        
        if len(df) < 50:
            logger.warning(f"[{symbol}] Data too short: {len(df)} rows")
            return df
        
        # 原有特征计算
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
        
        # ATR
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['atr'] = tr.rolling(self.atr_period, min_periods=1).mean()
        df['atr_pct'] = df['atr'] / df['close'] * 100
        
        # 布林带 - 放宽条件
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
        df['macd_expanding'] = df['macd_hist'] > df['macd_hist'].shift(1)  # MACD柱扩大
        
        # 量能
        df['volume_ma'] = df['volume'].rolling(30, min_periods=1).mean()
        df['volume_spike'] = df['volume'] > df['volume_ma'] * 1.5  # 放宽到1.5倍
        df['volume_ratio'] = df['volume'] / (df['volume_ma'] + 1e-10)
        
        # 价格变化
        df['price_change_1m'] = df['close'].pct_change(1) * 100
        df['price_change_5m'] = df['close'].pct_change(5) * 100
        df['price_change_15m'] = df['close'].pct_change(15) * 100
        
        # BTC趋势过滤（如果提供）
        if btc_df is not None and len(btc_df) == len(df):
            df['btc_trend'] = btc_df['trend'] if 'trend' in btc_df.columns else 0
        else:
            df['btc_trend'] = 0
            
        return df

    def check_position_exit(self, position: dict, current_price: float, symbol: str) -> dict:
        """改进版平仓检查，增加追踪止盈"""
        if not position:
            return None
        
        entry = position['entryPrice']
        qty = position['qty']
        side = position['side']
        leverage = CONFIG.get("LEVERAGE", 10)
        
        # 计算价格变动
        if side == "LONG":
            price_change_pct = (current_price - entry) / entry
        else:
            price_change_pct = (entry - current_price) / entry
        
        leveraged_pnl_pct = price_change_pct * leverage * 100
        notional_value = qty * entry
        pnl_amount = notional_value * price_change_pct
        
        # 更新最高盈利点（用于追踪止盈）
        pos_key = f"{symbol}_{side}"
        if pos_key not in self.position_high_watermark:
            self.position_high_watermark[pos_key] = leveraged_pnl_pct
        elif leveraged_pnl_pct > self.position_high_watermark[pos_key]:
            self.position_high_watermark[pos_key] = leveraged_pnl_pct
        
        max_profit = self.position_high_watermark.get(pos_key, 0)
        
        # 止损 -5%
        if leveraged_pnl_pct <= -5.0:
            self.consecutive_losses += 1
            if self.consecutive_losses >= self.max_consecutive_losses:
                self.daily_stop_loss_triggered = True
                logger.warning(f"🛑 连续{self.consecutive_losses}笔止损，暂停今日交易！")
            return {
                'action': 'CLOSE',
                'confidence': 1.0,
                'reason': f'Stop Loss: {leveraged_pnl_pct:.2f}% (Leveraged {leverage}x)',
                'symbol': symbol,
                'price': current_price,
                'pnl_pct': leveraged_pnl_pct,
                'pnl_amount': pnl_amount
            }
        
        # 止盈 +10%
        if leveraged_pnl_pct >= 10.0:
            self.consecutive_losses = 0  # 重置止损计数
            return {
                'action': 'CLOSE',
                'confidence': 1.0,
                'reason': f'Take Profit: {leveraged_pnl_pct:.2f}% (Leveraged {leverage}x)',
                'symbol': symbol,
                'price': current_price,
                'pnl_pct': leveraged_pnl_pct,
                'pnl_amount': pnl_amount
            }
        
        # 追踪止盈：盈利>6%后，回撤到+3%平仓
        if max_profit >= 6.0 and leveraged_pnl_pct <= 3.0:
            self.consecutive_losses = 0
            return {
                'action': 'CLOSE',
                'confidence': 1.0,
                'reason': f'Trailing Stop: Max {max_profit:.2f}%, Current {leveraged_pnl_pct:.2f}%',
                'symbol': symbol,
                'price': current_price,
                'pnl_pct': leveraged_pnl_pct,
                'pnl_amount': pnl_amount
            }
        
        return None

    def count_active_signals(self, row, prev, btc_trend_ok=True) -> tuple:
        """
        统计同时满足的多头/空头信号数量
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
        
        # MACD交叉
        macd_cross_up = (macd > macd_signal) and (prev.get('macd', macd) <= prev.get('macd_signal', macd_signal))
        macd_cross_down = (macd < macd_signal) and (prev.get('macd', macd) >= prev.get('macd_signal', macd_signal))
        
        volume_spike = row.get('volume_spike', False)
        volume_ratio = row.get('volume_ratio', 1.0)
        bb_width = row.get('bb_width', 0.05)
        bb_position = row.get('bb_position', 0.5)
        price_change_5m = row.get('price_change_5m', 0)
        price_change_15m = row.get('price_change_15m', 0)
        
        # ========== 多头信号（放宽条件）==========
        # 信号1: 完美多头共振（布林带放宽到0.05）
        if (trend == 1 and rsi < 45 and macd_cross_up and volume_spike and bb_width < 0.05):
            long_signals.append('Perfect Long (90%)')
        
        # 信号2: 趋势跟随多头（RSI放宽到40）
        if (trend == 1 and rsi < 40 and macd > macd_signal and price_change_5m > -2):
            long_signals.append('Trend Follow Long (75%)')
        
        # 信号3: MACD金叉+量能（RSI放宽到60）
        if (macd_cross_up and volume_ratio > 1.2 and rsi < 60 and trend_short == 1):
            long_signals.append('MACD Cross Long (70%)')
        
        # 信号4: 布林带反弹（布林带位置放宽到0.15）
        if (bb_position < 0.15 and rsi < 50 and macd_hist > 0 and trend >= 0):
            long_signals.append('BB Bounce Long (65%)')
        
        # 信号5: 超卖反弹（增加MACD扩大条件）
        if (rsi < 35 and (macd_hist > 0 or macd_expanding) and price_change_5m < -1.5):
            long_signals.append('Oversold Bounce (60%)')
        
        # 信号6: 长期超跌反弹（15分钟跌幅）
        if (rsi < 40 and price_change_15m < -3 and macd_hist > -0.5):
            long_signals.append('Oversold 15m (58%)')
        
        # ========== 空头信号（放宽条件）==========
        # 信号1: 完美空头共振
        if (trend == -1 and rsi > 55 and macd_cross_down and volume_spike and bb_width < 0.05):
            short_signals.append('Perfect Short (88%)')
        
        # 信号2: 趋势跟随空头
        if (trend == -1 and rsi > 60 and macd < macd_signal and price_change_5m < 2):
            short_signals.append('Trend Follow Short (73%)')
        
        # 信号3: MACD死叉+量能
        if (macd_cross_down and volume_ratio > 1.2 and rsi > 40 and trend_short == -1):
            short_signals.append('MACD Cross Short (68%)')
        
        # 信号4: 布林带回落
        if (bb_position > 0.85 and rsi > 50 and macd_hist < 0 and trend <= 0):
            short_signals.append('BB Reject Short (63%)')
        
        # 信号5: 超买回落
        if (rsi > 65 and (macd_hist < 0 or not macd_expanding) and price_change_5m > 1.5):
            short_signals.append('Overbought Drop (58%)')
        
        # 信号6: 长期超涨回落
        if (rsi > 60 and price_change_15m > 3 and macd_hist < 0.5):
            short_signals.append('Overbought 15m (56%)')
        
        # BTC趋势过滤（如果BTC趋势不一致，信号降级）
        if not btc_trend_ok:
            long_signals = [s + "[BTC Filter]" for s in long_signals]
            short_signals = [s + "[BTC Filter]" for s in short_signals]
        
        return len(long_signals), len(short_signals), long_signals + short_signals

    def check_funding_rate(self, api, symbol: str, side: str) -> bool:
        """
        检查资金费率过滤
        返回 True 表示可以交易，False 表示应该避开
        """
        try:
            funding_rate = api.get_funding_rate(symbol)
            
            # 资金费率阈值
            HIGH_FUNDING = 0.01  # 1% 视为高资金费
            
            if side == 'BUY' and funding_rate > HIGH_FUNDING:
                logger.warning(f"[{symbol}] 资金费率过高 ({funding_rate:.4%})，避开多头")
                return False
            
            if side == 'SELL' and funding_rate < -HIGH_FUNDING:
                logger.warning(f"[{symbol}] 资金费率过低 ({funding_rate:.4%})，避开空头")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"检查资金费率失败: {e}")
            return True  # 出错时默认允许交易
    
    def generate_signal(self, symbol: str, df: pd.DataFrame, position: dict = None, 
                       current_price: float = None, btc_df: pd.DataFrame = None, api=None) -> dict:
        """改进版信号生成 - 信号叠加机制"""
        
        # 检查连续止损保护
        if self.daily_stop_loss_triggered:
            return self._make_signal(symbol, df, 'HOLD', 0, 'Daily stop loss limit reached')
        
        # 首先检查是否需要平仓（止盈止损+追踪止盈）
        if position and current_price:
            exit_signal = self.check_position_exit(position, current_price, symbol)
            if exit_signal:
                # 平仓后清除追踪止盈记录
                pos_key = f"{symbol}_{position['side']}"
                if pos_key in self.position_high_watermark:
                    del self.position_high_watermark[pos_key]
                logger.info(f"[{symbol}] EXIT SIGNAL: {exit_signal['reason']}")
                return exit_signal
        
        # 检查数据
        if df is None or len(df) < 10:
            return self._make_signal(symbol, df, 'HOLD', 0, 'Insufficient data')
        
        row = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else row
        
        # 检查必要字段
        required_fields = ['close', 'rsi', 'macd', 'macd_signal', 'trend']
        for field in required_fields:
            if field not in row or pd.isna(row[field]):
                return self._make_signal(symbol, df, 'HOLD', 0, f'Missing field: {field}')
        
        # 计算BTC趋势过滤（ETH与BTC相关性高）
        btc_trend_ok = True
        if btc_df is not None and len(btc_df) > 0:
            btc_trend = btc_df.iloc[-1].get('trend', 0)
            eth_trend = row['trend']
            # 如果BTC和ETH趋势相反，谨慎交易
            if btc_trend != eth_trend and abs(btc_trend) == 1:
                btc_trend_ok = False
        
        # 统计信号数量
        long_count, short_count, signal_details = self.count_active_signals(row, prev, btc_trend_ok)
        
        # 每30秒记录市场状态
        current_time = time.time()
        if not hasattr(self, '_last_log_time'):
            self._last_log_time = {}
        if symbol not in self._last_log_time or current_time - self._last_log_time.get(symbol, 0) > 30:
            close = row['close']
            trend = row['trend']
            trend_short = row.get('trend_short', trend)
            rsi = row['rsi']
            macd = row['macd']
            volume_ratio = row.get('volume_ratio', 1.0)
            bb_position = row.get('bb_position', 0.5)
            price_change_5m = row.get('price_change_5m', 0)
            
            logger.info(
                f"[{symbol}] Market | Price:${close:.2f} | Trend:{trend}/{trend_short} | "
                f"RSI:{rsi:.1f} | MACD:{macd:.4f} | Vol:{volume_ratio:.2f}x | "
                f"BB:{bb_position:.2f} | 5m:{price_change_5m:.2f}% | "
                f"Signals: L{long_count}/S{short_count}"
            )
            self._last_log_time[symbol] = current_time
        
        # 信号叠加机制：需要至少2个信号同时出现才开仓
        MIN_SIGNALS = 2
        
        # 检查交易间隔（避免频繁交易）
        if current_time - self.last_trade_time < self.min_trade_interval:
            return self._make_signal(symbol, df, 'HOLD', 0, 'Trade interval too short')
        
        close = row['close']
        
        # 多头信号叠加
        if long_count >= MIN_SIGNALS and not position:
            # 避免反向开仓后立即反手
            if self.last_trade_side == 'SELL':
                return self._make_signal(symbol, df, 'HOLD', 0, 'Avoid immediate reverse trade')
            
            confidence = min(0.60 + (long_count - 2) * 0.10, 0.90)  # 2信号=60%，3信号=70%，最高90%
            sl = close * 0.96  # 放宽止损到4%
            tp = close * 1.08  # 止盈8%
            
            self.last_trade_side = 'BUY'
            self.last_trade_time = current_time
            
            return self._make_signal(
                symbol, df, 'BUY', confidence,
                f'Multi-Signal Long ({long_count} signals: {", ".join(signal_details[:3])})',
                sl=sl, tp=tp
            )
        
        # 空头信号叠加
        if short_count >= MIN_SIGNALS and not position:
            if self.last_trade_side == 'BUY':
                return self._make_signal(symbol, df, 'HOLD', 0, 'Avoid immediate reverse trade')
            
            confidence = min(0.58 + (short_count - 2) * 0.10, 0.88)
            sl = close * 1.04
            tp = close * 0.92
            
            self.last_trade_side = 'SELL'
            self.last_trade_time = current_time
            
            return self._make_signal(
                symbol, df, 'SELL', confidence,
                f'Multi-Signal Short ({short_count} signals: {", ".join(signal_details[:3])})',
                sl=sl, tp=tp
            )
        
        # 单个强信号也可以考虑（90%+置信度）
        if long_count == 1 and 'Perfect Long' in str(signal_details) and not position:
            self.last_trade_side = 'BUY'
            self.last_trade_time = current_time
            return self._make_signal(
                symbol, df, 'BUY', 0.85,
                f'Strong Single Signal: {signal_details[0]}',
                sl=close * 0.95, tp=close * 1.10
            )
        
        if short_count == 1 and 'Perfect Short' in str(signal_details) and not position:
            self.last_trade_side = 'SELL'
            self.last_trade_time = current_time
            return self._make_signal(
                symbol, df, 'SELL', 0.83,
                f'Strong Single Signal: {signal_details[0]}',
                sl=close * 1.05, tp=close * 0.90
            )
        
        # 无信号
        return self._make_signal(symbol, df, 'HOLD', 0, 
                                 f'No signals (L:{long_count}/S:{short_count})')
    
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
                'bb_position': row.get('bb_position'),
                'consecutive_losses': self.consecutive_losses,
                'daily_stopped': self.daily_stop_loss_triggered
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
            'bb_position': None,
            'consecutive_losses': self.consecutive_losses,
            'daily_stopped': self.daily_stop_loss_triggered
        }