"""
市场环境检测模型训练器
基于XGBoost的多分类训练流程
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
import logging
from pathlib import Path

# XGBoost导入（可选依赖）
try:
    import xgboost as xgb
    XGBOOST_AVAILABLE = True
except ImportError:
    XGBOOST_AVAILABLE = False
    logging.warning("XGBoost not installed. V2 will not work.")

from .features import RegimeFeatureExtractor


class MarketRegimeTrainer:
    """市场环境检测模型训练器"""
    
    # 市场环境类别定义（优化版：减少类别数，提高区分度）
    # 合并稀有类别，专注主要市场环境
    REGIME_CLASSES = [
        'SIDEWAYS',           # 震荡市（约36%）
        'TREND_UP',           # 上涨趋势（强+弱合并，约30%）
        'TREND_DOWN',         # 下跌趋势（强+弱合并，约29%）
        'BREAKOUT',           # 突破行情（约3%）
        'EXTREME',            # 极端行情（PUMP+DUMP合并，约4%）
    ]
    
    # 原始标签到优化类别的映射
    CLASS_MAPPING = {
        'SIDEWAYS': 'SIDEWAYS',
        'WEAK_TREND_UP': 'TREND_UP',
        'TRENDING_UP': 'TREND_UP',
        'WEAK_TREND_DOWN': 'TREND_DOWN',
        'TRENDING_DOWN': 'TREND_DOWN',
        'BREAKOUT': 'BREAKOUT',
        'BREAKDOWN': 'BREAKOUT',  # 突破包含向上和向下
        'PUMP': 'EXTREME',
        'DUMP': 'EXTREME',
        'HIGH_VOL': 'SIDEWAYS',
        'REVERSAL_TOP': 'SIDEWAYS',
        'REVERSAL_BOTTOM': 'SIDEWAYS',
    }
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.feature_extractor = RegimeFeatureExtractor()
        self.model = None
        self.label_encoder = {cls: i for i, cls in enumerate(self.REGIME_CLASSES)}
        self.label_decoder = {i: cls for cls, i in self.label_encoder.items()}
        
        # 训练参数
        self.lookforward = self.config.get('LOOKFORWARD_PERIODS', 12)
        self.return_threshold = self.config.get('RETURN_THRESHOLD', 0.015)
        self.test_size = self.config.get('TEST_SIZE', 0.2)
        
    def prepare_dataset(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.Series]:
        """
        从原始数据准备训练集 - 限制最近9个月
        
        Returns:
            X: 特征DataFrame
            y: 标签Series
        """
        # CRITICAL: 只使用最近9个月的数据
        # 9个月 * 30天 * 24小时 * 4 (15m bars) = 25920 bars
        NINE_MONTHS_BARS = 9 * 30 * 24 * 4
        if len(df) > NINE_MONTHS_BARS:
            original_len = len(df)
            df = df.tail(NINE_MONTHS_BARS).copy()
            print(f"[数据限制] 从 {original_len} 条限制到最近9个月: {len(df)} 条")
        
        print("Extracting features...")
        features_df = self.feature_extractor.extract(df)
        
        print("Generating labels...")
        labels = self._generate_labels(df)
        
        # 对齐长度（特征计算有rolling窗口）
        min_len = min(len(features_df), len(labels))
        features_df = features_df.iloc[-min_len:].copy()
        labels = labels.iloc[-min_len:].copy()
        
        # 移除NaN
        valid_idx = features_df.notna().all(axis=1) & labels.notna()
        features_df = features_df[valid_idx]
        labels = labels[valid_idx]
        
        # 映射到优化后的类别
        labels = labels.map(lambda x: self.CLASS_MAPPING.get(x, x))
        
        # 只保留定义的类别
        valid_classes = set(self.REGIME_CLASSES)
        labels = labels[labels.isin(valid_classes)]
        features_df = features_df.loc[labels.index]
        
        print(f"Dataset prepared: {len(features_df)} samples")
        print(f"Label distribution:\n{labels.value_counts()}")
        
        # 检查类别平衡
        min_count = labels.value_counts().min()
        if min_count < 10:
            print(f"WARNING: Some classes have very few samples (min={min_count})")
            print("Consider collecting more data or adjusting parameters")
        
        return features_df, labels
    
    def _generate_labels(self, df: pd.DataFrame) -> pd.Series:
        """
        生成市场环境标签（核心逻辑）
        
        基于多维度评估：
        1. 方向性：未来N周期净收益
        2. 持续性：收益是否持续（最大回撤vs最大收益）
        3. 波动性：过程中的波动程度
        4. 速度：收益是快速爆发还是缓慢积累
        """
        n = self.lookforward
        labels = []
        
        for i in range(len(df)):
            if i + n >= len(df):
                labels.append(None)
                continue
            
            # 获取未来n个周期数据
            future_prices = df['close'].iloc[i:i+n+1].values
            future_highs = df['high'].iloc[i:i+n+1].values
            future_lows = df['low'].iloc[i:i+n+1].values
            
            current_price = future_prices[0]
            final_price = future_prices[-1]
            
            # 维度1: 总收益
            total_return = (final_price - current_price) / current_price
            
            # 维度2: 持续性指标
            max_price = np.max(future_prices)
            min_price = np.min(future_prices)
            max_runup = (max_price - current_price) / current_price
            max_drawdown = (current_price - min_price) / current_price
            
            # 持续性比率（越高表示趋势越持续）
            sustainability = max_runup / (max_runup + max_drawdown + 1e-6)
            
            # 维度3: 波动性
            price_changes = np.diff(future_prices) / future_prices[:-1]
            volatility = np.std(price_changes)
            
            # 维度4: 速度（前1/3时间贡献的收益占比）
            one_third_idx = n // 3
            first_third_return = (future_prices[one_third_idx] - current_price) / current_price
            velocity = abs(first_third_return) / (abs(total_return) + 1e-6)
            velocity = min(velocity, 1.0)
            
            # 分类逻辑
            label = self._classify_regime(
                total_return, sustainability, volatility, velocity
            )
            labels.append(label)
        
        return pd.Series(labels, index=df.index)
    
    def _classify_regime(self, ret: float, sus: float, vol: float, vel: float) -> str:
        """
        优化版：5分类市场环境检测
        
        Args:
            ret: 总收益
            sus: 持续性比率 (0-1)
            vol: 波动率
            vel: 速度比率 (0-1)
        """
        abs_ret = abs(ret)
        
        # 1. 震荡市判定（低收益）
        if abs_ret < 0.012:  # 收益 < 1.2%
            return 'SIDEWAYS'
        
        # 2. 极端行情（极快速+大幅）
        if vel > 0.75 and abs_ret > 0.035:
            return 'EXTREME'
        
        # 3. 突破行情（快速+大幅+高持续性）
        if abs_ret > 0.03 and vel > 0.55 and sus > 0.45:
            return 'BREAKOUT'
        
        # 4. 趋势行情（中等以上收益+持续性）
        if abs_ret > 0.015 and sus > 0.4:
            return 'TREND_UP' if ret > 0 else 'TREND_DOWN'
        
        # 5. 弱趋势（中等收益但持续性不足）
        if abs_ret > 0.012:
            return 'TREND_UP' if ret > 0 else 'TREND_DOWN'
        
        # 默认震荡
        return 'SIDEWAYS'
    
    def train(self, X: pd.DataFrame, y: pd.Series, 
              eval_set: Optional[Tuple] = None,
              verbose: bool = True) -> Dict:
        """
        训练XGBoost模型
        
        Returns:
            训练历史记录
        """
        if not XGBOOST_AVAILABLE:
            raise ImportError("XGBoost is required for training")
        
        # 编码标签
        y_encoded = y.map(self.label_encoder)
        
        # 检查是否有无法编码的标签
        if y_encoded.isna().any():
            unknown_labels = y[y_encoded.isna()].unique()
            print(f"WARNING: Unknown labels found: {unknown_labels}")
            print("Removing samples with unknown labels")
            valid_mask = y_encoded.notna()
            X = X[valid_mask]
            y = y[valid_mask]
            y_encoded = y_encoded[valid_mask]
        
        y_encoded = y_encoded.astype(int)
        
        # 重新映射为连续整数（处理某些类别缺失的情况）
        unique_labels = sorted(y_encoded.unique())
        if len(unique_labels) < len(self.REGIME_CLASSES):
            print(f"Note: Only {len(unique_labels)} classes present out of {len(self.REGIME_CLASSES)}")
            print(f"Present classes: {[self.label_decoder[l] for l in unique_labels]}")
            
            # 创建新的连续编码映射
            new_encoder = {old: new for new, old in enumerate(unique_labels)}
            y_encoded = y_encoded.map(new_encoder)
            
            # 更新解码器
            self.label_decoder = {new: self.label_decoder[old] 
                                 for new, old in enumerate(unique_labels)}
        
        y_encoded = y_encoded.values
        
        # 计算类别权重（处理不平衡）
        class_weights = self._compute_class_weights(y)
        sample_weights = np.array([class_weights.get(label, 1.0) for label in y])
        
        # 训练/验证分割（时间序列分割）
        split_idx = int(len(X) * (1 - self.test_size))
        X_train, X_val = X.iloc[:split_idx], X.iloc[split_idx:]
        y_train, y_val = y_encoded[:split_idx], y_encoded[split_idx:]
        sw_train = sample_weights[:split_idx]
        
        # 获取实际的类别数量
        num_classes = len(np.unique(y_encoded))
        print(f"Training set: {len(X_train)}, Validation set: {len(X_val)}")
        print(f"Number of classes: {num_classes}")
        
        # XGBoost参数（优化版）
        params = {
            'objective': 'multi:softprob',
            'num_class': num_classes,
            'max_depth': 8,              # 增加深度
            'learning_rate': 0.1,        # 提高学习率
            'n_estimators': 300,         # 更多树
            'subsample': 0.9,            # 更多样本
            'colsample_bytree': 0.9,     # 更多特征
            'reg_alpha': 0.01,           # 减少正则化
            'reg_lambda': 0.1,
            'min_child_weight': 1,
            'gamma': 0.01,
            'random_state': 42,
        }
        
        self.model = xgb.XGBClassifier(**params)
        
        # 训练（兼容新旧版本XGBoost）
        fit_params = {
            'X': X_train,
            'y': y_train,
            'sample_weight': sw_train,
            'eval_set': [(X_val, y_val)],
            'verbose': verbose,
        }
        
        # 尝试使用early_stopping_rounds（新版本XGBoost需要放在fit_params中）
        try:
            # XGBoost 2.0+ API
            self.model.fit(**fit_params, early_stopping_rounds=20)
        except TypeError:
            # 旧版本或不同的API
            try:
                self.model.fit(**fit_params)
            except Exception as e:
                print(f"Training warning: {e}")
                # 最基本的训练方式
                self.model.fit(X_train, y_train, sample_weight=sw_train)
        
        # 评估
        train_acc = self.model.score(X_train, y_train)
        val_acc = self.model.score(X_val, y_val)
        
        print(f"\nTraining accuracy: {train_acc:.4f}")
        print(f"Validation accuracy: {val_acc:.4f}")
        
        return {
            'train_accuracy': train_acc,
            'val_accuracy': val_acc,
            'best_iteration': self.model.best_iteration if hasattr(self.model, 'best_iteration') else None,
        }
    
    def _compute_class_weights(self, y: pd.Series) -> Dict[str, float]:
        """计算类别权重（处理类别不平衡）"""
        counts = y.value_counts()
        total = len(y)
        n_classes = len(self.REGIME_CLASSES)
        
        weights = {}
        for cls in self.REGIME_CLASSES:
            count = counts.get(cls, 1)
            # 权重与频率成反比
            weights[cls] = total / (n_classes * count)
        
        return weights
    
    def cross_validate(self, X: pd.DataFrame, y: pd.Series, 
                       n_splits: int = 5) -> Dict:
        """
        时间序列交叉验证
        
        注意：不使用随机分割，避免数据泄露
        """
        fold_size = len(X) // n_splits
        scores = []
        
        for i in range(n_splits):
            train_end = fold_size * (i + 1)
            test_end = min(train_end + fold_size, len(X))
            
            if test_end > len(X) - 100:  # 确保测试集足够大
                break
            
            X_train = X.iloc[:train_end]
            y_train = y.iloc[:train_end]
            X_test = X.iloc[train_end:test_end]
            y_test = y.iloc[train_end:test_end]
            
            # 训练临时模型
            temp_trainer = MarketRegimeTrainer(self.config)
            temp_trainer.train(X_train, y_train, verbose=False)
            
            # 评估
            y_pred = temp_trainer.predict(X_test)
            accuracy = (y_pred == y_test).mean()
            scores.append(accuracy)
            
            print(f"Fold {i+1}: Accuracy = {accuracy:.4f}")
        
        return {
            'scores': scores,
            'mean': np.mean(scores),
            'std': np.std(scores),
        }
    
    def predict(self, X: pd.DataFrame) -> pd.Series:
        """预测标签"""
        if self.model is None:
            raise ValueError("Model not trained")
        
        y_pred = self.model.predict(X)
        return pd.Series([self.label_decoder.get(p, 'UNKNOWN') for p in y_pred])
    
    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """预测概率"""
        if self.model is None:
            raise ValueError("Model not trained")
        
        return self.model.predict_proba(X)
    
    def save(self, path: str):
        """保存模型"""
        if self.model is None:
            raise ValueError("Model not trained")
        
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        
        import pickle
        with open(path, 'wb') as f:
            pickle.dump({
                'model': self.model,
                'label_encoder': self.label_encoder,
                'label_decoder': self.label_decoder,
                'config': self.config,
                'feature_cols': self.feature_extractor.FEATURE_COLS,
            }, f)
        
        print(f"Model saved to {path}")
    
    def load(self, path: str):
        """加载模型"""
        import pickle
        with open(path, 'rb') as f:
            data = pickle.load(f)
        
        self.model = data['model']
        self.label_encoder = data['label_encoder']
        self.label_decoder = data['label_decoder']
        self.config = data['config']
        
        print(f"Model loaded from {path}")
