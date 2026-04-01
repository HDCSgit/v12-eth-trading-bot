# ML环境检测模块 - 一键关停设计

## 1. 设计目标

**一键关停**：通过一个配置开关，完全关闭ML环境检测模块，回退到纯技术指标判断。

**使用场景**：
- ML模块出现故障时紧急关闭
- 对比测试（开/关ML的效果对比）
- 策略回滚（发现ML判断不准确时）

---

## 2. 开关配置

### config.py 新增配置

```python
# ==========================================
# ML环境检测模块开关 (新增 2026-03-27)
# ==========================================
"ML_REGIME_ENABLED": True,  # ⭐ 总开关：True=启用, False=停用

# 子功能开关（仅在总开关为True时生效）
"ML_REGIME_OVERRIDE_ENABLED": True,   # 允许ML覆盖技术环境
"ML_REGIME_ADJUST_POSITION": True,    # 允许ML调整仓位
"ML_REGIME_ADJUST_EXECUTION": True,   # 允许ML影响下单方式
```

### 开关层级

```
ML_REGIME_ENABLED (总开关)
    ├── True: 启用ML环境检测
    │       ├── ML_REGIME_OVERRIDE_ENABLED
    │       ├── ML_REGIME_ADJUST_POSITION
    │       └── ML_REGIME_ADJUST_EXECUTION
    │
    └── False: 完全停用ML环境检测
            └── 所有子功能无效，回退到纯技术指标
```

---

## 3. 代码集成（带开关判断）

### 集成点1：初始化（带开关）

```python
# SignalGenerator.__init__
self.ml_regime_enabled = CONFIG.get("ML_REGIME_ENABLED", True)

if self.ml_regime_enabled:
    from ml_regime_detector import MLRegimeDetector
    self.ml_regime_detector = MLRegimeDetector(CONFIG)
    logger.info("✅ ML环境检测模块已启用")
else:
    self.ml_regime_detector = None
    logger.info("⚠️ ML环境检测模块已停用（使用纯技术指标）")
```

### 集成点2：检测调用（带开关）

```python
# generate_signal() 中

# ML预测（已有代码，不受影响）
ml_pred = self.ml_model.predict(df)
ml_confidence = ml_pred['confidence']
ml_direction = ml_pred['direction']

# ⭐ 开关判断：是否启用ML环境检测
if self.ml_regime_enabled and self.ml_regime_detector:
    # 启用ML环境检测
    ml_input = MLInput(direction=ml_direction, ...)
    ml_regime_result = self.ml_regime_detector.detect(ml_input)
    
    # 子开关：是否允许覆盖
    if CONFIG.get("ML_REGIME_OVERRIDE_ENABLED", True):
        final_regime, adjustments = self.ml_regime_detector.get_regime_mapping(...)
        if adjustments['override_regime']:
            regime = MarketRegime[adjustments['override_regime']]
    else:
        adjustments = {'position_mult': 1.0, 'use_limit_order': True}
else:
    # 停用ML环境检测
    ml_regime_result = None
    adjustments = {'position_mult': 1.0, 'use_limit_order': True}
    logger.debug("[ML环境] 模块已停用，使用纯技术指标判断")
```

### 集成点3：执行调整（带开关）

```python
# execute_open() 中

# ⭐ 开关判断：是否允许ML影响执行
if CONFIG.get("ML_REGIME_ENABLED", True) and \
   CONFIG.get("ML_REGIME_ADJUST_EXECUTION", True):
    # 检查ML紧急程度
    if hasattr(signal, 'ml_urgency') and signal.ml_urgency == 'HIGH':
        use_limit = False
else:
    # 使用默认配置（config中的限价单设置）
    pass  # 不应用ML调整
```

---

## 4. 关停操作指南

### 方法一：修改配置文件（推荐）

```python
# config.py
"ML_REGIME_ENABLED": False  # 改为False即可关停
```

重启系统后生效。

### 方法二：运行时热切换（可选）

```python
# 创建一个热切换脚本 toggle_ml_regime.py
import sqlite3
import json

def toggle_ml_regime(enable: bool):
    '''运行时切换ML模块开关（通过数据库）'''
    conn = sqlite3.connect('v12_optimized.db')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS runtime_config (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.execute('''
        INSERT OR REPLACE INTO runtime_config (key, value)
        VALUES (?, ?)
    ''', ('ML_REGIME_ENABLED', json.dumps(enable)))
    conn.commit()
    conn.close()
    print(f"ML环境检测模块: {'启用' if enable else '停用'}")
    print("下次信号生成时生效")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "off":
        toggle_ml_regime(False)
    else:
        toggle_ml_regime(True)
```

