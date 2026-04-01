# V12 重构迁移指南

## 当前状态

✅ PositionManager 已集成到 `main_v12_live_optimized.py`
- 开仓时调用 `position_manager.open()`
- 每周期调用 `position_manager.update()`
- 平仓时调用 `position_manager.close()`
- 兼容旧代码访问

⏸️ ExitSignalGenerator 待切换
- 代码已完成并通过测试
- 需要替换 `_check_exit_signal` 调用

---

## 迁移步骤（5分钟完成）

### 第1步：导入新模块

在 `main_v12_live_optimized.py` 顶部添加：

```python
# 重构新增：出场信号系统 (2026-03-24)
from refactor_integration import ExitSignalAdapter, get_exit_adapter
```

### 第2步：初始化适配器

在 `V12OptimizedTrader.__init__` 中添加：

```python
# 重构新增: PositionManager (2026-03-24)
from position_manager import PositionManager
self.position_manager = PositionManager(self.symbol, CONFIG)
# 兼容旧代码访问
self._pm = self.position_manager

# 重构新增: ExitSignalAdapter (2026-03-24)
self.exit_adapter = ExitSignalAdapter(CONFIG)
```

### 第3步：替换出场信号检查

找到 `_check_exit_signal` 调用位置（约在2400行附近），替换为：

```python
# ========== 原代码（注释掉）==========
# exit_signal = self.signal_gen._check_exit_signal(
#     current_price, entry_price, position_side,
#     atr, regime, funding_rate, df
# )

# ========== 新代码 ==========
# 从 PositionManager 获取出场信号
exit_signal = self.exit_adapter.check_exit(
    self.position_manager,
    current_price=current_price,
    atr=atr,
    regime=regime.value,
    funding_rate=funding_rate,
    df=df
)

if exit_signal.should_exit:
    return TradingSignal(
        'CLOSE', 
        1.0, 
        SignalSource.TECHNICAL,
        exit_signal.reason,
        atr,
        regime=regime,
        funding_rate=funding_rate
    )
```

### 第4步：验证

```bash
# 1. 检查语法
python -m py_compile main_v12_live_optimized.py

# 2. 运行单元测试
python position_manager.py
python exit_signals.py
python refactor_integration.py

# 3. 启动交易（观察模式）
python main_v12_live_optimized.py
```

---

## 回滚方案

如遇到问题，立即回滚：

```bash
# 恢复旧代码
git checkout main_v12_live_optimized.py

# 重启交易
python main_v12_live_optimized.py
```

---

## 验证清单

- [ ] 开仓正常，PositionManager 状态正确
- [ ] 每周期 PositionManager.update() 被调用
- [ ] 出场信号触发时机与旧系统一致
- [ ] 数据库记录格式不变
- [ ] 日志输出正常
- [ ] 运行2小时无异常

---

## 故障排查

### 问题1: `ImportError: No module named 'refactor_integration'`

解决：确保 `refactor_integration.py` 在同一目录

### 问题2: 出场信号不触发

排查：
```python
# 添加调试日志
exit_signal = self.exit_adapter.check_exit(...)
logger.debug(f"Exit check: {exit_signal}")
```

### 问题3: PositionManager 状态不同步

检查：
- `position_manager.open()` 在开仓时被调用
- `position_manager.update()` 在每周期被调用

---

**建议**：在周末或非交易时段进行切换。
