#!/usr/bin/env python3
"""
币安历史K线数据下载器
获取ETHUSDT 2024-2026年1小时K线数据
"""

import requests
import pandas as pd
import time
from datetime import datetime, timedelta
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)


class BinanceDataDownloader:
    """币安数据下载器"""
    
    def __init__(self):
        self.base_url = "https://fapi.binance.com"  # 合约API
        self.spot_url = "https://api.binance.com"   # 现货API
        self.max_limit = 1000  # 币安单次最大返回1000条
        self.rate_limit_delay = 0.1  # 请求间隔（秒）
        
    def get_klines(self, symbol: str, interval: str, start_time: int, end_time: int, limit: int = 1000):
        """
        获取K线数据
        
        Args:
            symbol: 交易对，如 'ETHUSDT'
            interval: 时间周期，如 '1h', '4h', '1d'
            start_time: 开始时间戳（毫秒）
            end_time: 结束时间戳（毫秒）
            limit: 返回条数，最大1000
        
        Returns:
            list: K线数据列表
        """
        url = f"{self.base_url}/fapi/v1/klines"
        
        params = {
            'symbol': symbol,
            'interval': interval,
            'startTime': start_time,
            'endTime': end_time,
            'limit': limit
        }
        
        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"请求失败: {e}")
            return None
    
    def download_full_history(self, symbol: str = 'ETHUSDT', interval: str = '1h',
                             start_date: str = '2024-01-01', 
                             end_date: str = '2026-03-20'):
        """
        下载完整历史数据（自动分页）
        
        Returns:
            pd.DataFrame: 完整数据
        """
        logger.info(f"开始下载 {symbol} {interval} 数据")
        logger.info(f"时间范围: {start_date} 至 {end_date}")
        
        # 转换时间为毫秒时间戳
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        
        start_ms = int(start_dt.timestamp() * 1000)
        end_ms = int(end_dt.timestamp() * 1000)
        
        all_data = []
        current_start = start_ms
        
        # 计算1小时对应毫秒数
        interval_ms = self._interval_to_ms(interval)
        
        batch_count = 0
        
        while current_start < end_ms:
            batch_count += 1
            current_end = min(current_start + (self.max_limit * interval_ms), end_ms)
            
            logger.info(f"下载批次 #{batch_count}: {self._ms_to_str(current_start)} - {self._ms_to_str(current_end)}")
            
            klines = self.get_klines(symbol, interval, current_start, current_end)
            
            if klines is None or len(klines) == 0:
                logger.warning("没有数据返回，跳过")
                # 前进一天
                current_start += 24 * 60 * 60 * 1000
                continue
            
            all_data.extend(klines)
            logger.info(f"获取 {len(klines)} 条数据，累计 {len(all_data)} 条")
            
            # 更新下一次请求的起始时间
            # 最后一条数据的close time + 1ms
            last_close_time = klines[-1][6]  # closeTime是第7个字段
            current_start = last_close_time + 1
            
            # 限速保护
            time.sleep(self.rate_limit_delay)
            
            # 每10批次暂停一下，避免IP被限
            if batch_count % 10 == 0:
                logger.info("暂停2秒避免限流...")
                time.sleep(2)
        
        logger.info(f"下载完成！共 {len(all_data)} 条数据")
        
        return self._process_klines(all_data)
    
    def _interval_to_ms(self, interval: str) -> int:
        """转换时间周期为毫秒"""
        mapping = {
            '1m': 60 * 1000,
            '3m': 3 * 60 * 1000,
            '5m': 5 * 60 * 1000,
            '15m': 15 * 60 * 1000,
            '30m': 30 * 60 * 1000,
            '1h': 60 * 60 * 1000,
            '2h': 2 * 60 * 60 * 1000,
            '4h': 4 * 60 * 60 * 1000,
            '6h': 6 * 60 * 60 * 1000,
            '8h': 8 * 60 * 60 * 1000,
            '12h': 12 * 60 * 60 * 1000,
            '1d': 24 * 60 * 60 * 1000,
            '3d': 3 * 24 * 60 * 60 * 1000,
            '1w': 7 * 24 * 60 * 60 * 1000,
        }
        return mapping.get(interval, 60 * 60 * 1000)  # 默认1小时
    
    def _ms_to_str(self, ms: int) -> str:
        """毫秒时间戳转字符串"""
        return datetime.fromtimestamp(ms / 1000).strftime('%Y-%m-%d %H:%M')
    
    def _process_klines(self, klines: list) -> pd.DataFrame:
        """
        处理原始K线数据
        
        币安K线字段：
        0: openTime (开盘时间)
        1: open (开盘价)
        2: high (最高价)
        3: low (最低价)
        4: close (收盘价)
        5: volume (成交量)
        6: closeTime (收盘时间)
        7: quoteAssetVolume (成交额)
        8: numberOfTrades (成交笔数)
        9: takerBuyBaseAssetVolume (主动买入成交量)
        10: takerBuyQuoteAssetVolume (主动买入成交额)
        11: ignore (忽略)
        """
        if not klines:
            return pd.DataFrame()
        
        df = pd.DataFrame(klines, columns=[
            'open_time', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'trades', 'taker_buy_base',
            'taker_buy_quote', 'ignore'
        ])
        
        # 转换时间戳
        df['timestamp'] = pd.to_datetime(df['open_time'], unit='ms')
        df['close_time'] = pd.to_datetime(df['close_time'], unit='ms')
        
        # 转换数值类型
        numeric_cols = ['open', 'high', 'low', 'close', 'volume', 
                       'quote_volume', 'trades', 'taker_buy_base', 'taker_buy_quote']
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # 删除ignore列
        df = df.drop('ignore', axis=1)
        
        # 排序
        df = df.sort_values('open_time').reset_index(drop=True)
        
        return df
    
    def verify_data(self, df: pd.DataFrame, expected_interval: str = '1h') -> dict:
        """
        验证数据完整性和准确性
        
        Args:
            df: DataFrame数据
            expected_interval: 期望的时间间隔
        
        Returns:
            dict: 验证结果
        """
        logger.info("开始验证数据...")
        
        report = {
            'total_rows': len(df),
            'start_time': df['timestamp'].min(),
            'end_time': df['timestamp'].max(),
            'time_span_days': (df['timestamp'].max() - df['timestamp'].min()).days,
            'missing_values': df.isnull().sum().sum(),
            'duplicates': df['open_time'].duplicated().sum(),
            'price_range': f"${df['low'].min():.2f} - ${df['high'].max():.2f}",
            'avg_volume': df['volume'].mean(),
            'is_continuous': True,
            'gaps': []
        }
        
        # 检查时间连续性
        interval_minutes = self._interval_to_ms(expected_interval) / (60 * 1000)
        expected_diff = timedelta(minutes=interval_minutes)
        
        time_diffs = df['timestamp'].diff().dropna()
        gaps = time_diffs[time_diffs > expected_diff * 1.5]  # 允许50%误差
        
        if len(gaps) > 0:
            report['is_continuous'] = False
            report['gaps_count'] = len(gaps)
            report['gaps'] = [(str(idx), str(diff)) for idx, diff in gaps.head(5).items()]
            logger.warning(f"发现 {len(gaps)} 个时间缺口！")
        
        # 价格合理性检查
        suspicious_prices = df[
            (df['high'] < df['low']) | 
            (df['close'] > df['high']) | 
            (df['close'] < df['low']) |
            (df['open'] > df['high']) | 
            (df['open'] < df['low'])
        ]
        
        report['suspicious_prices'] = len(suspicious_prices)
        
        if len(suspicious_prices) > 0:
            logger.warning(f"发现 {len(suspicious_prices)} 条价格异常数据！")
        
        # 成交量检查
        zero_volume = df[df['volume'] == 0]
        report['zero_volume_rows'] = len(zero_volume)
        
        logger.info("数据验证完成！")
        return report


