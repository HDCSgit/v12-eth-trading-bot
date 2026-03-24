#!/usr/bin/env python3
"""
币安市场数据获取 - 辅助信息源
多空比、爆仓数据、持仓量等，作为信号过滤参考，不主导决策
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from config import CONFIG
import logging

logger = logging.getLogger(__name__)


class BinanceMarketData:
    """币安市场辅助数据 - 轻量级参考"""
    
    BASE_URL = "https://fapi.binance.com"
    
    def __init__(self):
        self.cache = {}
        self.cache_time = {}
        self.cache_duration = 300  # 5分钟缓存
        
    def _get_cache(self, key: str) -> Optional[Dict]:
        """获取缓存数据"""
        if key in self.cache:
            if datetime.now() - self.cache_time[key] < timedelta(seconds=self.cache_duration):
                return self.cache[key]
        return None
    
    def _set_cache(self, key: str, data: Dict):
        """设置缓存"""
        self.cache[key] = data
        self.cache_time[key] = datetime.now()
    
    def get_long_short_ratio(self, symbol: str = "ETHUSDT", period: str = "5m") -> Optional[Dict]:
        """
        获取多空比 - 辅助参考，不作为主要信号
        
        Returns:
            {
                'long_short_ratio': 1.234,  # >1多头占优，<1空头占优
                'long_account': 55.2,       # 多头账户占比
                'short_account': 44.8,      # 空头账户占比
                'timestamp': datetime
            }
        """
        cache_key = f"lsr_{symbol}_{period}"
        cached = self._get_cache(cache_key)
        if cached:
            return cached
        
        try:
            url = f"{self.BASE_URL}/futures/data/globalLongShortAccountRatio"
            params = {
                'symbol': symbol,
                'period': period,
                'limit': 1  # 只取最新
            }
            
            response = requests.get(url, params=params, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                if data and len(data) > 0:
                    latest = data[0]
                    result = {
                        'long_short_ratio': float(latest['longShortRatio']),
                        'long_account': float(latest['longAccount']),
                        'short_account': float(latest['shortAccount']),
                        'timestamp': datetime.fromtimestamp(latest['timestamp'] / 1000)
                    }
                    self._set_cache(cache_key, result)
                    return result
            else:
                logger.debug(f"多空比API返回错误: {response.status_code}")
                
        except Exception as e:
            logger.debug(f"获取多空比失败: {e}")
        
        return None
    
    def get_liquidation_data(self, symbol: str = "ETHUSDT", limit: int = 100) -> Optional[Dict]:
        """
        获取近期爆仓数据 - 辅助参考
        
        Returns:
            {
                'long_liquidation': 125.5,    # 多头爆仓量(ETH)
                'short_liquidation': 45.2,    # 空头爆仓量(ETH)
                'total_liquidation': 170.7,   # 总爆仓量
                'liq_ratio': 2.78,            # 多空爆仓比
                'count': 100,                 # 爆仓笔数
                'timestamp': datetime
            }
        """
        cache_key = f"liq_{symbol}_{limit}"
        cached = self._get_cache(cache_key)
        if cached:
            return cached
        
        try:
            url = f"{self.BASE_URL}/fapi/v1/forceOrders"
            params = {
                'symbol': symbol,
                'limit': limit
            }
            
            response = requests.get(url, params=params, timeout=5)
            
            if response.status_code == 200:
                orders = response.json()
                
                if orders and len(orders) > 0:
                    long_liq = 0.0  # 多头爆仓是SELL
                    short_liq = 0.0  # 空头爆仓是BUY
                    
                    for order in orders:
                        qty = float(order.get('executedQty', 0))
                        side = order.get('side', '')
                        
                        if side == 'SELL':
                            long_liq += qty  # 多头爆仓
                        elif side == 'BUY':
                            short_liq += qty  # 空头爆仓
                    
                    total = long_liq + short_liq
                    # 修复除零问题
                    if short_liq > 0 and long_liq > 0:
                        ratio = long_liq / short_liq
                    elif short_liq == 0 and long_liq > 0:
                        ratio = 999.0  # 极大值表示多头爆仓为主
                    elif long_liq == 0 and short_liq > 0:
                        ratio = 0.001  # 极小值表示空头爆仓为主
                    else:
                        ratio = 1.0  # 都没有爆仓
                    
                    result = {
                        'long_liquidation': long_liq,
                        'short_liquidation': short_liq,
                        'total_liquidation': total,
                        'liq_ratio': ratio,
                        'count': len(orders),
                        'timestamp': datetime.now()
                    }
                    self._set_cache(cache_key, result)
                    return result
                    
        except Exception as e:
            logger.debug(f"获取爆仓数据失败: {e}")
        
        return None
    
    def get_open_interest(self, symbol: str = "ETHUSDT") -> Optional[Dict]:
        """
        获取持仓量 - 辅助参考
        
        Returns:
            {
                'open_interest': 125000.5,  # 持仓量(ETH)
                'change_1h': 0.02,          # 1小时变化率
                'timestamp': datetime
            }
        """
        cache_key = f"oi_{symbol}"
        cached = self._get_cache(cache_key)
        if cached:
            return cached
        
        try:
            # 当前持仓量
            url = f"{self.BASE_URL}/fapi/v1/openInterest"
            params = {'symbol': symbol}
            
            response = requests.get(url, params=params, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                result = {
                    'open_interest': float(data['openInterest']),
                    'timestamp': datetime.fromtimestamp(data['time'] / 1000)
                }
                self._set_cache(cache_key, result)
                return result
                
        except Exception as e:
            logger.debug(f"获取持仓量失败: {e}")
        
        return None
    
    def get_market_sentiment(self, symbol: str = "ETHUSDT") -> Dict:
        """
        获取综合市场情绪 - 轻量级参考
        
        Returns:
            {
                'long_short_ratio': 1.2,      # 多空比
                'long_short_signal': 'neutral', # 信号: extreme_long, long, neutral, short, extreme_short
                'liquidation_signal': 'neutral', # 爆仓信号: long_squeeze, short_squeeze, neutral
                'overall_bias': 0.0,           # 综合偏向: -1~1, 负值偏空, 正值偏多
                'info': "描述性信息",
                'timestamp': datetime
            }
        """
        sentiment = {
            'long_short_ratio': 1.0,
            'long_short_signal': 'neutral',
            'liquidation_signal': 'neutral',
            'overall_bias': 0.0,
            'info': '',
            'timestamp': datetime.now()
        }
        
        # 1. 多空比分析（权重较低）
        lsr_data = self.get_long_short_ratio(symbol)
        if lsr_data:
            ratio = lsr_data['long_short_ratio']
            sentiment['long_short_ratio'] = ratio
            
            # 极端值标记（不直接产生交易信号）
            if ratio > 4.0:
                sentiment['long_short_signal'] = 'extreme_long'
                sentiment['info'] += f"多空比{r:.2f}极高(>4),多头极端拥挤;".format(r=ratio)
            elif ratio > 2.5:
                sentiment['long_short_signal'] = 'long'
                sentiment['info'] += f"多空比{r:.2f}偏高(>2.5),多头占优;".format(r=ratio)
            elif ratio < 0.25:
                sentiment['long_short_signal'] = 'extreme_short'
                sentiment['info'] += f"多空比{r:.2f}极低(<0.25),空头极端拥挤;".format(r=ratio)
            elif ratio < 0.4:
                sentiment['long_short_signal'] = 'short'
                sentiment['info'] += f"多空比{r:.2f}偏低(<0.4),空头占优;".format(r=ratio)
        
        # 2. 爆仓数据分析（短期脉冲信号）
        liq_data = self.get_liquidation_data(symbol)
        if liq_data:
            liq_ratio = liq_data['liq_ratio']
            total_liq = liq_data['total_liquidation']
            
            # 只有爆仓量较大时才值得关注
            if total_liq > 50:  # >50 ETH
                if liq_ratio > 5.0:
                    sentiment['liquidation_signal'] = 'long_squeeze'
                    sentiment['info'] += f"多头爆仓{liq_data['long_liquidation']:.1f}ETH,可能是超跌;"
                elif liq_ratio < 0.2:
                    sentiment['liquidation_signal'] = 'short_squeeze'
                    sentiment['info'] += f"空头爆仓{liq_data['short_liquidation']:.1f}ETH,可能是超涨;"
        
        # 3. 计算综合偏向（-1~1，仅供参考）
        bias = 0.0
        
        # 多空比贡献（权重0.3）
        if lsr_data:
            # 将多空比转换为-1~1
            # ratio=4 -> bias=-0.6 (极端多头，偏空)
            # ratio=1 -> bias=0
            # ratio=0.25 -> bias=0.6 (极端空头，偏多)
            if lsr_data['long_short_ratio'] > 1:
                bias -= min(0.6, (lsr_data['long_short_ratio'] - 1) * 0.2)
            else:
                bias += min(0.6, (1 - lsr_data['long_short_ratio']) * 0.2)
        
        # 爆仓贡献（权重0.2，短期反向）
        if liq_data and liq_data['total_liquidation'] > 50:
            if liq_data['liq_ratio'] > 3:  # 多头爆仓多，可能反弹
                bias += 0.2
            elif liq_data['liq_ratio'] < 0.33:  # 空头爆仓多，可能回调
                bias -= 0.2
        
        sentiment['overall_bias'] = max(-1.0, min(1.0, bias))
        
        if not sentiment['info']:
            sentiment['info'] = '市场情绪中性'
        
        return sentiment


# 全局实例
market_data = BinanceMarketData()


def get_market_context(symbol: str = "ETHUSDT") -> Dict:
    """
    获取市场上下文 - 供策略参考
    
    这是一个轻量级的辅助函数，返回市场情绪数据
    建议只在主信号生成后作为微调参考
    """
    return market_data.get_market_sentiment(symbol)


if __name__ == "__main__":
    # 测试
    print("=== 币安市场数据测试 ===")
    
    data = BinanceMarketData()
    
    # 测试多空比
    lsr = data.get_long_short_ratio()
    if lsr:
        print(f"\n多空比: {lsr['long_short_ratio']:.2f}")
        print(f"多头占比: {lsr['long_account']:.1f}%")
        print(f"空头占比: {lsr['short_account']:.1f}%")
    
    # 测试爆仓数据
    liq = data.get_liquidation_data(limit=50)
    if liq:
        print(f"\n爆仓数据:")
        print(f"  多头爆仓: {liq['long_liquidation']:.2f} ETH")
        print(f"  空头爆仓: {liq['short_liquidation']:.2f} ETH")
        print(f"  爆仓比: {liq['liq_ratio']:.2f}")
    
    # 测试综合情绪
    sentiment = data.get_market_sentiment()
    print(f"\n市场情绪:")
    print(f"  综合偏向: {sentiment['overall_bias']:+.2f}")
    print(f"  信号: {sentiment['long_short_signal']}, {sentiment['liquidation_signal']}")
    print(f"  信息: {sentiment['info']}")
