# ETH/USDT 量化交易系统

## 🚀 系统概述

这是一个生产级的加密货币量化交易系统，支持币安合约交易，具备以下特点：

- **多因子策略**: 趋势 + RSI + MACD + 布林带 + ATR + 量能
- **智能风控**: 动态仓位管理、最大回撤熔断、每日交易限制
- **完整日志**: SQLite数据库记录所有交易、信号、持仓、余额
- **实时监控**: Prometheus + Telegram通知
- **模式切换**: 支持模拟盘(PAPER)和实盘(LIVE)

## 📁 文件结构

```
binancepro/
├── main.py                 # 主程序入口
├── config.py              # 配置文件
├── binance_api.py         # 币安API封装
├── strategy.py            # 交易策略
├── risk_execution.py      # 风控与执行引擎
├── view_logs.py           # 日志查看工具
├── start.bat              # Windows启动脚本
├── requirements.txt       # 依赖列表
├── elite_trades.db        # SQLite数据库
└── logs/                  # 日志目录
    ├── elite_production_YYYYMMDD.log
    ├── elite_trades_YYYYMMDD.log
    └── elite_errors_YYYYMMDD.log
```

## 🔧 安装配置

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置API密钥

编辑 `config.py`:

```python
API_KEY = "你的币安API Key"
SECRET_KEY = "你的币安Secret Key"
```

### 3. 配置代理(如需要)

```python
PROXY = "http://127.0.0.1:7897"  # 根据你的代理软件修改
```

### 4. 设置交易参数

```python
CONFIG = {
    "SYMBOLS": ["ETHUSDT", "BTCUSDT", "SOLUSDT"],  # 交易对
    "LEVERAGE": 5,                                    # 杠杆倍数
    "MODE": "PAPER",                                  # PAPER(模拟) / LIVE(实盘)
    "MAX_RISK_PCT": 0.012,                           # 单笔最大风险1.2%
    "MAX_DD_LIMIT": 0.15,                            # 最大回撤15%
    "CONFIDENCE_THRESHOLD": 0.72,                    # 信号置信度阈值
    "POLL_INTERVAL": 0.8,                            # 轮询间隔(秒)
}
```

## 🚀 启动系统

### Windows
```bash
start.bat
```

### Linux/Mac
```bash
python main.py
```

## 📊 查看日志

### 实时监控
```bash
python view_logs.py watch
```

### 查看今日汇总
```bash
python view_logs.py today
```

### 查看持仓
```bash
python view_logs.py positions
```

### 查看最近交易
```bash
python view_logs.py trades
```

### 查看总体统计
```bash
python view_logs.py stats
```

### 查看所有信息
```bash
python view_logs.py all
```

## 📝 日志说明

### 数据库表结构

**trades** - 交易记录
- timestamp: 时间戳
- symbol: 交易对
- action: 动作(BUY/SELL/CLOSE)
- qty: 数量
- price: 价格
- pnl: 盈亏
- reason: 交易原因
- confidence: 置信度

**positions** - 持仓记录
- timestamp: 时间戳
- symbol: 交易对
- side: 方向(LONG/SHORT)
- qty: 数量
- entry_price: 开仓价
- current_price: 当前价
- unrealized_pnl: 未实现盈亏

**balance_history** - 余额历史
- timestamp: 时间戳
- total_balance: 总余额
- available_balance: 可用余额
- drawdown_pct: 回撤百分比

**signals** - 信号记录
- timestamp: 时间戳
- symbol: 交易对
- action: 信号动作
- confidence: 置信度
- executed: 是否执行

### 日志文件

- `logs/elite_production_YYYYMMDD.log` - 系统运行日志
- `logs/elite_trades_YYYYMMDD.log` - 交易详细日志
- `logs/elite_errors_YYYYMMDD.log` - 错误日志

## ⚠️ 风险提示

1. **先跑模拟盘**: 建议先用PAPER模式运行至少7天
2. **小资金测试**: 实盘初期使用<500 USDT
3. **控制杠杆**: 建议不超过5倍杠杆
4. **设置止损**: 系统已内置-5%止损，但请确保能承受最大回撤
5. **监控运行**: 定期检查日志和数据库

## 🔍 策略说明

### 入场条件

**做多信号**:
- 趋势向上 (MA55 > MA200)
- RSI < 40 (超卖)
- MACD金叉
- 量能爆发 (>1.6倍均量)
- 布林带挤压 (<2%宽度)

**做空信号**:
- 趋势向下 (MA55 < MA200)
- RSI > 60 (超买)
- MACD死叉
- 量能爆发
- 布林带挤压

### 仓位管理

- 基于ATR动态计算止损距离
- Kelly公式优化仓位
- 单笔不超过25%资金
- 根据置信度调整仓位大小

### 风控机制

1. **止损**: -5%强制止损
2. **止盈**: +10%止盈
3. **回撤熔断**: 最大回撤15%全部平仓
4. **每日限制**: 最多20笔交易
5. **反向信号**: 自动平仓并反向开仓

## 📞 联系方式

如有问题或需要升级功能，请联系开发团队。

---

**免责声明**: 本系统仅供学习研究使用，不构成投资建议。加密货币交易风险极高，请谨慎投资。
