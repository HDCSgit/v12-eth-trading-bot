# Market Regime Detector V2 - 使用指南

## 概述

V2是基于XGBoost的**数据驱动型**市场环境检测系统，相比V1规则版本具有更高的准确性和适应性。

## 快速开始

### 1. 安装依赖

```bash
pip install xgboost pandas numpy
# 可选：可视化
pip install matplotlib plotly
```

### 2. 训练模型

```bash
# 基础训练
python train_regime_v2.py --data data/eth_1h.csv --output models/regime_xgb_v1.pkl

# 带交叉验证
python train_regime_v2.py --data data/eth_1h.csv --cv 5

# 自定义参数
python train_regime_v2.py --data data/eth_1h.csv --lookforward 24 --test-size 0.15
```

### 3. 测试模型

```bash
python test_regime_v2.py --model models/regime_xgb_v1.pkl --data data/eth_1h.csv
```

### 4. 启用V2

修改 `config.py`:

```python
"ML_REGIME_VERSION": "v2",  # 从 "v1" 改为 "v2"
"ML_REGIME_V2_MODEL_PATH": "models/regime_xgb_v1.pkl",
```

## 项目结构

```
market_regime_v2/           # V2模块目录
├── __init__.py            # 模块入口
├── detector.py            # 检测器主类
├── trainer.py             # 训练器
├── features.py            # 特征工程
├── visualizer.py          # 可视化工具
└── integration.py         # 主程序集成

train_regime_v2.py         # 训练脚本
test_regime_v2.py          # 测试脚本
models/                    # 模型存储目录
├── regime_xgb_v1.pkl     # 训练好的模型
docs/                      # 文档
├── V2_DESIGN_DEEP_DIVE.md # 深度设计文档
└── V2_README.md          # 本文件
```

## 核心特性

### 与V1对比

| 特性 | V1 (规则) | V2 (XGBoost) |
|------|-----------|--------------|
| **准确性** | 中等 | 更高（数据驱动） |
| **适应性** | 固定阈值 | 自动学习适应 |
| **输出** | 硬分类 | 概率分布 |
| **不确定性** | 无 | 有（熵度量） |
| **可解释性** | 规则清晰 | SHAP特征重要性 |
| **依赖** | 无 | xgboost |
| **训练** | 不需要 | 需要历史数据 |

### 支持的市场环境类型

```
SIDEWAYS          # 震荡市
TRENDING_UP       # 上涨趋势
TRENDING_DOWN     # 下跌趋势
WEAK_TREND_UP     # 弱趋势上
WEAK_TREND_DOWN   # 弱趋势下
BREAKOUT          # 向上突破
BREAKDOWN         # 向下突破
PUMP              # 爆拉行情
HIGH_VOL          # 高波动无序
REVERSAL_TOP      # 顶部反转
REVERSAL_BOTTOM   # 底部反转
```

## 代码示例

### 基础使用

```python
from market_regime_v2 import MarketRegimeDetectorV2

# 加载模型
detector = MarketRegimeDetectorV2(model_path='models/regime_xgb_v1.pkl')

# 预测
result = detector.predict(df)

print(f"当前环境: {result.regime.value}")
print(f"置信度: {result.confidence:.2%}")
print(f"建议: {result.recommended_action}")

# 概率分布
for regime, prob in result.probabilities.items():
    print(f"  {regime}: {prob:.1%}")
```

### 批量预测（回测）

```python
# 对整个DataFrame进行预测
result_df = detector.predict_batch(df)

# result_df 包含:
# - regime_pred: 预测的环境类型
# - regime_confidence: 置信度
```

### 可视化

```python
from market_regime_v2.visualizer import RegimeVisualizer

viz = RegimeVisualizer()

# 时间线可视化
viz.plot_regime_timeline(result_df, save_path='regime_timeline.png')

# 特征重要性
viz.plot_feature_importance(importance_dict, save_path='features.png')

# HTML报告
viz.generate_html_report(result_df, output_path='report.html')
```

## 集成到主程序

### 方式1：使用工厂模式（推荐）

```python
from market_regime_v2.integration import get_regime_detector

detector = get_regime_detector()

if detector:
    decision = detector.detect(df)
    print(f"环境: {decision.regime}")
    print(f"仓位倍数: {decision.adjustments['position_mult']}")
```

### 方式2：直接实例化

```python
from market_regime_v2 import MarketRegimeDetectorV2

detector = MarketRegimeDetectorV2(
    config={'CONFIDENCE_THRESHOLD': 0.7},
    model_path='models/regime_xgb_v1.pkl'
)

result = detector.predict(df)
regime_name, adjustments = result.to_v1_format()
```

## 训练参数说明

### 标签生成参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `lookforward` | 预测未来N周期 | 12 |
| `return_threshold` | 收益阈值 | 0.015 |

### 模型参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `max_depth` | 树最大深度 | 6 |
| `learning_rate` | 学习率 | 0.05 |
| `n_estimators` | 树数量 | 200 |
| `subsample` | 样本采样率 | 0.8 |

## 故障排除

### 模型加载失败

```
ERROR: Model not loaded!
```

- 检查模型文件路径是否正确
- 检查是否使用相同版本的xgboost训练/加载

### XGBoost未安装

```
ImportError: No module named 'xgboost'
```

```bash
pip install xgboost
```

### 数据格式错误

```
ValueError: Missing required column: close
```

确保CSV包含: `open`, `high`, `low`, `close`, `volume`

## 回退机制

如果V2模型加载失败或预测出错，系统会自动回退到V1规则版本或保守设置：

```python
# 回退决策
{
    'regime': 'SIDEWAYS',
    'confidence': 0.5,
    'position_mult': 1.0,
    'use_limit_order': True,
}
```

## 开发路线图

- [x] 基础XGBoost模型
- [x] 特征工程
- [x] 可视化工具
- [ ] 在线学习（增量更新）
- [ ] 多时间框架融合
- [ ] 注意力机制（LSTM+Attention）

## 相关文档

- `V2_DESIGN_DEEP_DIVE.md` - 深度设计分析
- `V1_README.md` - V1版本文档（如需对比）
