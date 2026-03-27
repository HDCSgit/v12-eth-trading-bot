# ML市场环境检测 V2 - 深度设计文档

## 一、V1规则版本的问题分析

### 1.1 核心问题

| 问题 | 影响 | 案例 |
|------|------|------|
| **阈值固定** | 无法适应不同波动率的市场 | ETH在1%波动和5%波动时使用相同阈值 |
| **单一时间点判断** | 忽略趋势持续性 | 短暂突破被误判为趋势启动 |
| **人工特征工程** | 可能遗漏隐含模式 | 复杂的顶部结构难以用规则描述 |
| **没有置信度校准** | 无法评估预测可靠性 | 所有预测都是"确定"的 |

### 1.2 具体场景分析

```
场景1: 假突破 (V1误判率 ~40%)
价格: |____/\\____| (快速上涨后迅速回落)
V1:    趋势上涨 (阈值被触发)
V2:    震荡/反转 (通过模式识别)

场景2: 缓慢趋势 (V1延迟 ~5-10周期)
价格: |/\_/\_/\_/\_/\_| (缓慢上涨)
V1:    震荡 (未达阈值)
V2:    弱趋势 (通过动量累积检测)

场景3: 震荡中的噪音 (V1过度交易)
价格: |~\~/\~~\/~~~| (无方向波动)
V1:    频繁切换 (趋势/震荡)
V2:    震荡 (高置信度)
```

## 二、V2 XGBoost方案设计

### 2.1 核心改进

