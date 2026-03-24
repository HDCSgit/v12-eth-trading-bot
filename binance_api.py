import requests
import hmac
import hashlib
import time
import json
import logging
import threading
import websocket
from datetime import datetime
from typing import Dict, Optional, Union
import pandas as pd
from urllib.parse import urlencode
from config import API_KEY, SECRET_KEY, PROXY, CONFIG

logger = logging.getLogger(__name__)


class BinanceExpertAPI:
    def __init__(self):
        # 确定使用哪个环境
        if CONFIG.get("USE_TESTNET", False):
            self.base_url = "https://testnet.binancefuture.com"
            self.ws_url = "wss://stream.binancefuture.com/ws"
            logger.info("🔧 使用 Binance Testnet (测试网)")
        else:
            self.base_url = "https://fapi.binance.com"
            self.ws_url = "wss://fstream.binance.com/ws"
            logger.info("🚀 使用 Binance LIVE (真实环境)")
        
        self.session = requests.Session()
        if PROXY:
            self.session.proxies = {"http": PROXY, "https": PROXY}
            logger.info(f"🌐 使用代理: {PROXY}")
        
        self.headers = {
            "X-MBX-APIKEY": API_KEY,
            "Content-Type": "application/x-www-form-urlencoded"
        }
        self.price_cache: Dict[str, float] = {}
        self.ws = None
        self.last_ws_reconnect = 0
        
        # 验证 API 连接
        self._validate_api_connection()
        self.start_websocket()
        logger.info("✅ Binance API + WebSocket 初始化完成")

    def _validate_api_connection(self):
        """验证 API 连接和权限"""
        try:
            # 测试非签名请求
            server_time = self.get_server_time()
            local_time = int(time.time() * 1000)
            time_diff = abs(local_time - server_time)
            logger.info(f"⏱️ 服务器时间差: {time_diff}ms")
            
            if time_diff > 5000:
                logger.warning(f"⚠️ 本地时间与服务器时间相差 {time_diff}ms，建议同步系统时间")
            
            # 测试签名请求
            balance = self.get_balance()
            logger.info(f"💰 API 验证成功，余额: ${balance:.2f} USDT")
            
        except Exception as e:
            logger.error(f"❌ API 连接验证失败: {e}")
            raise

    def get_server_time(self) -> int:
        """获取币安服务器时间"""
        try:
            response = self.session.get(f"{self.base_url}/fapi/v1/time", timeout=10)
            data = response.json()
            return data['serverTime']
        except Exception as e:
            logger.error(f"获取服务器时间失败: {e}")
            return int(time.time() * 1000)

    def _generate_signature(self, query_string: str) -> str:
        """使用 HMAC SHA256 生成签名"""
        return hmac.new(
            SECRET_KEY.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

    def _request(self, method: str, endpoint: str, params: Dict = None, signed: bool = False) -> Optional[Union[Dict, list]]:
        """
        币安官方标准请求方式
        参考: https://binance-docs.github.io/apidocs/futures/cn/#c6c9d2cb8d
        """
        url = f"{self.base_url}{endpoint}"
        params = params or {}
        
        # 非签名请求
        if not signed:
            try:
                if method == 'GET':
                    response = self.session.get(url, params=params, timeout=10)
                else:
                    response = self.session.post(url, data=params, timeout=10)
                response.raise_for_status()
                return response.json()
            except requests.exceptions.RequestException as e:
                logger.error(f"请求失败 [{endpoint}]: {e}")
                return None
        
        # 签名请求处理
        try:
            # 1. 添加时间戳和接收窗口
            params['timestamp'] = int(time.time() * 1000)
            params['recvWindow'] = 5000
            
            # 2. 将所有参数转换为字符串
            str_params = {k: str(v) for k, v in params.items()}
            
            # 3. 按字母顺序排序并编码
            query_string = urlencode(sorted(str_params.items()))
            
            # 4. 生成签名
            signature = self._generate_signature(query_string)
            
            # 5. 添加签名到查询字符串
            signed_query_string = f"{query_string}&signature={signature}"
            
            # 6. 发送请求
            if method == 'GET':
                # GET: 参数放 URL
                full_url = f"{url}?{signed_query_string}"
                response = self.session.get(full_url, headers={"X-MBX-APIKEY": API_KEY}, timeout=10)
            else:
                # POST/DELETE: 参数放 body
                response = self.session.post(
                    url, 
                    data=signed_query_string,
                    headers=self.headers,
                    timeout=10
                )
            
            response.raise_for_status()
            data = response.json()
            
            # 检查币安 API 返回的错误
            if isinstance(data, dict) and 'code' in data:
                if data.get('code') not in [None, 200]:
                    logger.error(f"Binance API 错误 [{data.get('code')}]: {data.get('msg')}")
                    return None
            
            return data
            
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP 错误 [{endpoint}]: {e}")
            try:
                error_data = response.json()
                logger.error(f"Binance 错误详情: {error_data}")
            except:
                logger.error(f"响应内容: {response.text if 'response' in locals() else 'N/A'}")
            return None
        except Exception as e:
            logger.error(f"请求异常 [{endpoint}]: {e}")
            return None

    def get_klines(self, symbol: str, limit: int = 800) -> Optional[pd.DataFrame]:
        """获取 K 线数据"""
        params = {
            "symbol": symbol,
            "interval": CONFIG["INTERVAL"],
            "limit": limit
        }
        data = self._request('GET', '/fapi/v1/klines', params)
        if not data or not isinstance(data, list):
            logger.error(f"获取K线数据失败: {data}")
            return None
        
        try:
            df = pd.DataFrame(data, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df.dropna()
        except Exception as e:
            logger.error(f"处理K线数据失败: {e}")
            return None

    def get_balance(self) -> float:
        """获取 USDT 可用余额"""
        data = self._request('GET', '/fapi/v2/balance', {}, signed=True)
        if not data or not isinstance(data, list):
            logger.error(f"获取余额失败，返回: {data}")
            return 0.0
        
        try:
            for balance in data:
                if balance.get('asset') == 'USDT':
                    available = float(balance.get('availableBalance', 0))
                    total = float(balance.get('balance', 0))
                    logger.debug(f"USDT 余额: 可用=${available:.2f}, 总=${total:.2f}")
                    return available
        except Exception as e:
            logger.error(f"解析余额数据失败: {e}")
        
        return 0.0

    def get_position(self, symbol: str) -> Optional[Dict]:
        """获取指定交易对的仓位信息"""
        data = self._request('GET', '/fapi/v2/positionRisk', {}, signed=True)
        if not data or not isinstance(data, list):
            logger.error(f"获取仓位失败，返回: {data}")
            return None
        
        try:
            for pos in data:
                if pos.get('symbol') == symbol:
                    amt = float(pos.get('positionAmt', 0))
                    if abs(amt) < 0.0001:
                        return None
                    return {
                        "symbol": symbol,
                        "side": "LONG" if amt > 0 else "SHORT",
                        "qty": abs(amt),
                        "entryPrice": float(pos.get('entryPrice', 0)),
                        "leverage": int(pos.get('leverage', CONFIG.get("LEVERAGE", 5))),
                        "unrealizedProfit": float(pos.get('unRealizedProfit', 0)),
                        "liquidationPrice": float(pos.get('liquidationPrice', 0)),
                        "notional": float(pos.get('notional', 0)),
                        "markPrice": float(pos.get('markPrice', 0)),
                        "marginType": pos.get('marginType', 'CROSSED')
                    }
        except Exception as e:
            logger.error(f"解析仓位数据失败: {e}")
        
        return None

    def get_all_positions(self) -> list:
        """获取所有持仓"""
        data = self._request('GET', '/fapi/v2/positionRisk', {}, signed=True)
        if not data or not isinstance(data, list):
            return []
        
        positions = []
        for pos in data:
            try:
                amt = float(pos.get('positionAmt', 0))
                if abs(amt) > 0.0001:
                    positions.append({
                        "symbol": pos.get('symbol'),
                        "side": "LONG" if amt > 0 else "SHORT",
                        "qty": abs(amt),
                        "entryPrice": float(pos.get('entryPrice', 0)),
                        "unrealizedProfit": float(pos.get('unRealizedProfit', 0))
                    })
            except:
                continue
        return positions

    def get_price(self, symbol: str) -> Optional[float]:
        """获取当前价格（优先从缓存）"""
        if symbol in self.price_cache:
            return self.price_cache[symbol]
        
        try:
            data = self._request('GET', '/fapi/v1/ticker/price', {'symbol': symbol})
            if data and 'price' in data:
                price = float(data['price'])
                self.price_cache[symbol] = price
                return price
        except Exception as e:
            logger.error(f"获取 {symbol} 价格失败: {e}")
        
        return None

    def place_order(self, symbol: str, side: str, qty: float, reduce_only: bool = False) -> Optional[Dict]:
        """
        下单（市场单）
        参考: https://binance-docs.github.io/apidocs/futures/cn/#trade-3
        """
        # 本地模拟模式
        if CONFIG["MODE"] == "PAPER":
            logger.info(f"[PAPER] 模拟下单: {side} {qty} {symbol}")
            return {"orderId": f"paper_{int(time.time()*1000)}", "symbol": symbol, "side": side, "qty": qty}
        
        # LIVE 模式
        if CONFIG["MODE"] != "LIVE":
            logger.error(f"未知的交易模式: {CONFIG['MODE']}")
            return None
        
        # 参数验证
        if qty < 0.001:
            logger.error(f"订单数量太小: {qty}，最小需要 0.001")
            return None
        
        # ETHUSDT精度为3位小数，确保格式化正确
        qty_formatted = f"{qty:.3f}"
        
        params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": qty_formatted,
            "reduceOnly": "true" if reduce_only else "false",
            "newOrderRespType": "RESULT"  # 返回完整成交结果
        }
        
        logger.info(f"[LIVE] 真实下单: {side} {qty} {symbol} (reduceOnly={reduce_only})")
        
        result = self._request('POST', '/fapi/v1/order', params, signed=True)
        
        if result and result.get('orderId'):
            logger.info(f"✅ 订单成功: orderId={result.get('orderId')}, "
                       f"avgPrice=${float(result.get('avgPrice', 0)):.2f}, "
                       f"executedQty={result.get('executedQty', 0)}")
        else:
            logger.error(f"❌ 下单失败: {result}")
        
        return result

    def cancel_all_orders(self, symbol: str) -> Optional[Dict]:
        """撤销所有挂单"""
        params = {"symbol": symbol}
        return self._request('DELETE', '/fapi/v1/allOpenOrders', params, signed=True)

    def set_leverage(self, symbol: str, leverage: int) -> Optional[Dict]:
        """设置杠杆倍数"""
        params = {
            "symbol": symbol,
            "leverage": leverage
        }
        return self._request('POST', '/fapi/v1/leverage', params, signed=True)

    def get_account_info(self) -> Optional[Dict]:
        """获取账户信息"""
        return self._request('GET', '/fapi/v2/account', {}, signed=True)

    def get_funding_rate(self, symbol: str) -> float:
        """
        获取资金费率（Funding Rate）
        正值：多头付空头，应该避免开多
        负值：空头付多头，应该避免开空
        """
        try:
            # 获取当前资金费率
            data = self._request('GET', '/fapi/v1/premiumIndex', {'symbol': symbol})
            if data and 'lastFundingRate' in data:
                funding_rate = float(data['lastFundingRate'])
                logger.debug(f"{symbol} 当前资金费率: {funding_rate:.4%}")
                return funding_rate
            return 0.0
        except Exception as e:
            logger.error(f"获取资金费率失败: {e}")
            return 0.0

    def get_next_funding_time(self, symbol: str) -> int:
        """获取下次资金费结算时间（毫秒时间戳）"""
        try:
            data = self._request('GET', '/fapi/v1/premiumIndex', {'symbol': symbol})
            if data and 'nextFundingTime' in data:
                return int(data['nextFundingTime'])
            return 0
        except Exception as e:
            logger.error(f"获取下次资金费时间失败: {e}")
            return 0

    # ==================== WebSocket 实时 ====================
    def start_websocket(self):
        """启动 WebSocket 连接（带重连控制）"""
        def on_message(ws, msg):
            try:
                data = json.loads(msg)
                if 'data' in data and 'c' in data['data']:
                    symbol = data['data'].get('s', '')
                    price = float(data['data']['c'])
                    self.price_cache[symbol] = price
            except Exception as e:
                logger.debug(f"WebSocket 消息处理失败: {e}")

        def on_error(ws, error):
            logger.error(f"WebSocket 错误: {error}")

        def on_close(ws, close_status_code, close_msg):
            # 防止频繁重连
            current_time = time.time()
            if current_time - self.last_ws_reconnect < 10:
                logger.warning("WebSocket 重连过于频繁，等待10秒...")
                time.sleep(10)
            
            self.last_ws_reconnect = current_time
            logger.warning(f"WebSocket 断开 (code: {close_status_code})，5秒后重连...")
            time.sleep(CONFIG.get("WS_RECONNECT_DELAY", 5))
            self.start_websocket()

        def on_open(ws):
            logger.info("WebSocket 连接成功")

        try:
            if not CONFIG.get("SYMBOLS"):
                logger.warning("没有配置交易对，不启动 WebSocket")
                return
            
            streams = "/".join([f"{s.lower()}@ticker" for s in CONFIG["SYMBOLS"]])
            ws_url = f"{self.ws_url}/stream?streams={streams}"
            
            self.ws = websocket.WebSocketApp(
                ws_url,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close
            )
            threading.Thread(target=self.ws.run_forever, daemon=True).start()
        except Exception as e:
            logger.error(f"启动 WebSocket 失败: {e}")

    def close_websocket(self):
        """关闭 WebSocket 连接"""
        if self.ws:
            try:
                self.ws.close()
                logger.info("WebSocket 已关闭")
            except:
                pass