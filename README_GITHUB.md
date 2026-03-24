# V12 ETHUSDT Trading Bot

高性能ETHUSDT永续合约量化交易系统

## 系统特性

### 核心功能
- **13种市场环境识别**：趋势、震荡、插针、突破等
- **ML信号融合**：XGBoost实时预测
- **完整止盈体系**：止损、保护、移动、EVT、ATR、ML、资金费率
- **风控系统**：动态仓位、回撤控制、冷却期
- **数据留痕**：所有止盈决策完整记录，支持后期分析

### 新增模块
- `evt_take_profit.py` - EVT极值止盈引擎
- `take_profit_manager.py` - 统一止盈管理器
- `binance_data_feed.py` - 市场辅助数据

## 目录结构

```
├── main_v12_live_optimized.py  # 主程序
├── config.py                   # 配置文件
├── binance_api.py             # 币安API封装
├── strategy*.py               # 策略文件
├── logs/                      # 日志目录（git忽略）
├── *.db                       # 数据库（git忽略）
└── .env                       # API密钥（git忽略）
```

## 安装依赖

```bash
pip install -r requirements.txt
```

## 配置

1. 复制环境变量模板：
```bash
cp .env.example .env
```

2. 编辑 `.env` 填入你的API密钥：
```
BINANCE_API_KEY=your_key
BINANCE_SECRET_KEY=your_secret
```

## 启动

```bash
python main_v12_live_optimized.py
```

## 版本历史

- v12.4.0 - 统一止盈留痕系统
- v12.3.0 - EVT极值止盈
- v12.2.0 - 市场辅助数据
- v12.1.0 - 顺势过滤修复

## 免责声明

⚠️ 实盘交易有风险，本系统仅供学习研究，不构成投资建议。
