#!/usr/bin/env python3
"""
ML模型准确度分析工具
========================
分析ML信号的历史表现，评估预测准确度

主要指标:
1. 预测准确率 - ML预测方向与实际走势的匹配度
2. 置信度校准 - 高置信度预测是否更准确
3. 特征稳定性 - 重要特征是否稳定
4. 信号胜率 - ML信号触发的交易胜率
"""

import sqlite3
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MLAccuracyAnalyzer:
    """ML准确度分析器"""
    
    def __init__(self, db_path: str = "v12_optimized.db"):
        self.db_path = db_path
        
    def load_signals(self, hours: int = 24) -> pd.DataFrame:
        """加载最近N小时的信号记录"""
        conn = sqlite3.connect(self.db_path)
        
        query = f"""
        SELECT 
            timestamp,
            action as signal_action,
            confidence as signal_confidence,
            source as signal_source,
            price,
            regime,
            confidence as ml_confidence,
            CASE 
                WHEN action = 'BUY' THEN 1
                WHEN action = 'SELL' THEN -1
                ELSE 0
            END as ml_direction
        FROM signals
        WHERE timestamp >= datetime('now', '-{hours} hours')
        ORDER BY timestamp
        """
        
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        return df
    
    def load_trades(self, hours: int = 24) -> pd.DataFrame:
        """加载交易记录"""
        conn = sqlite3.connect(self.db_path)
        
        query = f"""
        SELECT 
            timestamp,
            side,
            entry_price,
            exit_price,
            pnl_pct,
            result,
            confidence as signal_confidence,
            confidence as ml_confidence,
            reason as exit_strategy
        FROM trades
        WHERE timestamp >= datetime('now', '-{hours} hours')
        ORDER BY timestamp
        """
        
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        return df
    
    def analyze_confidence_vs_accuracy(self, df: pd.DataFrame) -> dict:
        """分析置信度与准确率的关系"""
        
        # 计算未来收益（假设信号后3根K线）
        df['future_return'] = df['price'].shift(-3) / df['price'] - 1
        
        # 实际方向
        df['actual_direction'] = np.where(df['future_return'] > 0, 1, -1)
        
        # 预测方向（从signal_action推断）
        df['predicted_direction'] = np.where(
            df['signal_action'] == 'BUY', 1,
            np.where(df['signal_action'] == 'SELL', -1, 0)
        )
        
        # 只分析有方向预测的记录
        mask = df['predicted_direction'] != 0
        df_valid = df[mask].copy()
        
        if len(df_valid) == 0:
            return {}
        
        # 是否正确预测
        df_valid['correct'] = df_valid['predicted_direction'] == df_valid['actual_direction']
        
        # 按置信度分桶分析
        bins = [0, 0.6, 0.7, 0.8, 0.9, 1.0]
        labels = ['0.5-0.6', '0.6-0.7', '0.7-0.8', '0.8-0.9', '0.9-1.0']
        df_valid['confidence_bucket'] = pd.cut(df_valid['ml_confidence'], bins=bins, labels=labels)
        
        accuracy_by_confidence = df_valid.groupby('confidence_bucket').agg({
            'correct': ['mean', 'count'],
            'future_return': 'mean'
        }).round(3)
        
        return {
            'overall_accuracy': df_valid['correct'].mean(),
            'total_signals': len(df_valid),
            'by_confidence': accuracy_by_confidence,
            'high_conf_accuracy': df_valid[df_valid['ml_confidence'] >= 0.75]['correct'].mean()
        }
    
    def analyze_trade_performance(self, trades_df: pd.DataFrame) -> dict:
        """分析ML信号触发的交易表现"""
        
        if len(trades_df) == 0:
            return {}
        
        # 总体表现
        total_trades = len(trades_df)
        win_rate = (trades_df['result'] == 'WIN').mean()
        avg_pnl = trades_df['pnl_pct'].mean()
        
        # 按ML置信度分组
        trades_df['confidence_bucket'] = pd.cut(
            trades_df['ml_confidence'], 
            bins=[0, 0.7, 0.8, 0.9, 1.0],
            labels=['<0.7', '0.7-0.8', '0.8-0.9', '>0.9']
        )
        
        performance_by_conf = trades_df.groupby('confidence_bucket').agg({
            'pnl_pct': ['mean', 'std', 'count'],
            'result': lambda x: (x == 'WIN').mean()
        }).round(4)
        
        return {
            'total_trades': total_trades,
            'overall_win_rate': win_rate,
            'avg_pnl': avg_pnl,
            'by_confidence': performance_by_conf,
            'high_conf_trades': len(trades_df[trades_df['ml_confidence'] >= 0.8]),
            'high_conf_win_rate': trades_df[trades_df['ml_confidence'] >= 0.8]['result'].apply(lambda x: x == 'WIN').mean() if len(trades_df[trades_df['ml_confidence'] >= 0.8]) > 0 else 0
        }
    
    def generate_report(self, hours: int = 24) -> str:
        """生成分析报告"""
        
        signals_df = self.load_signals(hours)
        trades_df = self.load_trades(hours)
        
        report = []
        report.append("="*70)
        report.append(f"ML模型准确度分析报告 - 最近{hours}小时")
        report.append("="*70)
        
        # 1. 信号统计
        report.append(f"\n【信号统计】")
        report.append(f"总信号数: {len(signals_df)}")
        report.append(f"BUY信号: {len(signals_df[signals_df['signal_action'] == 'BUY'])}")
        report.append(f"SELL信号: {len(signals_df[signals_df['signal_action'] == 'SELL'])}")
        report.append(f"平均ML置信度: {signals_df['ml_confidence'].mean():.2f}")
        
        # 2. 置信度与准确率分析
        conf_analysis = self.analyze_confidence_vs_accuracy(signals_df)
        if conf_analysis:
            report.append(f"\n【置信度校准分析】")
            report.append(f"整体预测准确率: {conf_analysis['overall_accuracy']*100:.1f}%")
            report.append(f"高置信度(>=0.75)准确率: {conf_analysis['high_conf_accuracy']*100:.1f}%")
            report.append(f"\n按置信度分桶:")
            report.append(str(conf_analysis['by_confidence']))
        
        # 3. 交易表现
        trade_analysis = self.analyze_trade_performance(trades_df)
        if trade_analysis:
            report.append(f"\n【交易表现】")
            report.append(f"总交易数: {trade_analysis['total_trades']}")
            report.append(f"整体胜率: {trade_analysis['overall_win_rate']*100:.1f}%")
            report.append(f"平均盈亏: {trade_analysis['avg_pnl']*100:.2f}%")
            report.append(f"高置信度交易数: {trade_analysis['high_conf_trades']}")
            report.append(f"高置信度胜率: {trade_analysis['high_conf_win_rate']*100:.1f}%")
            report.append(f"\n按置信度分桶表现:")
            report.append(str(trade_analysis['by_confidence']))
        
        report.append("\n" + "="*70)
        
        return "\n".join(report)


def main():
    """主函数"""
    analyzer = MLAccuracyAnalyzer("v12_optimized.db")
    
    # 生成24小时报告
    report = analyzer.generate_report(hours=24)
    print(report)
    
    # 保存报告
    with open(f"ml_accuracy_report_{datetime.now().strftime('%Y%m%d')}.txt", 'w', encoding='utf-8') as f:
        f.write(report)
    
    logger.info("报告已生成")


if __name__ == "__main__":
    main()
