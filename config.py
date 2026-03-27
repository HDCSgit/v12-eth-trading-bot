#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V12优化版量化交易系统 - 全局配置文件
所有可调参数集中管理，方便策略调整和风险控制

作者: AI Assistant
版本: 12.2.0
"""

import os
from dotenv import load_dotenv
load_dotenv()

# ==========================================
# 1. API 配置（从环境变量读取，安全）
# ==========================================
API_KEY = os.getenv("BINANCE_API_KEY", "")
SECRET_KEY = os.getenv("BINANCE_SECRET_KEY", "")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
PROXY = os.getenv("PROXY", None)  # 例如: http://127.0.0.1:7897

# ==========================================
# 2. 交易基础配置
# ==========================================
CONFIG = {
    # ---------- 交易对和时间 ----------
    "SYMBOLS": ["ETHUSDT"],           # 交易对列表，可添加 BTCUSDT/SOLUSDT
    "INTERVAL": "15m",                 # K线周期: 已从1m迁移到15m (2026-03-24)
    
    # ---------- 杠杆和模式 ----------
    "LEVERAGE": 5,                     # 杠杆倍数(1-125)，建议5-10倍
    "MODE": os.getenv("MODE", "PAPER"), # LIVE(实盘) / PAPER(模拟)
    "USE_TESTNET": False,              # True=使用币安测试网
    
    # ---------- 系统参数 ----------
    "POLL_INTERVAL": 0.8,              # 轮询间隔(秒)，建议0.5-2秒
    "WS_RECONNECT_DELAY": 5,           # WebSocket重连延迟(秒)
    
    # ==========================================
    # 3. 风控参数 - 严格设置防止爆仓
    # ==========================================
    
    # 日风控
    "MAX_DAILY_LOSS_PCT": 0.05,        # 日最大亏损5%，超过停止交易
    "MAX_DAILY_TRADES": 500,            # 日最大交易次数，防止过度交易
    "MAX_DD_LIMIT": 0.15,              # 最大回撤15%，触发熔断
    
    # 单笔风控
    "MAX_RISK_PCT": 0.025,             # 单笔基础风险2.5%（从3%降低，更稳健）
                                       # 作用：控制每笔交易的最大亏损
                                       # 边界：建议1%-5%，太小难以开仓，太大风险高
    
    # 仓位大小控制（名义价值，不考虑杠杆）
    "POSITION_SIZE_PCT_MIN": 0.30,     # 最小仓位20%（$100余额最少开$20）
    "POSITION_SIZE_PCT_MAX": 0.8,     # 最大仓位60%（$100余额最多开$60）
                                       # 说明：防止过度集中，同时保证有意义的开仓 在后续调试中发现最大仓位60%限制保证金才6usdt，
    #  当"POSITION_SIZE_PCT_MAX": 2.0时 ，报文：2026-03-23 08:36:33,314 | INFO | 仓位计算 | 基础风险:3.0%×$51=$1.53 | 置信度:0.97(极高)×3.90 | 止损:0.80% | 理论:1462.5%→限制:200.0% | 仓位:0.0501ETH($102)
    # ==========================================
    # 4. 信号生成参数
    # ==========================================
    
    # ML模型参数
    "ML_CONFIDENCE_THRESHOLD": 0.55,   # ML顺势信号门槛(提高到0.55，过滤低质量信号)
                                       # 更新日期：2026-03-24，原因：胜率过低10%
                                       # 旧值：0.65，新值：0.80
                                       # 作用：过滤低质量信号
                                       # 边界：0.5=所有信号，0.8=仅高确信
    "ML_MIN_TRAINING_SAMPLES": 200,    # 15分钟框架: 增加样本要求
                                       # 更新日期：2026-03-24
                                       # 旧值：30，新值：100
    "ML_TRAINING_INTERVAL_HOURS": 6,   # 15分钟框架: 6小时重新训练
    "ML_LABEL_THRESHOLD": 0.0015,      # ML标签阈值(0.15%收益)
    
    # 技术指标参数
    "TECH_RSI_OVERSOLD": 30,           # RSI超卖阈值
    "TECH_RSI_OVERBOUGHT": 70,         # RSI超买阈值
    "TECH_BB_WIDTH_THRESHOLD": 0.05,   # 布林带宽度阈值(判断震荡)
    "TECH_ADX_TREND_THRESHOLD": 23,    # ADX趋势强度阈值(23，平衡敏感度和准确度)
    
    # 网格策略参数
    "GRID_BB_LOWER_MULT": 1.01,        # 布林带下轨倍数
    "GRID_BB_UPPER_MULT": 0.99,        # 布林带上轨倍数
    "GRID_RSI_LONG_MAX": 40,           # 做多RSI上限（收紧，原为45）
    "GRID_RSI_SHORT_MIN": 60,          # 做空RSI下限（收紧，原为55）
    
    # 震荡市专用参数（新增）
    "SIDEWAYS_MIN_BB_WIDTH": 0.03,     # 最小布林带宽度（过滤假震荡）
    "SIDEWAYS_MIN_CONFIDENCE": 0.80,   # 震荡市最低置信度（进一步提高门槛）
                                       # 更新日期：2026-03-24，原因：胜率过低10%
                                       # 旧值：0.70，新值：0.80
    "SIDEWAYS_MIN_VOLUME_RATIO": 1.2,  # 震荡市最小成交量倍数
    "SIDEWAYS_STOP_LOSS_ATR_MULT": 1.35, # 震荡市专用止损倍数（1.5*0.9）
    "SIDEWAYS_COOLDOWN_MULT": 1.5,     # 震荡市冷却期倍数（更谨慎）
    
    # 新增市场环境参数
    "COUNTER_TREND_ML_THRESHOLD": 0.98,  # 逆势交易所需ML置信度（提高到0.98，几乎完全禁止逆势交易）
    "BREAKOUT_MIN_VOLUME": 1.5,          # 突破最小成交量倍数
    "BREAKDOWN_RSI_THRESHOLD": 20,       # 暴跌市RSI极度超卖阈值
    "PUMP_RSI_THRESHOLD": 80,            # 暴涨市RSI极度超买阈值
    "HIGH_VOL_ATR_THRESHOLD": 0.015,     # 高波动ATR阈值(1.5%)
    "HIGH_VOL_CONFIDENCE": 0.75,         # 高波动市最低置信度
    "LOW_VOL_ATR_THRESHOLD": 0.003,      # 低波动ATR阈值(0.3%)
    "TECH_ADX_HIGH_THRESHOLD": 40,       # 强趋势ADX阈值
    
    # ==========================================
    # 5. 止盈止损参数 - 核心盈利控制
    # ==========================================
    
    # 止损参数
    "STOP_LOSS_ATR_MULT": 1.5,         # 15分钟框架: 1.5x ATR (15分钟ATR更大)
                                       # 作用：控制单笔最大亏损，减少假止损
                                       # 边界：1.5=紧(旧)，2.0=标准(新)，2.5=松
                                       # 更新日期：2026-03-24，原因：胜率过低10%
    "STOP_LOSS_MIN_PCT": 0.008,        # 最小止损0.8%
    
    # 止盈参数 - 分市场环境
    "TP_SIDEWAYS_ATR_MULT": 4.0,       # 震荡市止盈(×ATR)，目标盈亏比1.7
    "TP_TRENDING_ATR_MULT": 8.0,       # 趋势市止盈(×ATR)，让利润奔跑
    
    # 移动止盈参数
    "TRAILING_STOP_ENABLE_PCT": 0.008, # 盈利>0.8%启用移动止盈
    "TRAILING_STOP_DRAWBACK_PCT": 0.30,# 峰值回撤30%触发移动止盈
                                       # 作用：锁定利润同时让利润奔跑
                                       # 边界：20%=紧，30%=平衡，40%=松
    
    # 盈利保护参数
    "PROFIT_PROTECTION_ENABLE_PCT": 0.005,  # 浮盈>0.5%启用盈利保护
    "PROFIT_PROTECTION_DRAWBACK_PCT": 0.50, # 回撤50%强制平仓
                                       # 作用：防止盈利变亏损
    
    # ==========================================
    # 6. 冷却期和交易频率控制
    # ==========================================
    
    # 信号质量对应冷却期（秒）
    "COOLDOWN_HIGH_CONFIDENCE": 10,    # 置信度>0.75
    "COOLDOWN_MID_CONFIDENCE": 30,     # 置信度0.65-0.75
    "COOLDOWN_LOW_CONFIDENCE": 45,     # 置信度<0.65
    "COOLDOWN_MAX_SECONDS": 120,       # 最高封顶120秒（增加）
    "COOLDOWN_AFTER_LOSS": 60,         # 止损后60秒冷却期(止盈后无冷却)
    
    # 信号来源调整系数
    "COOLDOWN_ML_FACTOR": 0.8,         # ML信号更快(×0.8)
    "COOLDOWN_GRID_FACTOR": 1.2,       # 网格信号更慢(×1.2)
    
    # ==========================================
    # 7. 插针熔断保护 - ETH合约生存关键
    # ==========================================
    
    "SPIKE_DETECTION_WINDOW_SECONDS": 60,   # 插针检测窗口(1分钟)
    "SPIKE_PRICE_CHANGE_THRESHOLD": 0.02,   # 价格波动>2%触发熔断
    "SPIKE_CIRCUIT_BREAKER_MINUTES": 5,     # 熔断暂停交易(5分钟)
    
    # ==========================================
    # 8. 资金费率过滤
    # ==========================================
    
    "FUNDING_RATE_THRESHOLD": 0.001,   # 资金费率过滤阈值(0.1%)
    "FUNDING_RATE_EXTREME": 0.01,      # 极端资金费率(1%)，触发平仓
    
    # ==========================================
    # 9. 仓位计算置信度分级
    # ==========================================
    
    # 置信度对应的仓位倍数（非线性分级）
    "CONFIDENCE_MULT_EXTREME": 2.5,    # ≥0.80: 2.5倍仓位(从3.0降低)
    "CONFIDENCE_MULT_HIGH": 2.0,       # 0.70-0.80: 2倍仓位
    "CONFIDENCE_MULT_MID": 1.2,        # 0.60-0.70: 1.2倍仓位
    "CONFIDENCE_MULT_LOW": 0.6,        # 0.55-0.60: 0.6倍仓位
    "CONFIDENCE_MULT_VERY_LOW": 0.3,   # <0.55: 0.3倍仓位(极轻)
    
    # ==========================================
    # 10. 市场环境调整系数
    # ==========================================
    
    # 趋势市
    "REGIME_TREND_HIGH_CONF_MULT": 1.3,  # 高置信度×1.3(加仓)
    "REGIME_TREND_LOW_CONF_MULT": 0.9,   # 低置信度×0.9(减仓)
    
    # 震荡市
    "REGIME_SIDEWAYS_LOW_CONF_MULT": 0.7,  # 低置信度×0.7(减仓)
    "REGIME_SIDEWAYS_HIGH_CONF_MULT": 1.0, # 高置信度×1.0(正常)
    
    # ==========================================
    # 11. ML模型训练参数
    # ==========================================
    
    "ML_N_ESTIMATORS": 150,            # XGBoost树数量
    "ML_MAX_DEPTH": 4,                 # 树最大深度
    "ML_LEARNING_RATE": 0.08,          # 学习率
    "ML_SUBSAMPLE": 0.8,               # 采样比例
    "ML_COLSAMPLE_BYTREE": 0.8,        # 特征采样
    
    # ==========================================
    # 12. 日志和监控
    # ==========================================
    
    "LOG_LEVEL": "INFO",               # DEBUG/INFO/WARNING/ERROR
    "DB_PATH": "v12_optimized.db",     # 数据库路径
    
    # ==========================================
    # ML环境检测模块 (新增 2026-03-27)
    # ==========================================
    # 总开关：一键关停所有ML环境相关功能
    "ML_REGIME_ENABLED": True,  # False = 完全停用，回退到纯技术指标
    
    # ⭐ V2 新增: XGBoost市场环境检测版本选择
    "ML_REGIME_VERSION": "v2",  # "v1" = 规则版本, "v2" = XGBoost模型版本
    "ML_REGIME_V2_MODEL_PATH": "models/regime_xgb_v1.pkl",
    "ML_REGIME_V2_CONFIDENCE_THRESHOLD": 0.65,
    "ML_REGIME_V2_ENABLE_UNCERTAINTY": True,
    "ML_REGIME_V2_ENABLE_VISUALIZATION": True,  # 🆕 启用控制台可视化
    
    # 子功能开关（仅在总开关为True时生效）
    "ML_REGIME_OVERRIDE_ENABLED": True,   # 允许ML覆盖技术环境判断
    "ML_REGIME_ADJUST_POSITION": True,    # 允许ML调整仓位倍数
    "ML_REGIME_ADJUST_EXECUTION": True,   # 允许ML影响下单方式
    
    # 故障自动保护
    "ML_REGIME_AUTO_DISABLE_ON_ERROR": True,  # 出故障时自动关停
    
    # V1 规则版本检测参数（V2不需要这些）
    "ML_REGIME_HISTORY_SIZE": 10,
    "ML_STRONG_TREND_CONFIDENCE": 0.75,
    "ML_STRONG_TREND_PROBA": 0.70,
    "ML_SIDEWAYS_MAX_CONFIDENCE": 0.60,
    "ML_SIDEWAYS_PROBA_DIFF": 0.20,
    
    # ==========================================
    # 限价单配置 (优化版 2026-03-27)
    # ==========================================
    # 策略：震荡市用Maker省费率，趋势市用Taker确保成交
    # 优化：IOC订单+短等待，避免长时间延迟
    "USE_LIMIT_ORDER": True,           # 启用智能限价单
    "LIMIT_PRICE_OFFSET": 0.0001,      # 0.01%偏离（轻微偏离，成交概率高）
    "LIMIT_WAIT_TIME": 1.0,            # 只等1秒（之前3秒太长）
    "LIMIT_ORDER_REGIMES": ["SIDEWAYS", "震荡上涨", "震荡下跌"],  # 只在震荡市用限价单
    # 趋势市直接用Taker，不在此列表
    "LIMIT_RETRY_MAX": 2,              # 限价单最大重试次数
    "LIMIT_WAIT_TIME": 0.8,            # 每次等待时间(秒)，应与POLL_INTERVAL一致
    
    # ==========================================
    # 参数调优指南
    # ==========================================
    # 
    # 【低风险偏好】
    # MAX_RISK_PCT = 0.02
    # POSITION_SIZE_PCT_MAX = 0.40
    # STOP_LOSS_ATR_MULT = 1.8
    # TP_SIDEWAYS_ATR_MULT = 3.0
    #
    # 【平衡型】（当前配置）
    # MAX_RISK_PCT = 0.03
    # POSITION_SIZE_PCT_MAX = 0.60
    # STOP_LOSS_ATR_MULT = 2.0
    # TP_SIDEWAYS_ATR_MULT = 4.0
    #
    # 【高风险偏好】
    # MAX_RISK_PCT = 0.05
    # POSITION_SIZE_PCT_MAX = 0.80
    # STOP_LOSS_ATR_MULT = 2.5
    # TP_SIDEWAYS_ATR_MULT = 5.0
}
