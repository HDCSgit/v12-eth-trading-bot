#!/usr/bin/env python3
"""
V12-ML-GRID-LIVE: ML+网格融合实盘交易
- ML主决策（XGBoost）
- 震荡市自动开启3层网格
- 趋势市直接交易
- 完整风控+实时监控
"""

import pandas as pd
import numpy as np
import logging
import time
import sqlite3
import sys
import io
from datetime import datetime
from typing import Dict, List, Optional
import warnings
warnings.filterwarnings('ignore')

from binance_api import BinanceExpertAPI
from config import CONFIG, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
import requests

# 编码修复
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler(f'logs/v12_ml_grid_{datetime.now().strftime("%Y%m%d")}.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ==================== ML模型部分 ====================
try:
    import xgboost as xgb
    from sklearn.preprocessing import StandardScaler
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    logger.error("缺少ML库，请运行: pip install xgboost scikit-learn")

class MLFeatureEngineer:
    """ML特征工程"""
    def create_features(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['returns'] = df['close'].pct_change()
        
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
        
        # 均线
        for period in [5, 10, 20]:
            df[f'ma_{period}'] = df['close'].rolling(period).mean()
        df['trend_short'] = np.where(df['ma_10'] > df['ma_20'], 1, -1)
        
        # 量能
        df['volume_ma'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma']
        
        # 动量
        for period in [3, 5, 10]:
            df[f'momentum_{period}'] = df['close'].pct_change(period)
        
        # ATR
        tr1 = df['high'] - df['low']
        tr2 = abs(df['high'] - df['close'].shift())
        tr3 = abs(df['low'] - df['close'].shift())
        df['atr'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).rolling(14).mean()
        
        return df.dropna()

class MLTradingModel:
    """ML交易模型"""
    def __init__(self):
        self.model = None
        self.scaler = StandardScaler()
        self.is_trained = False
        self.feature_eng = MLFeatureEngineer()
        
    def train(self, df: pd.DataFrame):
        if not ML_AVAILABLE:
            return
        
        df_feat = self.feature_eng.create_features(df)
        
        # 特征列
        feature_cols = ['rsi_12', 'rsi_24', 'macd_hist', 'bb_position', 'bb_width',
                       'volume_ratio', 'momentum_5', 'trend_short']
        
        # 目标：未来3周期涨跌
        df_feat['future_return'] = df_feat['close'].shift(-3) / df_feat['close'] - 1
        df_feat['target'] = np.where(df_feat['future_return'] > 0.004, 1,
                                    np.where(df_feat['future_return'] < -0.004, 0, -1))
        
        mask = df_feat['target'] != -1
        X = df_feat[feature_cols].loc[mask]
        y = df_feat['target'].loc[mask]
        
        if len(X) < 100:
            logger.warning(f"训练样本不足: {len(X)}")
            return
        
        X_scaled = self.scaler.fit_transform(X)
        
        self.model = xgb.XGBClassifier(
            n_estimators=150,
            max_depth=5,
            learning_rate=0.07,
            subsample=0.85,
            random_state=42
        )
        self.model.fit(X_scaled, y)
        self.is_trained = True
        logger.info(f"ML模型训练完成，样本数: {len(X)}")

    def predict(self, df: pd.DataFrame) -> dict:
        if not self.is_trained or not ML_AVAILABLE:
            return {'direction': 0, 'confidence': 0.5}
        
        df_feat = self.feature_eng.create_features(df)
        if len(df_feat) == 0:
            return {'direction': 0, 'confidence': 0.5}
        
        feature_cols = ['rsi_12', 'rsi_24', 'macd_hist', 'bb_position', 'bb_width',
                       'volume_ratio', 'momentum_5', 'trend_short']
        
        X = df_feat[feature_cols].iloc[-1:]
        X_scaled = self.scaler.transform(X)
        proba = self.model.predict_proba(X_scaled)[0]
        
        return {
            'direction': 1 if proba[1] > proba[0] else -1,
            'confidence': max(proba),
            'up_prob': proba[1],
            'down_prob': proba[0]
        }

# ==================== 主交易类 ====================
class V12MLGridLiveTrader:
    """V12 ML+网格实盘交易器"""
    
    def __init__(self):
        self.api = BinanceExpertAPI()
        self.symbol = CONFIG["SYMBOLS"][0]
        self.ml_model = MLTradingModel()
        
        # 交易参数
        self.leverage = 3
        self.position_pct = 0.08
        self.base_qty = 0.0
        
        # 风控
        self.stop_loss_pct = 0.025
        self.take_profit_pct = 0.05
        self.max_daily_loss = 0.05
        self.grid_take_profit = 0.03  # 网格每层3%
        
        # 状态
        self.daily_pnl = 0
        self.last_trade_day = datetime.now().day
        self.position = None
        self.grid_levels = []
        self.is_grid_mode = False
        
        # 初始化
        self.init_database()
        self.train_ml_model()
        
        logger.info("=" * 70)
        logger.info("V12-ML-GRID-LIVE 初始化完成")
        logger.info(f"交易对: {self.symbol}")
        logger.info(f"杠杆: {self.leverage}x")
        logger.info(f"仓位: {self.position_pct*100}%")
        logger.info(f"ML可用: {ML_AVAILABLE}")
        logger.info("=" * 70)

    def init_database(self):
        """初始化数据库"""
        conn = sqlite3.connect('v12_ml_grid_trades.db')
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                symbol TEXT,
                side TEXT,
                entry_price REAL,
                exit_price REAL,
                qty REAL,
                pnl_pct REAL,
                pnl_usdt REAL,
                result TEXT,
                trade_type TEXT,
                status TEXT
            )
        ''')
        conn.commit()
        conn.close()

    def train_ml_model(self):
        """训练ML模型"""
        logger.info("正在训练ML模型...")
        df = self.api.get_klines(self.symbol, limit=500)
        if df is not None and len(df) > 100:
            self.ml_model.train(df)
        else:
            logger.warning("获取历史数据失败，ML模型未训练")

    def send_telegram(self, message: str):
        """发送通知"""
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
            return
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=5)
        except Exception as e:
            logger.error(f"Telegram失败: {e}")

    def is_sideways_market(self, df: pd.DataFrame) -> bool:
        """判断是否为震荡市"""
        current = df.iloc[-1]
        bb_width = current.get('bb_width', 0.1)
        rsi = current.get('rsi_12', 50)
        # BB宽度小于0.08且RSI在40-60之间
        return bb_width < 0.08 and 40 < rsi < 60

    def open_grid_position(self, side: str, price: float, atr: float):
        """开启网格仓位"""
        self.is_grid_mode = True
        self.grid_levels = []
        
        # 3层网格
        for i, mult in enumerate([1.0, 2.0, 3.0]):
            if side == 'BUY':
                tp = price + (atr * mult * 2.0)  # ATR的2倍
            else:
                tp = price - (atr * mult * 2.0)
            
            qty = self.base_qty * (0.5 if i == 0 else 0.25)
            self.grid_levels.append({
                'level': i + 1,
                'tp_price': tp,
                'qty': qty,
                'filled': False
            })
        
        logger.info(f"开启网格模式: {side} | 入场价: ${price:.2f} | ATR: ${atr:.2f}")
        logger.info(f"网格层数: {len(self.grid_levels)}")

    def check_grid_take_profit(self, current_price: float) -> bool:
        """检查网格止盈"""
        if not self.is_grid_mode or not self.grid_levels:
            return False
        
        all_filled = True
        for level in self.grid_levels:
            if not level['filled']:
                all_filled = False
                tp_price = level['tp_price']
                
                # 检查是否触及止盈
                if (self.position['side'] == 'BUY' and current_price >= tp_price) or \
                   (self.position['side'] == 'SELL' and current_price <= tp_price):
                    
                    level['filled'] = True
                    pnl = self.grid_take_profit * (1 if self.position['side'] == 'BUY' else -1)
                    self.daily_pnl += pnl * (level['qty'] / self.base_qty)
                    
                    logger.info(f"网格第{level['level']}层止盈 | 价格: ${current_price:.2f}")
                    
                    # 发送部分止盈通知
                    self.send_telegram(f"网格止盈 L{level['level']} | ${current_price:.2f}")
        
        # 如果全部止盈，平仓
        if all_filled:
            logger.info("网格全部止盈，平仓")
            self.close_position(current_price, "网格全部止盈")
            return True
        
        return False

    def calculate_position_size(self, price: float) -> float:
        """计算仓位"""
        balance = self.api.get_balance()
        value = balance * self.position_pct * self.leverage
        qty = value / price
        
        # 精度处理
        if self.symbol == 'ETHUSDT':
            qty = round(qty, 3)
        
        return max(qty, 0.001)

    def open_position(self, side: str, price: float, reason: str, is_grid: bool = False):
        """开仓"""
        try:
            # 设置杠杆
            self.api.set_leverage(self.symbol, self.leverage)
            
            # 计算数量
            self.base_qty = self.calculate_position_size(price)
            
            # 下单
            order = self.api.place_order(self.symbol, side, self.base_qty)
            
            if order and order.get('orderId'):
                self.position = {
                    'side': side,
                    'entry_price': price,
                    'qty': self.base_qty,
                    'entry_time': datetime.now(),
                    'reason': reason
                }
                
                msg = f"[开仓] {side} | ${price:.2f} | {self.base_qty:.3f} ETH | {reason}"
                logger.info(msg)
                self.send_telegram(f"<b>开仓</b>\n{side} ${price:.2f}\n{self.base_qty:.3f} ETH\n{reason}")
                
                # 如果是网格模式，设置网格
                if is_grid:
                    df = self.api.get_klines(self.symbol, limit=50)
                    if df is not None:
                        atr = df['high'].rolling(14).max().iloc[-1] - df['low'].rolling(14).min().iloc[-1]
                        self.open_grid_position(side, price, atr)
                
                return True
                
        except Exception as e:
            logger.error(f"开仓失败: {e}")
        
        return False

    def close_position(self, price: float, reason: str):
        """平仓"""
        try:
            if not self.position:
                return False
            
            side = self.position['side']
            entry = self.position['entry_price']
            qty = self.position['qty']
            
            # 计算盈亏
            if side == 'BUY':
                pnl_pct = (price - entry) / entry * self.leverage
            else:
                pnl_pct = (entry - price) / entry * self.leverage
            
            pnl_usdt = qty * entry * pnl_pct
            
            # 下单
            close_side = 'SELL' if side == 'BUY' else 'BUY'
            order = self.api.place_order(self.symbol, close_side, qty, reduce_only=True)
            
            if order:
                result = 'WIN' if pnl_pct > 0 else 'LOSS'
                self.daily_pnl += pnl_pct
                
                # 记录
                conn = sqlite3.connect('v12_ml_grid_trades.db')
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO trades VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (None, datetime.now().isoformat(), self.symbol, side, entry, price,
                      qty, pnl_pct, pnl_usdt, result, 'GRID' if self.is_grid_mode else 'ML', 'CLOSED'))
                conn.commit()
                conn.close()
                
                msg = f"[平仓] {side} | PnL: {pnl_pct*100:+.2f}% | ${pnl_usdt:+.2f} | {reason}"
                logger.info(msg)
                self.send_telegram(f"<b>平仓</b> {result}\nPnL: {pnl_pct*100:+.2f}%\n${pnl_usdt:+.2f}\n{reason}")
                
                # 重置状态
                self.position = None
                self.grid_levels = []
                self.is_grid_mode = False
                
                return True
                
        except Exception as e:
            logger.error(f"平仓失败: {e}")
        
        return False

    def check_position(self, current_price: float):
        """检查持仓状态"""
        if not self.position:
            return
        
        entry = self.position['entry_price']
        side = self.position['side']
        
        if side == 'BUY':
            pnl_pct = (current_price - entry) / entry * self.leverage
        else:
            pnl_pct = (entry - current_price) / entry * self.leverage
        
        # 网格模式检查
        if self.is_grid_mode:
            if self.check_grid_take_profit(current_price):
                return
        else:
            # 普通模式：止损止盈
            if pnl_pct <= -self.stop_loss_pct:
                logger.info(f"触发止损: {pnl_pct*100:.2f}%")
                self.close_position(current_price, "止损")
            elif pnl_pct >= self.take_profit_pct:
                logger.info(f"触发止盈: {pnl_pct*100:.2f}%")
                self.close_position(current_price, "止盈")

    def run(self):
        """主循环"""
        logger.info("V12-ML-GRID 启动...")
        self.send_telegram("V12-ML-GRID 实盘启动")
        
        while True:
            try:
                # 日重置
                if datetime.now().day != self.last_trade_day:
                    self.daily_pnl = 0
                    self.last_trade_day = datetime.now().day
                    logger.info("新的一天，重置统计")
                    # 重新训练模型
                    self.train_ml_model()
                
                # 风控检查
                if self.daily_pnl < -self.max_daily_loss:
                    logger.warning(f"日亏损达{self.daily_pnl*100:.2f}%，暂停")
                    time.sleep(300)
                    continue
                
                # 获取数据
                df = self.api.get_klines(self.symbol, limit=100)
                if df is None or len(df) < 50:
                    logger.warning("获取数据失败")
                    time.sleep(5)
                    continue
                
                # 计算指标
                df = self.ml_model.feature_eng.create_features(df)
                current_price = float(df['close'].iloc[-1])
                
                # 有持仓则检查
                if self.position:
                    self.check_position(current_price)
                    logger.info(f"持仓: {self.position['side']} | 入场: ${self.position['entry_price']:.2f} | 当前: ${current_price:.2f}")
                    time.sleep(10)
                    continue
                
                # 无持仓则找信号
                if len(df) < 30:
                    time.sleep(5)
                    continue
                
                # ML预测
                ml_pred = self.ml_model.predict(df)
                logger.info(f"ML预测: 方向={ml_pred['direction']}, 置信度={ml_pred['confidence']:.2f}")
                
                # 判断市场类型
                is_sideways = self.is_sideways_market(df)
                logger.info(f"震荡市检测: {is_sideways}")
                
                action = None
                reason = ""
                use_grid = False
                
                # 策略1：ML高置信度趋势交易
                if ml_pred['confidence'] >= 0.55:
                    action = 'BUY' if ml_pred['direction'] == 1 else 'SELL'
                    reason = f"ML信号(置信度{ml_pred['confidence']:.2f})"
                    use_grid = is_sideways  # 震荡市用网格
                
                # 策略2：震荡市网格
                elif is_sideways:
                    current = df.iloc[-1]
                    bb_mid = current['bb_mid']
                    
                    if current_price > bb_mid * 1.005:  # 高于中轨1%做空
                        action = 'SELL'
                        reason = "震荡市上轨做空"
                        use_grid = True
                    elif current_price < bb_mid * 0.995:  # 低于中轨1%做多
                        action = 'BUY'
                        reason = "震荡市下轨做多"
                        use_grid = True
                
                # 执行交易
                if action:
                    self.open_position(action, current_price, reason, use_grid)
                
                time.sleep(10)
                
            except KeyboardInterrupt:
                logger.info("收到停止信号")
                if self.position:
                    price = self.api.get_price(self.symbol)
                    self.close_position(price, "程序退出")
                break
            except Exception as e:
                logger.error(f"错误: {e}")
                time.sleep(5)


def main():
    if CONFIG["MODE"] != "LIVE":
        logger.warning(f"当前模式: {CONFIG['MODE']}，输入LIVE确认实盘:")
        if input().strip() != "LIVE":
            return
    
    trader = V12MLGridLiveTrader()
    trader.run()


if __name__ == "__main__":
    main()