def main():
    """主函数"""
    downloader = BinanceDataDownloader()
    
    # 下载数据
    df = downloader.download_full_history(
        symbol='ETHUSDT',
        interval='1h',
        start_date='2024-01-01',
        end_date='2026-03-20'
    )
    
    if df.empty:
        logger.error("下载失败，没有数据")
        return
    
    # 保存数据
    output_file = 'eth_usdt_1h_binance.csv'
    df.to_csv(output_file, index=False)
    logger.info(f"数据已保存: {output_file}")
    
    # 验证数据
    report = downloader.verify_data(df, expected_interval='1h')
    
    # 打印验证报告
    print("\n" + "=" * 80)
    print("📊 数据验证报告")
    print("=" * 80)
    print(f"\n✅ 基本统计:")
    print(f"  总条数: {report['total_rows']:,}")
    print(f"  时间跨度: {report['start_time']} 至 {report['end_time']}")
    print(f"  天数: {report['time_span_days']} 天")
    print(f"  预期条数: ~{report['time_span_days'] * 24:,} (每小时1条)")
    
    print(f"\n📈 价格信息:")
    print(f"  价格范围: {report['price_range']}")
    print(f"  平均成交量: {report['avg_volume']:,.2f}")
    
    print(f"\n⚠️  数据质量:")
    print(f"  缺失值: {report['missing_values']}")
    print(f"  重复时间戳: {report['duplicates']}")
    print(f"  时间连续性: {'✅ 连续' if report['is_continuous'] else '❌ 有缺口'}")
    
    if not report['is_continuous']:
        print(f"  缺口数量: {report['gaps_count']}")
        print(f"  前5个缺口: {report['gaps']}")
    
    print(f"  价格异常: {report['suspicious_prices']} 条")
    print(f"  零成交量: {report['zero_volume_rows']} 条")
    
    # 数据样本
    print(f"\n📋 数据样本 (前5条):")
    print(df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].head().to_string())
    
    print(f"\n📋 数据样本 (后5条):")
    print(df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].tail().to_string())
    
    print("\n" + "=" * 80)
    
    # 生成数据摘要JSON
    import json
    summary = {
        'symbol': 'ETHUSDT',
        'interval': '1h',
        'start_time': str(report['start_time']),
        'end_time': str(report['end_time']),
        'total_rows': report['total_rows'],
        'price_low': float(df['low'].min()),
        'price_high': float(df['high'].max()),
        'data_quality': {
            'is_continuous': report['is_continuous'],
            'missing_values': int(report['missing_values']),
            'duplicates': int(report['duplicates']),
            'suspicious_prices': int(report['suspicious_prices'])
        }
    }
    
    with open('eth_data_summary.json', 'w') as f:
        json.dump(summary, f, indent=2)
    
    logger.info("数据摘要已保存: eth_data_summary.json")
    
    if report['is_continuous'] and report['missing_values'] == 0 and report['suspicious_prices'] == 0:
        logger.info("✅ 数据验证通过！数据完整准确")
    else:
        logger.warning("⚠️ 数据存在一些问题，但基本可用")


if __name__ == "__main__":
    main()