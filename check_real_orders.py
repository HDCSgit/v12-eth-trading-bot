#!/usr/bin/env python3
"""
检查币安真实订单状态
"""

import os
import sqlite3
from datetime import datetime
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 颜色输出
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"


def check_database_orders():
    """检查数据库中的订单记录"""
    print(f"\n{CYAN}========== 系统数据库中的交易记录 =========={RESET}")
    
    try:
        conn = sqlite3.connect('elite_trades.db')
        cursor = conn.execute(
            """SELECT timestamp, symbol, action, qty, price, pnl, order_id, mode 
               FROM trades 
               ORDER BY timestamp DESC"""
        )
        trades = cursor.fetchall()
        conn.close()
        
        if not trades:
            print(f"{YELLOW}数据库中没有交易记录{RESET}")
            return
        
        print(f"共找到 {len(trades)} 笔交易记录：\n")
        print(f"{'时间':<20} {'交易对':<10} {'动作':<15} {'数量':<8} {'价格':<12} {'订单ID':<20} {'模式'}")
        print("-" * 110)
        
        real_orders = 0
        failed_orders = 0
        paper_orders = 0
        
        for trade in trades:
            timestamp, symbol, action, qty, price, pnl, order_id, mode = trade
            
            # 判断订单类型
            if order_id and order_id.startswith('paper_'):
                order_type = f"{YELLOW}PAPER{RESET}"
                paper_orders += 1
            elif order_id == 'failed' or not order_id:
                order_type = f"{RED}FAILED{RESET}"
                failed_orders += 1
            else:
                order_type = f"{GREEN}REAL{RESET}"
                real_orders += 1
            
            ts = timestamp.split('T')[1].split('.')[0] if 'T' in timestamp else timestamp[-8:]
            order_id_short = order_id[:15] + "..." if order_id and len(order_id) > 15 else (order_id or "N/A")
            
            print(f"{ts:<20} {symbol:<10} {action:<15} {qty:<8.4f} ${price:<10.2f} {order_id_short:<20} {order_type}")
        
        print("-" * 110)
        print(f"\n统计：")
        print(f"  {GREEN}真实订单 (REAL): {real_orders}{RESET}")
        print(f"  {YELLOW}模拟订单 (PAPER): {paper_orders}{RESET}")
        print(f"  {RED}失败订单 (FAILED): {failed_orders}{RESET}")
        print(f"  总计: {len(trades)}")
        
        return real_orders, paper_orders, failed_orders
        
    except Exception as e:
        print(f"{RED}读取数据库失败: {e}{RESET}")
        return 0, 0, 0


def check_binance_orders():
    """查询币安API获取真实订单"""
    print(f"\n{CYAN}========== 从币安API查询订单 =========={RESET}")
    
    try:
        from binance_api import BinanceExpertAPI
        
        api = BinanceExpertAPI()
        
        # 获取所有成交历史
        print("正在查询币安成交历史...")
        
        # 查询最近10笔成交
        trades = api._request(
            'GET', 
            '/fapi/v1/userTrades', 
            {'symbol': 'ETHUSDT', 'limit': 20},
            signed=True
        )
        
        if trades and isinstance(trades, list):
            print(f"\n币安服务器返回 {len(trades)} 笔成交记录：\n")
            print(f"{'时间':<20} {'交易对':<10} {'方向':<8} {'数量':<10} {'价格':<12} {'订单ID':<15}")
            print("-" * 90)
            
            for trade in trades:
                ts = datetime.fromtimestamp(trade['time'] / 1000).strftime('%H:%M:%S')
                symbol = trade['symbol']
                side = trade['side']
                qty = float(trade['qty'])
                price = float(trade['price'])
                order_id = str(trade['orderId'])
                
                print(f"{ts:<20} {symbol:<10} {side:<8} {qty:<10.4f} ${price:<10.2f} {order_id:<15}")
            
            print(f"\n{GREEN}✅ 币安API连接正常，以上是在币安服务器上的真实成交记录{RESET}")
            return len(trades)
        else:
            print(f"{YELLOW}币安服务器没有返回成交记录，或API调用失败{RESET}")
            print(f"返回结果: {trades}")
            return 0
            
    except Exception as e:
        print(f"{RED}查询币安API失败: {e}{RESET}")
        return 0


def check_account_balance():
    """检查账户余额"""
    print(f"\n{CYAN}========== 账户余额检查 =========={RESET}")
    
    try:
        from binance_api import BinanceExpertAPI
        
        api = BinanceExpertAPI()
        balance = api.get_balance()
        
        print(f"当前可用余额: {GREEN}${balance:.2f} USDT{RESET}")
        
        if balance < 10:
            print(f"{RED}⚠️  警告：余额过低，可能无法开仓！{RESET}")
            print(f"ETH 当前价格约 $2140，最小交易 0.001 ETH ≈ $2.14")
            print(f"加上手续费和保证金要求，建议余额至少 $20-50")
        
        return balance
        
    except Exception as e:
        print(f"{RED}获取余额失败: {e}{RESET}")
        return 0


def main():
    print(f"{CYAN}{'='*80}{RESET}")
    print(f"{CYAN}币安交易记录诊断工具{RESET}")
    print(f"{CYAN}{'='*80}{RESET}")
    
    # 1. 检查数据库
    real, paper, failed = check_database_orders()
    
    # 2. 检查余额
    balance = check_account_balance()
    
    # 3. 查询币安API
    binance_trades = check_binance_orders()
    
    # 4. 汇总诊断
    print(f"\n{CYAN}========== 诊断汇总 =========={RESET}")
    
    if real > 0 and binance_trades == 0:
        print(f"{RED}⚠️  严重问题：系统记录了 {real} 笔真实订单，但币安API查询不到！{RESET}")
        print(f"可能原因：")
        print(f"  1. API Key 权限问题（需要有读取成交历史的权限）")
        print(f"  2. 查询的 symbol 不正确")
        print(f"  3. 订单实际未成交")
        
    elif real > 0 and binance_trades > 0:
        print(f"{GREEN}✅ 系统记录与币安API一致{RESET}")
        print(f"  系统记录真实订单: {real}")
        print(f"  币安API返回: {binance_trades}")
        
    elif real == 0 and paper > 0:
        print(f"{YELLOW}⚠️  所有交易都是 PAPER 模拟模式{RESET}")
        print(f"  检查 .env 文件中的 MODE 设置")
        print(f"  当前 MODE={os.getenv('MODE', '未设置')}")
        
    elif failed > 0:
        print(f"{RED}⚠️  有 {failed} 笔订单下单失败{RESET}")
        print(f"  可能原因：余额不足、网络问题、API错误")
    
    if balance < 10:
        print(f"\n{RED}💡 建议：余额过低 (${balance:.2f})，建议充值后再交易{RESET}")


if __name__ == "__main__":
    main()