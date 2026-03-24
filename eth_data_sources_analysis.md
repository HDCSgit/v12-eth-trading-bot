# ETH/ETHUSDT 高可信度数据源分析

## 一、交易所API可直接获取（币安）

### 1.1 多空比 (Long/Short Ratio) ⭐⭐⭐⭐⭐ 强烈推荐

```
API: GET /futures/data/globalLongShortAccountRatio
参数: symbol=ETHUSDT, period=5m/15m/1h

返回值:
{
  "symbol": "ETHUSDT",
  "longShortRatio": "1.2345",    // 多空比 >1多头占优，<1空头占优
  "longAccount": "55.23",         // 多头账户占比%
  "shortAccount": "44.77",        // 空头账户占比%
  "timestamp": 1711234567890
}
```

**使用策略**:
```python
# 极端多空比 = 反向指标
if long_short_ratio > 3.0:  # 多头是空头3倍
    signal = "极度贪婪，可能回调，偏空"
elif long_short_ratio < 0.33:  # 空头是多头3倍
    signal = "极度恐惧，可能反弹，偏多"

# 多空比变化率
ratio_change = current_ratio - prev_ratio
if ratio_change > 0.5:  # 多头快速增加
    signal = "FOMO情绪升温，警惕回调"
```

**可信度**: ⭐⭐⭐⭐⭐ 交易所原始数据，实时准确

---

### 1.2 爆仓数据 (Liquidation Data) ⭐⭐⭐⭐⭐ 强烈推荐

```
API: GET /fapi/v1/forceOrders
或聚合数据API

返回值:
{
  "symbol": "ETHUSDT",
  "side": "SELL",              // 多头爆仓是SELL（平仓卖出）
  "origQty": "125.5",          // 爆仓数量(ETH)
  "price": "3540.25",
  "executedQty": "125.5",
  "time": 1711234567890
}
```

**关键指标**:
```python
# 1. 多空爆仓比
long_liq = sum(qty for o in orders if o['side'] == 'SELL')  # 多头爆仓
short_liq = sum(qty for o in orders if o['side'] == 'BUY')  # 空头爆仓
liq_ratio = long_liq / short_liq

# 2. 爆仓集中度（某一价格区间）
price_clusters = cluster_by_price(orders, cluster_size=10)  # $10区间
max_cluster = max(price_clusters, key=lambda x: x['total_qty'])

# 策略应用
if long_liq > short_liq * 3:  # 多头爆仓是空头3倍
    signal = "多头踩踏，可能继续下跌或超跌反弹"
    
if max_cluster['price'] < current_price * 0.98:
    signal = f"大量爆仓集中在{max_cluster['price']}, 可能形成支撑"
```

**可信度**: ⭐⭐⭐⭐⭐ 交易所原始数据

---

### 1.3 资金费率 (Funding Rate) ⭐⭐⭐⭐ 已在使用

```
API: GET /fapi/v1/fundingRate

// 当前已有此数据，但可以更深入使用
```

**进阶用法**:
```python
# 资金费率趋势
funding_trend = calculate_trend(funding_rates, period=24)  # 24小时趋势

if funding_rate > 0.01 and funding_trend == 'increasing':
    signal = "多头付费加速增加，做空压力大，可能回调"
    
# 资金费率与价格背离
if price_up and funding_down:  # 价格涨但费率降
    signal = "多头力量减弱，上涨不可持续"
```

---

### 1.4 持仓量 (Open Interest) ⭐⭐⭐⭐ 重要

```
API: GET /fapi/v1/openInterest

返回值:
{
  "symbol": "ETHUSDT",
  "openInterest": "125000.5",   // 持仓量(ETH)
  "time": 1711234567890
}
```

**使用策略**:
```python
# 持仓量变化率
oi_change = (current_oi - prev_oi) / prev_oi

# 价量关系
if price_up and oi_up:
    signal = "量价齐升，趋势健康"
elif price_up and oi_down:
    signal = "量价背离，上涨无力（空头平仓推动）"
elif price_down and oi_up:
    signal = "增仓下跌，空头主动进攻"
elif price_down and oi_down:
    signal = "缩量下跌，可能企稳"

# OI与价格相关系数
oi_price_corr = correlation(oi_series, price_series, window=20)
if oi_price_corr < -0.5:
    signal = "OI与价格负相关，警惕反转"
```

**可信度**: ⭐⭐⭐⭐⭐ 交易所原始数据

---

### 1.5 大户持仓数据 (Top Trader Accounts) ⭐⭐⭐⭐