```
┌─────────────────────────────────────────────────────────────────┐
│                        V2 架构                                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │   Feature    │    │   XGBoost    │    │   Output     │      │
│  │   Extractor  │───>│   Classifier │───>│   Adapter    │      │
│  │   (34维)     │    │   (多分类)    │    │   (V1兼容)   │      │
│  └──────────────┘    └──────────────┘    └──────────────┘      │
│         │                   │                   │               │
│         ▼                   ▼                   ▼               │
│  • 价格行为特征         • 多分类概率输出      • Regime枚举      │
│  • 趋势强度特征         • SHAP可解释性       • 置信度校准      │
│  • 动量特征             • 在线学习支持       • 策略建议        │
│  • 波动率特征                                                   │
│  • 成交量特征                                                   │
│  • 统计特征                                                     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 标签生成逻辑（核心创新）

**问题**: 传统的"未来N周期收益"标签过于简单，无法区分"趋势"和"突破"。

**V2解决方案**: 多维度标签生成

```python
def generate_regime_label(df, lookforward=12):
    """
    基于未来多个维度生成市场环境标签
    
    维度1: 方向性 (Direction)
        - 未来N周期净收益
        
    维度2: 持续性 (Sustainability)  
        - 收益是否持续，还是快速反转
        
    维度3: 波动性 (Volatility)
        - 过程中的波动程度
        
    维度4: 速度 (Velocity)
        - 收益是快速爆发还是缓慢积累
    """
    future = df.shift(-lookforward)
    
    # 维度1: 方向性
    total_return = (future['close'] - df['close']) / df['close']
    
    # 维度2: 持续性 (最大回撤/最大收益比)
    future_prices = df['close'].rolling(lookforward).apply(lambda x: list(x))
    max_runup = future_prices.apply(lambda x: (max(x) - x[0]) / x[0] if len(x) > 0 else 0)
    max_drawdown = future_prices.apply(lambda x: (x[0] - min(x)) / x[0] if len(x) > 0 else 0)
    sustainability = max_runup / (max_runup + max_drawdown + 1e-6)
    
    # 维度3: 波动性
    future_vol = df['returns'].rolling(lookforward).std()
    vol_percentile = future_vol.rank(pct=True)
    
    # 维度4: 速度 (前1/3 vs 后2/3收益占比)
    first_third = df['close'].shift(-lookforward//3) / df['close'] - 1
    full_return = total_return
    velocity = abs(first_third) / (abs(full_return) + 1e-6)
    
    # 综合分类
    labels = []
    for i in range(len(df)):
        ret = total_return.iloc[i]
        sus = sustainability.iloc[i]
        vol = vol_percentile.iloc[i]
        vel = velocity.iloc[i]
        
        # 决策树逻辑
        if abs(ret) < 0.01:  # 收益 < 1%
            if vol > 0.7:
                labels.append('HIGH_VOL')  # 高波动无序
            else:
                labels.append('SIDEWAYS')  # 普通震荡
                
        elif ret > 0.03 and sus > 0.6 and vel > 0.5:
            labels.append('BREAKOUT')  # 向上突破
            
        elif ret < -0.03 and sus > 0.6 and vel > 0.5:
            labels.append('BREAKDOWN')  # 向下突破
            
        elif abs(ret) > 0.02 and vel > 0.7:
            labels.append('PUMP' if ret > 0 else 'DUMP')  # 爆拉/砸盘
            
        elif ret > 0.015 and sus > 0.5:
            labels.append('TRENDING_UP')  # 上涨趋势
            
        elif ret < -0.015 and sus > 0.5:
            labels.append('TRENDING_DOWN')  # 下跌趋势
            
        else:
            labels.append('WEAK_TREND' if abs(ret) > 0.01 else 'SIDEWAYS')
    
    return labels
```

### 2.3 特征与V1规则的对应关系

| V1规则 | V2特征 | 说明 |
|--------|--------|------|
| `confidence > 0.85` | `proba_max` | 模型输出的最大概率 |
| `ADX > 25` | `adx_14` | 趋势强度 |
| `连续3次同向` | `trend_consistency_3` | 趋势一致性 |
| `RSI 40-65` | `rsi_14` + `rsi_slope` | RSI值和斜率 |
| `MACD > 0` | `macd_hist` + `macd_slope` | MACD柱状图和动量 |
| `成交量 > 1.3x` | `volume_ratio_20` + `volume_trend` | 成交量比率 |
| `布林带收窄` | `bb_width` | 布林带宽度 |
| 无明显规则 | `hurst_exponent` | 随机游走特征 |
| 无明显规则 | `entropy_20` | 价格混乱度 |

### 2.4 模型训练策略

**类别不平衡处理**:
```python
# 市场环境分布通常不平衡
# SIDEWAYS: 60%, TRENDING: 30%, BREAKOUT: 7%, REVERSAL: 3%

# 解决方案
1. 类别权重: scale_pos_weight
2. 过采样: SMOTE for minority classes
3. 焦点损失: Focal Loss代替交叉熵
```

**时间序列交叉验证**:
```python
# 禁止使用随机分割（数据泄露）
# 使用滚动窗口验证

def time_series_cv(X, y, n_splits=5):
    """滚动窗口交叉验证"""
    n_samples = len(X)
    fold_size = n_samples // n_splits
    
    for i in range(n_splits):
        train_end = fold_size * (i + 1)
        test_end = min(train_end + fold_size, n_samples)
        
        X_train = X[:train_end]
        y_train = y[:train_end]
        X_test = X[train_end:test_end]
        y_test = y[train_end:test_end]
        
        yield X_train, X_test, y_train, y_test
```

## 三、与V1的集成方案

### 3.1 配置接口
```python
# config.py
"REGIME_DETECTOR": {
    "VERSION": "v2",  # "v1" or "v2"
    "MODEL_PATH": "models/regime_xgb_v1.pkl",
    "CONFIDENCE_THRESHOLD": 0.65,  # V2特有：置信度阈值
    "ENABLE_UNCERTAINTY": True,    # V2特有：不确定性量化
}
```

### 3.2 运行时切换
```python
class RegimeDetectorFactory:
    @staticmethod
    def create(config):
        version = config.get("REGIME_DETECTOR", {}).get("VERSION", "v1")
        
        if version == "v2":
            from market_regime_v2 import MarketRegimeDetectorV2
            return MarketRegimeDetectorV2(config)
        else:
            from ml_regime_detector import MLRegimeDetector
            return MLRegimeDetector(config)
```

## 四、可视化方案

### 4.1 实时市场状态面板
```
┌──────────────────────────────────────────────────────┐
│ Market Regime Monitor V2                             │
├──────────────────────────────────────────────────────┤
│                                                      │
│  Current Regime: [TRENDING_UP]                       │
│  Confidence:     [███████░░░] 72%                    │
│  Duration:       18 periods                          │
│                                                      │
│  Probability Distribution:                           │
│  TRENDING_UP    [███████░░░] 72%  ████████████████   │
│  SIDEWAYS       [██░░░░░░░░] 15%                     │
│  BREAKOUT       [█░░░░░░░░░] 8%                      │
│  REVERSAL       [░░░░░░░░░░] 5%                      │
│                                                      │
│  Feature Importance (SHAP):                          │
│  + adx_14       ▓▓▓▓▓▓▓▓▓▓  +0.15                   │
│  + rsi_14       ▓▓▓▓▓▓▓░░░  +0.10                   │
│  - bb_width     ░░░░░░░░░░  -0.05                   │
│                                                      │
└──────────────────────────────────────────────────────┘
```

### 4.2 历史回测分析
- 各环境类型识别准确率
- 环境转换时机捕捉
- 与V1规则的对比分析

## 五、开发里程碑

| 阶段 | 内容 | 时间 |
|------|------|------|
| 1 | 特征工程 + 标签生成 | 1天 |
| 2 | XGBoost模型 + 训练流程 | 1天 |
| 3 | 集成到主程序 | 0.5天 |
| 4 | 可视化工具 | 0.5天 |
| 5 | 测试优化 | 1天 |
| **总计** | | **4天** |
