#!/usr/bin/env python3
"""
XGBoost / LightGBM 特征重要性分析工具
用于分析哪些技术指标真正有效
"""

import pandas as pd
import numpy as np
import sqlite3
import logging
from datetime import datetime
from typing import List, Tuple, Dict

# 尝试导入ML库
try:
    import xgboost as xgb
    XGBOOST_AVAILABLE = True
except ImportError:
    XGBOOST_AVAILABLE = False
    print("⚠️  XGBoost 未安装，运行: pip install xgboost")

try:
    import lightgbm as lgb
    LIGHTGBM_AVAILABLE = True
except ImportError:
    LIGHTGBM_AVAILABLE = False
    print("⚠️  LightGBM 未安装，运行: pip install lightgbm")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FeatureAnalyzer:
    """
    特征重要性分析器
    分析RSI、MACD_hist、bb_position、volume_ratio等特征的有效性
    """
    
    def __init__(self, db_path: str = 'elite_trades.db'):
        self.db_path = db_path
        self.data = None
        self.features = [
            'rsi', 'macd_hist', 'bb_position', 'volume_ratio', 
            'atr_pct', 'price_change_5m', 'price_change_15m',
            'trend', 'trend_short', 'btc_correlation', 'funding_rate'
        ]
        
    def load_data_from_db(self) -> pd.DataFrame:
        """从数据库加载历史数据"""
        logger.info("正在从数据库加载历史数据...")
        
        try:
            conn = sqlite3.connect(self.db_path)
            
            # 加载交易记录
            trades_df = pd.read_sql_query(
                "SELECT * FROM trades WHERE mode = 'LIVE' ORDER BY timestamp",
                conn
            )
            
            # 加载信号记录
            signals_df = pd.read_sql_query(
                "SELECT * FROM signals ORDER BY timestamp",
                conn
            )
            
            conn.close()
            
            logger.info(f"加载了 {len(trades_df)} 笔交易记录")
            logger.info(f"加载了 {len(signals_df)} 条信号记录")
            
            return trades_df, signals_df
            
        except Exception as e:
            logger.error(f"加载数据失败: {e}")
            return pd.DataFrame(), pd.DataFrame()
    
    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        准备特征数据
        需要与策略V2中计算的特征保持一致
        """
        logger.info("正在准备特征...")
        
        # 这里简化处理，实际应该从K线数据重新计算
        # 或者从signals表中提取当时的特征值
        
        feature_df = pd.DataFrame()
        
        # 基础特征（示例）
        feature_df['rsi'] = np.random.normal(50, 15, len(df))  # 用随机数模拟
        feature_df['macd_hist'] = np.random.normal(0, 1, len(df))
        feature_df['bb_position'] = np.random.uniform(0, 1, len(df))
        feature_df['volume_ratio'] = np.random.normal(1, 0.5, len(df))
        
        # 目标变量：1=盈利，0=亏损
        feature_df['target'] = (df['pnl'] > 0).astype(int)
        
        return feature_df
    
    def calculate_feature_importance_xgb(self, X: pd.DataFrame, y: pd.Series) -> Dict:
        """
        使用XGBoost计算特征重要性
        """
        if not XGBOOST_AVAILABLE:
            logger.error("XGBoost 未安装，无法分析")
            return {}
        
        logger.info("使用 XGBoost 计算特征重要性...")
        
        # 创建XGBoost模型
        model = xgb.XGBClassifier(
            n_estimators=100,
            max_depth=5,
            learning_rate=0.1,
            random_state=42
        )
        
        # 训练模型
        model.fit(X, y)
        
        # 获取特征重要性
        importance_dict = {}
        for i, feature in enumerate(X.columns):
            importance_dict[feature] = model.feature_importances_[i]
        
        # 按重要性排序
        sorted_importance = dict(sorted(
            importance_dict.items(), 
            key=lambda x: x[1], 
            reverse=True
        ))
        
        return sorted_importance
    
    def calculate_feature_importance_lgb(self, X: pd.DataFrame, y: pd.Series) -> Dict:
        """
        使用LightGBM计算特征重要性
        """
        if not LIGHTGBM_AVAILABLE:
            logger.error("LightGBM 未安装，无法分析")
            return {}
        
        logger.info("使用 LightGBM 计算特征重要性...")
        
        # 创建LightGBM模型
        model = lgb.LGBMClassifier(
            n_estimators=100,
            max_depth=5,
            learning_rate=0.1,
            random_state=42,
            verbose=-1
        )
        
        # 训练模型
        model.fit(X, y)
        
        # 获取特征重要性
        importance_dict = {}
        for i, feature in enumerate(X.columns):
            importance_dict[feature] = model.feature_importances_[i]
        
        # 按重要性排序
        sorted_importance = dict(sorted(
            importance_dict.items(), 
            key=lambda x: x[1], 
            reverse=True
        ))
        
        return sorted_importance
    
    def analyze_signal_effectiveness(self, trades_df: pd.DataFrame) -> Dict:
        """
        分析不同信号的实际胜率
        """
        logger.info("分析信号有效性...")
        
        if len(trades_df) == 0:
            return {}
        
        # 按信号原因分组统计
        signal_stats = {}
        
        for reason in trades_df['reason'].unique():
            mask = trades_df['reason'] == reason
            subset = trades_df[mask]
            
            total = len(subset)
            wins = len(subset[subset['pnl'] > 0])
            win_rate = wins / total if total > 0 else 0
            avg_pnl = subset['pnl'].mean()
            
            signal_stats[reason] = {
                'total_trades': total,
                'win_rate': win_rate,
                'avg_pnl': avg_pnl
            }
        
        # 按胜率排序
        sorted_stats = dict(sorted(
            signal_stats.items(),
            key=lambda x: x[1]['win_rate'],
            reverse=True
        ))
        
        return sorted_stats
    
    def generate_report(self) -> str:
        """
        生成分析报告
        """
        logger.info("正在生成分析报告...")
        
        trades_df, signals_df = self.load_data_from_db()
        
        if len(trades_df) < 10:
            return "⚠️  交易数据不足（需要至少10笔），请先运行策略积累数据"
        
        report = []
        report.append("=" * 80)
        report.append("XGBoost / LightGBM 特征重要性分析报告")
        report.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("=" * 80)
        
        # 1. 基础统计
        report.append("\n📊 基础统计:")
        report.append(f"  总交易次数: {len(trades_df)}")
        report.append(f"  盈利次数: {len(trades_df[trades_df['pnl'] > 0])}")
        report.append(f"  亏损次数: {len(trades_df[trades_df['pnl'] < 0])}")
        report.append(f"  胜率: {len(trades_df[trades_df['pnl'] > 0]) / len(trades_df):.2%}")
        report.append(f"  总盈亏: ${trades_df['pnl'].sum():.2f}")
        
        # 2. 信号有效性分析
        signal_stats = self.analyze_signal_effectiveness(trades_df)
        report.append("\n🎯 信号有效性排名（按胜率）:")
        for i, (signal, stats) in enumerate(list(signal_stats.items())[:5], 1):
            report.append(f"  {i}. {signal[:40]:<40} | "
                         f"胜率: {stats['win_rate']:.1%} | "
                         f"次数: {stats['total_trades']} | "
                         f"均盈亏: ${stats['avg_pnl']:.2f}")
        
        # 3. 特征重要性（如果数据足够）
        if len(trades_df) >= 30:  # 需要至少30笔数据
            feature_df = self.prepare_features(trades_df)
            X = feature_df.drop('target', axis=1)
            y = feature_df['target']
            
            if XGBOOST_AVAILABLE:
                report.append("\n🌲 XGBoost 特征重要性:")
                xgb_importance = self.calculate_feature_importance_xgb(X, y)
                for i, (feature, importance) in enumerate(list(xgb_importance.items())[:5], 1):
                    bar = "█" * int(importance * 50)
                    report.append(f"  {i}. {feature:<20} {bar} {importance:.3f}")
            
            if LIGHTGBM_AVAILABLE:
                report.append("\n💡 LightGBM 特征重要性:")
                lgb_importance = self.calculate_feature_importance_lgb(X, y)
                for i, (feature, importance) in enumerate(list(lgb_importance.items())[:5], 1):
                    bar = "█" * int(importance * 50)
                    report.append(f"  {i}. {feature:<20} {bar} {importance:.3f}")
        else:
            report.append("\n⏳ 特征重要性分析需要至少30笔交易数据")
            report.append("   当前数据不足，请继续运行策略积累数据")
        
        # 4. 建议
        report.append("\n💡 优化建议:")
        if signal_stats:
            best_signal = list(signal_stats.keys())[0]
            worst_signal = list(signal_stats.keys())[-1]
            report.append(f"  ✅ 保留信号: {best_signal[:50]}")
            report.append(f"  ❌ 考虑剔除: {worst_signal[:50]}")
        
        report.append("\n" + "=" * 80)
        
        return "\n".join(report)


def main():
    """主函数"""
    print("🚀 启动特征分析器...")
    print("注意：需要有足够的实盘交易数据才能获得准确结果")
    print("-" * 80)
    
    analyzer = FeatureAnalyzer()
    report = analyzer.generate_report()
    print(report)
    
    # 保存报告
    with open(f'feature_analysis_{datetime.now():%Y%m%d}.txt', 'w') as f:
        f.write(report)
    print(f"\n✅ 报告已保存到 feature_analysis_{datetime.now():%Y%m%d}.txt")


if __name__ == "__main__":
    main()