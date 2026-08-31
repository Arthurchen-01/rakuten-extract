# -*- coding: utf-8 -*-
"""
Rakuten Japan 核心业务引擎
包含：
1. 纯协议订单接口对接 (purchasehistoryapi/orderlist)
2. Playwright 无头/有头浏览器指纹拟真与动态代理安全登录
3. 代理多格式智能解析 (支持 host:port:user:pass, user:pass@host:port 等)
4. 账号管理与数据持久化
5. 结构化订单解析与 Excel/CSV/JSON 导出
6. 逐步骤实时回调日志支持
"""

import os
import sys
import time
import json
import random
import logging
import threading
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple, Callable
from urllib.parse import urlparse
import requests
import pandas as pd
from playwright.sync_api import sync_playwright

CST_TZ = timezone(timedelta(hours=8))

def get_cst_now() -> datetime:
    return datetime.now(CST_TZ)

def get_cst_now_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return datetime.now(CST_TZ).strftime(fmt)

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("RakutenEngine")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
COOKIES_DIR = os.path.join(DATA_DIR, "cookies")
EXPORTS_DIR = os.path.join(DATA_DIR, "exports")
SCREENSHOTS_DIR = os.path.join(DATA_DIR, "screenshots")
ACCOUNTS_FILE = os.path.join(DATA_DIR, "accounts.json")
ORDERS_FILE = os.path.join(DATA_DIR, "orders_cache.json")
HISTORY_VAULT_FILE = os.path.join(DATA_DIR, "history_tested_accounts.json")
IMPORT_BATCHES_FILE = os.path.join(DATA_DIR, "import_batches.json")

os.makedirs(COOKIES_DIR, exist_ok=True)
os.makedirs(EXPORTS_DIR, exist_ok=True)
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

import re

JAPANESE_PHONE_REGEX = re.compile(
    r'(?<![\d\-])'
    r'(?:'
    r'0[25-9]0-\d{4}-\d{4}'                  # 11位 手机 (070, 080, 090, 050)
    r'|'
    r'0[36]-\d{4}-\d{4}'                      # 10位 东京/大阪 (03, 06)
    r'|'
    r'0\d{2}-\d{3,4}-\d{4}'                   # 10位 主要城市 (045, 052, 092...)
    r'|'
    r'0\d{3}-\d{2,3}-\d{4}'                   # 10位 地方城市
    r'|'
    r'0\d{4}-\d{1,2}-\d{4}'                   # 10位 局部号码
    r')'
    r'(?![\d\-])'
)

JAPANESE_ADDR_REGEX = re.compile(
    r'(?:〒\s*(\d{3}-\d{4})\s*)?'
    r'([一-龥ぁ-んァ-ン]+(?:都|道|府|県)[一-龥ぁ-んァ-ン0-9\-ー\s]{2,80})'
)

def clean_and_validate_address(addr_str: str) -> str:
    if not addr_str:
        return ""
    if not re.search(r'[\u4e00-\u9fa5\u3040-\u30ff]', addr_str):
        return ""
    lines = [l.strip() for l in addr_str.split("\n") if l.strip()]
    clean_lines = []
    for line in lines:
        if re.match(r'^\d{4,}-\d{4,}$', line) or re.match(r'^\d{6,}$', line):
            continue
        clean_lines.append(line)
    return "\n".join(clean_lines)


def normalize_proxy_for_playwright(proxy_str: Optional[str]) -> Optional[Dict[str, str]]:
    if not proxy_str:
        return None
    proxy_str = proxy_str.strip()
    if not proxy_str:
        return None

    parts = proxy_str.split(":")
    if len(parts) == 4 and not proxy_str.startswith("http") and not proxy_str.startswith("socks"):
        host, port, user, pwd = parts[0], parts[1], parts[2], parts[3]
        return {
            "server": f"http://{host}:{port}",
            "username": user,
            "password": pwd
        }
    elif len(parts) == 2 and not proxy_str.startswith("http") and not proxy_str.startswith("socks"):
        host, port = parts[0], parts[1]
        return {"server": f"http://{host}:{port}"}
    elif "@" in proxy_str:
        if not (proxy_str.startswith("http://") or proxy_str.startswith("https://") or proxy_str.startswith("socks5://")):
            proxy_str = "http://" + proxy_str
        p = urlparse(proxy_str)
        res = {"server": f"{p.scheme}://{p.hostname}:{p.port}"}
        if p.username:
            res["username"] = p.username
        if p.password:
            res["password"] = p.password
        return res
    else:
        if not (proxy_str.startswith("http://") or proxy_str.startswith("https://") or proxy_str.startswith("socks5://")):
            proxy_str = "http://" + proxy_str
        return {"server": proxy_str}


def normalize_proxy_for_requests(proxy_str: Optional[str]) -> Optional[Dict[str, str]]:
    if not proxy_str:
        return None
    proxy_str = proxy_str.strip()
    if not proxy_str:
        return None

    parts = proxy_str.split(":")
    if len(parts) == 4 and not proxy_str.startswith("http") and not proxy_str.startswith("socks"):
        host, port, user, pwd = parts[0], parts[1], parts[2], parts[3]
        p_url = f"http://{user}:{pwd}@{host}:{port}"
        return {"http": p_url, "https": p_url}
    elif len(parts) == 2 and not proxy_str.startswith("http") and not proxy_str.startswith("socks"):
        host, port = parts[0], parts[1]
        p_url = f"http://{host}:{port}"
        return {"http": p_url, "https": p_url}
    else:
        if not (proxy_str.startswith("http://") or proxy_str.startswith("https://") or proxy_str.startswith("socks5://")):
            proxy_str = "http://" + proxy_str
PROXY_POOL_FILE = os.path.join(DATA_DIR, "proxy_pool.json")


