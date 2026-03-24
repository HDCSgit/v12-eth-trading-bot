#!/usr/bin/env python3
"""
V12原版 vs 优化版 回测对比
验证优化效果
"""

import pandas as pd
import numpy as np
import logging
from datetime import datetime
from typing import Dict, List
import warnings
warnings.filterwarnings('ignore')

try:
    import xgboost as xgb
    from sklearn.preprocessing import StandardScaler
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)


# ==================== 原版V12策略 ====================
class V12OriginalStrategy:
    """原版V12策略 - RSI+MA简单信号"""
    
    def __init__(self, initial_balance: float = 1000.0):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.peak_balance = initial_balance
        self.max_drawdown = 0
        
        self.stats = {
            'total_trades': 0, 'wins': 0, 'losses': 0,
            'total_pnl': 0, 'max_win': 0, 'max_loss': 0
        }
        
        self.leverage = 3
        self.position_pct = 0.10
        self.stop_loss_pct = 0.03
        self.take_profit_pct = 0.06
        
        self.position = None
        self.entry_price = 0.0
        self.trade_log = []
    
    def calculate_rsi(self, prices: pd.Series, period: int = 14) -> float:
        delta = prices.diff()
        gain = delta.clip(lower=0).rolling(window=period).mean()
        loss = (-delta.clip(upper=0)).rolling(window=period).mean()
        rs = gain / loss
        return (100 - (100 / (1 + rs))).iloc[-1]
    
    def generate_signal(self, df: pd.DataFrame) -> str:
        current = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else current
        
        rsi = self.calculate_rsi(df['close'])
        ma10 = df['close'].rolling(10).mean().iloc[-1]
        ma20 = df['close'].rolling(20).mean().iloc[-1]
        prev_ma10 = df['close'].rolling(10).mean().iloc[-2]
        prev_ma20 = df['close'].rolling(20).mean().iloc[-2]
        
        # 超卖反弹做多
        if rsi < 35 and current['close'] > prev['close']:
            return 'BUY'
        
        # 超买回落做空
        elif rsi > 65 and current['close'] < prev['close']:
            return 'SELL'
        
        # 均线金叉做多
        elif ma10 > ma20 and prev_ma10 <= prev_ma20:
            return 'BUY'
        
        # 均线死叉做空
        elif ma10 < ma20 and prev_ma10 >= prev_ma20:
            return 'SELL'
        
        return 'HOLD'
    
    def run_backtest(self, df: pd.DataFrame) -> Dict:
        """运行回测"""
        for i in range(30, len(df)):
            price = df['close'].iloc[i]
            current_df = df.iloc[:i+1]
            
            # 更新峰值和回撤
            if self.balance > self.peak_balance:
                self.peak_balance = self.balance
            drawdown = (self.peak_balance - self.balance) / self.peak_balance
            self.max_drawdown = max(self.max_drawdown, drawdown)
            
            # 持仓管理
            if self.position:
                pnl_pct = (price - self.entry_price) / self.entry_price * self.leverage
                if self.position == 'SELL':
                    pnl_pct = -pnl_pct
                
                # 止盈止损
                if pnl_pct <= -self.stop_loss_pct or pnl_pct >= self.take_profit_pct:
                    self._close_position(price, pnl_pct)
                    continue
            
            # 开仓
            if not self.position:
                signal = self.generate_signal(current_df)
                if signal != 'HOLD':
                    self._open_position(signal, price)
        
        # 强制平仓最后一笔
        if self.position:
            price = df['close'].iloc[-1]
            pnl_pct = (price - self.entry_price) / self.entry_price * self.leverage
            if self.position == 'SELL':
                pnl_pct = -pnl_pct
            self._close_position(price, pnl_pct)
        
        return self._get_results()
    
    def _open_position(self, side: str, price: float):
        """开仓"""
        margin = self.balance * self.position_pct
        self.balance -= margin
        self.position = side
        self.entry_price = price
        self.stats['total_trades'] += 1
    
    def _close_position(self, price: float, pnl_pct: float):
        """平仓"""
        margin = self.initial_balance * self.position_pct
        pnl_amount = margin * pnl_pct
        self.balance += margin + pnl_amount
        
        if pnl_pct > 0:
            self.stats['wins'] += 1
            self.stats['max_win'] = max(self.stats['max_win'], pnl_pct)
        else:
            self.stats['losses'] += 1
            self.stats['max_loss'] = min(self.stats['max_loss'], pnl_pct)
        
        self.stats['total_pnl'] += pnl_pct
        self.trade_log.append({'pnl_pct': pnl_pct, 'result': 'WIN' if pnl_pct > 0 else 'LOSS'})
        self.position = None
    
    def _get_results(self) -> Dict:
        """获取结果"""
        total_return = (self.balance - self.initial_balance) / self.initial_balance * 100
        win_rate = self.stats['wins'] / max(self.stats['total_trades'], 1) * 100
        profit_factor = abs(self.stats['max_win'] / self.stats['max_loss']) if self.stats['max_loss'] != 0 else 0
        
        return {
            'name': '原版V12',
            'total_return': total_return,
            'win_rate': win_rate,
            'total_trades': self.stats['total_trades'],
            'wins': self.stats['wins'],
            'losses': self.stats['losses'],
            'max_drawdown': self.max_drawdown * 100,
            'profit_factor': profit_factor,
            'avg_pnl': self.stats['total_pnl'] / max(self.stats['total_trades'], 1) * 100
        }


