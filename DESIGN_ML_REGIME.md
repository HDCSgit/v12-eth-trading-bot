# ML市场环境检测模块设计文档

## 版本信息
- **版本**: 1.0.0
- **日期**: 2026-03-27
- **作者**: AI Assistant

---

## 1. 设计目标

### 1.1 核心目标
让ML模型参与市场环境判断，弥补纯技术指标的滞后性，实现：
- **更早发现趋势启动**（比技术指标早1-3分钟）
- **识别假突破/假跌破**（ML低置信度时谨慎交易）
- **反转预警**（ML方向与趋势背离时及时止盈）

### 1.2 设计原则
| 原则 | 说明 |
|------|------|
| **低耦合** | 模块独立，通过接口调用，不依赖主程序内部状态 |
| **高内聚** | 单一职责：仅负责ML→环境的映射判断 |
| **可配置** | 所有阈值参数化，支持运行时调整 |
| **可留痕** | 所有判断结果记录到日志和数据库，可追溯 |

---

## 2. 架构设计

### 2.1 模块位置
```
binancepro/
├── main_v12_live_optimized.py    # 主程序
├── ml_regime_detector.py          # ⭐ 新模块（ML环境检测）
├── config.py                      # 配置（新增ML相关参数）
├── DESIGN_ML_REGIME.md           # ⭐ 本文档
└── ...
```

### 2.2 调用关系
```
┌─────────────────────────────────────────────────────────┐
│                    主程序 (TradingSystem)                │
│  ┌─────────────────────────────────────────────────┐   │
│  │  generate_signal()                               │   │
│  │    ├── 技术指标分析 (MarketAnalyzer)              │   │
│  │    ├── ML模型预测 (XGBoost)                      │   │
│  │    └── ⭐ ML环境检测 (MLRegimeDetector)          │   │
│  │         └─→ 整合决策                              │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
                            ↓
                    ┌───────────────┐
                    │  数据库/日志   │
                    │  (留痕存储)   │
                    └───────────────┘
```

### 2.3 数据流
```
ML模型输出
    ├── direction (1/-1/0)
    ├── confidence (0-1)
    ├── proba_long (0-1)
    └── proba_short (0-1)
           ↓
    MLRegimeDetector.detect()
           ↓
    MLRegimeResult
           ├── regime (STRONG_UP/STRONG_DOWN/SIDEWAYS...)
           ├── confidence
           ├── recommended_action
           ├── position_size_mult
           └── reason
           ↓
    与技术指标环境整合
           ↓
    最终交易决策
```

---

## 3. 核心组件

### 3.1 MLRegimeType（枚举）
```python
class MLRegimeType(Enum):
    STRONG_UP       # 强趋势上涨 → 加大仓位
    STRONG_DOWN     # 强趋势下跌 → 加大仓位
    WEAK_UP         # 弱趋势上涨 → 降低仓位
    WEAK_DOWN       # 弱趋势下跌 → 降低仓位
    SIDEWAYS        # 震荡市 → 高抛低吸
    REVERSAL_TOP    # 顶部反转 → 立即止盈
    REVERSAL_BOTTOM # 底部反转 → 立即止盈
    UNCERTAIN       # 不确定 → 观望
```

### 3.2 检测规则（优先级排序）

| 优先级 | 规则 | 触发条件 | 结果 |
|--------|------|---------|------|
| 1 | 强趋势 | 置信度≥0.75 + 概率>0.70 | STRONG_UP/DOWN |
| 2 | 反转预警 | 方向翻转 + 置信度>0.65 | REVERSAL |
| 3 | 趋势延续 | 连续3次同方向 + 平均置信>0.65 | STRONG |
| 4 | 震荡市 | 置信度<0.60 + 概率差<0.20 | SIDEWAYS |
| 5 | 弱趋势 | 0.60≤置信度<0.75 | WEAK |
| 6 | 不确定 | 其他情况 | UNCERTAIN |

### 3.3 与技术指标整合策略

```python
# 场景1: ML强趋势 + 技术震荡 → 趋势可能启动
if ML says STRONG_UP and Technical says SIDEWAYS:
    override_regime = "趋势上涨"
    position_mult = 1.2
    use_limit_order = False  # 用Taker确保成交

# 场景2: ML震荡 + 技术趋势 → 趋势可能结束
if ML says SIDEWAYS and Technical says TREND:
    confidence_boost = -0.1
    position_mult = 0.7

# 场景3: ML反转 + 技术趋势 → 立即止盈
if ML says REVERSAL and Technical says TREND:
    close_position = True
```

---

## 4. 配置参数

### 4.1 config.py 新增配置
```python
# ==========================================
# ML环境检测配置 (新增 2026-03-27)
# ==========================================
"ML_REGIME_ENABLED": True,           # 启用ML环境检测
"ML_REGIME_HISTORY_SIZE": 10,        # 历史记录保留次数

# 强趋势阈值
"ML_STRONG_TREND_CONFIDENCE": 0.75,  # 强趋势最小置信度
"ML_STRONG_TREND_PROBA": 0.70,       # 强趋势最小概率

# 震荡市阈值
"ML_SIDEWAYS_MAX_CONFIDENCE": 0.60,  # 震荡市最大置信度
"ML_SIDEWAYS_PROBA_DIFF": 0.20,      # 震荡市概率差阈值

# 趋势延续
"ML_TREND_CONTINUITY_COUNT": 3,      # 连续判断次数
"ML_TREND_CONTINUITY_CONF": 0.65,    # 趋势延续最小置信度

# 反转预警
"ML_REVERSAL_CONFIDENCE": 0.65,      # 反转预警置信度

# 仓位调整
"ML_POS_STRONG": 1.2,                # 强趋势仓位倍数
"ML_POS_NORMAL": 1.0,                # 正常仓位倍数
"ML_POS_WEAK": 0.7,                  # 弱趋势仓位倍数
"ML_POS_REVERSAL": 0.5,              # 反转预警仓位倍数
```

