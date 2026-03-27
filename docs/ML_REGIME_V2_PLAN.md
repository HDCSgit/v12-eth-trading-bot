# ML市场环境检测 V2 计划

## 背景
当前V1版本：基于规则的市场环境检测 (`ml_regime_detector.py`)
- 优点：零依赖、可解释性强、即时可用
- 风险：规则阈值固定，可能无法适应所有市场状况

## V2 目标
基于XGBoost/LightGBM的机器学习市场环境分类器

## 设计方案

### 1. 架构（低耦合）
```
MarketRegimeMLV2 (可替换V1)
    │
    ├── Feature Extractor (特征提取)
    ├── XGBoost/LightGBM Classifier (分类器)
    └── Output Adapter (输出适配，兼容V1接口)
```

### 2. 接口设计（与V1兼容）
```python
class MarketRegimeMLV2:
    def __init__(self, model_path=None): ...
    def predict(self, df: pd.DataFrame) -> RegimeResult: ...
    def train(self, df: pd.DataFrame, labels: pd.Series): ...
```

### 3. 触发条件
- V1规则版本运行2周后，准确率 < 60%
- 特定市场环境频繁误判（如假突破）
- 需要更细粒度的环境分类

### 4. 对比

| 特性 | V1 (规则) | V2 (ML) |
|------|-----------|---------|
| 准确性 | 中等 | 更高（数据驱动）|
| 适应性 | 手动调参 | 自动学习 |
| 解释性 | 强 | 中等（SHAP）|
| 依赖 | 无 | xgboost/lightgbm |
| 训练 | 无需 | 需要历史数据 |

### 5. 开发预估
- 特征工程：1天
- 标签生成逻辑：1天
- 模型训练流程：1天
- 集成测试：1天
- 总计：4-5天