```
API: GET /futures/data/topLongShortAccountRatio
API: GET /futures/data/topLongShortPositionRatio

返回值:
{
  "symbol": "ETHUSDT",
  "longAccount": "52.3",      // 大户多头账户占比
  "shortAccount": "47.7",     // 大户空头账户占比
  "longPosition": "58.5",     // 大户多头持仓占比
  "shortPosition": "41.5"     // 大户空头持仓占比
}
```

**使用策略**:
```python
# 大户vs散户分歧
if top_long > 60 and retail_long < 40:
    signal = "大户看多，散户看空，跟随大户"
elif top_long < 40 and retail_long > 60:
    signal = "大户看空，散户看多，跟随大户"

# 大户持仓变化
top_position_change = current_top_long - prev_top_long
if abs(top_position_change) > 10:  # 大户调仓>10%
    signal = "大户大幅调仓，可能有内幕消息"
```

**可信度**: ⭐⭐⭐⭐ 交易所数据，但"大户"定义可能变化

---

## 二、链上数据 (On-Chain Data) ⭐⭐⭐⭐⭐ 高可信度

### 2.1 交易所净流入/流出 (Exchange Netflow)

```python
# Glassnode API (收费) 或公开API
# 原理：ETH流入交易所 = 可能卖出；流出 = 可能持有

if exchange_inflow > avg_30d * 2:  # 流入是均值2倍
    signal = "大量ETH转入交易所，抛压增加"
elif exchange_outflow > avg_30d * 2:
    signal = "大量ETH转出交易所，抛压减轻"

# 交易所余额趋势
if exchange_balance_trend == 'decreasing':
    signal = "交易所ETH余额持续下降，长期看涨"
```

**数据源**: Glassnode, CryptoQuant, OKLink
**可信度**: ⭐⭐⭐⭐⭐ 区块链公开透明数据

---

### 2.2 巨鲸动向 (Whale Activity)

```python
# 监控>1000 ETH的转账
whale_txns = get_large_transactions(min_amount=1000, timeframe='1h')

if len(whale_txns) > 10:  # 1小时内>10笔巨鲸转账
    to_exchanges = [tx for tx in whale_txns if tx['to'] in EXCHANGE_WALLETS]
    from_exchanges = [tx for tx in whale_txns if tx['from'] in EXCHANGE_WALLETS]
    
    if len(to_exchanges) > len(from_exchanges) * 2:
        signal = "巨鲸向交易所转入，抛压增加"
    elif len(from_exchanges) > len(to_exchanges) * 2:
        signal = "巨鲸从交易所转出，吸筹"
```

**可信度**: ⭐⭐⭐⭐⭐ 区块链公开数据

---

### 2.3 活跃地址数 / 新地址数

```python
# 网络活跃度
active_addresses = get_active_addresses('ETH', timeframe='1d')
new_addresses = get_new_addresses('ETH', timeframe='1d')

if active_addresses > sma(active_addresses, 30) * 1.2:
    signal = "网络活跃度激增，基本面改善"
```

---

### 2.4 Gas费数据 (Network Congestion)

```python
gas_price = get_avg_gas_price()

if gas_price > 100:  # Gwei
    signal = "网络拥堵，可能有大行情或NFT热潮"
elif gas_price < 20:
    signal = "网络冷清，市场低迷"
```

---

## 三、订单簿数据 (Order Book) ⭐⭐⭐⭐⭐ 实时性最高

### 3.1 买卖盘深度

```python
# 币安websocket或REST API
depth = get_order_book(symbol='ETHUSDT', limit=500)

# 计算买卖压力
bids_volume = sum([d['qty'] for d in depth['bids'][:10]])  # 前10档买单
asks_volume = sum([d['qty'] for d in depth['asks'][:10]])  # 前10档卖单
pressure_ratio = bids_volume / asks_volume

if pressure_ratio > 2:
    signal = "买盘压力大，支撑强"
elif pressure_ratio < 0.5:
    signal = "卖盘压力大，阻力大"

# 大单挂单（鲸鱼单）
large_bids = [d for d in depth['bids'] if d['qty'] > 100]  # >100 ETH
large_asks = [d for d in depth['asks'] if d['qty'] > 100]

if large_bids and min([d['price'] for d in large_bids]) > current_price * 0.99:
    support_price = max([d['price'] for d in large_bids])
    signal = f"大额买单支撑在 {support_price}"
```

**可信度**: ⭐⭐⭐⭐⭐ 交易所实时数据

---

### 3.2 买卖盘变化率