# ==================== 优化版V12策略 ====================
class V12OptimizedStrategy:
    """优化版V12策略 - ML+ATR动态风控"""
    
    def __init__(self, initial_balance: float = 1000.0):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.peak_balance = initial_balance
        self.max_drawdown = 0
        
        self.stats = {
            'total_trades': 0, 'wins': 0, 'losses': 0,
            'total_pnl': 0, 'max_win': 0, 'max_loss': 0
        }
        
        self.leverage = 5
        self.ml_model = None
        self.scaler = StandardScaler()
        self.position = None
        self.entry_price = 0.0
        self.trade_log = []
    
    def create_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """特征工程"""
        df = df.copy()
        
        # RSI
        for period in [6, 12, 24]:
            delta = df['close'].diff()
            gain = delta.clip(lower=0).rolling(period).mean()
            loss = (-delta.clip(upper=0)).rolling(period).mean()
            df[f'rsi_{period}'] = 100 - 100 / (1 + gain / (loss + 1e-10))
        
        # MACD
        ema12 = df['close'].ewm(span=12).mean()
        ema26 = df['close'].ewm(span=26).mean()
        df['macd'] = ema12 - ema26
        df['macd_signal'] = df['macd'].ewm(span=9).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']
        
        # 布林带
        df['bb_mid'] = df['close'].rolling(20).mean()
        df['bb_std'] = df['close'].rolling(20).std()
        df['bb_upper'] = df['bb_mid'] + 2 * df['bb_std']
        df['bb_lower'] = df['bb_mid'] - 2 * df['bb_std']
        df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_mid']
        df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'] + 1e-10)
        
        # ATR
        tr1 = df['high'] - df['low']
        tr2 = abs(df['high'] - df['close'].shift())
        tr3 = abs(df['low'] - df['close'].shift())
        df['atr'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).rolling(14).mean()
        df['atr_pct'] = df['atr'] / df['close']
        
        # 均线
        df['ma_10'] = df['close'].rolling(10).mean()
        df['ma_20'] = df['close'].rolling(20).mean()
        df['trend_short'] = np.where(df['ma_10'] > df['ma_20'], 1, -1)
        
        # 成交量
        df['volume_ma'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma']
        
        # 动量
        df['momentum_5'] = df['close'].pct_change(5)
        
        return df.dropna()
    
    def train_ml(self, df: pd.DataFrame):
        """训练ML模型"""
        if not ML_AVAILABLE:
            return
        
        df_feat = self.create_features(df)
        df_feat['future_return'] = df_feat['close'].shift(-3) / df_feat['close'] - 1
        df_feat['target'] = np.where(
            df_feat['future_return'] > 0.005, 1,
            np.where(df_feat['future_return'] < -0.005, 0, -1)
        )
        
        feature_cols = ['rsi_12', 'macd_hist', 'bb_position', 'bb_width', 'volume_ratio', 'momentum_5']
        mask = df_feat['target'] != -1
        X = df_feat[feature_cols].loc[mask]
        y = df_feat['target'].loc[mask]
        
        if len(X) < 100:
            return
        
        X_scaled = self.scaler.fit_transform(X)
        self.ml_model = xgb.XGBClassifier(
            n_estimators=100, max_depth=4, learning_rate=0.08, subsample=0.8, random_state=42
        )
        self.ml_model.fit(X_scaled, y)
    
    def ml_predict(self, df: pd.DataFrame) -> Dict:
        """ML预测"""
        if not ML_AVAILABLE or self.ml_model is None:
            return {'direction': 0, 'confidence': 0.5}
        
        try:
            df_feat = self.create_features(df)
            if len(df_feat) == 0:
                return {'direction': 0, 'confidence': 0.5}
            
            feature_cols = ['rsi_12', 'macd_hist', 'bb_position', 'bb_width', 'volume_ratio', 'momentum_5']
            X = df_feat[feature_cols].iloc[-1:]
            X_scaled = self.scaler.transform(X)
            proba = self.ml_model.predict_proba(X_scaled)[0]
            
            return {
                'direction': 1 if proba[1] > proba[0] else -1,
                'confidence': max(proba)
            }
        except:
            return {'direction': 0, 'confidence': 0.5}
    
    def is_sideways(self, df: pd.DataFrame) -> bool:
        """检测震荡市"""
        current = df.iloc[-1]
        bb_width = current.get('bb_width', 0.1)
        rsi = current.get('rsi_12', 50)
        return bb_width < 0.05 and 40 < rsi < 60
    
    def generate_signal(self, df: pd.DataFrame, has_position: bool = False) -> tuple:
        """生成信号"""
        df_feat = self.create_features(df)
        if len(df_feat) == 0:
            return 'HOLD', 0.5, 0.02
        
        current = df_feat.iloc[-1]
        atr_pct = current.get('atr_pct', 0.02)
        
        # ML信号
        ml = self.ml_predict(df)
        
        # 震荡市策略
        if self.is_sideways(df_feat):
            close = current['close']
            bb_upper = current['bb_upper']
            bb_lower = current['bb_lower']
            rsi = current['rsi_12']
            
            if close < bb_lower * 1.01 and rsi < 45:
                return 'BUY', 0.6, atr_pct
            if close > bb_upper * 0.99 and rsi > 55:
                return 'SELL', 0.6, atr_pct
        
        # 趋势市ML信号
        if ml['confidence'] >= 0.58:
            action = 'BUY' if ml['direction'] == 1 else 'SELL'
            return action, ml['confidence'], atr_pct
        
        # 技术指标补充
        rsi = current.get('rsi_12', 50)
        macd_hist = current.get('macd_hist', 0)
        
        if rsi < 30 and macd_hist > 0:
            return 'BUY', 0.65, atr_pct
        if rsi > 70 and macd_hist < 0:
            return 'SELL', 0.65, atr_pct
        
        return 'HOLD', 0.5, atr_pct
    
    def calculate_position_size(self, balance: float, price: float, confidence: float) -> float:
        """动态仓位计算"""
        base_risk = balance * 0.008  # 0.8%风险
        confidence_mult = min(confidence / 0.6, 2.0)
        stop_loss_pct = 0.015  # 1.5%止损
        
        qty = (base_risk * confidence_mult) / (stop_loss_pct * price)
        max_qty = balance * 0.15 / price
        
        return min(qty, max_qty)
    
    def run_backtest(self, df: pd.DataFrame) -> Dict:
        """运行回测"""
        # 训练ML模型
        train_size = int(len(df) * 0.3)
        self.train_ml(df.iloc[:train_size])
        
        test_df = df.iloc[train_size:].reset_index(drop=True)
        
        for i in range(50, len(test_df)):
            price = test_df['close'].iloc[i]
            current_df = test_df.iloc[:i+1]
            
            # 更新回撤
            if self.balance > self.peak_balance:
                self.peak_balance = self.balance
            drawdown = (self.peak_balance - self.balance) / self.peak_balance
            self.max_drawdown = max(self.max_drawdown, drawdown)
            
            # 持仓管理 - ATR动态止盈止损
            if self.position:
                pnl_pct = (price - self.entry_price) / self.entry_price * self.leverage
                if self.position == 'SELL':
                    pnl_pct = -pnl_pct
                
                # 获取ATR用于动态SL/TP
                _, _, atr_pct = self.generate_signal(current_df, True)
                sl_pct = -2.5 * atr_pct * self.leverage
                tp_pct = 4.0 * atr_pct * self.leverage
                
                if pnl_pct <= sl_pct or pnl_pct >= tp_pct:
                    self._close_position(price, pnl_pct)
                    continue
            
            # 开仓
            if not self.position:
                action, confidence, _ = self.generate_signal(current_df)
                if action != 'HOLD':
                    self._open_position(action, price, confidence)
        
        # 强制平仓
        if self.position:
            price = test_df['close'].iloc[-1]
            pnl_pct = (price - self.entry_price) / self.entry_price * self.leverage
            if self.position == 'SELL':
                pnl_pct = -pnl_pct
            self._close_position(price, pnl_pct)
        
        return self._get_results()
    
    def _open_position(self, side: str, price: float, confidence: float):
        """开仓"""
        qty = self.calculate_position_size(self.balance, price, confidence)
        margin = qty * price / self.leverage
        self.balance -= margin
        self.position = side
        self.entry_price = price
        self.stats['total_trades'] += 1
    
    def _close_position(self, price: float, pnl_pct: float):
        """平仓"""
        margin = (self.initial_balance * 0.15) / self.leverage
        pnl_amount = margin * pnl_pct
        self.balance += margin + pnl_amount
        
        if pnl_pct > 0:
            self.stats['wins'] += 1
            self.stats['max_win'] = max(self.stats['max_win'], pnl_pct)
        else:
            self.stats['losses'] += 1
            self.stats['max_loss'] = min(self.stats['max_loss'], pnl_pct)
        
        self.stats['total_pnl'] += pnl_pct
        self.trade_log.append({'pnl_pct': pnl_pct, 'result': 'WIN' if pnl_pct > 0 else 'LOSS'})
        self.position = None
    
    def _get_results(self) -> Dict:
        """获取结果"""
        total_return = (self.balance - self.initial_balance) / self.initial_balance * 100
        win_rate = self.stats['wins'] / max(self.stats['total_trades'], 1) * 100
        profit_factor = abs(self.stats['max_win'] / self.stats['max_loss']) if self.stats['max_loss'] != 0 else 0
        
        return {
            'name': '优化版V12',
            'total_return': total_return,
            'win_rate': win_rate,
            'total_trades': self.stats['total_trades'],
            'wins': self.stats['wins'],
            'losses': self.stats['losses'],
            'max_drawdown': self.max_drawdown * 100,
            'profit_factor': profit_factor,
            'avg_pnl': self.stats['total_pnl'] / max(self.stats['total_trades'], 1) * 100
        }


def print_comparison(original: Dict, optimized: Dict):
    """打印对比结果"""
    print("\n" + "=" * 80)
    print(" " * 25 + "📊 V12 策略对比报告")
    print("=" * 80)
    
    print(f"\n{'指标':<20} {'原版V12':>15} {'优化版V12':>15} {'提升':>15}")
    print("-" * 80)
    
    # 收益率
    ret_diff = optimized['total_return'] - original['total_return']
    ret_pct = (ret_diff / abs(original['total_return']) * 100) if original['total_return'] != 0 else 0
    print(f"{'总收益率':<20} {original['total_return']:>14.2f}% {optimized['total_return']:>14.2f}% {color_diff(ret_diff):>15}")
    
    # 胜率
    wr_diff = optimized['win_rate'] - original['win_rate']
    print(f"{'胜率':<20} {original['win_rate']:>14.2f}% {optimized['win_rate']:>14.2f}% {color_diff(wr_diff, '%'):>15}")
    
    # 交易次数
    trade_diff = optimized['total_trades'] - original['total_trades']
    print(f"{'总交易次数':<20} {original['total_trades']:>15} {optimized['total_trades']:>15} {color_diff(trade_diff, ''):>15}")
    
    # 盈亏比
    pf_diff = optimized['profit_factor'] - original['profit_factor']
    print(f"{'盈亏比':<20} {original['profit_factor']:>15.2f} {optimized['profit_factor']:>15.2f} {color_diff(pf_diff):>15}")
    
    # 最大回撤
    dd_diff = original['max_drawdown'] - optimized['max_drawdown']  # 回撤降低是正向
    print(f"{'最大回撤':<20} {original['max_drawdown']:>14.2f}% {optimized['max_drawdown']:>14.2f}% {'↓' + f'{dd_diff:.2f}%':>14}")
    
    # 平均盈亏
    avg_diff = optimized['avg_pnl'] - original['avg_pnl']
    print(f"{'平均每笔盈亏':<20} {original['avg_pnl']:>14.2f}% {optimized['avg_pnl']:>14.2f}% {color_diff(avg_diff):>15}")
    
    print("\n" + "=" * 80)
    
    # 综合评价
    score_original = calculate_score(original)
    score_optimized = calculate_score(optimized)
    
    print(f"\n{'综合评分':<20} {score_original:>15}/100 {score_optimized:>15}/100")
    
    if score_optimized > score_original:
        print(f"\n✅ 优化版表现更好，评分提升 +{score_optimized - score_original}")
    elif score_optimized < score_original:
        print(f"\n⚠️ 原版表现更好，建议检查优化参数")
    else:
        print(f"\n➡️ 两者表现相当")
    
    print("=" * 80)


def color_diff(value, suffix='%'):
    """颜色化差异"""
    if isinstance(value, str):
        return value
    
    sign = '+' if value >= 0 else ''
    return f"{sign}{value:.2f}{suffix}"


def calculate_score(result: Dict) -> int:
    """计算综合评分"""
    score = 0
    if result['max_drawdown'] < 20: score += 25
    if result['win_rate'] > 50: score += 25
    if result['total_return'] > 0: score += 25
    if result['profit_factor'] > 1.2: score += 25
    return score


def main():
    """主函数"""
    logger.info("加载ETH数据...")
    
    # 尝试加载数据
    data_files = ['eth_usdt_5m_2024_2026.csv', 'eth_usdt_1h.csv', 'eth_usdt_1h_binance.csv']
    df = None
    
    for file in data_files:
        try:
            df = pd.read_csv(file)
            logger.info(f"✅ 加载 {file}，共 {len(df)} 条数据")
            break
        except:
            continue
    
    if df is None:
        logger.error("❌ 未找到数据文件，请确保以下文件之一存在：")
        for f in data_files:
            logger.error(f"   - {f}")
        return
    
    # 数据预处理
    for col in ['open', 'high', 'low', 'close', 'volume']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    
    df = df.dropna()
    
    # 如果是5分钟数据，重采样到1小时
    if len(df) > 10000:
        logger.info("数据量较大，重采样到1小时...")
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df.set_index('timestamp', inplace=True)
        elif 'open_time' in df.columns:
            df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
            df.set_index('open_time', inplace=True)
        
        df = df.resample('1H').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna()
        df = df.reset_index()
        logger.info(f"重采样后: {len(df)} 条数据")
    
    # 运行原版回测
    logger.info("\n" + "=" * 50)
    logger.info("运行原版V12回测...")
    original_strategy = V12OriginalStrategy(initial_balance=1000.0)
    original_result = original_strategy.run_backtest(df)
    
    # 运行优化版回测
    logger.info("\n运行优化版V12回测...")
    if ML_AVAILABLE:
        optimized_strategy = V12OptimizedStrategy(initial_balance=1000.0)
        optimized_result = optimized_strategy.run_backtest(df)
    else:
        logger.warning("XGBoost未安装，优化版将使用备用策略")
        optimized_strategy = V12OptimizedStrategy(initial_balance=1000.0)
        optimized_result = optimized_strategy.run_backtest(df)
    
    # 打印对比
    print_comparison(original_result, optimized_result)


if __name__ == "__main__":
    main()
