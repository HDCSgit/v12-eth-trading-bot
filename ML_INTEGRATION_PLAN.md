# MLRegimeDetector 主程序集成方案

## 1. 主程序流程分析

```
┌─────────────────────────────────────────────────────────────────┐
│                    SignalGenerator.generate_signal()             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. 数据准备                                                     │
│     ├── 加载ML模型                                               │
│     ├── 特征工程 (MLFeatureEngineer)                            │
│     └── 市场环境分析 (MarketAnalyzer.analyze_regime)            │
│                        ↓                                         │
│  2. ML预测 (当前已有)                                            │
│     ├── ml_model.predict() → direction/confidence/proba         │
│     └── 保存到 _last_ml_info                                     │
│                        ↓                                         │
│  ⭐ 3. ML环境检测 (新增集成点1)                                   │
│     └── MLRegimeDetector.detect()                               │
│                        ↓                                         │
│  4. 策略路由 (根据regime选择策略)                                │
│     ├── BREAKDOWN/PUMP → 特殊处理                                │
│     ├── SIDEWAYS → 网格策略                                      │
│     ├── TRENDING → ML顺势策略                                    │
│     └── ...                                                      │
│                        ↓                                         │
│  ⭐ 5. 信号增强 (新增集成点2)                                     │
│     └── 根据ML环境调整信号参数                                   │
│                        ↓                                         │
│  6. 返回 TradingSignal                                           │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 集成点设计（3个核心点）

### 集成点1：ML环境检测（最重要）

**位置**：`generate_signal()` 第712-726行（ML预测后）

**当前代码**：
```python
# ML信号（可能未训练）
ml_pred = self.ml_model.predict(df)
ml_confidence = ml_pred['confidence']
ml_direction = ml_pred['direction']
```

**新增代码**：
```python
# ⭐ 集成点1: ML环境检测
from ml_regime_detector import MLRegimeDetector, MLInput

# 初始化（放在SignalGenerator.__init__）
self.ml_regime_detector = MLRegimeDetector(CONFIG)

# 在generate_signal中使用
ml_input = MLInput(
    direction=ml_direction,
    confidence=ml_confidence,
    proba_long=ml_proba[1],
    proba_short=ml_proba[0]
)

ml_regime_result = self.ml_regime_detector.detect(ml_input)

# 与技术指标环境整合
final_regime, adjustments = self.ml_regime_detector.get_regime_mapping(
    ml_regime_result.regime,
    regime.value  # 当前技术指标判断的环境
)

# 如果ML覆盖，更新regime
if adjustments['override_regime']:
    regime = MarketRegime[adjustments['override_regime']]
    logger.info(f"[ML环境] 技术环境={regime.value} → ML覆盖={final_regime}")
```

---

### 集成点2：信号参数调整

**位置**：`generate_signal()` 返回信号前（约897行）

**新增代码**：
```python
# ⭐ 集成点2: 根据ML环境调整信号参数
if hasattr(self, 'ml_regime_result'):
    ml_result = self.ml_regime_result
    
    # 调整置信度
    signal.confidence = min(1.0, signal.confidence + adjustments['confidence_boost'])
    
    # 记录ML环境信息到信号（用于后续留痕）
    signal.ml_regime = ml_result.regime.name
    signal.ml_regime_conf = ml_result.confidence
    signal.tech_regime = regime.value  # 原始技术环境
    signal.regime_override = adjustments['override_regime'] is not None
    signal.pos_size_mult = adjustments['position_mult']
```

---

### 集成点3：交易执行调整（TradingSystem中）

**位置**：`execute_open()` 第3030-3043行

**当前代码**：
```python
# 根据市场环境选择下单方式
if is_limit_regime and use_limit:
    # 震荡市使用限价单
elif use_limit:
    # 趋势市使用轻量限价
```

**新增代码**：
```python
# ⭐ 集成点3: 根据ML环境调整下单策略
# 检查ML环境是否建议使用Taker（ urgency='HIGH' 时）
if hasattr(signal, 'ml_regime_urgency') and signal.ml_regime_urgency == 'HIGH':
    # ML判断为强趋势或反转，用Taker确保成交
    use_limit = False
    logger.info(f"[ML执行] 紧急信号，使用市价单确保成交")
```

---

## 3. 修改文件清单

### 文件1: main_v12_live_optimized.py

**修改1**：SignalGenerator.__init__ 添加初始化
```python
def __init__(self):
    # ... 现有代码 ...
    
    # ⭐ 新增: ML环境检测器
    from ml_regime_detector import MLRegimeDetector
    self.ml_regime_detector = MLRegimeDetector(CONFIG)
    self.ml_regime_result = None  # 保存最近一次结果
