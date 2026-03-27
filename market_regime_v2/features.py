"""
市场环境特征工程模块
提取用于XGBoost分类器的特征
"""
import pandas as pd
import numpy as np
from typing import List, Optional


class RegimeFeatureExtractor:
    """市场环境特征提取器"""
    
    # 特征列表（与V1规则版本逻辑对应）
    FEATURE_COLS = [
        # === 价格行为 (对应V1的趋势判断) ===
        'returns_1h', 'returns_4h', 'returns_24h',
        'returns_std_20', 'returns_skew_20',
        
        # === 趋势强度 (对应V1的趋势强弱判断) ===
        'adx_14', 'di_plus_14', 'di_minus_14',
        'ma_slope_10', 'ma_slope_20', 'ma_slope_50',
        'price_vs_ma10', 'price_vs_ma20', 'price_vs_ma50',
        
        # === 动量指标 (对应V1的RSI/MACD判断) ===
        'rsi_14', 'rsi_slope',
        'macd_hist', 'macd_slope', 'macd_signal_dist',
        
        # === 波动性 (对应V1的震荡市判断) ===
        'atr_14', 'atr_ratio',
        'bb_width', 'bb_position',
        'keltner_upper_dist', 'keltner_lower_dist',
        
        # === 成交量 (对应V1的成交量确认) ===
        'volume_ratio_20', 'volume_trend',
        'obv_slope', 'mfi_14',
        
        # === 价格结构 (对应V1的突破/反转判断) ===
        'higher_highs_10', 'lower_lows_10',
        'support_distance', 'resistance_distance',
        'swing_high_distance', 'swing_low_distance',
        
        # === 统计特征 (V2新增，提升泛化能力) ===
        'hurst_exponent',  # 随机游走强弱
        'autocorr_1', 'autocorr_5',  # 自相关性
        'entropy_20',  # 价格熵，衡量无序程度
    ]
    
    def __init__(self, normalize: bool = True):
        self.normalize = normalize
        self.scaler = None
        
    def extract(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        从原始OHLCV数据中提取特征
        
        Args:
            df: 包含 open, high, low, close, volume 的DataFrame
            
        Returns:
            包含所有特征的DataFrame
        """
        data = df.copy()
        
        # 基础价格数据
        if 'returns' not in data.columns:
            data['returns'] = data['close'].pct_change()
        
        # === 价格行为特征 ===
        data['returns_1h'] = data['close'].pct_change(1)
        data['returns_4h'] = data['close'].pct_change(4)
        data['returns_24h'] = data['close'].pct_change(24)
        data['returns_std_20'] = data['returns'].rolling(20).std()
        data['returns_skew_20'] = data['returns'].rolling(20).skew()
        
        # === 趋势强度特征 (ADX) ===
        data = self._add_adx(data, period=14)
        
        # === 均线斜率 ===
        for period in [10, 20, 50]:
            ma_col = f'ma_{period}'
            data[ma_col] = data['close'].rolling(period).mean()
            data[f'ma_slope_{period}'] = data[ma_col].diff(5) / data[ma_col] * 100
            data[f'price_vs_ma{period}'] = (data['close'] - data[ma_col]) / data[ma_col] * 100
        
        # === 动量指标 ===
        data = self._add_rsi(data, period=14)
        data['rsi_slope'] = data['rsi_14'].diff(3)
        data = self._add_macd(data)
        
        # === 波动性特征 ===
        data = self._add_atr(data, period=14)
        data['atr_ratio'] = data['atr_14'] / data['close'] * 100
        data = self._add_bollinger(data)
        data = self._add_keltner(data)
        
        # === 成交量特征 ===
        data['volume_ratio_20'] = data['volume'] / data['volume'].rolling(20).mean()
        data['volume_trend'] = data['volume'].diff(5).rolling(5).mean()
        data = self._add_obv(data)
        data = self._add_mfi(data, period=14)
        
        # === 价格结构 ===
        data = self._add_price_structure(data)
        
        # === 统计特征 (V2新增) ===
        data['hurst_exponent'] = self._calc_hurst(data['close'])
        data['autocorr_1'] = data['returns'].autocorr(lag=1)
        data['autocorr_5'] = data['returns'].rolling(20).apply(lambda x: x.autocorr(lag=5))
        data['entropy_20'] = self._calc_entropy(data['returns'], window=20)
        
        return data[self.FEATURE_COLS]
    
    def _add_adx(self, df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """计算ADX趋势强度"""
        high, low, close = df['high'], df['low'], df['close']
        
        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0
        
        tr = pd.concat([
            high - low,
            abs(high - close.shift()),
            abs(low - close.shift())
        ], axis=1).max(axis=1)
        
        atr = tr.rolling(period).mean()
        plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
        
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        df['adx_14'] = dx.rolling(period).mean()
        df['di_plus_14'] = plus_di
        df['di_minus_14'] = minus_di
        return df
    
    def _add_rsi(self, df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """计算RSI"""
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(period).mean()
        loss = -delta.where(delta < 0, 0).rolling(period).mean()
        rs = gain / loss
        df['rsi_14'] = 100 - (100 / (1 + rs))
        return df
    
    def _add_macd(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算MACD"""
        ema12 = df['close'].ewm(span=12).mean()
        ema26 = df['close'].ewm(span=26).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9).mean()
        df['macd_hist'] = macd - signal
        df['macd_slope'] = df['macd_hist'].diff(3)
        df['macd_signal_dist'] = abs(macd - signal) / signal.abs()
        return df
    
    def _add_atr(self, df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """计算ATR"""
        high_low = df['high'] - df['low']
        high_close = abs(df['high'] - df['close'].shift())
        low_close = abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['atr_14'] = tr.rolling(period).mean()
        return df
    
    def _add_bollinger(self, df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
        """计算布林带"""
        ma = df['close'].rolling(period).mean()
        std = df['close'].rolling(period).std()
        upper = ma + 2 * std
        lower = ma - 2 * std
        df['bb_width'] = (upper - lower) / ma * 100
        df['bb_position'] = (df['close'] - lower) / (upper - lower)
        return df
    
    def _add_keltner(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算Keltner通道"""
        ema20 = df['close'].ewm(span=20).mean()
        atr = df['atr_14']
        upper = ema20 + 2 * atr
        lower = ema20 - 2 * atr
        df['keltner_upper_dist'] = (df['high'] - upper) / ema20 * 100
        df['keltner_lower_dist'] = (lower - df['low']) / ema20 * 100
        return df
    
    def _add_obv(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算OBV"""
        obv = [0]
        for i in range(1, len(df)):
            if df['close'].iloc[i] > df['close'].iloc[i-1]:
                obv.append(obv[-1] + df['volume'].iloc[i])
            elif df['close'].iloc[i] < df['close'].iloc[i-1]:
                obv.append(obv[-1] - df['volume'].iloc[i])
            else:
                obv.append(obv[-1])
        df['obv'] = obv
        df['obv_slope'] = df['obv'].diff(5)
        return df
    
    def _add_mfi(self, df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """计算MFI资金流量指标"""
        typical = (df['high'] + df['low'] + df['close']) / 3
        money_flow = typical * df['volume']
        
        positive = (typical > typical.shift()).astype(int) * money_flow
        negative = (typical < typical.shift()).astype(int) * money_flow
        
        positive_sum = positive.rolling(period).sum()
        negative_sum = negative.rolling(period).sum()
        
        mfi = 100 - (100 / (1 + positive_sum / negative_sum))
        df['mfi_14'] = mfi
        return df
    
    def _add_price_structure(self, df: pd.DataFrame, period: int = 10) -> pd.DataFrame:
        """计算价格结构特征"""
        # 计算局部高低点
        highs = df['high'].rolling(period, center=True).max() == df['high']
        lows = df['low'].rolling(period, center=True).min() == df['low']
        
        # 新高/新低计数（使用iloc避免FutureWarning）
        def count_higher_highs(x):
            return sum(x.iloc[i] > x.iloc[i-1] for i in range(1, len(x)))
        
        def count_lower_lows(x):
            return sum(x.iloc[i] < x.iloc[i-1] for i in range(1, len(x)))
        
        df['higher_highs_10'] = df['high'].rolling(period).apply(
            count_higher_highs, raw=False
        )
        df['lower_lows_10'] = df['low'].rolling(period).apply(
            count_lower_lows, raw=False
        )
        
        # 到支撑/阻力的距离
        recent_highs = df['high'].rolling(period).max()
        recent_lows = df['low'].rolling(period).min()
        df['resistance_distance'] = (recent_highs - df['close']) / df['close'] * 100
        df['support_distance'] = (df['close'] - recent_lows) / df['close'] * 100
        
        # 最近的摆动点距离（简化计算）
        # 使用expanding count来估算距离
        df['swing_high_distance'] = (~highs).groupby((~highs).cumsum()).cumcount()
        df['swing_low_distance'] = (~lows).groupby((~lows).cumsum()).cumcount()
        # 反转：从摆动点开始计数
        df['swing_high_distance'] = df['swing_high_distance'].where(~highs, 0)
        df['swing_low_distance'] = df['swing_low_distance'].where(~lows, 0)
        
        return df
    
    @staticmethod
    def _calc_hurst(prices: pd.Series, max_lag: int = 100) -> float:
        """计算Hurst指数 (随机游走强弱)"""
        lags = range(2, min(max_lag, len(prices) // 4))
        tau = [np.std(np.subtract(prices[lag:], prices[:-lag])) for lag in lags]
        
        if len(tau) < 2 or any(t == 0 for t in tau):
            return 0.5
        
        poly = np.polyfit(np.log(lags), np.log(tau), 1)
        return poly[0] * 2.0
    
    @staticmethod
    def _calc_entropy(returns: pd.Series, window: int = 20, bins: int = 10) -> pd.Series:
        """计算价格熵 (衡量无序程度)"""
        def _entropy(x):
            if len(x) < bins:
                return 1.0
            hist, _ = np.histogram(x, bins=bins, density=True)
            hist = hist[hist > 0]
            if len(hist) == 0:
                return 1.0
            return -np.sum(hist * np.log(hist)) / np.log(bins)
        
        return returns.rolling(window).apply(_entropy, raw=True)
