#!/usr/bin/env python3
"""
ML环境检测反馈系统 - 可监督学习
=================================
职责：
1. 记录ML预测和实际结果
2. 评估预测准确度
3. 提供反馈用于模型改进
4. 支持在线学习和模型微调

Author: AI Assistant
Version: 1.0.0
Date: 2026-03-27
"""

import sqlite3
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class MLFeedbackRecord:
    """ML预测反馈记录"""
    timestamp: str
    ml_regime: str           # ML预测的环境
    tech_regime: str         # 技术指标环境
    final_regime: str        # 最终使用环境
    
    # 预测时的市场状态
    ml_direction: int        # ML预测方向
    ml_confidence: float     # ML置信度
    entry_price: float       # 入场价格
    
    # 实际结果（事后填充）
    exit_price: float = 0.0          # 出场价格
    actual_pnl: float = 0.0          # 实际盈亏
    actual_regime: str = None        # 实际环境（事后判断）
    prediction_correct: bool = None  # 预测是否正确
    
    # 评估指标
    price_change_5min: float = 0.0   # 5分钟后价格变化
    price_change_15min: float = 0.0  # 15分钟后价格变化
    max_drawdown: float = 0.0        # 最大回撤
    max_profit: float = 0.0          # 最大盈利


class MLFeedbackSystem:
    """
    ML反馈系统
    
    实现可监督学习的关键组件
    """
    
    def __init__(self, db_path: str = 'v12_optimized.db'):
        self.db_path = db_path
        self._init_database()
        
        # 准确度统计
        self.stats_cache = {}
        self.last_update = None
        
        logger.info("[MLFeedback] 反馈系统初始化完成")
    
    def _init_database(self):
        """初始化反馈数据库表"""
        conn = sqlite3.connect(self.db_path)
        
        # ML预测记录表
        conn.execute('''
            CREATE TABLE IF NOT EXISTS ml_predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                ml_regime TEXT,
                tech_regime TEXT,
                final_regime TEXT,
                ml_direction INTEGER,
                ml_confidence REAL,
                entry_price REAL,
                exit_price REAL DEFAULT 0,
                actual_pnl REAL DEFAULT 0,
                actual_regime TEXT,
                prediction_correct INTEGER,  -- 0=false, 1=true, NULL=unknown
                price_change_5min REAL DEFAULT 0,
                price_change_15min REAL DEFAULT 0,
                max_drawdown REAL DEFAULT 0,
                max_profit REAL DEFAULT 0,
                evaluated INTEGER DEFAULT 0,  -- 0=未评估, 1=已评估
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 准确度统计表（按天汇总）
        conn.execute('''
            CREATE TABLE IF NOT EXISTS ml_accuracy_stats (
                date TEXT PRIMARY KEY,
                total_predictions INTEGER DEFAULT 0,
                correct_predictions INTEGER DEFAULT 0,
                wrong_predictions INTEGER DEFAULT 0,
                accuracy_rate REAL DEFAULT 0,
                avg_confidence REAL DEFAULT 0,
                avg_pnl_when_correct REAL DEFAULT 0,
                avg_pnl_when_wrong REAL DEFAULT 0,
                regime_breakdown TEXT,  -- JSON格式
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 模型改进建议表
        conn.execute('''
            CREATE TABLE IF NOT EXISTS ml_improvement_suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                issue_type TEXT,  -- 'threshold', 'feature', 'timing'
                description TEXT,
                current_value TEXT,
                suggested_value TEXT,
                confidence REAL,
                applied INTEGER DEFAULT 0,  -- 0=未应用, 1=已应用
                applied_at TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def record_prediction(self, record: MLFeedbackRecord) -> int:
        """
        记录ML预测
        
        Returns:
            记录ID
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute('''
            INSERT INTO ml_predictions 
            (timestamp, ml_regime, tech_regime, final_regime, 
             ml_direction, ml_confidence, entry_price)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            record.timestamp,
            record.ml_regime,
            record.tech_regime,
            record.final_regime,
            record.ml_direction,
            record.ml_confidence,
            record.entry_price
        ))
        
        record_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        logger.debug(f"[MLFeedback] 记录预测 ID={record_id}, ML={record.ml_regime}")
        return record_id
    
    def update_result(self, record_id: int, exit_price: float, 
                     actual_pnl: float, prices_5min: List[float] = None,
                     prices_15min: List[float] = None):
        """
        更新预测的实际结果（事后评估）
        
        Args:
            record_id: 预测记录ID
            exit_price: 出场价格
            actual_pnl: 实际盈亏
            prices_5min: 5分钟内的价格序列
            prices_15min: 15分钟内的价格序列
        """
        # 计算事后环境
        actual_regime = self._determine_actual_regime(prices_15min)
        
        # 计算价格变化
        pc_5min = self._calc_price_change(prices_5min) if prices_5min else 0
        pc_15min = self._calc_price_change(prices_15min) if prices_15min else 0
        
        # 计算最大回撤和盈利
        max_dd, max_prof = self._calc_drawdown_profit(prices_15min) if prices_15min else (0, 0)
        
        # 获取原始预测
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            'SELECT ml_regime FROM ml_predictions WHERE id = ?', 
            (record_id,)
        ).fetchone()
        
        if not row:
            logger.warning(f"[MLFeedback] 找不到记录 ID={record_id}")
            conn.close()
            return
        
        predicted_regime = row[0]
        
        # 判断预测是否正确
        # 简化规则：如果预测强趋势，实际有盈利且方向一致 = 正确
        correct = self._evaluate_prediction(
            predicted_regime, actual_regime, actual_pnl
        )
        
        conn.execute('''
            UPDATE ml_predictions SET
                exit_price = ?,
                actual_pnl = ?,
                actual_regime = ?,
                prediction_correct = ?,
                price_change_5min = ?,
                price_change_15min = ?,
                max_drawdown = ?,
                max_profit = ?,
                evaluated = 1
            WHERE id = ?
        ''', (
            exit_price, actual_pnl, actual_regime, 
            1 if correct else 0,
            pc_5min, pc_15min, max_dd, max_prof,
            record_id
        ))
        
        conn.commit()
        conn.close()
        
        logger.info(f"[MLFeedback] 评估完成 ID={record_id}, 预测={'正确' if correct else '错误'}, "
                   f"盈亏={actual_pnl:.4f}")
    
    def _determine_actual_regime(self, prices: List[float]) -> str:
        """根据价格序列确定实际环境"""
        if not prices or len(prices) < 5:
            return "UNKNOWN"
        
        # 计算价格变化
        price_change = (prices[-1] - prices[0]) / prices[0]
        volatility = self._calc_volatility(prices)
        
        # 简单规则判断
        if abs(price_change) > 0.005 and volatility < 0.002:
            return "趋势" if price_change > 0 else "趋势下跌"
        elif volatility > 0.003:
            return "高波动"
        else:
            return "震荡"
    
    def _calc_price_change(self, prices: List[float]) -> float:
        """计算价格变化率"""
        if not prices or len(prices) < 2:
            return 0
        return (prices[-1] - prices[0]) / prices[0]
    
    def _calc_volatility(self, prices: List[float]) -> float:
        """计算波动率（标准差/均值）"""
        if not prices or len(prices) < 2:
            return 0
        import numpy as np
        return np.std(prices) / np.mean(prices)
    
    def _calc_drawdown_profit(self, prices: List[float]) -> Tuple[float, float]:
        """计算最大回撤和最大盈利"""
        if not prices:
            return 0, 0
        
        max_dd = 0
        max_prof = 0
        peak = prices[0]
        
        for price in prices:
            if price > peak:
                peak = price
            dd = (peak - price) / peak
            prof = (price - prices[0]) / prices[0]
            max_dd = max(max_dd, dd)
            max_prof = max(max_prof, prof)
        
        return max_dd, max_prof
    
    def _evaluate_prediction(self, predicted: str, actual: str, pnl: float) -> bool:
        """评估预测是否正确"""
        # 简化评估规则
        strong_trends = ['STRONG_UP', 'STRONG_DOWN', '趋势上涨', '趋势下跌']
        
        if predicted in strong_trends:
            # 预测强趋势，实际盈利 = 正确
            return pnl > 0
        elif '震荡' in predicted:
            # 预测震荡，实际小盈亏 = 正确
            return abs(pnl) < 0.01
        else:
            # 其他情况，盈利即正确
            return pnl > 0
    
    def get_accuracy_stats(self, days: int = 7) -> Dict:
        """
        获取准确度统计
        
        Args:
            days: 最近N天
            
        Returns:
            统计字典
        """
        conn = sqlite3.connect(self.db_path)
        
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        
        # 总体统计
        row = conn.execute('''
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN prediction_correct = 1 THEN 1 ELSE 0 END) as correct,
                SUM(CASE WHEN prediction_correct = 0 THEN 1 ELSE 0 END) as wrong,
                AVG(ml_confidence) as avg_conf,
                AVG(CASE WHEN prediction_correct = 1 THEN actual_pnl END) as avg_pnl_correct,
                AVG(CASE WHEN prediction_correct = 0 THEN actual_pnl END) as avg_pnl_wrong
            FROM ml_predictions
            WHERE evaluated = 1 
            AND timestamp >= ?
        ''', (start_date,)).fetchone()
        
        total, correct, wrong, avg_conf, pnl_correct, pnl_wrong = row
        
        accuracy = correct / total if total > 0 else 0
        
        # 按环境类型统计
        regime_stats = conn.execute('''
            SELECT 
                ml_regime,
                COUNT(*) as count,
                SUM(CASE WHEN prediction_correct = 1 THEN 1 ELSE 0 END) as correct
            FROM ml_predictions
            WHERE evaluated = 1 AND timestamp >= ?
            GROUP BY ml_regime
        ''', (start_date,)).fetchall()
        
        regime_breakdown = {}
        for regime, count, regime_correct in regime_stats:
            regime_breakdown[regime] = {
                'total': count,
                'correct': regime_correct,
                'accuracy': regime_correct / count if count > 0 else 0
            }
        
        conn.close()
        
        return {
            'total_predictions': total,
            'correct': correct,
            'wrong': wrong,
            'accuracy_rate': accuracy,
            'avg_confidence': avg_conf,
            'avg_pnl_when_correct': pnl_correct,
            'avg_pnl_when_wrong': pnl_wrong,
            'regime_breakdown': regime_breakdown,
            'period_days': days
        }
    
    def generate_improvement_suggestions(self) -> List[Dict]:
        """
        生成模型改进建议
        
        Returns:
            建议列表
        """
        suggestions = []
        stats = self.get_accuracy_stats(days=14)
        
        # 建议1：置信度阈值调整
        if stats['accuracy_rate'] < 0.5 and stats['avg_confidence'] > 0.7:
            suggestions.append({
                'type': 'threshold',
                'description': '置信度高但准确度低，建议提高阈值',
                'current': '0.75',
                'suggested': '0.80',
                'confidence': 0.8
            })
        
        # 建议2：特定环境禁用
        for regime, regime_stat in stats.get('regime_breakdown', {}).items():
            if regime_stat['total'] > 5 and regime_stat['accuracy'] < 0.3:
                suggestions.append({
                    'type': 'regime',
                    'description': f'{regime}环境准确度低，建议禁用',
                    'current': f'enabled',
                    'suggested': 'disabled',
                    'confidence': 0.7
                })
        
        # 建议3：特征工程
        if stats['accuracy_rate'] < 0.4:
            suggestions.append({
                'type': 'feature',
                'description': '整体准确度低，建议增加特征或重新训练模型',
                'current': 'current features',
                'suggested': 'add volume/oi features',
                'confidence': 0.6
            })
        
        # 保存建议
        conn = sqlite3.connect(self.db_path)
        for sugg in suggestions:
            conn.execute('''
                INSERT INTO ml_improvement_suggestions 
                (issue_type, description, current_value, suggested_value, confidence)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                sugg['type'], sugg['description'],
                sugg['current'], sugg['suggested'],
                sugg['confidence']
            ))
        conn.commit()
        conn.close()
        
        return suggestions
    
    def print_accuracy_report(self, days: int = 7):
        """打印准确度报告"""
        stats = self.get_accuracy_stats(days)
        
        print("\n" + "="*70)
        print(f"ML环境检测准确度报告 (最近{days}天)")
        print("="*70)
        print(f"总预测数: {stats['total_predictions']}")
        print(f"正确: {stats['correct']} | 错误: {stats['wrong']}")
        print(f"准确度: {stats['accuracy_rate']*100:.1f}%")
        print(f"平均置信度: {stats['avg_confidence']:.3f}")
        print(f"正确时平均盈亏: ${stats['avg_pnl_when_correct']:.4f}")
        print(f"错误时平均盈亏: ${stats['avg_pnl_when_wrong']:.4f}")
        print("\n分环境准确度:")
        for regime, stat in stats['regime_breakdown'].items():
            print(f"  {regime}: {stat['accuracy']*100:.1f}% ({stat['correct']}/{stat['total']})")
        print("="*70)


# ========== 便捷使用函数 ==========

def create_feedback_system(db_path: str = 'v12_optimized.db') -> MLFeedbackSystem:
    """创建反馈系统实例"""
    return MLFeedbackSystem(db_path)


def record_ml_prediction(feedback_system: MLFeedbackSystem, 
                         ml_regime: str, tech_regime: str, final_regime: str,
                         ml_direction: int, ml_confidence: float, 
                         entry_price: float) -> int:
    """便捷函数：记录预测"""
    record = MLFeedbackRecord(
        timestamp=datetime.now().isoformat(),
        ml_regime=ml_regime,
        tech_regime=tech_regime,
        final_regime=final_regime,
        ml_direction=ml_direction,
        ml_confidence=ml_confidence,
        entry_price=entry_price
    )
    return feedback_system.record_prediction(record)


if __name__ == "__main__":
    # 测试
    logging.basicConfig(level=logging.INFO)
    
    feedback = MLFeedbackSystem()
    
    # 模拟记录预测
    record_id = record_ml_prediction(
        feedback, 'STRONG_UP', 'SIDEWAYS', '趋势上涨',
        1, 0.82, 2000.0
    )
    
    # 模拟更新结果
    prices = [2000, 2005, 2010, 2008, 2015, 2020]  # 价格上涨
    feedback.update_result(record_id, 2020, 0.01, prices, prices)
    
    # 打印报告
    feedback.print_accuracy_report()
