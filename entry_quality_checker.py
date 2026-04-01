#!/usr/bin/env python3
"""
入场位置质量评估模块
综合评分系统：多因子动态评估入场位置

完整留痕设计：
1. 每次检查都记录详细评分
2. 支持后期分析和策略优化
3. 记录被拒绝的入场机会（用于评估错过机会的成本）
"""

import numpy as np
import sqlite3
import json
from datetime import datetime
from typing import Tuple, List, Dict, Optional
from dataclasses import dataclass, field
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class EntryDecision(Enum):
    """入场决策类型"""
    APPROVED = "批准入场"
    REJECTED = "拒绝入场"
    REDUCED = "降低仓位入场"
    

@dataclass
class EntryCheckRecord:
    """
    入场检查完整记录 - 用于留痕分析
    """
    # 基础信息
    timestamp: datetime
    symbol: str
    action: str  # BUY/SELL
    current_price: float
    
    # 决策结果
    decision: EntryDecision
    final_score: float
    position_size_pct: float
    reason: str
    
    # 各因子评分（详细留痕）
    position_score: Optional[float] = None
    position_msg: str = ""
    rsi_score: Optional[float] = None
    rsi_msg: str = ""
    duration_score: Optional[float] = None
    duration_msg: str = ""
    
    # 市场环境
    market_regime: str = ""
    rsi_value: Optional[float] = None
    trend_duration_minutes: Optional[float] = None
    price_position_pct: Optional[float] = None  # 价格在区间中的位置
    
    # ML信息（如果可用）
    ml_confidence: Optional[float] = None
    ml_direction: Optional[int] = None
    
    # 后续结果（平仓后更新）
    actual_entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    pnl_pct: Optional[float] = None
    exit_reason: str = ""
    
    def to_dict(self) -> dict:
        """转为字典，便于数据库存储"""
        return {
            'timestamp': self.timestamp.isoformat(),
            'symbol': self.symbol,
            'action': self.action,
            'current_price': self.current_price,
            'decision': self.decision.value,
            'final_score': self.final_score,
            'position_size_pct': self.position_size_pct,
            'reason': self.reason,
            'position_score': self.position_score,
            'position_msg': self.position_msg,
            'rsi_score': self.rsi_score,
            'rsi_msg': self.rsi_msg,
            'duration_score': self.duration_score,
            'duration_msg': self.duration_msg,
            'market_regime': self.market_regime,
            'rsi_value': self.rsi_value,
            'trend_duration_minutes': self.trend_duration_minutes,
            'price_position_pct': self.price_position_pct,
            'ml_confidence': self.ml_confidence,
            'ml_direction': self.ml_direction,
            'actual_entry_price': self.actual_entry_price,
            'exit_price': self.exit_price,
            'pnl_pct': self.pnl_pct,
            'exit_reason': self.exit_reason
        }
    
    def to_log_string(self) -> str:
        """转为日志字符串"""
        emoji = "✅" if self.decision == EntryDecision.APPROVED else "❌" if self.decision == EntryDecision.REJECTED else "⚠️"
        base = (
            f"{emoji} [入场评估] {self.timestamp.strftime('%H:%M:%S')} | "
            f"{self.action} @ ${self.current_price:.2f} | "
            f"评分:{self.final_score:.2f} | 决策:{self.decision.value} | "
            f"仓位:{self.position_size_pct*100:.0f}%"
        )
        
        # 添加关键因素
        factors = []
        if self.position_score is not None:
            factors.append(f"位置:{self.position_score:.2f}")
        if self.rsi_score is not None:
            factors.append(f"RSI:{self.rsi_score:.2f}")
        if self.duration_score is not None:
            factors.append(f"时长:{self.duration_score:.2f}")
        
        if factors:
            base += f" | {' '.join(factors)}"
        
        return base


