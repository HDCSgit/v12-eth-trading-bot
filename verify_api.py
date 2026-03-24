#!/usr/bin/env python3
"""
币安 API 验证工具
用于检查 API Key 和 Secret 是否正确配置
"""

import requests
import hmac
import hashlib
import time
import os
from urllib.parse import urlencode
from dotenv import load_dotenv

load_dotenv()

# 颜色输出
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"

def print_success(msg): print(f"{GREEN}✅ {msg}{RESET}")
def print_error(msg): print(f"{RED}❌ {msg}{RESET}")
def print_warning(msg): print(f"{YELLOW}⚠️  {msg}{RESET}")
def print_info(msg): print(f"ℹ️  {msg}")


def test_api_connection():
    """测试 API 连接"""
    print("\n" + "="*60)
    print("🔍 币安 API 连接验证工具")
    print("="*60)
    
    # 1. 检查环境变量
    api_key = os.getenv("BINANCE_API_KEY", "")
    secret_key = os.getenv("BINANCE_SECRET_KEY", "")
    mode = os.getenv("MODE", "PAPER")
    use_testnet = os.getenv("USE_TESTNET", "False").lower() == "true"
    
    print_info(f"当前模式: {mode}")
    print_info(f"使用测试网: {use_testnet}")
    
    if not api_key or not secret_key:
        print_error("API Key 或 Secret Key 未设置！")
        print_info("请在 .env 文件中设置:")
        print("  BINANCE_API_KEY=你的APIKey")
        print("  BINANCE_SECRET_KEY=你的SecretKey")
        return False
    
    # 显示 API Key 前8位和后4位
    masked_key = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "***"
    print_info(f"API Key: {masked_key}")
    print_info(f"Secret Key 长度: {len(secret_key)} 字符")
    
    # 2. 选择环境
    if use_testnet:
        base_url = "https://testnet.binancefuture.com"
        print_info("连接到: Binance Testnet (测试网)")
    else:
        base_url = "https://fapi.binance.com"
        print_info("连接到: Binance LIVE (真实环境)")
    
    # 3. 测试非签名请求 - 服务器时间
    print("\n📡 测试 1: 获取服务器时间...")
    try:
        response = requests.get(f"{base_url}/fapi/v1/time", timeout=10)
        server_time = response.json()['serverTime']
        local_time = int(time.time() * 1000)
        diff = abs(local_time - server_time)
        print_success(f"服务器时间获取成功")
        print_info(f"  服务器时间: {server_time}")
        print_info(f"  本地时间: {local_time}")
        print_info(f"  时间差: {diff}ms")
        
        if diff > 5000:
            print_warning("时间差超过 5 秒，建议同步系统时间！")
    except Exception as e:
        print_error(f"无法连接到币安服务器: {e}")
        print_info("可能原因:")
        print("  - 网络连接问题")
        print("  - 代理配置错误")
        print("  - 防火墙阻止")
        return False
    
    # 4. 测试签名请求 - 账户余额
    print("\n📡 测试 2: 测试签名请求 (获取余额)...")
    
    timestamp = int(time.time() * 1000)
    params = {
        'timestamp': timestamp,
        'recvWindow': 5000
    }
    
    # 生成签名
    query_string = urlencode(sorted(params.items()))
    signature = hmac.new(
        secret_key.encode('utf-8'),
        query_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    headers = {
        'X-MBX-APIKEY': api_key
    }
    
    full_url = f"{base_url}/fapi/v2/balance?{query_string}&signature={signature}"
    
    try:
        response = requests.get(full_url, headers=headers, timeout=10)
        data = response.json()
        
        if response.status_code == 200 and isinstance(data, list):
            print_success("签名验证成功！")
            
            # 查找 USDT 余额
            usdt_balance = None
            for balance in data:
                if balance.get('asset') == 'USDT':
                    usdt_balance = balance
                    break
            
            if usdt_balance:
                available = float(usdt_balance.get('availableBalance', 0))
                total = float(usdt_balance.get('balance', 0))
                print_success(f"USDT 余额查询成功")
                print_info(f"  可用余额: {available:.2f} USDT")
                print_info(f"  总余额: {total:.2f} USDT")
            else:
                print_warning("未找到 USDT 余额信息")
            
            return True
            
        elif 'code' in data and 'msg' in data:
            print_error(f"API 错误: [{data['code']}] {data['msg']}")
            
            if data['code'] == -2015:
                print_info("错误原因: 无效的 API Key 或 Secret")
                print_info("解决方法:")
                print("  1. 检查 .env 文件中的 API Key 和 Secret 是否正确")
                print("  2. 确认使用的是 U本位合约 API Key（不是现货 API）")
                print("  3. 确认 API Key 有读取账户信息和交易的权限")
                print("  4. 如果使用测试网，需要去 https://testnet.binancefuture.com 申请 Testnet API Key")
            elif data['code'] == -1021:
                print_info("错误原因: 时间戳问题")
                print_info("解决方法: 同步系统时间")
            elif data['code'] == -2014:
                print_info("错误原因: API Key 格式不正确")
                
            return False
        else:
            print_error(f"未知错误: {data}")
            return False
            
    except Exception as e:
        print_error(f"请求异常: {e}")
        return False


def show_setup_guide():
    """显示设置指南"""
    print("\n" + "="*60)
    print("📖 币安 API 设置指南")
    print("="*60)
    
    print("""
1️⃣  获取 API Key:
   - 访问: https://www.binance.com/zh-CN/my/settings/api-management
   - 或使用测试网: https://testnet.binancefuture.com

2️⃣  创建 API Key:
   - 点击"创建 API"
   - 启用"启用期货交易"权限
   - 建议设置 IP 白名单（增加安全性）

3️⃣  配置 .env 文件:
   在项目根目录创建 .env 文件:
   
   # === 真实环境（投入真钱！）===
   BINANCE_API_KEY=你的真实APIKey
   BINANCE_SECRET_KEY=你的真实Secret
   MODE=LIVE
   USE_TESTNET=False
   
   # === 测试环境（推荐先测试）===
   # BINANCE_API_KEY=你的TestnetAPIKey
   # BINANCE_SECRET_KEY=你的TestnetSecret
   # MODE=PAPER
   # USE_TESTNET=True

4️⃣  安全提示:
   - 永远不要将 API Key 提交到 Git
   - 确保 .env 在 .gitignore 中
   - LIVE 模式会真实交易，请确保你了解风险
   - 建议先用 TESTNET 测试一周再切换到 LIVE

5️⃣  验证配置:
   运行: python verify_api.py
    """)


if __name__ == "__main__":
    try:
        success = test_api_connection()
        if not success:
            show_setup_guide()
            exit(1)
        else:
            print("\n" + "="*60)
            print_success("所有测试通过！API 配置正确")
            print("="*60)
            exit(0)
    except KeyboardInterrupt:
        print("\n\n已取消")
        exit(0)