class ProxyPoolManager:
    """
    全局动态住宅代理池管理器：
    1. 持久化存储基础代理模板
    2. 支持动态 Session ID 自动替换 (只要账户有余额即可生成无限全新日本 IP)
    3. 支持轮询调度、自动重试换 IP
    4. 支持代理连通性测试 (查询实际出口 IP 和地理位置)
    """
    _instance = None
    _lock = threading.RLock()

    def __init__(self):
        self.settings = {
            "auto_rotate_enabled": True,
            "base_proxies": [],
            "default_region": "JP",
            "session_ttl_minutes": 5
        }
        self.load_settings()

    @classmethod
    def get_instance(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = ProxyPoolManager()
            return cls._instance

    def load_settings(self):
        with self._lock:
            if os.path.exists(PROXY_POOL_FILE):
                try:
                    with open(PROXY_POOL_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, dict):
                            self.settings.update(data)
                except Exception as e:
                    logger.error(f"加载代理池配置失败: {e}")
            else:
                self.save_settings()

    def save_settings(self):
        with self._lock:
            with open(PROXY_POOL_FILE, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=2, ensure_ascii=False)

    @staticmethod
    def generate_random_sid(length=8) -> str:
        chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        return "".join(random.choice(chars) for _ in range(length))

    def rotate_proxy_session(self, proxy_str: str) -> str:
        """
        若代理包含 -sid- 或 -session-，自动替换为一个全新的随机 Session ID，
        只要代理账户有余额/流量，即可无缝获取全新的日本住宅 IP
        """
        if not proxy_str:
            return proxy_str
        
        new_sid = self.generate_random_sid(8)
        import re
        if "-sid-" in proxy_str:
            return re.sub(r"-sid-[A-Za-z0-9_-]+", f"-sid-{new_sid}", proxy_str)
        elif "-session-" in proxy_str:
            return re.sub(r"-session-[A-Za-z0-9_-]+", f"-session-{new_sid}", proxy_str)
        return proxy_str

    def get_dynamic_proxy_for_account(self, account_proxy: Optional[str] = None) -> Optional[str]:
        """
        获取一个可用的动态日本住宅代理：
        1. 若账号已有专属动态代理，自动刷新其 Session ID；
        2. 若账号未配置代理，从全局代理池中挑选模板并派发全新 Session 代理；
        3. 若全局代理池为空且账号无代理，返回 None。
        """
        if account_proxy and account_proxy.strip():
            return self.rotate_proxy_session(account_proxy.strip())

        if not self.settings.get("auto_rotate_enabled", True):
            return None

        base_list = self.settings.get("base_proxies", [])
        if not base_list:
            return None

        # 过滤空行
        valid_proxies = [p.strip() for p in base_list if p and p.strip()]
        if not valid_proxies:
            return None

        chosen_base = random.choice(valid_proxies)
        return self.rotate_proxy_session(chosen_base)

    def test_proxy(self, proxy_str: Optional[str] = None) -> Dict[str, Any]:
        """
        测试代理连通性并探测出口 IP、国家与城市（真实探测，不使用虚假默认值）
        """
        target_proxy = proxy_str or self.get_dynamic_proxy_for_account()
        if not target_proxy:
            return {"status": "error", "message": "未配置可用代理模板"}

        req_proxies = normalize_proxy_for_requests(target_proxy)
        try:
            resp = requests.get(
                "https://api.ipify.org?format=json",
                proxies=req_proxies,
                timeout=12
            )
            if resp.status_code == 200:
                ip = resp.json().get("ip", "")
                geo_info = "地理位置探测中..."
                try:
                    # 尝试查询真实归属地
                    geo_resp = requests.get(f"https://ipapi.co/{ip}/json/", proxies=req_proxies, timeout=6)
                    if geo_resp.status_code == 200:
                        gj = geo_resp.json()
                        city = gj.get('city', '')
                        region = gj.get('region', '')
                        country = gj.get('country_name', '')
                        org = gj.get('org', '')
                        parts = [p for p in [city, region, country] if p]
                        geo_info = ", ".join(parts)
                        if org:
                            geo_info += f" ({org})"
                    else:
                        geo_info = "归属地解析接口限流(未能获取城市)"
                except Exception as geo_err:
                    geo_info = f"归属地查询超时 ({str(geo_err)[:30]})"

                return {
                    "status": "success",
                    "proxy": target_proxy,
                    "ip": ip,
                    "location": geo_info,
                    "message": f"代理连通成功！出口 IP: {ip} · 地理信息: {geo_info}"
                }
            else:
                return {"status": "error", "message": f"代理响应异常: HTTP {resp.status_code}"}
        except Exception as e:
            return {"status": "error", "message": f"代理连接失败: {str(e)}"}


class RakutenOrderAPI:
    """
    基于 HAR 逆向解析的乐天购买履历官方 JSON API 客户端
    """
    ORDER_LIST_API = "https://order.my.rakuten.co.jp/purchasehistoryapi/orderlist"
    ORDER_PAGE_URL = "https://order.my.rakuten.co.jp/purchase-history/order-list?l-id=pc_header_func_ph"

    DEFAULT_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ja,zh-CN;q=0.9,zh;q=0.8,en-US;q=0.7,en;q=0.6",
        "Referer": "https://order.my.rakuten.co.jp/purchase-history/order-list?l-id=pc_header_func_ph",
        "Sec-Ch-Ua": '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin"
    }

    def __init__(self, cookies: Any, proxy: Optional[str] = None):
        self.session = requests.Session()
        self.session.headers.update(self.DEFAULT_HEADERS)
        self.proxy = proxy
        if proxy:
            req_proxies = normalize_proxy_for_requests(proxy)
            if req_proxies:
                self.session.proxies = req_proxies
        self.set_cookies(cookies)

    def set_cookies(self, cookies: Any):
        if isinstance(cookies, str):
            if os.path.exists(cookies):
                with open(cookies, "r", encoding="utf-8") as f:
                    cookies = json.load(f)
            else:
                cookie_dict = {}
                for item in cookies.split(";"):
                    if "=" in item:
                        k, v = item.strip().split("=", 1)
                        cookie_dict[k] = v
                cookies = cookie_dict

        if isinstance(cookies, list):
            for c in cookies:
                name = c.get("name")
                value = c.get("value")
                domain = c.get("domain", ".rakuten.co.jp")
                path = c.get("path", "/")
                if name and value:
                    self.session.cookies.set(name, value, domain=domain, path=path)
        elif isinstance(cookies, dict):
            for k, v in cookies.items():
                self.session.cookies.set(k, v, domain=".rakuten.co.jp")

    def check_and_fetch_orders(self, year: Optional[str] = None) -> Tuple[bool, List[Dict[str, Any]], str]:
        # 优先拉取全量订单或多年度订单
        years_to_query = [str(year)] if year else ["", str(datetime.now().year), str(datetime.now().year - 1), str(datetime.now().year - 2), str(datetime.now().year - 3), str(datetime.now().year - 4), str(datetime.now().year - 5), str(datetime.now().year - 6)]
        
        all_parsed_orders = []
        seen_ids = set()
        last_msg = ""
        is_any_valid = False

        for y in years_to_query:
            params = {}
            if y:
                params["order_year"] = str(y)

            try:
                res = self.session.get(self.ORDER_LIST_API, params=params, timeout=15, allow_redirects=True)
                if res.status_code == 200:
                    try:
                        data = res.json()
                    except Exception:
                        continue

                    flags = data.get("flags", {})
                    is_logged_in = flags.get("isUserLoggedIn", False)
                    if not is_logged_in:
                        continue

                    is_any_valid = True
                    raw_orders = data.get("orderList", [])
                    for o in raw_orders:
                        parsed = self._normalize_order(o)
                        if parsed and parsed["order_id"] not in seen_ids:
                            seen_ids.add(parsed["order_id"])
                            all_parsed_orders.append(parsed)
                    
                    if not y and len(all_parsed_orders) > 0:
                        # 全量请求直接成功返回了数据
                        break
            except Exception as e:
                pass

        if is_any_valid:
            return True, all_parsed_orders, f"成功获取 {len(all_parsed_orders)} 笔历史订单"
        else:
            return False, [], "未能获取到登录态或请求未响应"
    def _normalize_order(self, raw_order: Dict[str, Any]) -> Dict[str, Any]:
        order_id = raw_order.get("orderId") or raw_order.get("orderNumber") or "N/A"
        order_date = raw_order.get("orderDate") or raw_order.get("orderDatetime") or ""
        shop_info = raw_order.get("shop", {}) or {}
        shop_name = shop_info.get("shopName") or raw_order.get("shopName") or "乐天店铺"
        
        items_raw = raw_order.get("itemList") or raw_order.get("items") or []
        items_list = []
        calc_total_price = 0
        for it in items_raw:
            item_name = it.get("itemName") or it.get("title") or "商品"
            item_price = it.get("itemPrice") if it.get("itemPrice") is not None else it.get("price", 0)
            units = it.get("itemUnits") or it.get("units") or it.get("quantity") or 1
            item_img = it.get("imagePathPC") or it.get("imagePathSP") or it.get("imageUrl") or ""
            try:
                price_num = int(str(item_price).replace(",", "").replace("円", "")) if str(item_price).strip() else 0
            except Exception:
                price_num = 0
            calc_total_price += price_num * int(units)
            items_list.append({
                "name": item_name,
                "price": price_num,
                "units": int(units),
                "image": item_img
            })

        payment = raw_order.get("payment", {}) or {}
        total_price = payment.get("totalPrice") or raw_order.get("totalAmount") or raw_order.get("price")
        if not total_price or total_price == "0" or total_price == 0:
            total_price = calc_total_price

        shipping = raw_order.get("shipping", {}) or {}
        shipping_status = shipping.get("status") or raw_order.get("shippingStatus") or "已受理"
        tracking_num = shipping.get("trackingNumber") or ""

        items_summary = " | ".join([f"{it['name']} (x{it['units']})" for it in items_list]) if items_list else "无商品信息"

        return {
            "order_id": order_id,
            "order_date": order_date,
            "shop_name": shop_name,
            "total_price": total_price,
            "shipping_status": shipping_status,
            "tracking_number": tracking_num,
            "items_count": len(items_list),
            "items_summary": items_summary,
            "items_detail": items_list,
            "raw_data": raw_order
        }


def fetch_order_detail_real_data(cookies: Any, order: Dict[str, Any], proxy: Optional[str] = None) -> Tuple[str, str, str, str]:
    """
    深度解析订单详情页 HTML：
    提取真实信用卡品牌/尾号、真实收件地址、真实联系电话/手机号、收件人姓名、物流单号
    """
    if order.get("card_info") and order.get("delivery_address"):
        return order.get("card_info"), order.get("delivery_address"), order.get("phone", ""), order.get("recipient_name", "")

    raw = order.get("raw_data", {})
    det_url = raw.get("orderDetailsUrl")
    if not det_url:
        return "", "", "", ""

    try:
        s = requests.Session()
        s.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            "Referer": "https://order.my.rakuten.co.jp/purchase-history/order-list"
        })
        if proxy:
            req_proxies = normalize_proxy_for_requests(proxy)
            if req_proxies:
                s.proxies = req_proxies

        if isinstance(cookies, list):
            for c in cookies:
                s.cookies.set(c["name"], c["value"], domain=c.get("domain", ".rakuten.co.jp"), path=c.get("path", "/"))
        elif isinstance(cookies, dict):
            for k, v in cookies.items():
                s.cookies.set(k, v, domain=".rakuten.co.jp")

        r = s.get(det_url, timeout=12)
        if "align_token" in r.text:
            token_m = re.search(r'name="align_token" value="([^"]+)"', r.text)
            if token_m:
                token = token_m.group(1)
                r = s.post("https://member.id.rakuten.co.jp/rms/nid/sessionAlign", data={"align_token": token}, allow_redirects=True, timeout=12)

        # 1. 提取真实信用卡信息 (VISA / MasterCard / JCB / AMEX / Diners / 楽天カード)
        card_info = ""
        card_m = re.search(r'(VISA|MasterCard|Master|JCB|AMEX|Diners|楽天カード)[^\n<]{0,25}\*{3,4}\s*(\d{4})', r.text, re.I)
        if card_m:
            brand = card_m.group(1).strip()
            if brand.lower() == "master":
                brand = "MasterCard"
            last4 = card_m.group(2).strip()
            card_info = f"{brand} **** {last4}"
        elif "一括払い" in r.text or "クレジットカード" in r.text:
            m_any = re.search(r'\*{3,4}\s*(\d{4})', r.text)
            if m_any:
                card_info = f"クレジットカード **** {m_any.group(1)}"
            else:
                card_info = "クレジットカード決済(一括払い)"
        elif "代金引換" in r.text:
            card_info = "代金引換"
        elif "ポイント" in r.text:
            card_info = "楽天ポイント全額決済"

        # 2. 提取真实联系电话/手机号 (严格排除订单号干扰)
        phone_str = ""
        phone_m = JAPANESE_PHONE_REGEX.search(r.text)
        if phone_m:
            phone_str = phone_m.group(0).replace(" ", "-")

        # 3. 提取真实收件地址 (必须包含日本都道府县或日文字符，绝不误匹配订单号)
        real_addr = ""
        recipient_name = ""
        addr_m = JAPANESE_ADDR_REGEX.search(r.text)
        if addr_m:
            zip_code = addr_m.group(1) or ""
            addr_text = addr_m.group(2).strip()
            real_addr = (f"〒{zip_code}\n" if zip_code else "") + addr_text
        else:
            zip_m = re.search(r'〒\s*(\d{3}-\d{4})', r.text)
            if zip_m:
                zip_code = zip_m.group(1)
                real_addr = f"〒{zip_code}"

        # 4. 提取真实快递单号 (佐川急便 / ヤマト運輸 / 伝票番号)
        track_m = re.search(r'(伝票番号|お荷物伝票番号|お問合せ番号|お問合せ先|追跡番号)[^\d]{0,20}(\d{10,14})', r.text)
        if track_m:
            order["tracking_number"] = track_m.group(2)
        elif "伝票番号" in r.text:
            m_t = re.search(r'伝票番号[^\n<]{0,40}', r.text)
            if m_t:
                digits = re.findall(r'\d{10,14}', m_t.group(0))
                if digits:
                    order["tracking_number"] = digits[0]

        if card_info:
            order["card_info"] = card_info
        if real_addr:
            order["delivery_address"] = real_addr
        if phone_str:
            order["phone"] = phone_str

        return card_info, real_addr, phone_str, recipient_name
    except Exception:
        return "", "", "", ""


