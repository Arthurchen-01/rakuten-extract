#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
Rakuten Cluster Deep Profile & Bana-Grade Orchestrator
乐天 16 列法定标准【Bana 级真本】全集群深度采集与交付导出器
==============================================================================
"""

import os
import sys
import time
import json
import logging
import argparse
from typing import Optional, Dict, List, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
EXPORTS_DIR = os.path.join(DATA_DIR, "exports")
SCREENSHOTS_DIR = os.path.join(DATA_DIR, "screenshots")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(EXPORTS_DIR, exist_ok=True)
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

from rakuten_deep_profile_extractor import RakutenProfileExtractor
from csms_exporter import generate_csms_deliverable_excel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(threadName)s) %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("ClusterBanaRunner")

PROGRESS_FILE = os.path.join(DATA_DIR, "live_profile_progress.json")
ACCOUNTS_DEEP_FILE = os.path.join(DATA_DIR, "accounts_profile_deep.json")


def update_live_progress(current: int, total: int, latest_res: dict, all_results: list):
    """实时原子更新进度与统计数据"""
    success_count = sum(1 for r in all_results if r.get("status") == "正常活跃")
    order_count = sum(1 for r in all_results if len(r.get("orders", [])) > 0)
    phone_count = sum(1 for r in all_results if r.get("phone"))
    
    data = {
        "is_running": current < total,
        "current": current,
        "total": total,
        "success_count": success_count,
        "order_count": order_count,
        "phone_count": phone_count,
        "order_coverage_rate": f"{(order_count / max(1, current) * 100):.1f}%",
        "latest_account": latest_res.get("email", ""),
        "latest_phone": latest_res.get("phone", ""),
        "latest_orders": len(latest_res.get("orders", [])),
        "latest_name": f"{latest_res.get('last_name', '')} {latest_res.get('first_name', '')}".strip(),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    
    tmp_file = f"{PROGRESS_FILE}.tmp.{os.getpid()}"
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_file, PROGRESS_FILE)
    except Exception:
        pass


def run_cluster_deep_pipeline(input_file: str, workers: int = 3, max_count: Optional[int] = None, headless: bool = True):
    if not os.path.exists(input_file):
        logger.error(f"输入文件不存在: {input_file}")
        return
        
    accounts = []
    if input_file.endswith(".json"):
        with open(input_file, "r", encoding="utf-8") as f:
            acc_data = json.load(f)
            for item in acc_data:
                em = item.get("email") or item.get("username")
                pw = item.get("password")
                px = item.get("proxy")
                if em and pw:
                    accounts.append((em, pw, px))
    else:
        with open(input_file, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip().lstrip("\ufeff")
                if not line or line.startswith("#"):
                    continue
                parts = line.split("----")
                if len(parts) >= 2:
                    em = parts[0].strip().lstrip("\ufeff")
                    pw = parts[1].strip().lstrip("\ufeff")
                    px = parts[2].strip() if len(parts) >= 3 and not parts[2].startswith("{") else None
                    accounts.append((em, pw, px))
                
    if max_count and max_count > 0:
        accounts = accounts[:max_count]
        
    total = len(accounts)
    processed_map = {}
    if os.path.exists(ACCOUNTS_DEEP_FILE):
        try:
            with open(ACCOUNTS_DEEP_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
                for item in existing:
                    if item.get("email") and item.get("status") == "正常活跃":
                        processed_map[item["email"]] = item
        except Exception:
            pass

    all_results = list(processed_map.values())
    pending_accounts = [acc for acc in accounts if acc[0] not in processed_map]
    
    current = len(all_results)
    logger.info(f"🚀 启动全集群 Bana 级 16 列深度全要素采集任务: 总计 {total} 户 (已就绪 {current} 户，待采集 {len(pending_accounts)} 户)，并发线程: {workers}")
    
    update_live_progress(current, total, all_results[-1] if all_results else {}, all_results)
    
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="BanaCollector") as executor:
        futures = {
            executor.submit(RakutenProfileExtractor(em, pw, px, headless).execute): em
            for em, pw, px in pending_accounts
        }
        
        for future in as_completed(futures):
            em = futures[future]
            try:
                res = future.result()
                all_results.append(res)
                current += 1
                
                tmp_json = f"{ACCOUNTS_DEEP_FILE}.tmp.{os.getpid()}"
                with open(tmp_json, "w", encoding="utf-8") as f:
                    json.dump(all_results, f, ensure_ascii=False, indent=2)
                os.replace(tmp_json, ACCOUNTS_DEEP_FILE)
                    
                update_live_progress(current, total, res, all_results)
                
                ph_str = res.get('phone') or '未提取到'
                nm_str = f"{res.get('last_name', '')} {res.get('first_name', '')}".strip() or '-'
                orders_n = len(res.get('orders', []))
                logger.info(f"[{current}/{total}] 实时落盘: {em} -> 订单数: {orders_n} | 手机: {ph_str} | 姓名: {nm_str} | 卡号: {res.get('card_info', '-')}")
                
            except Exception as e:
                logger.error(f"处理失败 [{em}]: {e}")
                current += 1
                
    tag = time.strftime("%m.%d下午_%H%M")
    succ_n = sum(1 for r in all_results if r.get("status") == "正常活跃")
    fail_n = total - succ_n
    excel_out = os.path.join(EXPORTS_DIR, f"{time.strftime('%m.%d下午')}_{total}户全量汇总_{succ_n}活跃-{fail_n}失败.xlsx")
    generate_csms_deliverable_excel(all_results, out_filepath=excel_out)
    
    update_live_progress(total, total, all_results[-1] if all_results else {}, all_results)
    logger.info(f"🎉 任务全部完成! 成功导出法定标准 16 列真本: {excel_out}")
    return excel_out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cluster Deep Profile Runner")
    parser.add_argument("--input", "-i", type=str, default="accounts.json", help="账号文件路径 (json/txt)")
    parser.add_argument("--workers", "-w", type=int, default=3, help="并发线程数 (默认 3)")
    parser.add_argument("--limit", "-l", type=int, default=None, help="限制处理数量 (用于测试)")
    parser.add_argument("--headful", action="store_true", help="开启有头浏览器模式")
    
    args = parser.parse_args()
    run_cluster_deep_pipeline(
        input_file=args.input,
        workers=args.workers,
        max_count=args.limit,
        headless=not args.headful
    )
