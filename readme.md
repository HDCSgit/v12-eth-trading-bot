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
| 1 | Dynamic Stop Loss | ATR×1.5倍止损 |
| 2 | Profit Protection | 回撤50%保护利润 |
| 3 | Trailing Stop | 峰值回撤30%跟踪止盈 |
| 4 | **EVT Extreme** | GPD 95%分位数极端止盈 |
| 5 | ATR Fixed | 盘整4xATR/趋势8xATR |
| 6 | ML Reversal | ML置信度>0.75反转信号 |
| 7 | Funding Extreme | 资金费率>1%极端值 |
| 8 | Time Exit | 超时强制出场 |

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
├── strategy_v12_*.py            # 各版本策略实现
├── *.db                         # SQLite交易数据库
├── logs/                        # 交易日志目录
│
├── requirements.txt             # Python依赖
├── start_v12_optimized.bat      # 启动脚本
└── README.md                    # 本文件
```

---

## ⚙️ 配置参数

### 核心交易参数 (`config.py`)
```python
# 杠杆与资金
LEVERAGE = 5                    # 固定5倍杠杆
MAX_RISK_PCT = 0.03            # 单笔风险3%
MAX_DAILY_TRADES = 20          # 日最大交易次数

# ML阈值
COUNTER_TREND_ML_THRESHOLD = 0.85   # 逆势交易需0.85置信度
SIDEWAYS_MIN_CONFIDENCE = 0.70      # 盘整最低0.70置信度
NIGHT_TRADING_CONFIDENCE = 0.75     # 凌晨时段(02-05)需0.75

# 风控参数
STOP_LOSS_ATR_MULT = 1.5       # 止损1.5倍ATR
MAX_DRAWDOWN_PCT = 0.10        # 最大回撤10%暂停
COOLDOWN_MINUTES = 15          # 连败冷却15分钟

# EVT参数
EVT_LOOKBACK = 300             # 5小时回看窗口
EVT_THRESHOLD_PCT = 80         # POT阈值80%分位
EVT_QUANTILE = 0.95            # 目标95%分位数
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

### 3. 启动交易
```bash
# Windows双击启动
start_v12_optimized.bat

# 或命令行
python main_v12_live_optimized.py
```

---

## 📊 性能表现

### 最新优化（2025-03-24）
| 指标 | 优化前 | 优化后目标 |
|-----|-------|-----------|
| **胜率** | 26.9% | **35-40%** |
| 日均交易 | 26笔/8h | 维持频率 |
| 最大回撤 | <10% | <10% |

### 关键修复（4项紧急修复）
1. **Spike检测收紧**: 1.0% → 1.5%阈值，减少假突破
2. **凌晨时段过滤**: 02:00-05:00需置信度≥0.75
3. **禁用盘整策略**: CONSOLIDATION状态0%胜率，暂时禁用
4. **逆势阈值提升**: 0.82 → 0.85，减少趋势中逆势交易

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
- **多层防护**: 技术信号+ML过滤+风控拦截，三重过滤
- **动态适应**: EVT根据市场波动率自适应调整止盈
- **完整审计**: 每笔交易记录策略归因，便于分析优化

---

**免责声明**: 本软件按"原样"提供，作者不对使用本软件产生的任何损失负责。交易有风险，入市需谨慎。