---

## 5. 留痕设计

### 5.1 日志记录
```python
# 检测日志
logger.info(f"[ML环境检测] 输入: 方向={direction}, 置信度={confidence}")
logger.info(f"[ML环境检测] 输出: 环境={result.regime.name}, 建议={result.recommended_action}")
logger.info(f"[ML环境检测] 整合: 技术环境={tech_regime} → 最终={final_regime}")

# 决策日志
logger.info(f"[ML决策] 仓位调整: {original_size} × {mult} = {adjusted_size}")
logger.info(f"[ML决策] 策略选择: {strategy} (原因: {reason})")
```

### 5.2 数据库记录（新增字段）
```sql
-- signals表新增
ALTER TABLE signals ADD COLUMN ml_regime TEXT;        -- ML判断的环境
ALTER TABLE signals ADD COLUMN ml_regime_conf REAL;   -- ML判断置信度
ALTER TABLE signals ADD COLUMN tech_regime TEXT;      -- 技术判断的环境
ALTER TABLE signals ADD COLUMN final_regime TEXT;     -- 最终整合的环境
ALTER TABLE signals ADD COLUMN regime_override INTEGER; -- 是否覆盖(0/1)
ALTER TABLE signals ADD COLUMN pos_size_mult REAL;    -- 仓位倍数

-- trades表已有order_type，保持不变
```

### 5.3 通知显示
```
📊 ML环境分析
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ML预测: 看多 (置信度: 0.82)
ML环境: 强趋势上涨
技术环境: 震荡市
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
整合结果: 趋势上涨 (ML覆盖)
建议操作: LONG
仓位倍数: 1.2x
策略: 用Taker确保成交
原因: ML发现趋势启动
```

---

## 6. 集成代码示例

### 6.1 初始化
```python
# 在TradingSystem.__init__中
from ml_regime_detector import MLRegimeDetector

self.ml_regime_detector = MLRegimeDetector(CONFIG)
```

### 6.2 检测调用
```python
# 在generate_signal中
ml_input = MLInput(
    direction=signal.ml_direction,
    confidence=signal.ml_confidence,
    proba_long=signal.ml_proba_long,
    proba_short=signal.ml_proba_short
)

ml_result = self.ml_regime_detector.detect(ml_input)

# 与技术指标整合
final_regime, adjustments = self.ml_regime_detector.get_regime_mapping(
    ml_result.regime,
    technical_regime.value
)

# 应用调整
if adjustments['override_regime']:
    signal.regime = MarketRegime[adjustments['override_regime']]
position_size *= adjustments['position_mult']
```

### 6.3 记录留痕
```python
# 记录到数据库
self.db.log_signal_with_ml(
    signal=signal,
    ml_regime=ml_result.regime.name,
    ml_confidence=ml_result.confidence,
    tech_regime=technical_regime.value,
    final_regime=final_regime,
    override=adjustments['override_regime'] is not None,
    pos_mult=adjustments['position_mult']
)
```

---

## 7. 性能考虑

### 7.1 计算开销
- ML环境检测: **< 0.1ms**（纯规则判断，无复杂计算）
- 历史记录: 内存存储，固定长度（默认10条）
- 对整体性能影响: **可忽略**

### 7.2 内存占用
- 历史缓冲: ~1KB（10条记录）
- 检测器对象: ~10KB
- 总计: **< 20KB**

---

## 8. 测试计划

### 8.1 单元测试
```bash
python ml_regime_detector.py  # 运行模块自带测试
```

### 8.2 集成测试
1. ML强趋势场景 → 验证覆盖技术震荡判断
2. ML震荡场景 → 验证降低仓位
3. ML反转场景 → 验证及时止盈
4. 高频交易场景 → 验证性能无影响

### 8.3 回测验证
- 对比开启/关闭ML环境检测的收益曲线
- 统计ML判断准确率
- 分析假阳性/假阴性比例

---

## 9. 风险控制

### 9.1 失效保护
```python
# ML检测失败时，回退到纯技术指标
try:
    ml_result = detector.detect(ml_input)
except Exception as e:
    logger.error(f"ML环境检测失败: {e}")
    ml_result = None  # 不使用ML判断
    # 继续使用技术指标判断
```

### 9.2 过度交易防护
- ML判断变化时，需要连续2-3次确认才切换策略
- 避免ML信号抖动导致的频繁切换

---

## 10. 后续优化方向

1. **自适应阈值**: 根据市场波动率动态调整置信度阈值
2. **多时间框架**: 结合1min/5min/15min的ML判断
3. **特征工程**: 将ML环境判断作为特征输入到交易模型
4. **A/B测试**: 不同参数配置的并行运行对比

---

## 附录：接口定义

```python
# 主要接口
class MLRegimeDetector:
    def __init__(self, config: Dict)
    def detect(self, ml_input: MLInput) -> MLRegimeResult
    def get_regime_mapping(self, ml_regime, tech_regime) -> Tuple[str, Dict]

# 便捷函数
def detect_ml_regime(direction, confidence, proba_long, proba_short, config) -> MLRegimeResult
```