class RakutenBrowserWorker:
    """
    Playwright 浏览器自动化：支持无头/有头模式、代理自动转换、反检测指纹注入与实时日志
    """
    ORDER_URL = "https://order.my.rakuten.co.jp/"
    
    STEALTH_JS = """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    window.navigator.chrome = { runtime: {}, loadTimes: function() {}, csi: function() {}, app: {} };
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    Object.defineProperty(navigator, 'languages', { get: () => ['ja-JP', 'ja', 'en-US', 'en'] });
    """

    @staticmethod
    def login_account(email: str, password: str, proxy: Optional[str] = None, headless: bool = True, timeout_sec: int = 60, log_cb: Optional[Callable[[str, str], None]] = None, initial_cookies: Optional[Dict[str, Any]] = None) -> Tuple[bool, Optional[List[Dict]], List[Dict], str]:
        def send_log(msg: str, level: str = "INFO"):
            logger.info(f"[{email}] {msg}")
            if log_cb:
                log_cb(f"[{email}] {msg}", level)

        mode_str = "无头静默模式" if headless else "有头可视模式"
        send_log(f"启动 {mode_str} 隔离会话", "STEP")

        # 1. 获取专属代理或全局动态轮换住宅代理 (只要账户有余额即可持续生成全新日本 IP)
        rotator = ProxyPoolManager.get_instance()
        first_proxy = rotator.get_dynamic_proxy_for_account(proxy)
        
        # 2. 构建重试策略队列：
        # - 尝试 1：分配的动态日本住宅代理 (全新 Session)
        # - 尝试 2：若超时/故障，自动生成另一个全新 Session 的日本住宅代理进行重试
        # - 尝试 3：仅当无代理池时直连备用
        proxy_attempts = []
        if first_proxy:
            proxy_attempts.append(first_proxy)
            retry_proxy = rotator.rotate_proxy_session(first_proxy)
            proxy_attempts.append(retry_proxy)
        else:
            proxy_attempts.append(None)

        for attempt_idx, curr_proxy_str in enumerate(proxy_attempts):
            is_fallback = (attempt_idx > 0)
            pw_proxy = normalize_proxy_for_playwright(curr_proxy_str)

            if pw_proxy:
                send_log(f"挂载动态住宅代理: {pw_proxy.get('server')} (Session 动态轮换第 {attempt_idx+1} 轮)", "STEP")
            else:
                send_log("直连/备用网络（未配置代理）" if not is_fallback else "⚠️ 代理故障，自动切换备用网络重试...", "STEP")

            with sync_playwright() as p:
                launch_args = {
                    "headless": headless,
                    "args": [
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-infobars",
                        "--disable-dev-shm-usage",
                        "--lang=ja-JP"
                    ]
                }
                if pw_proxy:
                    launch_args["proxy"] = pw_proxy
                    
                try:
                    browser = p.chromium.launch(**launch_args)
                except Exception as e:
                    err_msg = f"启动浏览器失败: {str(e)}"
                    send_log(err_msg, "ERROR")
                    if attempt_idx < len(proxy_attempts) - 1:
                        continue
                    return False, None, [], err_msg

                context = browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                    locale="ja-JP",
                    timezone_id="Asia/Tokyo"
                )
                context.add_init_script(RakutenBrowserWorker.STEALTH_JS)

                # 注入已存 Cookie 或 ODID 信任设备指纹
                if initial_cookies and isinstance(initial_cookies, dict):
                    pw_cookies = []
                    for ck_name, ck_val in initial_cookies.items():
                        if ck_name and ck_val:
                            s_name = str(ck_name).strip()
                            s_val = str(ck_val).strip()
                            pw_cookies.append({"name": s_name, "value": s_val, "domain": ".rakuten.co.jp", "path": "/"})
                            pw_cookies.append({"name": s_name, "value": s_val, "domain": "login.account.rakuten.com", "path": "/"})
                            pw_cookies.append({"name": s_name, "value": s_val, "domain": "order.my.rakuten.co.jp", "path": "/"})
                    if pw_cookies:
                        try:
                            context.add_cookies(pw_cookies)
                            send_log(f"已注入已存/信任设备凭据 (含 {list(initial_cookies.keys())})", "INFO")
                        except Exception as ck_err:
                            send_log(f"注入初始凭据失败: {ck_err}", "WARNING")

                page = context.new_page()

                def take_snap(tag: str):
                    try:
                        if not page or page.url in ["about:blank", ""] or ("rakuten.co.jp" not in page.url and "rakuten.com" not in page.url):
                            return
                        clean_name = "".join([c if c.isalnum() else "_" for c in email])
                        snap_file = os.path.join(SCREENSHOTS_DIR, f"{clean_name}_{tag}.png")
                        page.screenshot(path=snap_file)
                        send_log(f"已生成页面快照: {os.path.basename(snap_file)}", "INFO")
                    except Exception:
                        pass

                try:
                    send_log("正在打开乐天购买履历与 SSO 登录网关...", "STEP")
                    try:
                        page.goto(RakutenBrowserWorker.ORDER_URL, wait_until="domcontentloaded", timeout=30000)
                    except Exception as nav_err:
                        err_text = str(nav_err)
                        if ("ERR_EMPTY_RESPONSE" in err_text or "ERR_PROXY" in err_text or "ERR_CONNECTION_RESET" in err_text or "Timeout" in err_text) and attempt_idx < len(proxy_attempts) - 1:
                            browser.close()
                            send_log("⚠️ 动态住宅代理连接抖动，正在自动轮换全新住宅 IP 重试...", "WARNING")
                            continue
                        raise nav_err

                    time.sleep(2.5)

                    # --- 步骤 1: 填入用户名并提交第一步 ---
                    send_log(f"[{email}] 正在定位用户名输入框...")
                    user_input = page.locator('#user_id, input[name="username"], input[type="email"], input[type="text"]').first
                    try:
                        user_input.wait_for(state="visible", timeout=10000)
                    except Exception as input_err:
                        body_txt = page.inner_text("body") if page.locator("body").count() > 0 else ""
                        if "予想以上" in body_txt or "Page not available" in body_txt or "再読み込み" in body_txt:
                            send_log(f"[{email}] ⚠️ 乐天 SSO 组件加载延迟，正在自动重载页面并重试定位...", "WARNING")
                            page.reload(wait_until="domcontentloaded", timeout=20000)
                            time.sleep(3.0)
                            user_input = page.locator('#user_id, input[name="username"], input[type="email"], input[type="text"]').first
                            user_input.wait_for(state="visible", timeout=10000)
                        else:
                            raise input_err

                    user_input.click()
                    user_input.fill(email)
                    time.sleep(0.5)
                    send_log(f"[{email}] 用户名已填入，正在提交第一步(次へ)...")
                    # 乐天 SSO 的 CTA 是 div[role=button]，不能只依赖 Enter。
                    next_btn = page.locator('#cta001, div[role="button"]:has-text("次へ"), button:has-text("次へ")').first
                    try:
                        next_btn.wait_for(state="visible", timeout=5000)
                        next_btn.click()
                    except Exception:
                        user_input.press("Enter")

                    # --- 步骤 2: 智能检测登录模式 (常规密码直通 vs 通行密钥 Passkey 自动降级与硬隔离) ---
                    send_log(f"[{email}] 正在等待密码输入框或通行密钥挑战...")
                    pwd_input = page.locator('input[type="password"]:visible, #password_current:visible, input[name="password"]:visible').first
                    passkey_detected = False
                    
                    # 响应式轮询 (最大 6s，每 200ms 一次)：快速识别密码直通或 Passkey 拦截
                    for _ in range(30):
                        # 1. 常规账号：密码输入框已可见，毫秒级快速放行
                        if pwd_input.count() > 0 and pwd_input.is_visible():
                            break
                        
                        curr_url = page.url.lower()
                        body_txt = page.inner_text("body") if page.locator("body").count() > 0 else ""
                        
                        # 2. 完备 Passkey 初始探测条件 (URL特征 + 页面文本 + 官方次级 seco_* 切换按钮)
                        switch_btn = page.locator('[id^="seco_"]:visible, div[role="button"]:has-text("パスワード"):visible, button:has-text("パスワード"):visible, a:has-text("パスワード"):visible, div[role="button"]:has-text("別の方法"):visible, button:has-text("別の方法"):visible').first
                        has_switch_btn = (switch_btn.count() > 0 and switch_btn.is_visible())
                        
                        if "webauthn" in curr_url or "パスキー" in body_txt or "passkey" in curr_url or has_switch_btn:
                            passkey_detected = True
                            send_log(f"[{email}] 🔑 检测到账号触发通行密钥 (Passkey / WebAuthn)，正在自动执行降级切换...", "WARNING")
                            take_snap("passkey_detected")
                            
                            # 执行降级点击
                            try:
                                if has_switch_btn:
                                    switch_btn.click()
                                    send_log(f"[{email}] 👆 已点击【密码登录】切换按钮，等待密码框渲染...", "INFO")
                                else:
                                    # 兜底 JS 执行模拟点击任意次级切换按钮
                                    page.evaluate('''() => {
                                        const el = document.querySelector('[id^="seco_"]') || 
                                                   Array.from(document.querySelectorAll('div[role="button"], button, a')).find(b => b.textContent && (b.textContent.includes('パスワード') || b.textContent.includes('別の方法')));
                                        if (el) el.click();
                                    }''')
                                    send_log(f"[{email}] 👆 已通过脚本派发次级按钮切换事件...", "INFO")
                            except Exception as sw_err:
                                send_log(f"[{email}] 点击切换密码按钮异常: {sw_err}", "WARNING")
                            
                            # 等待切换接口网络响应或路由跳入 #/sign_in/password
                            time.sleep(1.5)
                            break
                        
                        time.sleep(0.2)

                    try:
                        # 确保密码框渲染并获得焦点
                        pwd_input = page.locator('input[type="password"]:visible, #password_current:visible, input[name="password"]:visible').first
                        pwd_input.wait_for(state="visible", timeout=6000)
                        pwd_input.click()
                        pwd_input.fill(password)
                        time.sleep(0.5)
                        send_log(f"[{email}] 密码已填入，正在提交登录鉴权...")
                        
                        # 优先匹配当前真正可见的提交按钮 (#cta011:visible 优先于 #cta001:visible)
                        login_btn = page.locator('#cta011:visible, #cta001:visible, div[role="button"]:has-text("ログイン"):visible, button:has-text("ログイン"):visible, button[type="submit"]:visible').first
                        try:
                            login_btn.wait_for(state="visible", timeout=4000)
                            login_btn.click()
                        except Exception:
                            pwd_input.press("Enter")
                        page.wait_for_load_state("domcontentloaded", timeout=12000)
                        time.sleep(3.5)
                    except Exception as pwd_err:
                        # Fail-Closed 严谨隔离：若曾检测到 Passkey 但最终未能进入密码流程，判定为强制硬件 Passkey 账号
                        curr_url = page.url.lower()
                        body_txt = page.inner_text("body") if page.locator("body").count() > 0 else ""
                        if passkey_detected or "webauthn" in curr_url or "パスキー" in body_txt or "passkey" in curr_url:
                            take_snap("passkey_locked")
                            browser.close()
                            err = "⚠️ 触发通行密钥锁定 (强制硬件Passkey，无可用密码通道)"
                            send_log(err, "WARNING")
                            return False, None, [], err
                        send_log(f"[{email}] ⚠️ 密码框未出现或加载超时: {pwd_err}", "WARNING")

                    # --- 步骤 3: 严格状态门禁判定 (Strict Verification Gate & Resilient Redirect Polling) ---
                    send_log(f"[{email}] 正在等待乐天鉴权重定向与登录态确认 (最多等待 12s)...")
                    is_truly_logged_in = False
                    
                    for poll_idx in range(12):
                        time.sleep(1.0)
                        current_url = page.url
                        body_text = page.inner_text("body") if page.locator("body").count() > 0 else ""

                        # 1. 密码错误即时判定
                        if "正しくありません" in body_text or "一致しません" in body_text:
                            take_snap("wrong_password")
                            browser.close()
                            err = "密码错误 (ユーザIDまたはパスワードが正しくありません)"
                            send_log(err, "ERROR")
                            return False, None, [], err

                        # 2. 2FA 邮箱/短信验证码判定
                        if "ワンタイムパスワード" in body_text or "確認コード" in body_text or "認証コード" in body_text or "2段階認証" in body_text:
                            take_snap("otp_challenge")
                            browser.close()
                            err = "⚠️ 触发 2FA 邮箱/手机验证码挑战"
                            send_log(err, "WARNING")
                            return False, None, [], err

                        # 3. Akamai 人机滑块判定
                        if "ロボット" in body_text or "challenge" in current_url.lower() or page.locator('div[id*="challenge"], div[class*="captcha"], iframe[src*="challenge"]').count() > 0:
                            take_snap("captcha_challenge")
                            browser.close()
                            err = "⚠️ 触发 Akamai 人机验证/滑块挑战"
                            send_log(err, "WARNING")
                            return False, None, [], err

                        # 4. 真正登录成功判定 (进入 order.my.rakuten.co.jp 或包含购买记录特征)
                        if ("order.my.rakuten.co.jp" in current_url and "login" not in current_url) or "購入履歴" in body_text or "ログアウト" in body_text:
                            is_truly_logged_in = True
                            break

                    if is_truly_logged_in:
                        cookies = context.cookies()
                        cookie_path = os.path.join(COOKIES_DIR, f"{email}.json")
                        with open(cookie_path, "w", encoding="utf-8") as f:
                            json.dump(cookies, f, indent=2, ensure_ascii=False)
                        take_snap("login_success")

                        # 截取乐天内部购买履历页面
                        try:
                            if "order-list" not in page.url:
                                page.goto("https://order.my.rakuten.co.jp/purchase-history/order-list", wait_until="domcontentloaded", timeout=15000)
                                time.sleep(2)
                            take_snap("internal_orders")
                        except Exception:
                            pass

                        in_browser_orders = []
                        try:
                            # 1. 尝试全量年度同源 API 拉取
                            api_res = page.evaluate("""async () => {
                                try {
                                    const r = await fetch('/purchasehistoryapi/orderlist');
                                    return await r.json();
                                } catch(e) {
                                    return null;
                                }
                            }""")
                            if api_res and isinstance(api_res, dict):
                                raw_list = api_res.get("orderList", [])
                                api_obj = RakutenOrderAPI(cookies={})
                                in_browser_orders = [api_obj._normalize_order(o) for o in raw_list if o]
                        except Exception:
                            pass

                        # 2. 如果同源 API 为空，直接使用页面现场 DOM 正则/选择器深度提取
                        if not in_browser_orders:
                            try:
                                dom_orders = page.evaluate("""() => {
                                    const list = [];
                                    const bodyText = document.body.innerText;
                                    const orderBlocks = bodyText.split(/注文日[：:]/);
                                    
                                    for (let i = 1; i < orderBlocks.length; i++) {
                                        const block = orderBlocks[i];
                                        const dateMatch = block.match(/^([0-9]{4}[/-][0-9]{2}[/-][0-9]{2}[^\s\n]*)/);
                                        const orderIdMatch = block.match(/注文番号[：:]\s*([0-9\-]+)/);
                                        const priceMatch = block.match(/([0-9,]+)\s*円/);
                                        
                                        if (orderIdMatch) {
                                            const orderDate = dateMatch ? dateMatch[1] : '';
                                            const orderId = orderIdMatch[1];
                                            const priceStr = priceMatch ? priceMatch[1].replace(/,/g, '') : '0';
                                            
                                            // 提取店铺与商品简述
                                            const lines = block.split('\n').map(l => l.trim()).filter(l => l.length > 0);
                                            const shopName = lines.length > 0 ? lines[0] : '乐天店铺';
                                            const itemName = lines.length > 2 ? lines[2] : '商品信息';

                                            list.push({
                                                order_id: orderId,
                                                order_date: orderDate,
                                                shop_name: shopName,
                                                total_price: parseInt(priceStr) || 0,
                                                shipping_status: '已完成',
                                                tracking_number: '',
                                                items_count: 1,
                                                items_summary: itemName,
                                                items: [{ name: itemName, price: priceStr, units: 1, image: '' }]
                                            });
                                        }
                                    }
                                    return list;
                                }""")
                                if dom_orders:
                                    in_browser_orders = dom_orders
                                    send_log(f"现场 DOM 深度提取到 {len(in_browser_orders)} 笔真实订单！", "SUCCESS")
                            except Exception as dom_err:
                                send_log(f"DOM 提取异常: {dom_err}", "WARNING")

                        browser.close()
                        success_msg = f"登录成功！捕获 {len(cookies)} 个会话 Cookie，获取 {len(in_browser_orders)} 条订单"
                        send_log(success_msg, "SUCCESS")
                        return True, cookies, in_browser_orders, success_msg

                    take_snap("login_failed")
                    browser.close()
                    fail_msg = f"登录未完成 (当前停留: {current_url[:60]}...)"
                    send_log(fail_msg, "ERROR")
                    if attempt_idx < len(proxy_attempts) - 1:
                        continue
                    return False, None, [], fail_msg

                except Exception as e:
                    take_snap("error")
                    browser.close()
                    err = f"无头浏览器交互异常: {str(e)}"
                    send_log(err, "ERROR")
                    if attempt_idx < len(proxy_attempts) - 1:
                        continue
                    return False, None, [], err

        return False, None, [], "所有连接尝试均失败"


