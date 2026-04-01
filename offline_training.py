#!/usr/bin/env python3
"""
ML模型离线训练工具
====================
使用下载的历史数据训练模型，提高模型稳定性

使用方法:
    python offline_training.py

功能:
1. 加载历史数据(30天+)
2. 训练ML模型
3. 评估模型性能
4. 保存训练好的模型
"""

import pandas as pd
import numpy as np
import sqlite3
import pickle
from config import CONFIG
import json
from datetime import datetime
from typing import Dict, Tuple
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')
logger = logging.getLogger(__name__)


def load_historical_data(source='sqlite') -> pd.DataFrame:
    """加载历史数据"""
    if source == 'sqlite':
        try:
            conn = sqlite3.connect('historical_data.db')
            df = pd.read_sql_query('''
                SELECT * FROM klines 
                ORDER BY timestamp
            ''', conn)
            conn.close()
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            logger.info(f"从SQLite加载: {len(df)} 条记录")
            return df
        except Exception as e:
            logger.error(f"SQLite加载失败: {e}")
    
    if source == 'csv':
        import glob
        csv_files = glob.glob('data/eth_usdt_1m_*.csv')
        if csv_files:
            df = pd.read_csv(csv_files[-1])  # 最新的文件
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            logger.info(f"从CSV加载: {len(df)} 条记录")
            return df
    
    return pd.DataFrame()


def create_advanced_features(df: pd.DataFrame) -> pd.DataFrame:
    """创建高级特征"""
    logger.info("生成特征...")
    
    # 价格特征
    df['returns'] = df['close'].pct_change()
    df['log_returns'] = np.log(df['close'] / df['close'].shift(1))
    
    # RSI
    for period in [6, 14, 24]:
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        df[f'rsi_{period}'] = 100 - (100 / (1 + rs))
    
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
    
    # 移动平均线
    for period in [10, 20, 55, 120]:
        df[f'ma_{period}'] = df['close'].rolling(period).mean()
    
    # 趋势
    df['trend_short'] = np.where(df['ma_10'] > df['ma_20'], 1, -1)
    df['trend_mid'] = np.where(df['ma_20'] > df['ma_55'], 1, -1)
    
    # 成交量
    df['volume_ma'] = df['volume'].rolling(20).mean()
    df['volume_ratio'] = df['volume'] / df['volume_ma']
    df['taker_ratio'] = df['taker_buy_base'] / df['volume']
    
    # 动量
    for period in [5, 10, 20]:
        df[f'momentum_{period}'] = df['close'].pct_change(period)
    
    # ATR
    tr1 = df['high'] - df['low']
    tr2 = abs(df['high'] - df['close'].shift())
    tr3 = abs(df['low'] - df['close'].shift())
    df['atr'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).rolling(14).mean()
    df['atr_pct'] = df['atr'] / df['close']
    
    # 价格位置
    df['high_20'] = df['high'].rolling(20).max()
    df['low_20'] = df['low'].rolling(20).min()
    df['price_position'] = (df['close'] - df['low_20']) / (df['high_20'] - df['low_20'] + 1e-10)
    
    # 时间特征
    df['hour'] = df['timestamp'].dt.hour
    df['day_of_week'] = df['timestamp'].dt.dayofweek
    
    logger.info(f"特征生成完成: {len(df.columns)} 列")
    return df


def create_labels(df: pd.DataFrame, forecast_periods: int = 10, threshold: float = 0.003) -> pd.DataFrame:
    """
    创建标签
    
    Args:
        forecast_periods: 预测未来多少根K线
        threshold: 收益阈值
    """
    logger.info(f"创建标签: 预测未来{forecast_periods}根K线, 阈值{threshold*100:.2f}%")
    
    df['future_return'] = df['close'].shift(-forecast_periods) / df['close'] - 1
    
    df['target'] = np.where(
        df['future_return'] > threshold, 1,      # 上涨
        np.where(df['future_return'] < -threshold, 0, -1)  # 下跌或震荡
    )
    
    # 统计标签分布
    label_counts = df['target'].value_counts()
    logger.info(f"标签分布: 上涨={label_counts.get(1, 0)}, 下跌={label_counts.get(0, 0)}, 忽略={label_counts.get(-1, 0)}")
    
    return df