```python
# 监控挂单变化
depth_change = current_depth - prev_depth

if depth_change['bids'] > 0 and depth_change['asks'] < 0:
    signal = "买盘增加，卖盘减少，看涨"
elif depth_change['bids'] < 0 and depth_change['asks'] > 0:
    signal = "买盘减少，卖盘增加，看跌"
```

---

## 四、市场情绪指标 ⭐⭐⭐

### 4.1 恐惧贪婪指数 (Fear & Greed Index)

```python
# Alternative.me API
fear_greed = get_fear_greed_index()
# 0-24: 极度恐惧, 25-49: 恐惧, 50-74: 贪婪, 75-100: 极度贪婪

if fear_greed < 20:
    signal = "极度恐惧，可能是买入机会"
elif fear_greed > 80:
    signal = "极度贪婪，可能是卖出机会"
```

**可信度**: ⭐⭐⭐ 综合指标，滞后性

---

### 4.2 期权数据 (Options Data)

```python
# Deribit API
# 看跌/看涨比率 (Put/Call Ratio)
pc_ratio = get_put_call_ratio('ETH')

if pc_ratio > 1.2:
    signal = "PUT多于CALL，市场情绪悲观"
elif pc_ratio < 0.7:
    signal = "CALL多于PUT，市场情绪乐观"

# 最大痛点 (Max Pain)
max_pain_price = get_max_pain_price('ETH', expiry='weekly')
if current_price > max_pain_price * 1.05:
    signal = "价格高于最大痛点，可能回调"
```

**数据源**: Deribit, skew.com
**可信度**: ⭐⭐⭐⭐ 专业衍生品数据

---

## 五、推荐优先级

| 优先级 | 数据源 | 延迟 | 可信度 | 是否免费 |
|-------|-------|------|-------|---------|
| 1 | 爆仓数据 | <1秒 | ⭐⭐⭐⭐⭐ | ✅ 币安API |
| 2 | 多空比 | 5-15分钟 | ⭐⭐⭐⭐⭐ | ✅ 币安API |
| 3 | 订单簿深度 | <100ms | ⭐⭐⭐⭐⭐ | ✅ 币安API |
| 4 | 持仓量 | 1分钟 | ⭐⭐⭐⭐⭐ | ✅ 币安API |
| 5 | 交易所净流入 | 1小时 | ⭐⭐⭐⭐⭐ | ⚠️ Glassnode收费 |
| 6 | 巨鲸动向 | 实时 | ⭐⭐⭐⭐⭐ | ⚠️ 需节点 |
| 7 | 大户持仓 | 1小时 | ⭐⭐⭐⭐ | ✅ 币安API |
| 8 | 期权数据 | 1小时 | ⭐⭐⭐⭐ | ⚠️ Deribit API |
| 9 | 恐惧贪婪 | 1天 | ⭐⭐⭐ | ✅ 免费API |

---

## 六、建议接入顺序

```python
# Phase 1: 交易所数据（立即接入，免费且高可信度）
1. 多空比 (Long/Short Ratio)
2. 爆仓数据 (Liquidation)
3. 持仓量 (Open Interest)
4. 订单簿深度 (Order Book Depth)

# Phase 2: 链上数据（需要开发或购买服务）
5. 交易所净流入
6. 巨鲸动向

# Phase 3: 情绪指标（辅助决策）
7. 期权数据
8. 恐惧贪婪指数
```

---

## 七、实战策略示例

```python
def generate_enhanced_signal(price_data, onchain_data, market_data):
    signals = []
    
    # 1. 多空比极端值
    if market_data['long_short_ratio'] > 3.0:
        signals.append(('S', 0.7, '多空比>3，极度贪婪'))
    elif market_data['long_short_ratio'] < 0.33:
        signals.append(('B', 0.7, '多空比<0.33，极度恐惧'))
    
    # 2. 爆仓信号
    if market_data['long_liquidation_1h'] > market_data['short_liquidation_1h'] * 3:
        signals.append(('B', 0.6, '多头大量爆仓，可能反弹'))
    
    # 3. 持仓量+价格背离
    if price_data['change_24h'] > 0.05 and market_data['oi_change'] < -0.1:
        signals.append(('S', 0.65, '价格上涨但持仓下降，空头平仓推动'))
    
    # 4. 交易所净流入
    if onchain_data['exchange_inflow_1h'] > onchain_data['avg_inflow'] * 3:
        signals.append(('S', 0.6, '大量ETH转入交易所，抛压增加'))
    
    # 综合评分
    return aggregate_signals(signals)
```

---

**下一步**: 是否需要我先接入「多空比」和「爆仓数据」到系统中？这两个是币安API免费提供的，可信度最高。
