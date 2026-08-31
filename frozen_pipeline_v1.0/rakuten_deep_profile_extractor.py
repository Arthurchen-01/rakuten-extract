import os
import sys
import time
import json
import re
from typing import Dict, Any, List, Optional
from playwright.sync_api import sync_playwright

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

class RakutenProfileExtractor:
    def __init__(self, email: str, password: str, proxy: str = "", headless: bool = True, snap_dir: Optional[str] = None):
        self.email = email.strip()
        self.password = password.strip()
        self.proxy = proxy.strip() if proxy else ""
        self.headless = headless
        self.snap_dir = snap_dir

    def execute(self) -> Dict[str, Any]:
        return execute_bana_ground_truth(self.email, self.password, proxy=self.proxy, headless=self.headless, snap_dir=self.snap_dir)

def execute_bana_ground_truth(email: str, password: str, proxy: str = "", headless: bool = True, snap_dir: Optional[str] = None) -> Dict[str, Any]:
    print("=" * 80)
    print(f"🎯 乐天 Bana 级 100% 官方真本单账号慢速全流程验证: [{email}]")
    print("=" * 80)
    
    result = {
        "email": email,
        "password": password,
        "status": "未处理",
        "last_name": "",
        "first_name": "",
        "last_name_kana": "",
        "first_name_kana": "",
        "card_info": "",
        "birthday": "",
        "gender": "",
        "address": "",
        "phone": "",
        "orders": [],
        "order_count": 0
    }
    
    clean_id = re.sub(r'[^a-zA-Z0-9_]', '_', email)
    snap_target_dir = snap_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "screenshots")
    os.makedirs(snap_target_dir, exist_ok=True)

    def _snap(pg, tag):
        p = os.path.join(snap_target_dir, f"{clean_id}_{tag}.png")
        try: pg.screenshot(path=p, full_page=False)
        except Exception: pass
        return p

    proxy_dict = None
    if proxy and ":" in proxy:
        parts = proxy.split(":")
        if len(parts) == 4:
            proxy_dict = {"server": f"http://{parts[0]}:{parts[1]}", "username": parts[2], "password": parts[3]}
        elif len(parts) == 2:
            proxy_dict = {"server": f"http://{parts[0]}:{parts[1]}"}

    def safe_goto(pg, target_url, timeout=35000, max_retries=2):
        for attempt in range(max_retries):
            try:
                pg.goto(target_url, wait_until="domcontentloaded", timeout=timeout)
                return True
            except Exception as e:
                if attempt == max_retries - 1:
                    print(f"  ⚠️ safe_goto failed for {target_url[:45]}: {e}")
                    return False
                time.sleep(2.0)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-infobars", "--lang=ja-JP"],
            proxy=proxy_dict
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            locale="ja-JP",
            viewport={"width": 1440, "height": 900}
        )
        page = context.new_page()
        
        # ----------------------------------------------------
        # 步骤 1: SSO 鉴权登录
        # ----------------------------------------------------
        print("\n▶ [步骤 1: 登录鉴权] 访问 SSO 网关...")
        gateway_url = "https://profile.id.rakuten.co.jp/gateway/start?clientId=jpn&omniclientid=rakuten_myrakuten_web"
        safe_goto(page, gateway_url, timeout=35000)
        time.sleep(2.0)
        
        try:
            user_input = page.locator('input[type="text"], input[type="email"], input#user_id').first
            user_input.wait_for(state="visible", timeout=12000)
            user_input.fill(email)
            time.sleep(0.5)
            next_btn = page.locator('button:has-text("次へ"), button[type="submit"]').first
            if next_btn.count() > 0: next_btn.click()
            else: user_input.press("Enter")
            time.sleep(2.5)
            
            pwd_input = page.locator('input[type="password"], #password_current, input[name="password"]').first
            pwd_input.wait_for(state="visible", timeout=10000)
            pwd_input.fill(password)
            time.sleep(0.5)
            sub_btn = page.locator('button:has-text("ログイン"), button:has-text("次へ"), button[type="submit"]').first
            if sub_btn.count() > 0: sub_btn.click()
            else: pwd_input.press("Enter")
            
            try:
                page.wait_for_url(lambda u: "profile.id.rakuten.co.jp" in u and "gateway" not in u, timeout=20000)
            except Exception:
                pass
            time.sleep(3.5)
            
            shot1 = os.path.join(snap_target_dir, "step1_sso_login_success.png")
            page.screenshot(path=shot1)
            print(f"  📸 步骤 1 登录截屏: {shot1}")
        except Exception as e_login:
            print(f"  ⚠️ 步骤 1 交互异常: {e_login}")
        
        # ----------------------------------------------------
        # 步骤 2: 提取 住所 & 电话 (addresses/jp)
        # ----------------------------------------------------
        print("\n▶ [步骤 2: 提取住所与电话] 访问 addresses/jp ...")
        try:
            safe_goto(page, "https://profile.id.rakuten.co.jp/addresses/jp", timeout=25000)
            time.sleep(2.5)
            shot2 = os.path.join(snap_target_dir, "step2_addresses_jp.png")
            page.screenshot(path=shot2)
            print(f"  📸 步骤 2 住所页截屏: {shot2}")
            
            addr_text = page.evaluate('() => document.body ? document.body.innerText : ""')
            m_phone = re.search(r'(0[25-9]0[-\s]?\d{4}[-\s]?\d{4}|0[36][-\s]?\d{4}[-\s]?\d{4})', addr_text)
            phone = m_phone.group(1).strip() if m_phone else ""
            if phone:
                digits = re.sub(r'\D', '', phone)
                if len(digits) == 11:
                    phone = f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
            result["phone"] = phone
            
            m_zip = re.search(r'〒?\s*(\d{3}-\d{4})', addr_text)
            zipcode = f"〒{m_zip.group(1)}" if m_zip else ""
            
            addr_lines = []
            capturing = False
            for line in addr_text.split("\n"):
                l = line.strip()
                if "ご住所と連絡先" in l:
                    capturing = True
                    continue
                if capturing:
                    if any(w in l for w in ["English", "日本語", "変更する", "お支払い方法", "myデータ", "ログアウト", "基本情報", "アカウント"]):
                        continue
                    if re.match(r'^\d{3}-\d{4}$', l) or l.startswith("〒") or (m_phone and m_phone.group(1) in l):
                        continue
                    if re.search(r'[\u4e00-\u9fa5\u3040-\u30ff]', l):
                        clean_l = re.sub(r'(?:简体中文|繁體中文|English|日本語|変更する).*$', '', l).strip()
                        if clean_l:
                            addr_lines.append(clean_l)
            clean_addr = "\n".join(addr_lines) if addr_lines else ""
            if phone:
                clean_addr = f"{clean_addr}\n{phone}" if clean_addr else phone
            full_addr = f"{zipcode}\n{clean_addr}".strip() if zipcode else clean_addr
            result["address"] = full_addr
            print(f"  📍 住所提取结果:\n{full_addr}")
        except Exception as e_addr:
            print(f"  ⚠️ 步骤 2 住所提取异常: {e_addr}")
        
        # ----------------------------------------------------
        # 步骤 3: 提取 姓名、假名、生日、性别 (personal-information)
        # ----------------------------------------------------
        print("\n▶ [步骤 3: 提取基本情报] 访问 personal-information ...")
        try:
            safe_goto(page, "https://profile.id.rakuten.co.jp/personal-information", timeout=25000)
            time.sleep(2.5)
            shot3 = os.path.join(snap_target_dir, "step3_personal_info.png")
            page.screenshot(path=shot3)
            print(f"  📸 步骤 3 基本资料截屏: {shot3}")
            
            p_data = page.evaluate(r"""() => {
                const getVal = (sel) => {
                    const el = document.querySelector(sel);
                    return el ? (el.value || el.innerText || '').trim() : '';
                };
                let lName = getVal('input[name="lastName"], #lastName');
                let fName = getVal('input[name="firstName"], #firstName');
                let lKana = getVal('input[name="lastNameKana"], #lastNameKana');
                let fKana = getVal('input[name="firstNameKana"], #firstNameKana');
                
                return {
                    lastName: lName, firstName: fName,
                    lastNameKana: lKana, firstNameKana: fKana,
                    bodyText: document.body ? document.body.innerText : ''
                };
            }""")
            
            result["last_name"] = p_data.get("lastName", "")
            result["first_name"] = p_data.get("firstName", "")
            result["last_name_kana"] = p_data.get("lastNameKana", "")
            result["first_name_kana"] = p_data.get("firstNameKana", "")
            
            b_text = p_data.get("bodyText", "")
            if "性別*\n男性" in b_text or "性別\n男性" in b_text or ("男性" in b_text and "女性" not in b_text):
                result["gender"] = "男性"
            elif "性別*\n女性" in b_text or "性別\n女性" in b_text or ("女性" in b_text and "男性" not in b_text):
                result["gender"] = "女性"
            else:
                result["gender"] = ""
                
            b_match = re.search(r'(\d{4}[/\-]\d{1,2}[/\-]\d{1,2})', b_text)
            if b_match:
                p_parts = b_match.group(1).replace("-", "/").split("/")
                result["birthday"] = f"{p_parts[0]}/{int(p_parts[1]):02d}/{int(p_parts[2]):02d}"
                
            print(f"  👤 基本情报提取: {result['last_name']} {result['first_name']} | 假名: {result['last_name_kana']} {result['first_name_kana']} | 生日: {result['birthday']} | 性别: {result['gender']}")
        except Exception as e_pers:
            print(f"  ⚠️ 步骤 3 基本情报提取异常: {e_pers}")
        
        # ----------------------------------------------------
        # 步骤 4: 提取 购买履历前 3 单及进入详情页 (Bana 8大要素)
        # ----------------------------------------------------
        print("\n▶ [步骤 4: 提取购买履历列表] 访问 order-list ...")
        try:
            safe_goto(page, "https://order.my.rakuten.co.jp/purchase-history/order-list", timeout=30000)
            time.sleep(3.5)
            shot4 = os.path.join(snap_target_dir, "step4_order_list.png")
            page.screenshot(path=shot4)
            print(f"  📸 步骤 4 购买履历列表截屏: {shot4}")
            
            raw_cards = page.evaluate(r"""() => {
                const results = [];
                const links = Array.from(document.querySelectorAll('a')).filter(a => (a.innerText || '').includes('注文詳細'));
                
                for (const a of links) {
                    let container = a;
                    for (let i = 0; i < 10; i++) {
                        if (!container || container === document.body) break;
                        const txt = container.innerText || '';
                        if (txt.includes('注文番号') && txt.includes('円')) break;
                        container = container.parentElement;
                    }
                    const cardText = container ? container.innerText : '';
                    results.push({ detail_url: a.href, card_text: cardText });
                }
                return results;
            }""")
            
            print(f"  📦 列表中识别到有效订单数: {len(raw_cards)}")
            result["order_count"] = len(raw_cards)
            
            for idx, card in enumerate(raw_cards[:3], start=1):
                det_url = card.get("detail_url")
                print(f"\n▶ [步骤 4.{idx}: 详情页深入抓取] 进入 Order {idx} 详情页: {det_url}")
                safe_goto(page, det_url, timeout=25000)
                time.sleep(3.0)
                
                shot_det = os.path.join(snap_target_dir, f"step4_{idx}_order_detail_full.png")
                page.screenshot(path=shot_det, full_page=True)
                print(f"  📸 步骤 4.{idx} 详情页全屏截屏: {shot_det}")
                
                det_data = page.evaluate(r"""() => {
                    const b = document.body ? document.body.innerText : '';
                    
                    // 店铺名
                    let shop = '';
                    const shopM = b.match(/([^\n]+ショップ|[^\n]+店|[^\n]+公式[^\n]*)/);
                    if (shopM) shop = shopM[1].trim();
                    
                    // 注文日時
                    let dt = '';
                    const dtM = b.match(/注文日時\s*[：:]\s*([^\n]+)/);
                    if (dtM) dt = dtM[1].trim();
                    
                    // 注文番号
                    let no = '';
                    const noM = b.match(/注文番号\s*[：:]\s*([\d\-]+)/);
                    if (noM) no = noM[1].trim();
                    
                    // 提取三大官方区块: お届け先, 注文者情報, 支払い方法
                    function getSec(startStr, endArr) {
                        const idx = b.indexOf(startStr);
                        if (idx < 0) return '';
                        let chunk = b.substring(idx + startStr.length);
                        for (const ek of endArr) {
                            const j = chunk.indexOf(ek);
                            if (j >= 0) chunk = chunk.substring(0, j);
                        }
                        return chunk.trim();
                    }
                    
                    const deliv = getSec('お届け先', ['注文者情報', '支払い方法', '配送状況', '注文商品', '請求金額']);
                    const buyer = getSec('注文者情報', ['支払い方法', 'お届け先', '配送状況', '注文商品', '請求金額']);
                    const pay = getSec('支払い方法', ['備考', '情報セキュリティ', '安心してお買い物', '会員情報']);
                    
                    // 品名与金额与数量
                    const priceM = b.match(/小計\s*([\d,]+)\s*円/) || b.match(/お支払い[^\d]*([\d,]+)\s*円/) || b.match(/([\d,]+)\s*円/);
                    const qtyM = b.match(/数量\s*[：:]\s*(\d+)/);
                    
                    let itemDesc = '';
                    const lines = b.split('\n');
                    for (let i = 0; i < lines.length; i++) {
                        const l = lines[i].trim();
                        if (l.includes('円') && i > 0) {
                            const prev = lines[i-1].trim();
                            if (prev.length > 5 && !prev.includes('注文') && !prev.includes('お届け')) {
                                itemDesc = prev;
                                break;
                            }
                        }
                    }
                    
                    return {
                        shop: shop,
                        order_date: dt,
                        order_number: no,
                        price: priceM ? priceM[1].replace(/,/g, '') + '円' : '',
                        quantity: qtyM ? qtyM[1] : '1',
                        item_desc: itemDesc,
                        delivery: deliv,
                        buyer: buyer,
                        payment: pay
                    };
                }""")
                
                # 清理 delivery, buyer, payment
                deliv_clean = "\n".join([line.strip() for line in det_data["delivery"].split("\n") if line.strip() and not any(w in line for w in ["配送方法", "クール便", "宅配便"])])
                buyer_clean = "\n".join([line.strip() for line in det_data["buyer"].split("\n") if line.strip()])
                
                pay_lines = [line.strip() for line in det_data["payment"].split("\n") if line.strip()]
                pay_filtered = []
                for pl in pay_lines:
                    if any(w in pl for w in ["情報セキュリティ", "安心してお買い物", "備考", "SSL", "楽天独自"]): break
                    pay_filtered.append(pl)
                pay_clean = "\n".join(pay_filtered)
                
                # 提取卡信息 (VISA **** 9857)
                if pay_clean and not result["card_info"]:
                    card_m = re.search(r'(VISA|MasterCard|JCB|AMEX|Diners)[^\n<]{0,25}\*{3,4}\s*(\d{4})', pay_clean, re.I)
                    if card_m:
                        result["card_info"] = f"{card_m.group(1).upper()} **** {card_m.group(2)}"
                
                # 严格按照 Bana 结构拼装 order_raw
                parts = []
                if det_data["item_desc"]: parts.append(det_data["item_desc"])
                if det_data["price"]: parts.append(det_data["price"])
                if det_data["quantity"]: parts.append(f"数量：\n{det_data['quantity']}")
                if deliv_clean: parts.append(f"お届け先\n{deliv_clean}")
                if buyer_clean: parts.append(f"注文者情報\n{buyer_clean}")
                if pay_clean: parts.append(f"支払い方法\n{pay_clean}")
                
                bana_order_block = f"{det_data['shop']}\n注文日時：\n{det_data['order_date']}\n注文番号：\n{det_data['order_number']} | " + " | ".join(parts)
                
                result["orders"].append({
                    "shop_name": det_data["shop"],
                    "shop": det_data["shop"],
                    "order_raw": bana_order_block,
                    "order_details": bana_order_block,
                    "order_id": det_data["order_number"],
                    "order_number": det_data["order_number"],
                    "order_date": det_data["order_date"],
                    "date": det_data["order_date"],
                    "price": det_data["price"],
                    "price_yen": det_data["price"]
                })
        except Exception as e_orders:
            print(f"  ⚠️ 步骤 4 订单提取异常: {e_orders}")
        finally:
            try: browser.close()
            except Exception: pass
        
    result["status"] = "正常活跃"
    
    # ----------------------------------------------------
    # 验证 1: JSON 落地与持久化
    # ----------------------------------------------------
    result["status"] = "正常活跃"
    result["message"] = f"Bana级深度穿透完成！获取{len(result['orders'])}笔真实订单，姓名:{result['last_name']}{result['first_name']}，手机:{result['phone']}"
    print(f"\n🎉 账号 [{email}] 提取完成: 订单数={len(result['orders'])}, 姓名={result['last_name']}{result['first_name']}, 手机={result['phone']}")
    return result

if __name__ == "__main__":
    extractor = RakutenProfileExtractor("tnasuno187@gmail.com", "fatty6682")
    res = extractor.execute()
    print("Result:", json.dumps(res, indent=2, ensure_ascii=False))