```

**修改2**：generate_signal 添加检测调用
```python
# 在ML预测后（约第726行）
ml_regime_result = self.ml_regime_detector.detect(ml_input)
self.ml_regime_result = ml_regime_result  # 保存供后续使用

# 整合环境判断
final_regime, adjustments = self.ml_regime_detector.get_regime_mapping(
    ml_regime_result.regime,
    regime.value
)

# 应用调整
if adjustments['override_regime']:
    old_regime = regime
    regime = MarketRegime[adjustments['override_regime']]
    logger.info(f"[ML整合] {old_regime.value} → {regime.value} "
                f"(原因: {ml_regime_result.reason})")
```

**修改3**：TradingSignal添加新字段
```python
@dataclass
class TradingSignal:
    # ... 现有字段 ...
    
    # ⭐ 新增: ML环境相关字段（用于留痕）
    ml_regime: str = None           # ML判断的环境
    ml_regime_conf: float = 0.0     # ML环境置信度
    tech_regime: str = None         # 技术指标环境
    regime_override: bool = False   # 是否被ML覆盖
    pos_size_mult: float = 1.0      # 仓位倍数
    ml_urgency: str = 'LOW'         # ML紧急程度
```

### 文件2: TradingSystem.execute_open

**修改**：根据ML紧急程度调整下单方式
```python
# 在下单前检查ML紧急程度
if hasattr(signal, 'ml_urgency') and signal.ml_urgency == 'HIGH':
    # 紧急信号（强趋势/反转），用市价单
    logger.info(f"[ML执行] ML紧急度={signal.ml_urgency}，使用市价单")
    use_limit = False
```

### 文件3: TradeDatabase.log_signal

**修改**：记录ML环境信息
```python
def log_signal(self, symbol, signal, price, executed=True):
    # 记录ML环境信息
    ml_regime = getattr(signal, 'ml_regime', None)
    tech_regime = getattr(signal, 'tech_regime', None)
    regime_override = getattr(signal, 'regime_override', False)
    
    # 插入数据库（新增字段）
    conn.execute('''
        INSERT INTO signals (..., ml_regime, tech_regime, regime_override)
        VALUES (..., ?, ?, ?)
    ''', (..., ml_regime, tech_regime, regime_override))
```

---

## 4. 数据库表结构更新

```sql
-- signals表新增字段
ALTER TABLE signals ADD COLUMN ml_regime TEXT;        -- ML判断的环境
ALTER TABLE signals ADD COLUMN ml_regime_conf REAL;   -- ML环境置信度
ALTER TABLE signals ADD COLUMN tech_regime TEXT;      -- 技术判断的环境
ALTER TABLE signals ADD COLUMN final_regime TEXT;     -- 最终环境
ALTER TABLE signals ADD COLUMN regime_override INTEGER; -- 是否覆盖(0/1)
ALTER TABLE signals ADD COLUMN pos_size_mult REAL;    -- 仓位倍数
ALTER TABLE signals ADD COLUMN ml_urgency TEXT;       -- ML紧急程度
```

---

## 5. 日志输出设计

### 正常情况（ML确认技术判断）
```
[ML环境] 输入: 方向=1, 置信度=0.82, 多=0.85, 空=0.15
[ML环境] 检测: 强趋势上涨 (置信度=0.82)
[ML整合] 技术环境=趋势上涨 → ML确认 ✓ (一致)
[ML执行] 使用限价单策略 (非紧急)
```

### 覆盖情况（ML发现趋势启动）
```
[ML环境] 输入: 方向=1, 置信度=0.81, 多=0.84, 空=0.16
[ML环境] 检测: 强趋势上涨 (置信度=0.81)
[ML整合] 技术环境=震荡上行 → ML覆盖=趋势上涨 (原因: ML发现趋势启动，加大仓位)
[ML执行] 紧急信号，使用市价单确保成交
```

---

## 6. 风险控制

### 失效保护
```python
try:
    ml_regime_result = self.ml_regime_detector.detect(ml_input)
except Exception as e:
    logger.error(f"[ML环境] 检测失败: {e}，回退到纯技术判断")
    ml_regime_result = None
    # 继续使用技术指标判断，不受影响
```

### 参数边界
```python
# 确保仓位倍数在安全范围
adjustments['position_mult'] = max(0.5, min(1.5, adjustments['position_mult']))
```

---

## 7. 测试验证点

1. **ML强趋势 + 技术震荡** → 环境被覆盖为趋势
2. **ML震荡 + 技术趋势** → 降低仓位
3. **ML反转预警** → 立即止盈
4. **检测失败** → 回退到技术判断
5. **日志留痕** → 数据库有ml_regime字段

---

要我按这个方案开始集成吗？
