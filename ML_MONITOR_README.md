# V12 ML模型自检与维护系统 - 快速启动指南

> **最后更新**: 2026-03-24  
> **版本**: 1.0  
> **状态**: 生产就绪

---

## 📦 已创建的文件

| 文件 | 大小 | 功能 |
|-----|------|------|
| `ml_self_diagnosis.py` | 21KB | 核心自检与诊断引擎 |
| `ml_monitor_integration.py` | 14KB | 交易系统集成桥接器 |
| `start_ml_monitor.bat` | 1.5KB | 启动脚本 |
| `ML_MONITOR_GUIDE.md` | 12KB | 完整使用文档 |
| `INTEGRATION_EXAMPLE.py` | 8KB | 集成示例代码 |

---

## 🚀 立即使用

### 方式1: 独立诊断工具（推荐先试用）

```bash
# 双击启动
start_ml_monitor.bat

# 然后选择:
# [1] 立即诊断报告 - 查看当前模型状态
# [2] 启动自动监控 - 后台运行监控
# [3] 查看历史警报 - 查看过去的警报
# [4] 手动恢复交易 - 紧急恢复
```

### 方式2: 集成到交易系统（完整功能）

按照 `INTEGRATION_EXAMPLE.py` 中的步骤，修改 `main_v12_live_optimized.py`：

1. 导入模块
2. 初始化监控
3. 添加交易前检查
4. 添加定期检查

---

## 📊 系统能力

### ✅ 自动检测
- [x] 胜率下降趋势
- [x] 回撤过大
- [x] ML信号质量下降
- [x] 特征稳定性变化
- [x] 预测准确度退化

### ✅ 自动维护
- [x] 动态调整ML阈值
- [x] 动态调整止损倍数
- [x] 动态调整仓位大小
- [x] 自动暂停交易
- [x] 自动恢复交易

### ✅ 报告生成
- [x] 实时诊断报告
- [x] 历史趋势分析
- [x] 维护建议
- [x] 警报通知

---

## 🎯 核心特性

### 健康状态分级
```
🟢 健康 (胜率≥40%) → 维持现状
🟡 警告 (胜率30-40%) → 提高阈值，收紧止损
🔴 危险 (胜率<30%) → 暂停交易，紧急维护
```

### 自适应调整示例
```python
# 胜率下降时
胜率 45% → 35%: ML阈值 0.80 → 0.82
胜率 35% → 25%: ML阈值 0.82 → 0.85, 止损 2.0x → 1.8x
胜率 < 20%: 暂停交易

# 恢复时
连续健康3次: 逐步恢复正常参数
```

---

## 📈 预期效果

### 当前问题
- 胜率: 10% ❌
- 频繁亏损 ❌
- 无自动保护 ❌

### 优化后目标
- 胜率: 35-40% ✅
- 自动止损保护 ✅
- 模型退化自动检测 ✅

---

## 🔧 配置调整

### 修改阈值
编辑 `ml_self_diagnosis.py`：
```python
THRESHOLDS = {
    'win_rate_warning': 0.30,    # 警告线
    'win_rate_critical': 0.20,   # 危险线
    'drawdown_warning': 0.10,    # 回撤警告
    'drawdown_critical': 0.20,   # 回撤危险
}
```

### 修改检查频率
```python
# 在 MLAutoMaintenance 中
start_monitoring(interval_minutes=30)  # 30分钟检查一次
```

---

## 🆘 紧急操作

### 立即停止交易
```bash
# 方式1: 在监控菜单中选择停止
start_ml_monitor.bat
# 选择 4 - 手动恢复交易 (先停止)

# 方式2: Python控制台
python -c "from ml_monitor_integration import MLMonitorBridge; m = MLMonitorBridge(None); m.manual_override('trading_enabled', False)"
```

### 查看当前状态
```bash
python -c "from ml_self_diagnosis import MLSelfDiagnosis; d = MLSelfDiagnosis(); print(d.generate_report())"
```

### 恢复交易
```bash
start_ml_monitor.bat
# 选择 4 - 手动恢复交易
```

---

## 📚 详细文档

- **完整指南**: `ML_MONITOR_GUIDE.md`
- **集成示例**: `INTEGRATION_EXAMPLE.py`
- **架构设计**: 见文档第2章

---

## ⚡ 下一步建议

### 立即执行（5分钟）
1. 运行 `start_ml_monitor.bat`
2. 选择 `1` - 生成诊断报告
3. 查看当前模型状态

### 短期（今天）
1. 集成到 `main_v12_live_optimized.py`
2. 测试监控功能
3. 观察参数自动调整

### 中期（本周）
1. 收集监控数据
2. 调整阈值配置
3. 优化维护策略

---

## 🔮 未来升级

- [ ] 微信/钉钉实时通知
- [ ] Web管理界面
- [ ] A/B测试框架
- [ ] 在线学习（增量训练）

---

**现在运行 `start_ml_monitor.bat` 开始使用！**