def train_model(df: pd.DataFrame) -> Tuple[object, object, Dict]:
    """训练模型"""
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import accuracy_score, classification_report
    import xgboost as xgb
    
    # 选择特征
    feature_cols = [
        'returns', 'log_returns', 'rsi_6', 'rsi_14', 'rsi_24',
        'macd', 'macd_signal', 'macd_hist', 'bb_width', 'bb_position',
        'trend_short', 'trend_mid', 'volume_ratio', 'taker_ratio',
        'momentum_5', 'momentum_10', 'momentum_20', 'atr_pct',
        'price_position', 'hour', 'day_of_week'
    ]
    
    # 过滤有效样本
    mask = df['target'] != -1
    X = df[feature_cols].loc[mask]
    y = df['target'].loc[mask]
    
    # 删除NaN
    valid_idx = X.dropna().index
    X = X.loc[valid_idx]
    y = y.loc[valid_idx]
    
    logger.info(f"训练样本: {len(X)}")
    
    # 划分训练集和测试集
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, shuffle=False)
    
    # 标准化
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    
    # 训练模型
    logger.info("训练XGBoost模型...")
    model = xgb.XGBClassifier(
        n_estimators=300,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        eval_metric='logloss'
    )
    
    model.fit(X_train_scaled, y_train)
    
    # 评估
    y_pred = model.predict(X_test_scaled)
    accuracy = accuracy_score(y_test, y_pred)
    
    logger.info(f"测试集准确率: {accuracy*100:.2f}%")
    
    # 特征重要性
    importance = dict(zip(feature_cols, model.feature_importances_))
    top_features = sorted(importance.items(), key=lambda x: x[1], reverse=True)[:10]
    
    logger.info("Top 10 重要特征:")
    for feat, imp in top_features:
        logger.info(f"  {feat}: {imp:.4f}")
    
    metrics = {
        'accuracy': accuracy,
        'train_samples': len(X_train),
        'test_samples': len(X_test),
        'top_features': top_features,
        'training_time': datetime.now().isoformat()
    }
    
    return model, scaler, metrics


def save_model(model, scaler, metrics: Dict, filepath: str = 'ml_model_trained.pkl'):
    """保存模型"""
    model_package = {
        'model': model,
        'scaler': scaler,
        'metrics': metrics,
        'saved_at': datetime.now().isoformat()
    }
    
    with open(filepath, 'wb') as f:
        pickle.dump(model_package, f)
    
    logger.info(f"模型已保存到: {filepath}")
    
    # 同时保存metrics到JSON
    with open('ml_training_metrics.json', 'w') as f:
        json.dump(metrics, f, indent=2, default=str)


def main():
    """主函数"""
    print("="*70)
    print("ML模型离线训练工具")
    print("="*70)
    print()
    
    # 1. 加载数据
    print("1. 加载历史数据...")
    df = load_historical_data(source='sqlite')
    
    if len(df) == 0:
        print("❌ 没有找到历史数据")
        print("请先运行: python download_historical_data.py")
        return
    
    # 根据配置选择数据范围模式（默认滑动窗口，最新鲜）
    data_mode = CONFIG.get("TRAINING_DATA_MODE", "sliding_window")
    
    if data_mode == "fixed_start":
        # 固定起点模式: 从指定日期开始，保留所有之后的数据
        fixed_start = CONFIG.get("TRAINING_FIXED_START_DATE", "2025-07-05")
        original_len = len(df)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df[df['timestamp'] >= fixed_start].copy()
        print(f"   [数据范围-固定起点] 从 {original_len} 条限制到 {fixed_start} 之后: {len(df)} 条")
    else:
        # 滑动窗口模式: 最近N个月（确保最新鲜）
        sliding_months = CONFIG.get("TRAINING_SLIDING_MONTHS", 9)
        bars_per_month = 30 * 24 * 4  # 15m bars
        max_bars = sliding_months * bars_per_month
        original_len = len(df)
        if len(df) > max_bars:
            df = df.tail(max_bars).copy()
        print(f"   [数据范围-滑动窗口] 从 {original_len} 条限制到最近{sliding_months}个月: {len(df)} 条")
    
    if len(df) < 1000:
        print(f"❌ 数据过滤后不足: {len(df)} < 1000")
        return
    
    print(f"   加载了 {len(df)} 条记录")
    print()
    
    # 2. 特征工程
    print("2. 特征工程...")
    df = create_advanced_features(df)
    print()
    
    # 3. 创建标签
    print("3. 创建标签...")
    df = create_labels(df, forecast_periods=10, threshold=0.003)
    print()
    
    # 4. 训练模型
    print("4. 训练模型...")
    model, scaler, metrics = train_model(df)
    print()
    
    # 5. 保存模型
    print("5. 保存模型...")
    save_model(model, scaler, metrics)
    print()
    
    print("="*70)
    print("✅ 训练完成!")
    print("="*70)
    print()
    print(f"测试集准确率: {metrics['accuracy']*100:.2f}%")
    print(f"训练样本数: {metrics['train_samples']}")
    print()
    print("模型文件: ml_model_trained.pkl")
    print("指标文件: ml_training_metrics.json")
    print()
    print("现在可以将训练好的模型集成到交易系统中:")
    print("  修改 main_v12_live_optimized.py 加载此模型")


if __name__ == '__main__':
    main()
