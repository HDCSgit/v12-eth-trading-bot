#!/usr/bin/env python3
"""
V7-5Min-Backtest: V7高频交易系统5分钟数据回测与优化
目标：最大化回报率，分析优势信号，参数调优
"""

import pandas as pd
import numpy as np
import logging
from datetime import datetime
from typing import Dict, List, Tuple
import json
import warnings
warnings.filterwarnings('ignore')

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)


class V7SignalAnalyzer:
    """V7信号分析器 - 深度分析各信号表现"""
    
    def __init__(self):
        self.trade_log = []
        
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算V7标准指标"""
        df = df.copy()
        
        # RSI
        delta = df['close'].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        df['rsi'] = 100 - 100 / (1 + gain / (loss + 1e-10))
        
        # MACD
        ema12 = df['close'].ewm(span=12).mean()
        ema26 = df['close'].ewm(span=26).mean()
        df['macd'] = ema12 - ema26
        df['macd_signal'] = df['macd'].ewm(span=9).mean()
        
        # 均线
        df['ma5'] = df['close'].rolling(5).mean()
        df['ma10'] = df['close'].rolling(10).mean()
        df['ma20'] = df['close'].rolling(20).mean()
        
        # 布林带
        df['bb_mid'] = df['close'].rolling(20).mean()
        df['bb_std'] = df['close'].rolling(20).std()
        df['bb_upper'] = df['bb_mid'] + 2 * df['bb_std']
        df['bb_lower'] = df['bb_mid'] - 2 * df['bb_std']
        
        # 量能
        df['volume_ma'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma']
        
        # 价格变化
        df['price_change_3'] = df['close'].pct_change(3) * 100
        
        return df.dropna()
    
    def generate_signals(self, df: pd.DataFrame, params: Dict) -> Dict:
        """生成交易信号"""
        df = self.calculate_indicators(df)
        
        if len(df) < 20:
            return {'action': 'HOLD', 'signals': []}
        
        row = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else row
        
        signals = []
        
        # 信号1: RSI超卖
        if row['rsi'] < params.get('rsi_threshold', 35):
            signals.append(('RSI_Oversold', params.get('rsi_weight', 0.60)))
        
        # 信号2: MACD金叉
        if (row['macd'] > row['macd_signal'] and 
            prev['macd'] <= prev['macd_signal']):
            signals.append(('MACD_Cross', params.get('macd_weight', 0.65)))
        
        # 信号3: 布林带下轨
        if row['close'] < row['bb_lower'] * params.get('bb_threshold', 1.01):
            signals.append(('BB_Lower', params.get('bb_weight', 0.55)))
        
        # 信号4: 均线金叉
        if (row['ma5'] > row['ma10'] and 
            prev['ma5'] <= prev['ma10']):
            signals.append(('MA_Cross', params.get('ma_weight', 0.60)))
        
        # 信号5: 放量突破
        if (row['volume_ratio'] > params.get('volume_threshold', 1.3) and 
            row['close'] > row['open']):
            signals.append(('Volume_Break', params.get('volume_weight', 0.55)))
        
        # 信号6: 超跌反弹
        if row['price_change_3'] < params.get('drop_threshold', -1.5):
            signals.append(('Drop_Bounce', params.get('drop_weight', 0.50)))
        
        # 只要有信号就交易
        if len(signals) > 0:
            score = sum([conf for _, conf in signals])
            return {
                'action': 'BUY',
                'signals': signals,
                'score': score
            }
        else:
            return {'action': 'HOLD', 'signals': []}


class V7BacktestEngine:
    """V7回测引擎"""
    
    def __init__(self, initial_balance: float = 1000.0, params: Dict = None):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.params = params or {}
        
        # 交易参数
        self.leverage = self.params.get('leverage', 2)
        self.stop_loss = self.params.get('stop_loss', 0.02)  # 2%
        self.take_profit = self.params.get('take_profit', 0.04)  # 4%
        self.position_size = self.params.get('position_size', 0.10)  # 10%
        
        # 风控
        self.max_drawdown = self.params.get('max_drawdown', 0.25)
        
        # 统计
        self.stats = {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'liquidations': 0,
            'signal_performance': {}
        }
        
        self.trade_log = []
        self.equity_curve = []
        
    def run_backtest(self, df: pd.DataFrame, signal_generator) -> Dict:
        """运行回测"""
        position = None
        entry_time = None
        
        for i in range(50, len(df)):
            current_df = df.iloc[:i+1]
            current_price = df['close'].iloc[i]
            current_time = df['timestamp'].iloc[i]
            
            # 持仓管理
            if position:
                entry = position['entry_price']
                
                if position['side'] == 'LONG':
                    pnl_pct = (current_price - entry) / entry * self.leverage
                else:
                    pnl_pct = (entry - current_price) / entry * self.leverage
                
                # 爆仓检查
                if pnl_pct <= -48:
                    self.stats['liquidations'] += 1
                    self.balance *= 0.04
                    position = None
                    continue
                
                # 止损
                if pnl_pct <= -self.stop_loss * self.leverage * 100:
                    loss = position['margin'] * self.stop_loss * self.leverage
                    self.balance -= loss
                    self.stats['losing_trades'] += 1
                    
                    # 记录交易
                    self.trade_log.append({
                        'type': 'LOSE',
                        'entry_price': entry,
                        'exit_price': current_price,
                        'pnl_pct': pnl_pct,
                        'signals': position['signals']
                    })
                    
                    position = None
                    continue
                
                # 止盈
                if pnl_pct >= self.take_profit * self.leverage * 100:
                    profit = position['margin'] * self.take_profit * self.leverage
                    self.balance += position['margin'] + profit
                    self.stats['winning_trades'] += 1
                    
                    # 记录交易
                    self.trade_log.append({
                        'type': 'WIN',
                        'entry_price': entry,
                        'exit_price': current_price,
                        'pnl_pct': pnl_pct,
                        'signals': position['signals']
                    })
                    
                    position = None
                    continue
            
            # 新开仓
            else:
                signal = signal_generator.generate_signals(current_df, self.params)
                
                if signal['action'] == 'BUY':
                    margin = self.balance * self.position_size
                    self.balance -= margin
                    
                    position = {
                        'side': 'LONG',
                        'entry_price': current_price,
                        'margin': margin,
                        'signals': [s[0] for s in signal['signals']],
                        'score': signal['score']
                    }
                    self.stats['total_trades'] += 1
            
            # 记录权益
            equity = self.balance
            if position:
                unrealized = position['margin'] * (current_price - position['entry_price']) / position['entry_price'] * self.leverage
                equity += position['margin'] + unrealized
            
            self.equity_curve.append({
                'time': current_time,
                'equity': equity,
                'price': current_price
            })
        
        # 最终平仓
        if position:
            if position['side'] == 'LONG':
                pnl_pct = (current_price - position['entry_price']) / position['entry_price'] * self.leverage
            else:
                pnl_pct = (position['entry_price'] - current_price) / position['entry_price'] * self.leverage
            
            if pnl_pct > 0:
                self.stats['winning_trades'] += 1
            else:
                self.stats['losing_trades'] += 1
        
        # 分析信号表现
        self._analyze_signal_performance()
        
        # 计算结果
        final_equity = self.equity_curve[-1]['equity'] if self.equity_curve else self.initial_balance
        total_return = (final_equity - self.initial_balance) / self.initial_balance * 100
        
        max_dd = 0
        peak = self.initial_balance
        for eq in self.equity_curve:
            if eq['equity'] > peak:
                peak = eq['equity']
            dd = (peak - eq['equity']) / peak
            if dd > max_dd:
                max_dd = dd
        
        # 年化计算
        years = 2.2
        annual_trades = self.stats['total_trades'] / years
        annual_return = total_return / years
        
        return {
            'total_return': total_return,
            'annual_return': annual_return,
            'max_drawdown': max_dd * 100,
            'total_trades': self.stats['total_trades'],
            'annual_trades': annual_trades,
            'winning_trades': self.stats['winning_trades'],
            'losing_trades': self.stats['losing_trades'],
            'win_rate': self.stats['winning_trades'] / max(self.stats['total_trades'], 1) * 100,
            'liquidations': self.stats['liquidations'],
            'profit_factor': self._calculate_profit_factor(),
            'sharpe_ratio': self._calculate_sharpe(),
            'signal_performance': self.stats['signal_performance']
        }
    
    def _analyze_signal_performance(self):
        """分析各信号的表现"""
        for trade in self.trade_log:
            for signal in trade.get('signals', []):
                if signal not in self.stats['signal_performance']:
                    self.stats['signal_performance'][signal] = {
                        'total': 0,
                        'wins': 0,
                        'losses': 0
                    }
                
                self.stats['signal_performance'][signal]['total'] += 1
                if trade['type'] == 'WIN':
                    self.stats['signal_performance'][signal]['wins'] += 1
                else:
                    self.stats['signal_performance'][signal]['losses'] += 1
    
    def _calculate_profit_factor(self) -> float:
        """计算盈亏比"""
        wins = [t for t in self.trade_log if t['type'] == 'WIN']
        losses = [t for t in self.trade_log if t['type'] == 'LOSE']
        
        total_win = sum([t['pnl_pct'] for t in wins]) if wins else 0
        total_loss = abs(sum([t['pnl_pct'] for t in losses])) if losses else 1
        
        return total_win / total_loss if total_loss > 0 else 0
    
    def _calculate_sharpe(self) -> float:
        """计算夏普比率（简化）"""
        if len(self.equity_curve) < 2:
            return 0
        
        returns = []
        for i in range(1, len(self.equity_curve)):
            ret = (self.equity_curve[i]['equity'] - self.equity_curve[i-1]['equity']) / self.equity_curve[i-1]['equity']
            returns.append(ret)
        
        if len(returns) == 0:
            return 0
        
        avg_return = np.mean(returns)
        std_return = np.std(returns)
        
        return (avg_return / std_return * np.sqrt(252 * 12 * 5)) if std_return > 0 else 0  # 5分钟数据年化


def grid_search_optimization(df: pd.DataFrame, signal_generator) -> List[Dict]:
    """网格搜索最优参数"""
    logger.info("\n" + "=" * 70)
    logger.info("🔍 开始网格搜索参数优化...")
    logger.info("=" * 70)
    
    # 参数搜索空间
    param_grid = {
        'rsi_threshold': [30, 35, 40],
        'bb_threshold': [1.00, 1.01, 1.02],
        'volume_threshold': [1.3, 1.5, 1.8],
        'drop_threshold': [-1.0, -1.5, -2.0],
        'stop_loss': [0.015, 0.02, 0.025],
        'take_profit': [0.03, 0.04, 0.05]
    }
    
    results = []
    
    # 简化搜索：测试关键组合
    test_combinations = [
        {'rsi_threshold': 30, 'bb_threshold': 1.00, 'volume_threshold': 1.3, 'drop_threshold': -2.0, 'stop_loss': 0.015, 'take_profit': 0.03},
        {'rsi_threshold': 35, 'bb_threshold': 1.01, 'volume_threshold': 1.5, 'drop_threshold': -1.5, 'stop_loss': 0.02, 'take_profit': 0.04},
        {'rsi_threshold': 40, 'bb_threshold': 1.02, 'volume_threshold': 1.8, 'drop_threshold': -1.0, 'stop_loss': 0.025, 'take_profit': 0.05},
        {'rsi_threshold': 30, 'bb_threshold': 1.01, 'volume_threshold': 1.5, 'drop_threshold': -1.5, 'stop_loss': 0.02, 'take_profit': 0.04},
    ]
    
    for i, params in enumerate(test_combinations):
        logger.info(f"\n测试组合 {i+1}/{len(test_combinations)}: {params}")
        
        engine = V7BacktestEngine(initial_balance=1000.0, params=params)
        result = engine.run_backtest(df, signal_generator)
        
        # 综合评分
        score = (
            result['total_return'] * 0.3 +  # 收益权重30%
            (result['win_rate'] - 50) * 0.3 +  # 胜率权重30%
            (20 - result['max_drawdown']) * 0.2 +  # 回撤权重20%
            min(result['annual_trades'] / 100, 10) * 0.2  # 交易频率权重20%
        )
        
        results.append({
            'params': params,
            'result': result,
            'score': score
        })
        
        logger.info(f"  收益: {result['total_return']:+.2f}%, 胜率: {result['win_rate']:.1f}%, 交易: {result['total_trades']}")
    
    # 排序
    results.sort(key=lambda x: x['score'], reverse=True)
    
    return results


def print_detailed_report(result: Dict):
    """打印详细回测报告"""
    print("\n" + "=" * 70)
    print("🚀 V7-HighFreq 5分钟数据详细回测报告")
    print("=" * 70)
    
    print("\n💰 收益表现:")
    print(f"  初始资金: $1,000.00")
    print(f"  最终资金: ${1000 * (1 + result['total_return']/100):.2f}")
    print(f"  总回报率: {result['total_return']:+.2f}%")
    print(f"  年化回报: {result['annual_return']:+.2f}%")
    
    print("\n📊 交易统计:")
    print(f"  总交易次数: {result['total_trades']}")
    print(f"  年化交易: {result['annual_trades']:.0f} 笔")
    print(f"  盈利次数: {result['winning_trades']}")
    print(f"  亏损次数: {result['losing_trades']}")
    print(f"  胜率: {result['win_rate']:.1f}%")
    print(f"  盈亏比: {result['profit_factor']:.2f}")
    print(f"  夏普比率: {result['sharpe_ratio']:.2f}")
    
    print("\n🛡️ 风险控制:")
    print(f"  最大回撤: {result['max_drawdown']:.2f}%")
    print(f"  爆仓次数: {result['liquidations']}")
    
    print("\n📈 信号表现分析:")
    for signal, perf in sorted(result['signal_performance'].items(), 
                               key=lambda x: x[1]['wins']/max(x[1]['total'],1), reverse=True):
        win_rate = perf['wins'] / perf['total'] * 100 if perf['total'] > 0 else 0
        print(f"  {signal:15s}: 触发{perf['total']:4d}次, 胜{perf['wins']:3d}次, 胜率{win_rate:5.1f}%")
    
    # 评分
    score = 0
    if result['liquidations'] == 0: score += 30
    if result['win_rate'] > 55: score += 25
    if result['win_rate'] > 50: score += 10
    if result['total_return'] > 0: score += 15
    if result['annual_trades'] > 400: score += 10
    if result['sharpe_ratio'] > 1: score += 10
    
    print(f"\n⭐ 综合评分: {score}/100")
    
    if score >= 80:
        print("🟢 优秀 - 建议实盘")
    elif score >= 60:
        print("🟡 良好 - 可谨慎使用")
    elif score >= 40:
        print("🟠 一般 - 需继续优化")
    else:
        print("🔴 较差 - 不建议使用")
    
    print("=" * 70)


def main():
    """主函数"""
    # 加载5分钟数据
    logger.info("加载5分钟ETH数据...")
    df = pd.read_csv('eth_usdt_5m_2024_2026.csv')
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    logger.info(f"数据条数: {len(df):,}")
    
    # 创建信号生成器
    signal_generator = V7SignalAnalyzer()
    
    # 第一步：使用默认参数回测
    logger.info("\n" + "=" * 70)
    logger.info("📊 第一步：默认参数回测")
    logger.info("=" * 70)
    
    default_params = {
        'rsi_threshold': 35,
        'bb_threshold': 1.01,
        'volume_threshold': 1.3,
        'drop_threshold': -1.5,
        'stop_loss': 0.02,
        'take_profit': 0.04
    }
    
    engine_default = V7BacktestEngine(initial_balance=1000.0, params=default_params)
    result_default = engine_default.run_backtest(df, signal_generator)
    print_detailed_report(result_default)
    
    # 第二步：网格搜索优化
    logger.info("\n" + "=" * 70)
    logger.info("🔍 第二步：参数优化")
    logger.info("=" * 70)
    
    optimized_results = grid_search_optimization(df, signal_generator)
    
    # 打印最优参数
    best = optimized_results[0]
    logger.info(f"\n🏆 最优参数组合:")
    logger.info(f"  参数: {best['params']}")
    logger.info(f"  评分: {best['score']:.1f}")
    
    # 使用最优参数重新回测
    logger.info("\n" + "=" * 70)
    logger.info("📊 第三步：最优参数回测")
    logger.info("=" * 70)
    
    engine_optimal = V7BacktestEngine(initial_balance=1000.0, params=best['params'])
    result_optimal = engine_optimal.run_backtest(df, signal_generator)
    print_detailed_report(result_optimal)
    
    # 对比
    logger.info("\n" + "=" * 70)
    logger.info("📈 优化效果对比")
    logger.info("=" * 70)
    logger.info(f"  收益提升: {result_optimal['total_return'] - result_default['total_return']:+.2f}%")
    logger.info(f"  胜率提升: {result_optimal['win_rate'] - result_default['win_rate']:+.1f}%")
    logger.info(f"  回撤变化: {result_optimal['max_drawdown'] - result_default['max_drawdown']:+.2f}%")
    logger.info(f"  交易次数: {result_optimal['total_trades'] - result_default['total_trades']:+d}")


if __name__ == "__main__":
    main()