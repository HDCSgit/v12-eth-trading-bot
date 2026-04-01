# V12 ETHUSDT 高频量化交易系统

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Private-red)]()
[![Status](https://img.shields.io/badge/Status-Live%20Trading-green)]()

> **专业级ETHUSDT永续合约高频交易策略系统**  
> 基于多市场状态识别 + ML信号融合 + EVT极端值动态止盈

---

## 🚀 核心特性

### 1. 七维市场状态识别
| 市场状态 | 识别条件 | 适配策略 |
|---------|---------|---------|
| **TRENDING_UP** | ADX>25, 价格>MA20>MA50 | 趋势跟踪做多 |
| **TRENDING_DOWN** | ADX>25, 价格<MA20<MA50 | 趋势跟踪做空 |
| **SIDEWAYS_UP** | ADX<20, 价格接近BB中轨 | 区间做多 |
| **SIDEWAYS_DOWN** | ADX<20, 价格在区间下沿 | 区间做空 |
| **BREAKOUT** | 价格突破BB上轨+放量 | 突破追涨 |
| **BREAKDOWN** | 价格跌破BB下轨+放量 | 破位追空 |
| **HIGH_VOL** | ATR>阈值+波动率扩张 | 波动率策略 |

### 1.5 🆕 ML市场环境检测 V2 (XGBoost)
**基于XGBoost的数据驱动市场环境识别系统**

```
V2 vs V1 对比:
┌──────────────┬──────────────────┬──────────────────┐
│     特性      │   V1 (规则版)     │   V2 (XGBoost)   │
├──────────────┼──────────────────┼──────────────────┤
│ 判断依据      │ 固定阈值          │ 数据驱动学习      │
│ 输出类型      │ 硬分类            │ 概率分布          │
│ 不确定性      │ 无               │ 熵度量+置信度     │
│ 类别数量      │ 7类              │ 5类（优化合并）   │
│ 准确率        │ ~60% (规则)      │ 数据依赖          │
│ 特征维度      │ 手工规则          │ 39维自动特征      │
└──────────────┴──────────────────┴──────────────────┘
```

**V2 五类市场环境**:
| 类别 | 占比 | 适配策略 |
|------|------|---------|
| **SIDEWAYS** | ~36% | 均值回归，限价单 |
| **TREND_UP** | ~30% | 趋势跟踪做多，市价单 |
| **TREND_DOWN** | ~29% | 趋势跟踪做空，市价单 |
| **BREAKOUT** | ~3% | 动量突破，追势 |
| **EXTREME** | ~4% | 极端行情，减仓观望 |

**核心优势**:
- ✅ **不确定性量化**: 知道"不知道"，高熵时建议观望
- ✅ **概率输出**: 不是单一判断，而是概率分布
- ✅ **自动适应**: 无需人工调整阈值
- ✅ **可解释性**: SHAP特征重要性分析

**配置切换** (`config.py`):
```python
"ML_REGIME_VERSION": "v2",  # "v1"=规则, "v2"=XGBoost
"ML_REGIME_V2_MODEL_PATH": "models/regime_xgb_v1.pkl",
"ML_REGIME_V2_CONFIDENCE_THRESHOLD": 0.65,
```

### 2. ML信号融合系统
- **模型**: XGBoost分类器
- **特征**: 15+技术指标（RSI, MACD, 布林带, ATR等）
- **输出**: 0-1置信度分数
- **融合**: ML信号与技术分析信号加权融合

### 3. EVT极端值动态止盈
```python
# Generalized Pareto Distribution (GPD)
ξ (shape) ≈ 0.31  # 厚尾特征
β (scale) 动态估计
u (threshold) 80%分位数

# 动态止盈计算
TP% = max(GPD_95%_quantile × 0.8, ATR × 4)
TP% = clamp(TP%, 0.3%, 3%)  # 硬限制
```

### 4. 统一出场管理器 (8种策略)
| 优先级 | 出场策略 | 触发条件 |
|-------|---------|---------|
| 1 | Fixed Stop Loss | 固定0.8%止损 (v12.7) |
| 2 | Fixed Take Profit | 固定1.6%止盈 (v12.7) |
| 3 | Profit Protection | 回撤50%保护利润 |
| 4 | Trailing Stop | 峰值回撤30%跟踪止盈 |
| 5 | **EVT Extreme** | GPD 95%分位数极端止盈 |
| 6 | ML Reversal | ML置信度>0.75反转信号 |
| 7 | Funding Extreme | 资金费率>1%极端值 |
| 8 | Time Exit | 超时强制出场 |

### 5. 多空平衡检查 (v12.7)
防止系统过度偏向单一方向（如连续做空）：
- 跟踪最近5笔交易记录
- 同方向连续亏损2笔后，暂停该方向开仓
- 强制切换方向或观望，直到平衡恢复

```python
# 配置参数
"consecutive_loss_limit": 2  # 连续亏损次数限制
"max_recent_trades": 10      # 跟踪交易数
```

---

## 📁 项目结构

```
binancepro/
├── main_v12_live_optimized.py    # 核心交易引擎（主程序）
├── take_profit_manager.py        # 统一出场管理器
├── evt_take_profit.py           # EVT极端值止盈引擎
├── binance_data_feed.py         # 市场数据模块（多空比/爆仓）
├── binance_api.py               # Binance API封装
├── config.py                    # 全局配置参数
├── risk_execution_v2_5.py       # 风控执行模块
│
├── market_regime_v2/            # ML市场环境检测V2模块
│   ├── detector.py              # XGBoost检测器主类
│   ├── trainer.py               # 模型训练器
│   ├── features.py              # 39维特征工程
│   ├── visualizer.py            # 可视化工具
│   └── integration.py           # 主程序集成接口
│
├── auto_ml_trainer.py           # 自动ML训练器
├── quick_train.py               # 快速训练启动器(v12.7)
├── offline_training.py          # 离线训练工具
├── train_regime_v2.py           # V2模型训练脚本
├── test_regime_v2.py            # V2模型测试脚本
├── check_freshness.py           # 数据新鲜度检查
├── sync_data.py                 # CSV与SQLite同步
│
├── models/                      # 模型文件目录
│   └── regime_xgb_v1.pkl        # V2训练好的模型
│
├── strategy_v12_*.py            # 各版本策略实现
├── *.db                         # SQLite交易数据库
├── logs/                        # 交易日志目录
│
├── requirements.txt             # Python依赖
├── start_v12_optimized.bat      # 启动脚本
├── start_auto_training.bat      # 自动训练服务（中英双语）
└── README.md                    # 本文件
```

---

## ⚙️ 配置参数

### 核心交易参数 (`config.py`)
```python
# 杠杆与资金
LEVERAGE = 5                    # 固定5倍杠杆
MAX_RISK_PCT = 0.025           # 单笔风险2.5%
MAX_DAILY_TRADES = 500         # 日最大交易次数

# ML阈值
COUNTER_TREND_ML_THRESHOLD = 0.85   # 逆势交易需0.85置信度
SIDEWAYS_MIN_CONFIDENCE = 0.80      # 盘整最低0.80置信度
ML_CONFIDENCE_THRESHOLD = 0.55      # ML顺势信号门槛

# 训练数据模式 (v12.7新增)
TRAINING_DATA_MODE = "sliding_window"     # "sliding_window"=滑动窗口 | "fixed_start"=固定起点
TRAINING_FIXED_START_DATE = "2025-07-05"  # 固定起点模式的起始日期
TRAINING_SLIDING_MONTHS = 9               # 滑动窗口月数

# ML市场环境检测V2配置 (当前禁用)
ML_REGIME_ENABLED = False               # 总开关 (当前使用V1规则)
ML_REGIME_VERSION = "v1"                # "v1"=规则, "v2"=XGBoost

# 风控参数
USE_FIXED_RR_WITH_EVT = True   # 启用固定盈亏比
FIXED_STOP_PCT = 0.008         # 固定止损0.8%
FIXED_TP_PCT = 0.016           # 固定止盈1.6%
PURE_FIXED_TP = True           # 纯固定止盈，不追踪
MAX_DRAWDOWN_PCT = 0.15        # 最大回撤15%暂停

# 多空平衡参数
consecutive_loss_limit = 2     # 连续亏损次数限制
max_recent_trades = 10         # 跟踪交易数
```

### API配置 (`.env`)
```bash
BINANCE_API_KEY=your_api_key
BINANCE_SECRET_KEY=your_secret
ENABLE_LIVE_TRADING=false      # 实盘开关
TELEGRAM_BOT_TOKEN=xxx         # 可选：电报通知
TELEGRAM_CHAT_ID=xxx
```

---

## 🚀 快速启动

### 1. 环境安装
```bash
# 创建虚拟环境
python -m venv venv
venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置API密钥
```bash
# 复制模板并编辑
copy .env.example .env
# 编辑 .env 填入你的Binance API密钥
```

### 3. 训练模型（双模型系统）

系统包含两个独立的ML模型：
1. **交易信号模型** (V1) - 预测涨跌方向
2. **市场环境模型** (V2) - 识别市场环境类型

#### 训练数据模式（v12.7新增）

| 模式 | 说明 | 配置项 |
|------|------|--------|
| **滑动窗口** (默认) | 最近9个月数据，随时间滑动 | `TRAINING_DATA_MODE: "sliding_window"` |
| **固定起点** | 2025-07-05后所有数据，累积增长 | `TRAINING_DATA_MODE: "fixed_start"` |

```bash
# 方式1: 使用自动训练服务（推荐）
start_auto_training.bat
# 菜单选项:
#   [3] Quick Train - Sliding Window (滑动窗口)
#   [4] Quick Train - Fixed Start (固定起点)
#   [5] Full Train - Sliding Window (完整重训练)
#   [6] Full Train - Fixed Start (完整重训练)

# 方式2: 使用快速训练脚本
python quick_train.py                    # 默认滑动窗口
python quick_train.py --fixed            # 固定起点模式
python quick_train.py --full             # 完整训练(非增量)
python quick_train.py --fixed --full     # 固定起点+完整训练
python quick_train.py --months 6         # 自定义滑动月数

# 方式3: 单独训练V2市场环境模型
python train_regime_v2.py \
    --data eth_usdt_15m_binance.csv \
    --output models/regime_xgb_v1.pkl \
    --lookforward 48

# 方式4: 测试V2模型
python test_regime_v2.py \
    --model models/regime_xgb_v1.pkl \
    --data eth_usdt_15m_binance.csv
```

**V2模型训练参数说明**:
| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--lookforward` | 48 | 预测未来48个15分钟周期（12小时） |
| `--test-size` | 0.15 | 验证集比例 |
| `--cv` | 0 | 交叉验证折数（可选） |

**训练输出示例**:
```
Dataset prepared: 78268 samples
Label distribution:
SIDEWAYS           28051 (36%)
TREND_UP           23576 (30%)
TREND_DOWN         22686 (29%)
BREAKOUT            1346 (2%)
EXTREME             2609 (3%)

Training accuracy: 0.4903
Validation accuracy: 0.2667
```

### 3. 启动交易
```bash
# Windows双击启动
start_v12_optimized.bat

# 或命令行
python main_v12_live_optimized.py
```

---

## 📊 性能表现

### 最新优化（2026-04-01）
| 指标 | 优化前 | 优化后目标 |
|-----|-------|-----------|
| **胜率** | 41% | **45-50%** |
| 日均交易 | 18笔/8h | 10-15笔（提高质量） |
| 最大回撤 | <15% | <10% |
| 止损控制 | -5.88% | -0.8%（固定） |

### 关键修复（v12.7核心修复）
1. **固定止损止盈**: 放弃ATR动态，使用固定0.8%止损/1.6%止盈
2. **多空平衡检查**: 防止连续同方向亏损，强制方向切换
3. **训练数据模式**: 支持滑动窗口(最新鲜)和固定起点(样本多)两种模式
4. **ML Regime禁用**: V2准确率41%低于阈值，回退到V1规则
5. **数据同步工具**: CSV与SQLite自动同步，确保数据一致性

---

## 🛡️ 风控体系

### 事前风控
- ✅ 杠杆固定5x，不追加
- ✅ 单笔最大3%风险敞口
- ✅ ML置信度过滤低质量信号
- ✅ 市场状态适配策略

### 事中风控
- ✅ ATR动态止损（1.5x ATR）
- ✅ 利润保护机制（回撤50%止盈）
- ✅ 跟踪止盈（回撤30%）
- ✅ EVT极端值止盈

### 事后风控
- ✅ 日最大交易次数限制（20次）
- ✅ 连败冷却机制（15分钟）
- ✅ 日最大回撤10%暂停交易
- ✅ 完整交易日志审计

---

## 📝 交易日志

所有交易记录存储在SQLite数据库中：
- `v12_optimized.db` - 主交易记录
- `elite_trades_v2_5.db` - 精选交易

记录字段：
```sql
- timestamp: 交易时间
- side: 方向 (LONG/SHORT)
- entry_price: 入场价格
- exit_price: 出场价格
- pnl: 盈亏金额
- pnl_pct: 盈亏百分比
- exit_strategy: 出场策略名称
- regime: 市场状态
- ml_confidence: ML置信度
```

---

## ⚠️ 风险提示

1. **市场风险**: 加密货币市场波动剧烈，策略可能在极端行情失效
2. **技术风险**: API延迟、网络中断可能导致订单异常
3. **模型风险**: ML模型基于历史数据训练，未来表现可能偏差
4. **杠杆风险**: 5倍杠杆放大盈亏，请确保理解杠杆交易风险
5. **回测≠实盘**: 历史表现不代表未来收益

**重要**: 本系统仅供学习研究使用，不构成投资建议。请根据自身风险承受能力谨慎使用。

---

## 🔄 更新日志

### v12.7 (2026-04-01) 🔄 训练数据模式优化
- [x] **双模式训练数据**: 滑动窗口(最近9个月) vs 固定起点(2025-07-05后所有)
- [x] **配置化切换**: `TRAINING_DATA_MODE` 配置项控制
- [x] **快速训练脚本**: `quick_train.py` 支持命令行参数切换
- [x] **多空平衡检查**: 防止连续同方向亏损，强制方向切换
- [x] **修复position_pct未定义错误**

### v12.6.6 (2026-03-27) ✅ 纯固定止盈1.6%
- [x] **最简策略**: 放弃所有复杂止盈逻辑，纯固定1.6%
- [x] **超过即平**: 盈利≥1.6%立即触发止盈，不追踪不贪
- [x] **日志简化**: 接近目标(80%)时提示，超过时立即执行
- [x] 保留后备ATR止盈作为兜底

### v12.6.4 (2026-03-27) 🐛 修复止盈触发逻辑
- [x] **修复EVT追踪止盈不触发Bug**: 原逻辑`if >=1.6% and <=1.6%`永远为假

### v12.6.3 (2026-03-27) ⚡ 全部Taker+简化开仓
- [x] **全部订单改为Taker**: `USE_LIMIT_ORDER: False`，禁用所有限价单
- [x] **移除开仓重复检查**: 删除execute_open中的ML环境禁止开仓检查，信号已通过即执行

### v12.6.2 (2026-03-27) 🎯 修复止盈策略执行顺序
- [x] **修复固定止盈+EVT追踪策略**: 纯EVT止盈目标强制≥1.76%，确保先触发固定止盈+追踪
- [x] **回撤触发逻辑修正**: 从"回撤1.6%幅度"改为"回撤到1.6%固定止盈点"

### v12.6.1 (2026-03-27) 🐛 修复开仓日志Bug
- [x] **修复tech_signal未定义错误**: 在execute_open中初始化tech_signal=None，避免日志打印时访问未定义变量

### v12.6 (2026-03-24) 🛡️ 退出确认与日志优化
- [x] **Ctrl+C退出确认**: 程序退出时显示持仓盈亏，询问是否平仓后退出
  - 输入Y/回车: 平仓后退出
  - 输入n: 保留持仓直接退出
  - 非交互式环境: 自动平仓
- [x] **ML过滤日志冷却**: 5分钟内相同原因只输出一次info日志，避免刷屏

### v12.5 (2025-03-27) 🆕 ML市场环境检测V2
- [x] **XGBoost市场环境检测V2上线**
- [x] 5分类优化模型（SIDEWAYS/TREND_UP/TREND_DOWN/BREAKOUT/EXTREME）
- [x] 39维特征工程（价格/趋势/动量/波动率/成交量/统计特征）
- [x] 不确定性量化（熵度量，高不确定时自动建议观望）
- [x] 概率分布输出（不再是单一判断）
- [x] 配套可视化工具（时间线/热力图/特征重要性）
- [x] 低耦合集成（config一键切换V1/V2）
- [x] 自动训练服务支持V2模型训练

### v12.4 (2025-03-24)
- [x] 4项紧急Bug修复（胜率26.9%→35-40%目标）
- [x] Spike检测阈值收紧至1.5%
- [x] 凌晨时段(02-05)提高置信度门槛至0.75
- [x] 禁用CONSOLIDATION策略（0%胜率）
- [x] 逆势交易阈值提升至0.85

### v12.3 (2025-03-23)
- [x] EVT极端值止盈系统上线
- [x] GPD分布拟合与95%分位数计算
- [x] 统一出场管理器重构

### v12.2 (2025-03-22)
- [x] 市场数据模块集成（多空比/爆仓数据）
- [x] 7维市场状态识别系统
- [x] ML信号融合框架

### v12.1 (2025-03-20)
- [x] 风控执行模块V2.5
- [x] 数据库交易记录系统

### v12.0 (2025-03-19)
- [x] V12系统正式发布
- [x] 高频1分钟K线交易框架

---

## 📧 联系方式

- **GitHub**: [HDCSgit/v12-eth-trading-bot](https://github.com/HDCSgit/v12-eth-trading-bot)
- **备用路径**: `D:\openclaw\V124\` (本地完整备份)

---

## 🏆 设计哲学

> **"简单胜于复杂，清晰胜于聪明"**

- **状态机驱动**: 7种明确的市场状态，避免模糊判断
- **数据驱动**: ML V2基于XGBoost自动学习市场模式，减少人工规则
- **多层防护**: 技术信号+ML过滤+风控拦截，三重过滤
- **不确定性量化**: V2知道"不知道"，高熵时自动观望
- **动态适应**: EVT根据市场波动率自适应调整止盈
- **完整审计**: 每笔交易记录策略归因，便于分析优化

---

## 📚 相关文档

- [V2深度设计文档](docs/V2_DESIGN_DEEP_DIVE.md) - V2架构与技术细节
- [V2使用指南](docs/V2_README.md) - V2快速上手指南
- [V2开发总结](docs/V2_SUMMARY.md) - V2开发过程与成果

---

**免责声明**: 本软件按"原样"提供，作者不对使用本软件产生的任何损失负责。交易有风险，入市需谨慎。
