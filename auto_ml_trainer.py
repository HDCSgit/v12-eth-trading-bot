#!/usr/bin/env python3
"""
ML模型定时自动训练模块
=========================
每6小时自动重新训练ML模型，保持模型最新

使用方法:
    方式1: 直接运行
        python auto_ml_trainer.py
    
    方式2: 后台运行
        python auto_ml_trainer.py --daemon
    
    方式3: 单次训练
        python auto_ml_trainer.py --once
"""

import schedule
import time
import logging
import argparse
from datetime import datetime
import os
import sys
import pandas as pd

# 导入配置
from config import CONFIG

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler('ml_auto_training.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class AutoMLTrainer:
    """自动ML训练器"""
    
    def __init__(self, interval='15m', training_hours=6):
        """
        初始化
        
        Args:
            interval: K线周期
            training_hours: 训练间隔小时数
        """
        self.interval = interval
        self.training_hours = training_hours
        self.training_count = 0
        self.last_training_time = None
        
    def run_training(self):
        """执行训练"""
        logger.info("="*70)
        logger.info(f"开始自动训练 #{self.training_count + 1}")
        logger.info(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("="*70)
        
        try:
            # 导入训练模块
            from offline_training import load_historical_data, create_advanced_features, create_labels, train_model, save_model
            
            # 1. 加载最新数据
            logger.info("1. 加载历史数据...")
            df = load_historical_data(source='sqlite')
            
            if len(df) < 1000:
                logger.warning(f"数据量不足: {len(df)} < 1000，跳过本次训练")
                return False
            
            # 根据配置选择数据范围模式
            data_mode = CONFIG.get("TRAINING_DATA_MODE", "sliding_window")
            
            if data_mode == "fixed_start":
                # 固定起点模式: 从指定日期开始，保留所有之后的数据
                fixed_start = CONFIG.get("TRAINING_FIXED_START_DATE", "2025-07-05")
                original_len = len(df)
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                df = df[df['timestamp'] >= fixed_start].copy()
                logger.info(f"   [数据范围-固定起点] 从 {original_len} 条限制到 {fixed_start} 之后: {len(df)} 条")
            else:
                # 滑动窗口模式: 最近N个月（确保最新鲜）
                sliding_months = CONFIG.get("TRAINING_SLIDING_MONTHS", 9)
                bars_per_month = 30 * 24 * 4  # 15m bars
                max_bars = sliding_months * bars_per_month
                original_len = len(df)
                if len(df) > max_bars:
                    df = df.tail(max_bars).copy()
                logger.info(f"   [数据范围-滑动窗口] 从 {original_len} 条限制到最近{sliding_months}个月: {len(df)} 条")
            
            if len(df) < 1000:
                logger.warning(f"数据过滤后不足: {len(df)} < 1000")
                return False
            
            logger.info(f"   加载了 {len(df)} 条记录")
            
            # 2. 特征工程
            logger.info("2. 生成特征...")
            df = create_advanced_features(df)
            
            # 3. 创建标签（15分钟框架：预测未来30分钟，阈值0.5%）
            logger.info("3. 创建标签...")
            forecast_periods = 2  # 2根15分钟K线 = 30分钟
            threshold = 0.005     # 0.5%
            df = create_labels(df, forecast_periods=forecast_periods, threshold=threshold)
            
            # 4. 检查是否有新数据
            if self.last_training_time:
                new_data = df[df['timestamp'] > self.last_training_time]
                logger.info(f"   新增数据: {len(new_data)} 条")
                if len(new_data) < 50:
                    logger.info("新增数据不足，跳过训练")
                    return False
            
            # 5. 训练模型
            logger.info("4. 训练模型...")
            
            # 尝试增量训练
            model, scaler, metrics = self._train_with_incremental(df)
            
            # 6. 保存模型
            logger.info("5. 保存模型...")
            save_model(model, scaler, metrics)
            
            # 7. 更新状态
            self.training_count += 1
            self.last_training_time = datetime.now()
            
            # 8. 发送通知（如果有配置）
            self._send_notification(f"ML模型训练完成 #{self.training_count}", 
                                   f"准确率: {metrics['accuracy']*100:.1f}%, 样本: {metrics['train_samples']}")
            
            logger.info("="*70)
            logger.info(f"训练 #{self.training_count} 完成!")
            logger.info(f"准确率: {metrics['accuracy']*100:.2f}%")
            logger.info(f"训练样本: {metrics['train_samples']}")
            logger.info("="*70)
            
            return True
            
        except Exception as e:
            logger.error(f"训练失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def _train_with_incremental(self, df):
        """使用增量训练"""
        import pickle
        from offline_training import create_advanced_features, create_labels, train_model
        from sklearn.preprocessing import StandardScaler
        import xgboost as xgb
        
        # 尝试加载现有模型
        existing_model = None
        existing_scaler = None
        
        if os.path.exists('ml_model_trained.pkl'):
            try:
                with open('ml_model_trained.pkl', 'rb') as f:
                    pkg = pickle.load(f)
                    existing_model = pkg.get('model')
                    existing_scaler = pkg.get('scaler')
                logger.info("   加载现有模型进行增量训练")
            except Exception as e:
                logger.warning(f"   无法加载现有模型: {e}，将全量训练")
        
        # 准备数据
        feature_cols = [
            'returns', 'log_returns', 'rsi_6', 'rsi_14', 'rsi_24',
            'macd', 'macd_signal', 'macd_hist', 'bb_width', 'bb_position',
            'trend_short', 'trend_mid', 'volume_ratio', 'taker_ratio',
            'momentum_5', 'momentum_10', 'momentum_20', 'atr_pct',
            'price_position', 'hour', 'day_of_week'
        ]
        
        mask = df['target'] != -1
        X = df[feature_cols].loc[mask]
        y = df['target'].loc[mask]
        
        # 删除NaN
        valid_idx = X.dropna().index
        X = X.loc[valid_idx]
        y = y.loc[valid_idx]
        
        if existing_scaler:
            X_scaled = existing_scaler.transform(X)
            scaler = existing_scaler
        else:
            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X)
        
        # 训练
        if existing_model and len(X) > 100:
            # 增量训练
            logger.info(f"   增量训练: 新增 {len(X)} 个样本")
            new_model = xgb.XGBClassifier(
                n_estimators=50,  # 增量时少训练一些
                max_depth=4,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8
            )
            new_model.fit(X_scaled, y, xgb_model=existing_model.get_booster())
            model = new_model
        else:
            # 全量训练
            logger.info(f"   全量训练: {len(X)} 个样本")
            model = xgb.XGBClassifier(
                n_estimators=300,
                max_depth=6,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                random_state=42
            )
            model.fit(X_scaled, y)
        
        # 计算指标
        from sklearn.metrics import accuracy_score
        y_pred = model.predict(X_scaled)
        accuracy = accuracy_score(y, y_pred)
        
        importance = dict(zip(feature_cols, model.feature_importances_))
        top_features = sorted(importance.items(), key=lambda x: x[1], reverse=True)[:10]
        
        metrics = {
            'accuracy': accuracy,
            'train_samples': len(X),
            'top_features': top_features,
            'training_time': datetime.now().isoformat(),
            'is_incremental': existing_model is not None
        }
        
        return model, scaler, metrics
    
    def _send_notification(self, title, message):
        """发送通知"""
        # 这里可以集成微信/钉钉/邮件通知
        logger.info(f"[通知] {title}: {message}")
    
    def schedule_training(self):
        """设置定时训练"""
        logger.info(f"设置定时训练: 每 {self.training_hours} 小时")
        
        # 使用schedule库
        if self.training_hours == 1:
            schedule.every().hour.do(self.run_training)
        elif self.training_hours == 2:
            schedule.every(2).hours.do(self.run_training)
        elif self.training_hours == 4:
            schedule.every(4).hours.do(self.run_training)
        elif self.training_hours == 6:
            schedule.every(6).hours.do(self.run_training)
        elif self.training_hours == 12:
            schedule.every(12).hours.do(self.run_training)
        else:
            schedule.every(self.training_hours).hours.do(self.run_training)
        
        # 立即执行一次
        logger.info("立即执行首次训练...")
        self.run_training()
        
        # 保持运行
        logger.info("定时训练已启动，按Ctrl+C停止...")
        try:
            while True:
                schedule.run_pending()
                time.sleep(60)  # 每分钟检查一次
        except KeyboardInterrupt:
            logger.info("定时训练已停止")
    
    def run_once(self):
        """只运行一次"""
        return self.run_training()


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='ML模型自动训练器')
    parser.add_argument('--interval', default='15m', help='K线周期 (默认: 15m)')
    parser.add_argument('--hours', type=int, default=6, help='训练间隔小时数 (默认: 6)')
    parser.add_argument('--once', action='store_true', help='只运行一次')
    parser.add_argument('--daemon', action='store_true', help='后台定时运行')
    
    args = parser.parse_args()
    
    print("="*70)
    print("V12 ML模型自动训练器")
    print("="*70)
    print(f"K线周期: {args.interval}")
    print(f"训练间隔: {args.hours}小时")
    print(f"运行模式: {'单次' if args.once else '定时'}")
    print("="*70)
    print()
    
    trainer = AutoMLTrainer(interval=args.interval, training_hours=args.hours)
    
    if args.once:
        # 单次训练
        success = trainer.run_once()
        sys.exit(0 if success else 1)
    else:
        # 定时训练
        trainer.schedule_training()


if __name__ == '__main__':
    main()