class AccountManager:
    """
    多账号与订单数据库调度管理器
    """
    def __init__(self):
        self.accounts: List[Dict[str, Any]] = []
        self.orders_cache: Dict[str, List[Dict[str, Any]]] = {}
        self.history_vault: Dict[str, Dict[str, Any]] = {}
        self.import_batches: List[Dict[str, Any]] = []
        self._lock = threading.RLock()
        self._last_save = 0.0
        self._dirty = False
        self.load_data()
        
        # 启动后台脏数据周期性落盘线程 (防高并发写锁风暴)
        def _bg_flusher():
            while True:
                time.sleep(3.0)
                if getattr(self, "_dirty", False) and (time.time() - getattr(self, "_last_save", 0.0) >= 3.0):
                    try:
                        self.save_data(force=True)
                    except Exception:
                        pass
        t = threading.Thread(target=_bg_flusher, daemon=True)
        t.start()

    def load_data(self):
        with getattr(self, "_lock", threading.RLock()):
            if os.path.exists(ACCOUNTS_FILE):
                try:
                    with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                        self.accounts = json.load(f)
                except Exception as e:
                    logger.error(f"加载账号数据失败: {e}")
                    self.accounts = []
            else:
                self.accounts = []

            if os.path.exists(ORDERS_FILE):
                try:
                    with open(ORDERS_FILE, "r", encoding="utf-8") as f:
                        self.orders_cache = json.load(f)
                except Exception as e:
                    logger.error(f"加载订单缓存失败: {e}")
                    self.orders_cache = {}
            else:
                self.orders_cache = {}

            if os.path.exists(HISTORY_VAULT_FILE):
                try:
                    with open(HISTORY_VAULT_FILE, "r", encoding="utf-8") as f:
                        self.history_vault = json.load(f)
                except Exception as e:
                    logger.error(f"加载历史已测库失败: {e}")
                    self.history_vault = {}
            else:
                self.history_vault = {}

            if os.path.exists(IMPORT_BATCHES_FILE):
                try:
                    with open(IMPORT_BATCHES_FILE, "r", encoding="utf-8") as f:
                        self.import_batches = json.load(f)
                except Exception as e:
                    logger.error(f"加载导入批次记录失败: {e}")
                    self.import_batches = []
            else:
                self.import_batches = []

            # 智能补全现有账号的默认批次记录（若不存在批次）
            if not self.import_batches and self.accounts:
                initial_batch = {
                    "batch_id": "batch_initial",
                    "import_time": get_cst_now_str(),
                    "count": len(self.accounts),
                    "emails": [a["email"] for a in self.accounts],
                    "note": f"历史全量账号归档批次 ({len(self.accounts)} 户)"
                }
                for a in self.accounts:
                    if not a.get("import_batch_id"):
                        a["import_batch_id"] = "batch_initial"
                        a["imported_at"] = initial_batch["import_time"]
                self.import_batches.append(initial_batch)
                self.save_import_batches()

            # 自动全库扫描并提取/修复历史账号手机号与纯净地址
            self.repair_and_extract_phones_for_all_accounts()


    def repair_and_extract_phones_for_all_accounts(self) -> int:
        """
        自动全库扫描并修复历史已测账号的手机号 (Phone Number) 与纯净地址
        """
        count = 0
        with getattr(self, "_lock", threading.RLock()):
            for acc in self.accounts:
                changed = False
                phone = acc.get("phone", "")
                addr = acc.get("address", "")
                extra = acc.get("extra_info", "")
                msg = acc.get("message", "")
                
                # 1. 尝试从 address/extra_info/message 中提取合法日本电话
                if not phone:
                    for source in [addr, extra, msg]:
                        if source:
                            m = JAPANESE_PHONE_REGEX.search(str(source))
                            if m:
                                phone = m.group(0).replace(" ", "-")
                                acc["phone"] = phone
                                changed = True
                                break
                                
                # 2. 如果 extra_info 为空或只有泛化卡名，回填手机号
                if phone and (not acc.get("extra_info") or "一括払い" in str(acc.get("extra_info")) or "クレジットカード" in str(acc.get("extra_info"))):
                    acc["extra_info"] = phone
                    changed = True

                # 3. 清理 address 中混入的订单号或粘连电话，非合法日文地址自动清空
                if addr:
                    clean_addr = clean_and_validate_address(addr)
                    if phone and phone in clean_addr:
                        clean_addr = clean_addr.replace(phone, "").strip()
                    if clean_addr != addr:
                        acc["address"] = clean_addr
                        changed = True

                if changed:
                    count += 1
            if count > 0:
                self.save_data()
        return count

    def save_data(self, force: bool = False):
        now = time.time()
        self._dirty = True
        if not force and hasattr(self, "_last_save") and (now - self._last_save < 4.0):
            return
        self._last_save = now
        self._dirty = False

        with getattr(self, "_lock", threading.RLock()):
            tmp_acc = f"{ACCOUNTS_FILE}.tmp.{os.getpid()}.{random.randint(1000, 9999)}"
            tmp_ord = f"{ORDERS_FILE}.tmp.{os.getpid()}.{random.randint(1000, 9999)}"
            accs_copy = list(self.accounts)
            ords_copy = dict(self.orders_cache)
            try:
                with open(tmp_acc, "w", encoding="utf-8") as f:
                    json.dump(accs_copy, f, ensure_ascii=False)
                os.replace(tmp_acc, ACCOUNTS_FILE)
            except Exception as e:
                logger.error(f"原子保存账号数据失败: {e}")
                if os.path.exists(tmp_acc):
                    try: os.remove(tmp_acc)
                    except Exception: pass

            try:
                with open(tmp_ord, "w", encoding="utf-8") as f:
                    json.dump(ords_copy, f, ensure_ascii=False)
                os.replace(tmp_ord, ORDERS_FILE)
            except Exception as e:
                logger.error(f"原子保存订单缓存失败: {e}")
                if os.path.exists(tmp_ord):
                    try: os.remove(tmp_ord)
                    except Exception: pass

    def save_history_vault(self):
        with getattr(self, "_lock", threading.RLock()):
            tmp_vault = f"{HISTORY_VAULT_FILE}.tmp.{os.getpid()}.{random.randint(1000, 9999)}"
            try:
                with open(tmp_vault, "w", encoding="utf-8") as f:
                    json.dump(self.history_vault, f, indent=2, ensure_ascii=False)
                os.replace(tmp_vault, HISTORY_VAULT_FILE)
            except Exception as e:
                logger.error(f"原子保存历史归档失败: {e}")
                if os.path.exists(tmp_vault):
                    try: os.remove(tmp_vault)
                    except Exception: pass

    def save_import_batches(self):
        with getattr(self, "_lock", threading.RLock()):
            tmp_batches = f"{IMPORT_BATCHES_FILE}.tmp.{os.getpid()}.{random.randint(1000, 9999)}"
            try:
                with open(tmp_batches, "w", encoding="utf-8") as f:
                    json.dump(self.import_batches, f, indent=2, ensure_ascii=False)
                os.replace(tmp_batches, IMPORT_BATCHES_FILE)
            except Exception as e:
                logger.error(f"原子保存导入批次失败: {e}")
                if os.path.exists(tmp_batches):
                    try: os.remove(tmp_batches)
                    except Exception: pass

    def get_account(self, email: str) -> Optional[Dict[str, Any]]:
        email = email.strip().lower()
        with getattr(self, "_lock", threading.RLock()):
            for acc in self.accounts:
                if acc["email"].lower() == email:
                    return dict(acc)
        return None

    def add_or_update_account(self, email: str, password: str, proxy: str = "", note: str = "", save: bool = True, batch_id: str = "", import_time: str = "", cookie_data: Optional[Dict[str, Any]] = None):
        email = email.strip()
        with getattr(self, "_lock", threading.RLock()):
            for acc in self.accounts:
                if acc["email"].lower() == email.lower():
                    acc["password"] = password.strip()
                    if proxy:
                        acc["proxy"] = proxy.strip()
                    if note:
                        acc["message"] = note.strip()
                    if batch_id:
                        acc["import_batch_id"] = batch_id
                    if import_time:
                        acc["imported_at"] = import_time
                    if cookie_data and isinstance(cookie_data, dict):
                        acc["cookie_data"] = cookie_data
                        # 若含有 OSSO / OSAT，自动写入持久化 cookie 文件
                        if "OSSO" in cookie_data or "OSAT" in cookie_data:
                            cookie_file = os.path.join(COOKIES_DIR, f"{email}.json")
                            try:
                                with open(cookie_file, "w", encoding="utf-8") as cf:
                                    json.dump(cookie_data, cf, indent=2, ensure_ascii=False)
                            except Exception:
                                pass
                    if save:
                        self.save_data()
                    return acc
                    
            new_acc = {
                "email": email,
                "password": password.strip(),
                "proxy": proxy.strip(),
                "status": "未检测" if not note else "导入待测",
                "order_count": 0,
                "total_spent": 0,
                "last_check": "",
                "message": note.strip() if note else "",
                "import_batch_id": batch_id or "",
                "imported_at": import_time or get_cst_now_str(),
                "cookie_data": cookie_data or {}
            }
            if cookie_data and isinstance(cookie_data, dict) and ("OSSO" in cookie_data or "OSAT" in cookie_data):
                cookie_file = os.path.join(COOKIES_DIR, f"{email}.json")
                try:
                    with open(cookie_file, "w", encoding="utf-8") as cf:
                        json.dump(cookie_data, cf, indent=2, ensure_ascii=False)
                except Exception:
                    pass

            self.accounts.append(new_acc)
            if save:
                self.save_data()
            return new_acc

    @staticmethod
    def _is_proxy(s: str) -> bool:
        s = s.strip()
        if not s:
            return False
        if any(s.lower().startswith(proto) for proto in ["http://", "https://", "socks5://", "socks4://", "socks5h://"]):
            return True
        import re
        if re.search(r'[\u4e00-\u9fa5]', s):
            return False
        parts = s.split(":")
        if len(parts) == 4:
            host, port, user, pwd = parts
            if port.isdigit() and 1 <= int(port) <= 65535:
                return True
        if len(parts) == 2:
            host, port = parts
            if port.isdigit() and 1 <= int(port) <= 65535:
                if re.match(r"^[a-zA-Z0-9.\-_]+$", host) and ('.' in host or host.lower() == 'localhost'):
                    return True
        if re.match(r"^[^:@\s]+:[^:@\s]+@[a-zA-Z0-9.\-_]+:\d{1,5}$", s):
            port_str = s.split(":")[-1]
            if port_str.isdigit() and 1 <= int(port_str) <= 65535:
                return True
        return False

    def batch_import(self, text: str, default_proxy: str = "", proxy_list_text: str = "", batch_note: str = "") -> Tuple[int, Dict[str, Any]]:
        lines = text.strip().split("\n")
        proxy_pool = [p.strip() for p in proxy_list_text.strip().split("\n") if p.strip()]
        proxy_idx = 0
        count = 0
        now_str = get_cst_now_str()
        batch_id = f"batch_{get_cst_now_str('%Y%m%d_%H%M%S')}"
        imported_emails = []

        with getattr(self, "_lock", threading.RLock()):
            for line in lines:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = []
                for sep in ["----", "---", "--", "\t", ",", "|"]:
                    if sep in line:
                        parts = [p.strip() for p in line.split(sep)]
                        break
                if not parts:
                    if ":" in line and not self._is_proxy(line):
                        subparts = line.split(":")
                        if len(subparts) >= 2 and "@" in subparts[0]:
                            parts = [p.strip() for p in subparts]
                    if not parts:
                        parts = line.strip().split()

                if len(parts) >= 2:
                    email = parts[0].strip()
                    pwd = parts[1].strip()
                    
                    if email.lower() in ["账号", "邮箱", "email", "account", "user", "用户名"]:
                        continue
                    if not email or not pwd:
                        continue
                    if "@" not in email and len(parts) >= 3 and "@" in parts[1]:
                        email = parts[1].strip()
                        pwd = parts[2].strip()
                        parts = [email, pwd] + parts[3:]

                    proxy = ""
                    note_list = []
                    cookie_data = {}

                    for extra in parts[2:]:
                        extra_clean = extra.strip()
                        if not extra_clean:
                            continue
                        
                        # 识别是否包含序列化的 Cookie / 凭据字典（如 {'ODID': '...', 'OSSO': '...'}）
                        if (extra_clean.startswith("{") and extra_clean.endswith("}")) or ("'ODID'" in extra_clean or '"ODID"' in extra_clean or "'OSSO'" in extra_clean or '"OSSO"' in extra_clean):
                            try:
                                import ast
                                parsed_c = ast.literal_eval(extra_clean)
                                if isinstance(parsed_c, dict):
                                    cookie_data.update(parsed_c)
                                    continue
                            except Exception:
                                try:
                                    parsed_c = json.loads(extra_clean)
                                    if isinstance(parsed_c, dict):
                                        cookie_data.update(parsed_c)
                                        continue
                                except Exception:
                                    pass

                        if self._is_proxy(extra_clean) and not proxy:
                            proxy = extra_clean
                        else:
                            note_list.append(extra_clean)

                    if not proxy:
                        if proxy_pool:
                            proxy = proxy_pool[proxy_idx % len(proxy_pool)]
                            proxy_idx += 1
                        elif default_proxy:
                            proxy = default_proxy.strip()
                        else:
                            rotator = ProxyPoolManager.get_instance()
                            proxy = rotator.get_dynamic_proxy_for_account() or ""

                    note = " | ".join(note_list)
                    em_lower = email.lower()
                    if em_lower in self.history_vault:
                        hist_info = self.history_vault[em_lower]
                        last_st = hist_info.get("last_status", "已测")
                        note = (f"[历史已测: {last_st}] " + note).strip()

                    self.add_or_update_account(email, pwd, proxy, note, save=False, batch_id=batch_id, import_time=now_str, cookie_data=cookie_data)
                    imported_emails.append(email)
                    count += 1

            batch_info = {
                "batch_id": batch_id,
                "import_time": now_str,
                "count": len(imported_emails),
                "emails": imported_emails,
                "note": batch_note or f"第 {len(self.import_batches) + 1} 批导入 ({len(imported_emails)} 户)"
            }
            if count > 0:
                self.import_batches.append(batch_info)
                self.save_import_batches()
                self.save_data()

        return count, batch_info

    def batch_import_from_file(self, file_content: bytes, filename: str, default_proxy: str = "", proxy_list_text: str = "", batch_note: str = "") -> Tuple[int, Dict[str, Any]]:
        """支持直接从 Excel (.xlsx, .xls) 或 CSV (.csv) 文件批量导入"""
        filename_lower = filename.lower()
        text_lines = []
        # 存储从 CSMS 16 列 Excel 解析出的结构化字段（假名、地址等），key=email.lower()
        _csms_profile_map: Dict[str, Dict[str, str]] = {}
        
        if filename_lower.endswith(".xlsx") or filename_lower.endswith(".xls"):
            import openpyxl
            import io
            wb = openpyxl.load_workbook(io.BytesIO(file_content), data_only=True)
            sheet_names = wb.sheetnames
            target_sheet = wb["乐天导出导入"] if "乐天导出导入" in sheet_names else wb.active
            
            # 检测是否为 CSMS 16 列标准格式（通过表头行判断）
            is_csms_16col = False
            header_row_vals = []
            for row in target_sheet.iter_rows(min_row=1, max_row=1, values_only=True):
                header_row_vals = [str(c).strip() if c else "" for c in row]
            if len(header_row_vals) >= 6 and "假名" in header_row_vals[4] and "假名" in header_row_vals[5]:
                is_csms_16col = True
            elif len(header_row_vals) >= 6 and header_row_vals[0] in ["账号", "邮箱", "email", "Email", "Account"] and header_row_vals[2] in ["姓", "姓氏"]:
                is_csms_16col = True
            
            for row in target_sheet.iter_rows(values_only=True):
                if not row or not any(row):
                    continue
                row_strs = [str(c).strip() if c is not None else "" for c in row]
                if not row_strs[0]:
                    continue
                if row_strs[0].lower() in ["账号", "邮箱", "email", "account", "user", "用户名"]:
                    continue
                if "@" not in row_strs[0] and len(row_strs) > 1 and "@" in row_strs[1]:
                    email = row_strs[1]
                    pwd = row_strs[2] if len(row_strs) > 2 else ""
                    profile_offset = 3  # 结构化字段从第 3 列开始
                else:
                    email = row_strs[0]
                    pwd = row_strs[1] if len(row_strs) > 1 else ""
                    profile_offset = 2  # 结构化字段从第 2 列开始
                    
                if email and pwd:
                    # 如果是 CSMS 16 列标准格式，提取姓名、假名、其他信息、生日、性别、地址
                    if is_csms_16col and len(row_strs) >= profile_offset + 4:
                        profile = {}
                        field_mapping = [
                            ("last_name", profile_offset),
                            ("first_name", profile_offset + 1),
                            ("last_name_kana", profile_offset + 2),
                            ("first_name_kana", profile_offset + 3),
                            ("extra_info", profile_offset + 4),
                            ("birth_date", profile_offset + 5),
                            ("gender", profile_offset + 6),
                            ("address", profile_offset + 7),
                        ]
                        for field_name, col_idx in field_mapping:
                            if col_idx < len(row_strs) and row_strs[col_idx]:
                                profile[field_name] = row_strs[col_idx]
                        if profile:
                            _csms_profile_map[email.lower()] = profile
                    
                    # 仍然生成 email----pwd 文本行给 batch_import 处理
                    extras = []
                    # 对于 CSMS 16 列，不把结构化字段塞进 extras（它们已经通过 profile_map 处理）
                    if not is_csms_16col:
                        extras = [e for e in row_strs[profile_offset:] if e]
                    line_parts = [email, pwd] + extras
                    text_lines.append("----".join(line_parts))
                    
        elif filename_lower.endswith(".csv"):
            import io
            import csv
            content_str = None
            for enc in ["utf-8-sig", "utf-8", "gbk", "shift_jis", "cp932"]:
                try:
                    content_str = file_content.decode(enc)
                    break
                except Exception:
                    continue
            if not content_str:
                content_str = file_content.decode("utf-8", errors="ignore")
                
            reader = csv.reader(io.StringIO(content_str))
            for row in reader:
                if not row or not any(row):
                    continue
                row_strs = [str(c).strip() for c in row]
                if not row_strs[0] or row_strs[0].lower() in ["账号", "邮箱", "email", "account"]:
                    continue
                if len(row_strs) >= 2:
                    text_lines.append("----".join(row_strs))
        else:
            content_str = file_content.decode("utf-8", errors="ignore")
            text_lines = content_str.splitlines()
            
        combined_text = "\n".join(text_lines)
        note = batch_note or f"Excel/文件导入: {filename} ({len(text_lines)} 行)"
        count, batch_info = self.batch_import(combined_text, default_proxy=default_proxy, proxy_list_text=proxy_list_text, batch_note=note)
        
        # 将 CSMS 16 列解析出的结构化字段（假名、地址等）回写到对应账号对象
        if _csms_profile_map:
            with getattr(self, "_lock", threading.RLock()):
                for acc in self.accounts:
                    em_lower = acc["email"].lower()
                    if em_lower in _csms_profile_map:
                        profile = _csms_profile_map[em_lower]
                        for field_name, value in profile.items():
                            # 只在字段为空时写入，避免覆盖已有的真实数据
                            if not acc.get(field_name):
                                acc[field_name] = value
                self.save_data()
        
        return count, batch_info

    def get_import_batches_summary(self) -> List[Dict[str, Any]]:
        """获取所有导入批次的结构化统计（含当前状态分布）"""
        with getattr(self, "_lock", threading.RLock()):
            acc_map = {a["email"].lower(): a for a in self.accounts}
            summaries = []
            for idx, b in enumerate(self.import_batches):
                b_emails = [e.lower() for e in b.get("emails", [])]
                matched_accs = [acc_map[e] for e in b_emails if e in acc_map]
                
                active_cnt = sum(1 for a in matched_accs if a.get("status") == "正常活跃")
                wrong_cnt = sum(1 for a in matched_accs if a.get("status") == "密码错误")
                failed_cnt = sum(1 for a in matched_accs if a.get("status") in ["登录失败", "异常", "需滑块验证", "需2FA验证码"])
                pending_cnt = sum(1 for a in matched_accs if a.get("status") in ["未检测", "导入待测", "异常待重试", "代理超时", None, ""])
                total_spent = sum(a.get("total_spent", 0) for a in matched_accs)
                total_orders = sum(a.get("order_count", 0) for a in matched_accs)

                summaries.append({
                    "batch_id": b.get("batch_id"),
                    "import_time": b.get("import_time"),
                    "count": b.get("count", len(b_emails)),
                    "current_in_workspace": len(matched_accs),
                    "active_count": active_cnt,
                    "wrong_password_count": wrong_cnt,
                    "failed_count": failed_cnt,
                    "pending_count": pending_cnt,
                    "total_spent_yen": total_spent,
                    "total_orders": total_orders,
                    "note": b.get("note", ""),
                    "is_last_batch": (idx == len(self.import_batches) - 1)
                })
            return summaries

    def get_last_import_batch(self) -> Optional[Dict[str, Any]]:
        with getattr(self, "_lock", threading.RLock()):
            if self.import_batches:
                return self.import_batches[-1]
            return None

    def get_accounts_by_scope(self, scope: str = "all", batch_id: Optional[str] = None, emails: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        with getattr(self, "_lock", threading.RLock()):
            if scope == "last_batch":
                last_b = self.get_last_import_batch()
                if last_b:
                    b_emails = set(e.lower() for e in last_b.get("emails", []))
                    return [a for a in self.accounts if a["email"].lower() in b_emails]
                return list(self.accounts)
            elif scope == "batch" and batch_id:
                matched_b = next((b for b in self.import_batches if b.get("batch_id") == batch_id), None)
                if matched_b:
                    b_emails = set(e.lower() for e in matched_b.get("emails", []))
                    return [a for a in self.accounts if a["email"].lower() in b_emails]
                return [a for a in self.accounts if a.get("import_batch_id") == batch_id]
            elif scope == "since_batch" and batch_id:
                idx = next((i for i, b in enumerate(self.import_batches) if b.get("batch_id") == batch_id), -1)
                if idx != -1:
                    target_batches = self.import_batches[idx:]
                    all_target_emails = set()
                    for b in target_batches:
                        for e in b.get("emails", []):
                            all_target_emails.add(e.lower())
                    return [a for a in self.accounts if a["email"].lower() in all_target_emails]
                return list(self.accounts)
            elif scope == "selected" and emails:
                target_set = set(e.lower() for e in emails)
                return [a for a in self.accounts if a["email"].lower() in target_set]
            return list(self.accounts)
    def assign_global_proxies_to_all_empty(self) -> int:
        """为所有未配置代理的账号一键分配全局动态轮换住宅代理"""
        rotator = ProxyPoolManager.get_instance()
        count = 0
        for acc in self.accounts:
            if not acc.get("proxy"):
                p = rotator.get_dynamic_proxy_for_account()
                if p:
                    acc["proxy"] = p
                    count += 1
        if count > 0:
            self.save_data()
        return count

    def assign_proxies(self, proxy_list_text: str, scope: str = "all", selected_emails: Optional[List[str]] = None) -> int:
        proxy_pool = [p.strip() for p in proxy_list_text.strip().split("\n") if p.strip()]
        if not proxy_pool:
            return 0

        target_accs = []
        if scope == "selected" and selected_emails:
            sel_set = {e.lower() for e in selected_emails}
            target_accs = [a for a in self.accounts if a["email"].lower() in sel_set]
        elif scope == "no_proxy":
            target_accs = [a for a in self.accounts if not a.get("proxy") or a.get("proxy") == "直连"]
        elif scope == "unchecked":
            target_accs = [a for a in self.accounts if a.get("status") in ["未检测", "导入待测"]]
        else:
            target_accs = self.accounts

        if not target_accs:
            return 0

        for idx, acc in enumerate(target_accs):
            acc["proxy"] = proxy_pool[idx % len(proxy_pool)]

        self.save_data()
        return len(target_accs)

    def delete_account(self, email: str):
        self.accounts = [a for a in self.accounts if a["email"].lower() != email.lower()]
        if email in self.orders_cache:
            del self.orders_cache[email]
        cookie_path = os.path.join(COOKIES_DIR, f"{email}.json")
        if os.path.exists(cookie_path):
            try:
                os.remove(cookie_path)
            except Exception:
                pass
        self.save_data()

    def delete_batch(self, emails: List[str]) -> int:
        email_set = {e.strip().lower() for e in emails if e.strip()}
        orig_count = len(self.accounts)
        self.accounts = [a for a in self.accounts if a["email"].lower() not in email_set]
        for e in email_set:
            if e in self.orders_cache:
                del self.orders_cache[e]
            cookie_path = os.path.join(COOKIES_DIR, f"{e}.json")
            if os.path.exists(cookie_path):
                try:
                    os.remove(cookie_path)
                except Exception:
                    pass
        self.save_data()
        return orig_count - len(self.accounts)

    def archive_accounts(self, accounts_to_archive: List[Dict[str, Any]]) -> int:
        """
        将账号全量归档落盘至历史已测库，永久记住所有邮箱/ID、最终状态与历史订单
        """
        with getattr(self, "_lock", threading.RLock()):
            count = 0
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for a in accounts_to_archive:
                em = a.get("email", "").strip().lower()
                if not em:
                    continue
                existing = self.history_vault.get(em, {})
                self.history_vault[em] = {
                    "email": a["email"],
                    "password": a.get("password", existing.get("password", "")),
                    "last_status": a.get("status", existing.get("last_status", "未检测")),
                    "last_message": a.get("message", existing.get("last_message", "")),
                    "order_count": a.get("order_count", existing.get("order_count", 0)),
                    "total_spent": a.get("total_spent", existing.get("total_spent", 0)),
                    "orders": self.orders_cache.get(a["email"], existing.get("orders", [])),
                    "archived_at": now_str,
                    "tested_history_count": existing.get("tested_history_count", 0) + (1 if a.get("status") not in ["未检测", "导入待测"] else 0)
                }
                count += 1
            self.save_history_vault()
            return count

    def clear_accounts(self, scope: str = "all") -> int:
        orig_count = len(self.accounts)
        # 1. 无论何种清理，先将全量现有账号归档落盘至历史已测库，永久记住所有邮箱/ID
        self.archive_accounts(self.accounts)
        
        # 2. 清理工作区活跃列表
        if scope == "all":
            self.accounts = []
            self.orders_cache = {}
        elif scope == "tested":
            self.accounts = [a for a in self.accounts if a.get("status") in ["未检测", "导入待测"]]
        elif scope == "failed":
            self.accounts = [a for a in self.accounts if a.get("status") not in ["登录失败", "密码错误", "异常"]]
        elif scope == "wrong_password":
            self.accounts = [a for a in self.accounts if a.get("status") != "密码错误"]
            
        self.save_data()
        return orig_count - len(self.accounts)

    def move_to_tail(self, email: str):
        """将遭遇临时网络/超时异常的账号物理移动到队列末尾，并换用全新住宅代理以待最后重试"""
        with getattr(self, "_lock", threading.RLock()):
            idx = next((i for i, a in enumerate(self.accounts) if a["email"].lower() == email.lower()), -1)
            if idx != -1:
                acc = self.accounts.pop(idx)
                rotator = ProxyPoolManager.get_instance()
                new_p = rotator.get_dynamic_proxy_for_account()
                if new_p:
                    acc["proxy"] = new_p
                self.accounts.append(acc)
                self.save_data()

    def process_account(self, email: str, force_browser_login: bool = False, headless: bool = True, log_cb: Optional[Callable[[str, str], None]] = None) -> Tuple[bool, str]:
        def send_log(msg: str, level: str = "INFO"):
            if log_cb:
                log_cb(msg, level)

        email_key = email.strip().lower()
        with getattr(self, "_lock", threading.RLock()):
            if not hasattr(self, "_inflight_emails"):
                self._inflight_emails = set()
            if email_key in self._inflight_emails:
                send_log(f"[{email}] ⚠️ 账号正在被其他后台 Worker 处理中，已自动阻止并发重叠执行", "WARNING")
                return False, "账号已在处理中，跳过并发重叠"
            self._inflight_emails.add(email_key)

        try:
            return self._process_account_impl(email, force_browser_login, headless, log_cb)
        finally:
            with getattr(self, "_lock", threading.RLock()):
                if hasattr(self, "_inflight_emails"):
                    self._inflight_emails.discard(email_key)

    def _process_account_impl(self, email: str, force_browser_login: bool = False, headless: bool = True, log_cb: Optional[Callable[[str, str], None]] = None) -> Tuple[bool, str]:
        def send_log(msg: str, level: str = "INFO"):
            if log_cb:
                log_cb(msg, level)

        acc = next((a for a in self.accounts if a["email"].lower() == email.lower()), None)
        if not acc:
            return False, "账号不存在"

        pwd = acc.get("password", "")
        proxy = acc.get("proxy", "")
        cookie_path = os.path.join(COOKIES_DIR, f"{email}.json")

        orders = []
        is_success = False
        msg = ""

        # Step 1: 尝试本地 Cookie 或导入的 OSSO/OSAT 凭据协议直通
        cookies = None
        acc_cookie_data = acc.get("cookie_data")
        if (os.path.exists(cookie_path) or (acc_cookie_data and isinstance(acc_cookie_data, dict) and ("OSSO" in acc_cookie_data or "OSAT" in acc_cookie_data))) and not force_browser_login:
            send_log(f"[{email}] 发现可用 Cookie 凭据，优先执行纯协议极速查单...", "INFO")
            if os.path.exists(cookie_path):
                try:
                    with open(cookie_path, "r", encoding="utf-8") as cf:
                        cookies = json.load(cf)
                except Exception:
                    cookies = cookie_path
            elif acc_cookie_data:
                cookies = acc_cookie_data

            api = RakutenOrderAPI(cookies=cookies, proxy=proxy if proxy else None)
            valid, orders, msg = api.check_and_fetch_orders()
            if valid:
                is_success = True
                send_log(f"[{email}] 协议直连查单成功！获取到 {len(orders)} 条记录", "SUCCESS")
                if isinstance(cookies, (dict, list)):
                    try:
                        with open(cookie_path, "w", encoding="utf-8") as cf:
                            json.dump(cookies, cf, indent=2, ensure_ascii=False)
                    except Exception:
                        pass
            else:
                send_log(f"[{email}] ⚠️ Cookie 已失效，自动平滑切换至浏览器登录通道...", "WARNING")

        # Step 2: 若 Cookie 失效，走 Playwright 无头/有头浏览器登录 (注入 ODID/设备凭据)
        if not is_success:
            initial_ck = acc.get("cookie_data") or (cookies if isinstance(cookies, dict) else None)
            ok, cookies, in_browser_orders, login_msg = RakutenBrowserWorker.login_account(
                email=email,
                password=pwd,
                proxy=proxy if proxy else None,
                headless=headless,
                log_cb=log_cb,
                initial_cookies=initial_ck
            )
            if not ok:
                if "正しくありません" in login_msg or "密码错误" in login_msg:
                    acc["status"] = "密码错误"
                elif "ワンタイムパスワード" in login_msg or "2FA" in login_msg or "2段階認証" in login_msg or "確認コード" in login_msg or "認証コード" in login_msg:
                    acc["status"] = "需2FA验证码"
                elif "ロボット" in login_msg or "challenge" in login_msg or "captcha" in login_msg.lower() or "滑块" in login_msg:
                    acc["status"] = "需滑块验证"
                elif "通行密钥" in login_msg or "Passkey" in login_msg or "webauthn" in login_msg.lower():
                    acc["status"] = "需Passkey验证"
                elif "ERR_" in login_msg or "Proxy" in login_msg or "proxy" in login_msg or "代理" in login_msg or "超时" in login_msg or "Connection" in login_msg:
                    acc["status"] = "代理超时"
                elif "登录未完成" in login_msg or "sso" in login_msg.lower():
                    acc["status"] = "异常待重试"
                else:
                    acc["status"] = "登录失败"
                acc["message"] = login_msg
                acc["last_check"] = get_cst_now_str()
                self.save_data()
                return False, login_msg

            # 优先使用浏览器现场 DOM 提取的订单
            if in_browser_orders:
                orders = in_browser_orders
                is_success = True
                msg = f"登录成功并现场提取 {len(orders)} 笔订单"
            else:
                # 登录成功，调用协议查单兜底
                api = RakutenOrderAPI(cookies=cookies, proxy=proxy if proxy else None)
                valid, orders, fetch_msg = api.check_and_fetch_orders()
                if valid:
                    is_success = True
                    msg = f"登录成功并获取 {len(orders)} 条订单"
                else:
                    is_success = True
                    msg = f"登录成功，但查单提示: {fetch_msg}"

        # 深度提取订单详情（前 3 笔核心订单的真实卡号、地址、手机号、收件人）
        top_card = ""
        top_addr = ""
        top_phone = ""
        sender_name = ""
        
        if orders:
            for idx, o in enumerate(orders[:3]):
                try:
                    c_inf, a_inf, p_inf, r_name = fetch_order_detail_real_data(cookies, o, proxy=proxy if proxy else None)
                    if c_inf and not top_card:
                        top_card = c_inf
                    if a_inf and not top_addr:
                        top_addr = a_inf
                    if p_inf and not top_phone:
                        top_phone = p_inf
                except Exception:
                    pass
                if not sender_name:
                    items = o.get("raw_data", {}).get("items", []) or o.get("items_detail", [])
                    if items and items[0].get("senderName"):
                        sender_name = items[0]["senderName"]

        if sender_name:
            name_parts = sender_name.strip().split()
            if len(name_parts) >= 2:
                acc["last_name"] = name_parts[0]
                acc["first_name"] = " ".join(name_parts[1:])
            else:
                acc["last_name"] = sender_name
                acc["first_name"] = ""

        if top_card:
            acc["card_info"] = top_card
        if top_phone:
            acc["phone"] = top_phone
            if not acc.get("extra_info") or "一括払い" in str(acc.get("extra_info")):
                acc["extra_info"] = top_phone
        elif top_card and not acc.get("extra_info"):
            acc["extra_info"] = top_card
        if top_addr:
            acc["address"] = top_addr

        # 结算并更新数据
        self.orders_cache[email] = orders
        acc["status"] = "正常活跃" if is_success else "异常"
        acc["order_count"] = len(orders)
        
        total_yen = 0
        for o in orders:
            price_val = o.get("total_price", 0)
            order_p = 0
            if isinstance(price_val, (int, float)) and price_val > 0:
                order_p = int(price_val)
            elif isinstance(price_val, str) and price_val.strip() and price_val.strip() != "0":
                digits = "".join([c for c in price_val if c.isdigit()])
                order_p = int(digits) if digits else 0
            
            if order_p == 0:
                raw = o.get("raw_data", {})
                items = raw.get("items", []) or o.get("items_detail", [])
                for it in items:
                    p = it.get("itemPrice") if it.get("itemPrice") is not None else it.get("price", 0)
                    u = it.get("itemUnits") or it.get("units") or 1
                    try:
                        p_n = int(str(p).replace(",", "").replace("円", "")) if str(p).strip() else 0
                        order_p += p_n * int(u)
                    except Exception:
                        pass
                o["total_price"] = order_p
            total_yen += order_p
                
        acc["total_spent"] = total_yen
        acc["last_check"] = get_cst_now_str()
        
        card_log = f" [真实卡号: {top_card}]" if top_card else ""
        acc["message"] = f"{msg}{card_log}"
        self.save_data()
        return True, f"{msg}{card_log}"

    def recalculate_all_accounts_total_spent(self) -> int:
        """从 orders_cache 重新计算并修正所有账号的 total_spent 与订单价格"""
        with getattr(self, "_lock", threading.RLock()):
            updated_count = 0
            for acc in self.accounts:
                email = acc.get("email", "")
                orders = self.orders_cache.get(email, [])
                total_yen = 0
                for o in orders:
                    price_val = o.get("total_price", 0)
                    order_p = 0
                    if isinstance(price_val, (int, float)) and price_val > 0:
                        order_p = int(price_val)
                    elif isinstance(price_val, str) and price_val.strip() and price_val.strip() != "0":
                        digits = "".join([c for c in price_val if c.isdigit()])
                        order_p = int(digits) if digits else 0
                    
                    if order_p == 0:
                        raw = o.get("raw_data", {})
                        items = raw.get("items", []) or o.get("items_detail", [])
                        for it in items:
                            p = it.get("itemPrice") if it.get("itemPrice") is not None else it.get("price", 0)
                            u = it.get("itemUnits") or it.get("units") or 1
                            try:
                                p_n = int(str(p).replace(",", "").replace("円", "")) if str(p).strip() else 0
                                order_p += p_n * int(u)
                            except Exception:
                                pass
                        o["total_price"] = order_p
                    total_yen += order_p
                acc["total_spent"] = total_yen
                acc["order_count"] = len(orders)
                updated_count += 1
            self.save_data()
            return updated_count

    def export_all_orders_to_excel(self, standard: str = "csms") -> str:
        """
        导出符合 CSMS 乐天定期便导入表规范的 Excel 文件
        每个账号一行，最多携带 3 笔订单（店铺名称1+订单1、店铺名称2+订单2、店铺名称3+订单3）
        """
        import openpyxl
        from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

        wb = openpyxl.Workbook()
        ws_data = wb.active
        ws_data.title = "乐天导出导入"

        headers = [
            "账号", "密码", "姓", "名", "姓（假名）", "名（假名）", "其他信息", "生日", "性别", "地址",
            "店铺名称1", "订单1", "店铺名称2", "订单2", "店铺名称3", "订单3"
        ]
        ws_data.append(headers)

        # 样式定义
        header_font = Font(name="Arial", size=10, bold=True, color="000000")
        header_fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
        thin_border = Border(
            left=Side(style='thin', color='D3D3D3'),
            right=Side(style='thin', color='D3D3D3'),
            top=Side(style='thin', color='D3D3D3'),
            bottom=Side(style='thin', color='D3D3D3')
        )
        data_font = Font(name="Arial", size=9)
        align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)
        align_left = Alignment(horizontal="left", vertical="top", wrap_text=True)

        for col_idx in range(1, len(headers) + 1):
            cell = ws_data.cell(row=1, column=col_idx)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = align_center
            cell.border = thin_border

        # 遍历所有账号（优先导出正常活跃与有订单的账号）
        for acc in self.accounts:
            email = acc.get("email", "")
            pwd = acc.get("password", "")
            orders = self.orders_cache.get(email, [])

            # 最多取 3 笔订单
            top3_orders = orders[:3]

            row_data = [
                email,
                pwd,
                acc.get("last_name", ""),
                acc.get("first_name", ""),
                acc.get("last_name_kana", ""),
                acc.get("first_name_kana", ""),
                acc.get("extra_info", ""),
                acc.get("birth_date", ""),
                acc.get("gender", ""),
                acc.get("address", "")
            ]

            # 填充最多 3 笔订单
            for i in range(3):
                if i < len(top3_orders):
                    o = top3_orders[i]
                    shop = o.get("shop_name", "乐天店铺")
                    dt = o.get("order_date", "")
                    order_id = o.get("order_id", "N/A")
                    items = o.get("items_summary", "商品信息")
                    price = o.get("total_price", 0)
                    units = o.get("units", 1)
                    
                    # 组装包含お届け先与注文者情報の完整订单块
                    lname = acc.get("last_name", "")
                    fname = acc.get("first_name", "")
                    addr = acc.get("address", "")
                    extra = acc.get("extra_info", "")
                    lkana = acc.get("last_name_kana", "")
                    fkana = acc.get("first_name_kana", "")

                    order_block = (
                        f"{shop}\n"
                        f"注文日時：\n{dt}\n"
                        f"注文番号：\n{order_id} | {items} | {price}円 | 数量：\n{units}"
                    )
                    if lname and addr:
                        order_block += (
                            f" | お届け先\n{lname} {fname}\n{addr} | "
                            f"注文者情報\n{lname} {fname}\n{addr}\n{email} | "
                            f"支払い方法\nクレジットカード決済(一括払い)\n{extra}\n{lkana} {fkana}"
                        )

                    row_data.append(shop)
                    row_data.append(order_block)
                else:
                    row_data.append("")
                    row_data.append("")

            ws_data.append(row_data)
            current_row = ws_data.max_row
            for col_idx in range(1, len(headers) + 1):
                c = ws_data.cell(row=current_row, column=col_idx)
                c.font = data_font
                c.border = thin_border
                c.alignment = align_left

        # 设置列宽
        ws_data.column_dimensions['A'].width = 28
        ws_data.column_dimensions['B'].width = 16
        for c_letter in ['C', 'D', 'E', 'F', 'G', 'H', 'I']:
            ws_data.column_dimensions[c_letter].width = 12
        ws_data.column_dimensions['J'].width = 30
        for c_letter in ['K', 'M', 'O']:
            ws_data.column_dimensions[c_letter].width = 20
        for c_letter in ['L', 'N', 'P']:
            ws_data.column_dimensions[c_letter].width = 50

        # Sheet 2: 口径说明 (与用户业务铁律 100% 逐字逐句对齐)
        ws_doc = wb.create_sheet(title="口径说明")
        red_header_fill = PatternFill(start_color="C00000", end_color="C00000", fill_type="solid")
        red_header_font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
        
        ws_doc.append(["口径（按用户原话，不要自行删列）", None])
        ws_doc.append(["项", "规则"])
        
        doc_rows = [
            ["账号", "乐天「账号密码」左侧，明文入库"],
            ["密码", "乐天「账号密码」右侧，明文入库。不要脱敏、不要删除、不要只存哈希"],
            ["姓 / 名 / 假名 / 其他信息 / 生日 / 性别 / 地址", "乐天导出原样"],
            ["店铺名称N + 订单N", "一笔订单入库一行；有几单跟几单"],
            ["订单块里取", "注文番号、注文日時、品名、数量、金额、支払い方法、卡后四位、お届け先"],
            ["金额", "乐天写出的円，当实付。有小計才另存。不要×12、不要÷12"],
            ["业务", "楽天市场定期便 / 每月定期采购。不存在12期"],
            ["受理编号", "不要出现在本表。导入后系统自动生成（2位大写字母+6位数字）"],
            ["不要的列", "acceptance_code、installment_count、installment_amount、installment_total_12、period_index"],
            ["第2行", "黄色行为格式示例，导入前删掉。真实客户账密按乐天原文粘贴"],
            [None, None],
            ["本文件已填真实数据，无第2行黄色示例。来源：乐天自动化协议作战室（每个账号最多取3单，近3月优先、金额高优先）。账密明文。无受理编号。", None]
        ]
        for r in doc_rows:
            ws_doc.append(r)

        # 设置第 1 行与第 2 行样式
        for col_idx in range(1, 3):
            c1 = ws_doc.cell(row=1, column=col_idx)
            c1.fill = red_header_fill
            c1.font = red_header_font
            c2 = ws_doc.cell(row=2, column=col_idx)
            c2.fill = red_header_fill
            c2.font = red_header_font

        ws_doc.column_dimensions['A'].width = 35
        ws_doc.column_dimensions['B'].width = 85

        timestamp = get_cst_now_str("%Y%m%d_%H%M%S")
        export_file = os.path.join(EXPORTS_DIR, f"CSMS_乐天定期便_导入表_已填_{timestamp}.xlsx")
        wb.save(export_file)
        return export_file

    def export_all_orders_to_csv(self, target_accounts: Optional[List[Dict[str, Any]]] = None, export_tag: str = "") -> str:
        rows = []
        target_emails = set(a["email"].lower() for a in target_accounts) if target_accounts is not None else None

        for email, orders in self.orders_cache.items():
            if target_emails is not None and email.lower() not in target_emails:
                continue
            for o in orders:
                rows.append({
                    "所属账号": email,
                    "注文番号 (订单号)": o.get("order_id"),
                    "注文日時 (下单时间)": o.get("order_date"),
                    "ショップ名 (店铺)": o.get("shop_name"),
                    "商品明細与数量": o.get("items_summary"),
                    "支払総額 (日元)": o.get("total_price"),
                    "発送状況 (物流状态)": o.get("shipping_status"),
                    "伝票番号 (快递单号)": o.get("tracking_number")
                })
        if not rows:
            rows.append({"提示": "暂无匹配的订单数据"})
        df = pd.DataFrame(rows)
        timestamp = get_cst_now_str("%Y%m%d_%H%M%S")
        tag_clean = f"_{export_tag}" if export_tag else ""
        export_file = os.path.join(EXPORTS_DIR, f"Rakuten_Orders_{timestamp}{tag_clean}.csv")
        df.to_csv(export_file, index=False, encoding="utf-8-sig")
        return export_file
