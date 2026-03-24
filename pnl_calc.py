#!/usr/bin/env python3
"""
合约盈亏计算器
"""

# 你的持仓信息
entry_price = 2195.95
current_price = 2138.14  # 根据日志更新
qty = 0.023
leverage = 10

# 名义价值
notional = qty * entry_price

# 价格变动
price_change_pct = (current_price - entry_price) / entry_price

# 名义盈亏（不加杠杆）
pnl_no_leverage = notional * price_change_pct

# 杠杆后收益率
leveraged_pnl_pct = price_change_pct * leverage * 100

print('='*60)
print('ETH/USDT 合约盈亏计算')
print('='*60)
print(f'开仓价: ${entry_price:.2f}')
print(f'当前价: ${current_price:.2f}')
print(f'数量: {qty} ETH')
print(f'杠杆: {leverage}x')
print('')
print(f'名义价值: ${notional:.2f}')
print(f'价格变动: {price_change_pct*100:.2f}%')
print('')
print(f'名义盈亏: ${pnl_no_leverage:.2f}')
print(f'杠杆后收益率: {leveraged_pnl_pct:.2f}%')
print('')
print(f'实际盈亏金额: ${pnl_no_leverage:.2f} USDT')
print(f'保证金回报率: {leveraged_pnl_pct:.2f}%')
print('='*60)

# 止损止盈计算
print('\n止损止盈计算:')
print(f'止损(-5%): 价格需跌到 ${entry_price * (1 - 5/leverage/100):.2f}')
print(f'止盈(+10%): 价格需涨到 ${entry_price * (1 + 10/leverage/100):.2f}')
print('='*60)