class EntryQualityChecker:
    """
    入场位置质量检查器 - 带完整留痕
    
    功能：
    1. 多因子综合评分
    2. 动态仓位建议
    3. 完整留痕记录（包括被拒绝的机会）
    4. 后续结果追踪
    """
    
    def __init__(self, db_path: str = 'v12_optimized.db'):
        self.trend_start_time = None
        self.trend_direction = None
        self.db_path = db_path
        self.records: List[EntryCheckRecord] = []
        self._init_database()
    
    def _init_database(self):
        """初始化数据库表"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 创建入场检查记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS entry_check_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    symbol TEXT,
                    action TEXT,
                    current_price REAL,
                    decision TEXT,
                    final_score REAL,
                    position_size_pct REAL,
                    reason TEXT,
                    position_score REAL,
                    position_msg TEXT,
                    rsi_score REAL,
                    rsi_msg TEXT,
                    duration_score REAL,
                    duration_msg TEXT,
                    market_regime TEXT,
                    rsi_value REAL,
                    trend_duration_minutes REAL,
                    price_position_pct REAL,
                    ml_confidence REAL,
                    ml_direction INTEGER,
                    actual_entry_price REAL,
                    exit_price REAL,
                    pnl_pct REAL,
                    exit_reason TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 创建索引
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_entry_check_timestamp 
                ON entry_check_records(timestamp)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_entry_check_decision 
                ON entry_check_records(decision)
            ''')
            
            conn.commit()
            conn.close()
            logger.info("[入场评估] 数据库表初始化完成")
            
        except Exception as e:
            logger.error(f"[入场评估] 数据库初始化失败: {e}")
    
    def save_record(self, record: EntryCheckRecord):
        """保存记录到数据库"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO entry_check_records (
                    timestamp, symbol, action, current_price, decision,
                    final_score, position_size_pct, reason, position_score,
                    position_msg, rsi_score, rsi_msg, duration_score, duration_msg,
                    market_regime, rsi_value, trend_duration_minutes, price_position_pct,
                    ml_confidence, ml_direction
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                record.timestamp.isoformat(),
                record.symbol,
                record.action,
                record.current_price,
                record.decision.value,
                record.final_score,
                record.position_size_pct,
                record.reason,
                record.position_score,
                record.position_msg,
                record.rsi_score,
                record.rsi_msg,
                record.duration_score,
                record.duration_msg,
                record.market_regime,
                record.rsi_value,
                record.trend_duration_minutes,
                record.price_position_pct,
                record.ml_confidence,
                record.ml_direction
            ))
            
            conn.commit()
            record_id = cursor.lastrowid
            conn.close()
            
            # 保存到内存列表
            self.records.append(record)
            
            # 输出日志
            logger.info(record.to_log_string())
            
            return record_id
            
        except Exception as e:
            logger.error(f"[入场评估] 保存记录失败: {e}")
            return None
    
    def update_record_result(self, timestamp: datetime, actual_entry_price: float, 
                            exit_price: float, pnl_pct: float, exit_reason: str):
        """更新记录的实际结果（平仓后调用）"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE entry_check_records 
                SET actual_entry_price = ?, exit_price = ?, pnl_pct = ?, exit_reason = ?
                WHERE timestamp = ?
            ''', (actual_entry_price, exit_price, pnl_pct, exit_reason, timestamp.isoformat()))
            
            conn.commit()
            conn.close()
            
            # 更新内存中的记录
            for record in self.records:
                if record.timestamp == timestamp:
                    record.actual_entry_price = actual_entry_price
                    record.exit_price = exit_price
                    record.pnl_pct = pnl_pct
                    record.exit_reason = exit_reason
                    break
                    
        except Exception as e:
            logger.error(f"[入场评估] 更新记录结果失败: {e}")
    
    def get_statistics(self) -> Dict:
        """获取统计信息"""
        if not self.records:
            return {}
        
        approved = [r for r in self.records if r.decision == EntryDecision.APPROVED]
        rejected = [r for r in self.records if r.decision == EntryDecision.REJECTED]
        reduced = [r for r in self.records if r.decision == EntryDecision.REDUCED]
        
        # 计算被拒绝机会的后续表现（如果数据可用）
        missed_opportunities = []
        for r in rejected:
            if r.pnl_pct is not None and r.pnl_pct > 0:
                missed_opportunities.append(r)
        
        return {
            'total_checks': len(self.records),
            'approved': len(approved),
            'rejected': len(rejected),
            'reduced': len(reduced),
            'approval_rate': len(approved) / len(self.records) * 100 if self.records else 0,
            'avg_score': np.mean([r.final_score for r in self.records]) if self.records else 0,
            'missed_opportunities': len(missed_opportunities),
            'missed_pnl': sum([r.pnl_pct for r in missed_opportunities]) if missed_opportunities else 0
        }
    
    def update_trend_info(self, direction: str, timestamp: datetime = None):
        """更新趋势开始时间"""
        if self.trend_direction != direction:
            # 趋势转变，重置时间
            self.trend_direction = direction
            self.trend_start_time = timestamp or datetime.now()
            logger.info(f"[趋势转变] {direction}，重置计时")
    
    def assess_position_quality(
        self, 
        current_price: float, 
        recent_prices: List[float], 
        trend_direction: str
    ) -> Tuple[bool, str, float]:
        """
        评估入场位置质量（价格区间位置）
        
        Returns:
            (是否通过, 消息, 得分0-1)
        """
        if len(recent_prices) < 20:
            return True, "数据不足，跳过位置检查", 0.7
        
        # 计算近期价格区间
        high_20 = max(recent_prices[-20:])
        low_20 = min(recent_prices[-20:])
        price_range = high_20 - low_20
        
        if price_range < 0.001:
            return True, "价格无波动", 0.5
        
        # 计算当前位置百分比 (0=最低, 1=最高)
        position_pct = (current_price - low_20) / price_range
        
        if trend_direction == 'SELL' or trend_direction == 'DOWN':
            # 做空：希望位置在上部 (>50%)
            if position_pct > 0.7:
                score = 1.0
                msg = f"位置优秀({position_pct:.1%})，适合做空"
            elif position_pct > 0.5:
                score = 0.7 + (position_pct - 0.5) * 1.5
                msg = f"位置良好({position_pct:.1%})，可以做空"
            elif position_pct > 0.3:
                score = 0.4 + (position_pct - 0.3)
                msg = f"位置一般({position_pct:.1%})，谨慎做空"
            else:
                score = position_pct / 0.3 * 0.3  # 0-0.3
                msg = f"位置较差({position_pct:.1%})，底部做空风险高"
            
        elif trend_direction == 'BUY' or trend_direction == 'UP':
            # 做多：希望位置在下部 (<50%)
            if position_pct < 0.3:
                score = 1.0
                msg = f"位置优秀({position_pct:.1%})，适合做多"
            elif position_pct < 0.5:
                score = 0.7 + (0.5 - position_pct) * 1.5
                msg = f"位置良好({position_pct:.1%})，可以做多"
            elif position_pct < 0.7:
                score = 0.4 + (0.7 - position_pct)
                msg = f"位置一般({position_pct:.1%})，谨慎做多"
            else:
                score = (1 - position_pct) / 0.3 * 0.3  # 0-0.3
                msg = f"位置较差({position_pct:.1%})，顶部做多风险高"
        else:
            score = 0.5
            msg = "趋势方向不明"
        
        return score >= 0.2, msg, min(score, 1.0)
    
    def check_rsi_extreme(
        self, 
        current_rsi: float, 
        action: str
    ) -> Tuple[bool, str, float]:
        """
        RSI极端值检查
        
        Returns:
            (是否通过, 消息, 得分0-1)
        """
        if action == 'SELL':
            # 做空：RSI越低越危险（可能反弹）
            if current_rsi > 65:
                score = 1.0
                msg = f"RSI偏高({current_rsi:.1f})，适合做空"
            elif current_rsi > 50:
                score = 0.7 + (current_rsi - 50) / 50 * 0.3
                msg = f"RSI适中({current_rsi:.1f})，可以做空"
            elif current_rsi > 35:
                score = 0.4 + (current_rsi - 35) / 35 * 0.3
                msg = f"RSI偏低({current_rsi:.1f})，谨慎做空"
            else:
                score = current_rsi / 35 * 0.3
                msg = f"RSI超卖({current_rsi:.1f})，底部做空风险高"
                
        elif action == 'BUY':
            # 做多：RSI越高越危险（可能回调）
            if current_rsi < 35:
                score = 1.0
                msg = f"RSI偏低({current_rsi:.1f})，适合做多"
            elif current_rsi < 50:
                score = 0.7 + (50 - current_rsi) / 50 * 0.3
                msg = f"RSI适中({current_rsi:.1f})，可以做多"
            elif current_rsi < 65:
                score = 0.4 + (65 - current_rsi) / 35 * 0.3
                msg = f"RSI偏高({current_rsi:.1f})，谨慎做多"
            else:
                score = (100 - current_rsi) / 35 * 0.3
                msg = f"RSI超买({current_rsi:.1f})，顶部做多风险高"
        else:
            score = 0.5
            msg = "方向不明"
        
        return score >= 0.2, msg, min(score, 1.0)
    
    def assess_trend_duration(
        self, 
        current_time: datetime = None
    ) -> Tuple[bool, str, float]:
        """
        趋势持续时间评估
        
        Returns:
            (是否通过, 消息, 得分0-1)
        """
        if self.trend_start_time is None:
            return True, "趋势刚开始", 1.0
        
        current_time = current_time or datetime.now()
        duration_minutes = (current_time - self.trend_start_time).total_seconds() / 60
        
        # 评分逻辑：趋势初期高分，持续过久分数降低
        if duration_minutes < 15:
            score = 1.0
            msg = f"趋势初期({duration_minutes:.0f}分钟)，积极入场"
        elif duration_minutes < 30:
            score = 0.8
            msg = f"趋势早期({duration_minutes:.0f}分钟)，正常入场"
        elif duration_minutes < 60:
            score = 0.6
            msg = f"趋势中期({duration_minutes:.0f}分钟)，谨慎入场"
        elif duration_minutes < 90:
            score = 0.4
            msg = f"趋势后期({duration_minutes:.0f}分钟)，可能反转"
        else:
            score = 0.2
            msg = f"趋势过久({duration_minutes:.0f}分钟)，高风险"
        
        return score >= 0.2, msg, score
    
    def comprehensive_check(
        self,
        signal_action: str,
        current_price: float,
        recent_prices: List[float],
        current_rsi: float,
        weights: Dict[str, float] = None
    ) -> Tuple[bool, str, float, Dict]:
        """
        综合入场检查
        
        Args:
            signal_action: 'BUY' or 'SELL'
            current_price: 当前价格
            recent_prices: 近期价格列表
            current_rsi: 当前RSI值
            weights: 各因子权重，默认{'position': 0.4, 'rsi': 0.3, 'duration': 0.3}
        
        Returns:
            (是否入场, 消息, 综合评分, 详细结果)
        """
        if weights is None:
            weights = {'position': 0.4, 'rsi': 0.3, 'duration': 0.3}
        
        checks = {}
        total_weight = 0
        weighted_score = 0
        
        # 1. 位置质量检查
        if weights.get('position', 0) > 0:
            pos_ok, pos_msg, pos_score = self.assess_position_quality(
                current_price, recent_prices, signal_action
            )
            checks['position'] = {
                'passed': pos_ok,
                'message': pos_msg,
                'score': pos_score,
                'weight': weights['position']
            }
            weighted_score += pos_score * weights['position']
            total_weight += weights['position']
        
        # 2. RSI检查
        if weights.get('rsi', 0) > 0:
            rsi_ok, rsi_msg, rsi_score = self.check_rsi_extreme(
                current_rsi, signal_action
            )
            checks['rsi'] = {
                'passed': rsi_ok,
                'message': rsi_msg,
                'score': rsi_score,
                'weight': weights['rsi']
            }
            weighted_score += rsi_score * weights['rsi']
            total_weight += weights['rsi']
        
        # 3. 趋势持续时间检查
        if weights.get('duration', 0) > 0:
            dur_ok, dur_msg, dur_score = self.assess_trend_duration()
            checks['duration'] = {
                'passed': dur_ok,
                'message': dur_msg,
                'score': dur_score,
                'weight': weights['duration']
            }
            weighted_score += dur_score * weights['duration']
            total_weight += weights['duration']
        
        # 计算最终评分
        final_score = weighted_score / total_weight if total_weight > 0 else 0.5
        
        # 根据评分决定行动
        if final_score < 0.2:
            should_enter = False
            action_msg = f"综合评分{final_score:.2f}<0.2，禁止入场"
            position_size_pct = 0.0
        elif final_score < 0.5:
            should_enter = True
            action_msg = f"综合评分{final_score:.2f}，谨慎入场（仓位30%）"
            position_size_pct = 0.3
        elif final_score < 0.7:
            should_enter = True
            action_msg = f"综合评分{final_score:.2f}，正常入场（仓位60%）"
            position_size_pct = 0.6
        elif final_score < 0.85:
            should_enter = True
            action_msg = f"综合评分{final_score:.2f}，积极入场（仓位80%）"
            position_size_pct = 0.8
        else:
            should_enter = True
            action_msg = f"综合评分{final_score:.2f}，全力入场（仓位100%）"
            position_size_pct = 1.0
        
        # 构建详细消息
        detail_msg = action_msg + " | "
        for name, result in checks.items():
            detail_msg += f"{name}:{result['score']:.2f} "
        
        return should_enter, detail_msg, final_score, {
            'checks': checks,
            'final_score': final_score,
            'position_size_pct': position_size_pct
        }


# 全局实例
_checker = None

def get_entry_checker() -> EntryQualityChecker:
    """获取入场质量检查器"""
    global _checker
    if _checker is None:
        _checker = EntryQualityChecker()
    return _checker


# 测试代码
if __name__ == '__main__':
    checker = EntryQualityChecker()
    
    # 测试场景：底部做空（高风险）
    print("=" * 80)
    print("测试场景1：底部做空（模拟14:01的情况）")
    print("=" * 80)
    
    # 模拟数据：价格从2146跌到2116
    recent_prices = list(range(2146, 2116, -2))  # 2146, 2144, ... 2118
    current_price = 2116.99
    current_rsi = 28  # 超卖
    
    checker.update_trend_info('SELL')
    # 模拟趋势持续了很久
    checker.trend_start_time = datetime.now() - __import__('datetime').timedelta(minutes=75)
    
    should_enter, msg, score, details = checker.comprehensive_check(
        'SELL', current_price, recent_prices, current_rsi
    )
    
    print(f"当前价格: {current_price}")
    print(f"20周期高点: {max(recent_prices[-20:])}")
    print(f"20周期低点: {min(recent_prices[-20:])}")
    print(f"RSI: {current_rsi}")
    print(f"趋势持续时间: 75分钟")
    print()
    print(f"综合评分: {score:.2f}")
    print(f"入场建议: {msg}")
    print(f"建议仓位: {details['position_size_pct']*100:.0f}%")
    print()
    
    # 详细分解
    for name, result in details['checks'].items():
        print(f"  {name}: {result['score']:.2f} - {result['message']}")
    
    print()
    print("=" * 80)
    print("测试场景2：良好位置做空")
    print("=" * 80)
    
    # 模拟数据：价格在中上部
    recent_prices2 = list(range(2100, 2160, 2)) + list(range(2160, 2140, -1))
    current_price2 = 2155
    current_rsi2 = 58
    
    checker2 = EntryQualityChecker()
    checker2.update_trend_info('SELL')
    checker2.trend_start_time = datetime.now() - __import__('datetime').timedelta(minutes=20)
    
    should_enter2, msg2, score2, details2 = checker2.comprehensive_check(
        'SELL', current_price2, recent_prices2, current_rsi2
    )
    
    print(f"当前价格: {current_price2}")
    print(f"RSI: {current_rsi2}")
    print(f"趋势持续时间: 20分钟")
    print()
    print(f"综合评分: {score2:.2f}")
    print(f"入场建议: {msg2}")
    print(f"建议仓位: {details2['position_size_pct']*100:.0f}%")