使用方法：
```bash
python toggle_ml_regime.py off  # 关停
python toggle_ml_regime.py on   # 启用
```

---

## 5. 日志标识

### 启用状态日志

```
✅ ML环境检测模块已启用
   ├─ 环境覆盖: 启用
   ├─ 仓位调整: 启用
   └─ 执行影响: 启用
```

### 关停状态日志

```
⚠️ ML环境检测模块已停用（一键关停）
   └─ 回退到：纯技术指标判断
```

### 每次信号生成日志

```
# 启用时
[ML环境] 输入: 方向=1, 置信度=0.82
[ML环境] 检测: 强趋势上涨
[ML整合] 技术环境=震荡 → ML覆盖=趋势上涨

# 关停时
[ML环境] 模块已停用（配置开关），跳过ML环境检测
[信号生成] 使用纯技术指标环境: 震荡市
```

---

## 6. 关停后的影响对比

| 功能 | 启用ML | 关停ML |
|------|--------|--------|
| **环境判断** | ML+技术指标整合 | 纯技术指标 |
| **趋势发现** | ML提前1-3分钟发现 | 技术指标滞后 |
| **反转预警** | ML预警及时止盈 | 依赖技术指标止损 |
| **仓位调整** | 根据ML强度调整 | 固定1.0倍 |
| **下单方式** | ML紧急时用Taker | 完全按配置 |
| **手续费** | 可能更优 | 按原策略 |

---

## 7. 紧急关停场景

### 场景1：ML模块故障

```python
# 检测到ML检测异常
try:
    ml_result = detector.detect(ml_input)
except Exception as e:
    logger.error(f"[ML环境] 检测异常: {e}")
    
    # 自动关停保护
    if CONFIG.get("ML_REGIME_AUTO_DISABLE_ON_ERROR", True):
        CONFIG["ML_REGIME_ENABLED"] = False
        logger.warning("⚠️ ML环境检测模块已自动关停（故障保护）")
```

### 场景2：策略效果不佳

```
用户观察发现：
- 开启ML后胜率下降
- 或手续费增加
- 或回撤变大

操作：
1. 修改 config.py: "ML_REGIME_ENABLED": False
2. 重启系统
3. 对比观察效果
```

---

## 8. 完整配置示例

```python
# config.py - ML环境检测完整配置

# ==========================================
# ML环境检测模块 (新增 2026-03-27)
# ==========================================

# 总开关：一键关停所有ML环境相关功能
"ML_REGIME_ENABLED": True,  # False = 完全停用，回退到纯技术指标

# 子功能开关（仅在总开关为True时生效）
"ML_REGIME_OVERRIDE_ENABLED": True,   # 允许ML覆盖技术环境判断
"ML_REGIME_ADJUST_POSITION": True,    # 允许ML调整仓位倍数
"ML_REGIME_ADJUST_EXECUTION": True,   # 允许ML影响下单方式（紧急时用Taker）

# 故障自动保护
"ML_REGIME_AUTO_DISABLE_ON_ERROR": True,  # 出故障时自动关停

# 检测参数（与之前相同）
"ML_REGIME_HISTORY_SIZE": 10,
"ML_STRONG_TREND_CONFIDENCE": 0.75,
"ML_STRONG_TREND_PROBA": 0.70,
"ML_SIDEWAYS_MAX_CONFIDENCE": 0.60,
"ML_SIDEWAYS_PROBA_DIFF": 0.20,
```

---

## 9. 一键关停检查清单

关停前检查：
- [ ] 是否有持仓？（建议平仓后再关停，避免逻辑混乱）
- [ ] 是否记录了ML效果数据？（用于对比）
- [ ] 是否通知了相关人员？

关停操作：
- [ ] 修改 config.py: `"ML_REGIME_ENABLED": False`
- [ ] 重启系统
- [ ] 确认日志显示"ML环境检测模块已停用"

关停后观察：
- [ ] 交易频率是否正常？
- [ ] 胜率是否有变化？
- [ ] 手续费是否有变化？

---

**总结：通过 `ML_REGIME_ENABLED` 一个开关，可以完全控制ML环境检测模块的启停，实现真正的一键关停！**
