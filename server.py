# -*- coding: utf-8 -*-
"""
Rakuten Manager FastAPI Server
提供：
1. 账号管理 RESTful API
2. 批量与单账号检测控制
3. WebSocket 实时日志流 (/ws/logs)
4. 任务停止与最新快照伺服
5. 订单导出与心跳守护
"""

import os
import sys
import time
import asyncio
import json
import re
import hashlib

import logging
import threading
import concurrent.futures
from collections import deque
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

CST_TZ = timezone(timedelta(hours=8))

def get_cst_now_str(fmt: str = "%H:%M:%S") -> str:
    return datetime.now(CST_TZ).strftime(fmt)

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from rakuten_engine import AccountManager, SCREENSHOTS_DIR

# --- Monkey-Patch Windows asyncio ConnectionResetError bug ---
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    from asyncio.proactor_events import _ProactorBasePipeTransport

    def _silence_connection_lost(self, exc):
        try:
            if exc is not None and isinstance(exc, (ConnectionResetError, ConnectionAbortedError)):
                return
        except Exception:
            pass
        try:
            self._real_call_connection_lost(exc)
        except Exception:
            pass

    if not hasattr(_ProactorBasePipeTransport, '_real_call_connection_lost'):
        _ProactorBasePipeTransport._real_call_connection_lost = _ProactorBasePipeTransport._call_connection_lost
        _ProactorBasePipeTransport._call_connection_lost = _silence_connection_lost


app = FastAPI(title="Rakuten Japan Order & Account Hub", version="2.0.0")

BUILD_ID = "v2026.08.27.120s-resilient-build"
VERSION = "2.0.0"
SERVER_START_TIME = datetime.now(CST_TZ).strftime("%Y-%m-%d %H:%M:%S")

async def idle_export_daemon():
    """空闲状态兜底守护机制：检测系统空闲时是否已为最后一批导入生成报表"""
    import glob
    from csms_exporter import generate_csms_deliverable_excel as generate_excel_with_screenshots, EXPORTS_DIR
    while True:
        await asyncio.sleep(30)
        # 如果正在扫描，或者总库没有账号，则跳过
        if task_status["is_running"] or not manager.accounts:
            continue
            
        last_b = manager.get_last_import_batch()
        if not last_b:
            continue
            
        time_part = last_b.get("import_time", "").replace(":", "").replace("-", "").replace(" ", "_")
        if not time_part:
            continue
            
        # 以 time_part 构造专属 tag 用来识别该批次是否已出报表
        tag = f"预生成_{time_part}"
        
        try:
            existing = glob.glob(os.path.join(EXPORTS_DIR, f"*{tag}*.xlsx"))
            if not existing:
                # 还没有生成，开始预生成
                target_accs = manager.get_accounts_by_scope(scope="last_batch")
                if target_accs:
                    await asyncio.to_thread(generate_excel_with_screenshots, target_accs, tag)
        except Exception as e:
            logging.error(f"Idle daemon error: {e}")

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(idle_export_daemon())

DEFAULT_TASK_TIMEOUT = 120.0

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# 本地静态资源（Bootstrap CSS/JS），彻底消除 CDN 依赖
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

manager = AccountManager()
worker_executor = concurrent.futures.ThreadPoolExecutor(max_workers=32, thread_name_prefix="RakutenWorker")


class ConnectionBroadcaster:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.history = deque(maxlen=300)
        self.loop = None
        self._lock = threading.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        self.loop = asyncio.get_event_loop()
        # 客户端一旦建立连接，立即回放最近 100 条实时日志，确保前台绝不白屏！
        with self._lock:
            history_snapshot = list(self.history)[-100:]
        for entry in history_snapshot:
            try:
                await websocket.send_text(json.dumps(entry, ensure_ascii=False))
            except Exception:
                pass

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str, level: str = "INFO"):
        now_str = get_cst_now_str()
        data = {
            "time": now_str,
            "level": level,
            "message": message
        }
        with self._lock:
            self.history.append(data)
        for connection in list(self.active_connections):
            try:
                await connection.send_text(json.dumps(data, ensure_ascii=False))
            except Exception:
                self.disconnect(connection)

    def sync_broadcast(self, message: str, level: str = "INFO"):
        """供同步线程安全调用，无论前端是否在线均永久计入环形历史缓冲区"""
        now_str = get_cst_now_str()
        data = {
            "time": now_str,
            "level": level,
            "message": message
        }
        with self._lock:
            self.history.append(data)
        if self.loop and self.loop.is_running() and self.active_connections:
            for connection in list(self.active_connections):
                asyncio.run_coroutine_threadsafe(self._safe_send(connection, data), self.loop)

    async def _safe_send(self, ws: WebSocket, data: dict):
        try:
            await ws.send_text(json.dumps(data, ensure_ascii=False))
        except Exception:
            self.disconnect(ws)


broadcaster = ConnectionBroadcaster()

CLUSTER_NODE_COUNT = 4
CLUSTER_WORKERS_PER_NODE = 30
CLUSTER_TOTAL_WORKERS = CLUSTER_NODE_COUNT * CLUSTER_WORKERS_PER_NODE


task_status = {
    "is_running": False,
    "concurrency": 1,
    "configured_concurrency": 1,
    "active_concurrency": 0,
    "current_account": "",
    "active_workers": {},
    "current": 0,
    "total": 0,
    "success_count": 0,
    "failed_count": 0,
    "stop_requested": False,
    "start_time": "",
    "latest_snapshot": ""
}


# --- 数据模型 ---

class AccountImportRequest(BaseModel):
    text: str
    default_proxy: Optional[str] = ""
    proxy_list_text: Optional[str] = ""

class AccountAssignProxiesRequest(BaseModel):
    proxy_list_text: str
    scope: Optional[str] = "all"  # all, no_proxy, unchecked, selected
    selected_emails: Optional[List[str]] = []

class AccountActionRequest(BaseModel):
    email: str
    force_browser_login: Optional[bool] = False
    headless: Optional[bool] = True

class AccountDeleteRequest(BaseModel):
    email: str

class AccountDeleteBatchRequest(BaseModel):
    emails: List[str]

class AccountClearRequest(BaseModel):
    scope: Optional[str] = "all"  # all, tested, failed, wrong_password

class BatchCheckRequest(BaseModel):
    filter_type: Optional[str] = "all"  # all, unchecked, failed, selected
    selected_emails: Optional[List[str]] = []
    force_browser_login: Optional[bool] = False
    headless: Optional[bool] = True
    delay_sec: Optional[float] = 2.0
    concurrency: Optional[int] = 5
class ProxyPoolSettingsRequest(BaseModel):
    auto_rotate_enabled: Optional[bool] = True
    base_proxies: Optional[List[str]] = []
    default_region: Optional[str] = "JP"
    session_ttl_minutes: Optional[int] = 5

class ProxyTestRequest(BaseModel):
    proxy: Optional[str] = None


# --- API 路由 ---

@app.get("/api/accounts")
async def get_accounts():
    stats = {}
    for a in manager.accounts:
        st = a.get("status", "未检测")
        stats[st] = stats.get(st, 0) + 1
    return {
        "accounts": manager.accounts,
        "total_accounts": len(manager.accounts),
        "total_orders": sum(a.get("order_count", 0) for a in manager.accounts),
        "total_spent_yen": sum(a.get("total_spent", 0) for a in manager.accounts),
        "stats": stats
    }

@app.post("/api/accounts/import")
async def import_accounts(req: AccountImportRequest):
    count, batch_info = manager.batch_import(req.text, req.default_proxy or "", req.proxy_list_text or "")
    await broadcaster.broadcast(f"成功批量导入/更新 {count} 个乐天账号（已打上批次标签: {batch_info['note']}，时间: {batch_info['import_time']}）", "SUCCESS")
    return {"status": "ok", "imported_count": count, "batch": batch_info}

@app.post("/api/accounts/import-file")
async def import_accounts_file(
    file: UploadFile = File(...),
    default_proxy: Optional[str] = Form(""),
    proxy_list_text: Optional[str] = Form("")
):
    try:
        content = await file.read()
        count, batch_info = manager.batch_import_from_file(
            file_content=content,
            filename=file.filename or "upload.xlsx",
            default_proxy=default_proxy or "",
            proxy_list_text=proxy_list_text or ""
        )
        await broadcaster.broadcast(f"成功从文件 [{file.filename}] 导入/更新 {count} 个账号（批次: {batch_info['note']}）", "SUCCESS")
        return {"status": "ok", "imported_count": count, "batch": batch_info}
    except Exception as e:
        logging.exception("File import failed")
        raise HTTPException(status_code=400, detail=f"文件导入解析失败: {str(e)}")

@app.get("/api/accounts/import-batches")
async def get_import_batches_api():
    summaries = manager.get_import_batches_summary()
    last_batch = manager.get_last_import_batch()
    return {
        "batches": summaries,
        "total_batches": len(summaries),
        "last_batch": last_batch
    }

@app.post("/api/accounts/assign-proxies")
async def assign_proxies_api(req: AccountAssignProxiesRequest):
    count = manager.assign_proxies(req.proxy_list_text, req.scope or "all", req.selected_emails or [])
    await broadcaster.broadcast(f"已为 {count} 个账号按顺序自动批量更新分配代理", "SUCCESS")
    return {"status": "ok", "assigned_count": count}

@app.get("/api/proxy-pool")
async def get_proxy_pool_api():
    from rakuten_engine import ProxyPoolManager
    rotator = ProxyPoolManager.get_instance()
    rotator.load_settings()
    return rotator.settings

@app.post("/api/proxy-pool")
async def update_proxy_pool_api(req: ProxyPoolSettingsRequest):
    from rakuten_engine import ProxyPoolManager
    rotator = ProxyPoolManager.get_instance()
    rotator.settings["auto_rotate_enabled"] = req.auto_rotate_enabled if req.auto_rotate_enabled is not None else True
    rotator.settings["base_proxies"] = [p.strip() for p in (req.base_proxies or []) if p.strip()]
    if req.default_region:
        rotator.settings["default_region"] = req.default_region
    if req.session_ttl_minutes:
        rotator.settings["session_ttl_minutes"] = req.session_ttl_minutes
    rotator.save_settings()
    await broadcaster.broadcast(f"已更新全局动态住宅代理池配置（已保存 {len(rotator.settings['base_proxies'])} 条模板，7x24h 自动轮换开启）", "SUCCESS")
    return {"status": "ok", "settings": rotator.settings}

@app.post("/api/proxy-pool/test")
async def test_proxy_pool_api(req: ProxyTestRequest):
    from rakuten_engine import ProxyPoolManager
    rotator = ProxyPoolManager.get_instance()
    res = rotator.test_proxy(req.proxy)
    return res

@app.post("/api/accounts/assign-global-proxy")
async def assign_global_proxy_api():
    count = manager.assign_global_proxies_to_all_empty()
    await broadcaster.broadcast(f"已自动为全盘 {count} 个无代理账号绑定全局动态轮换住宅 IP", "SUCCESS")
    return {"status": "ok", "assigned_count": count}

@app.get("/api/maintenance/status")
async def get_maintenance_status():
    from datetime import timezone, timedelta
    CST = timezone(timedelta(hours=8))
    now_cst = datetime.now(CST)
    hour = now_cst.hour
    
    # 计算下一次运行时间
    if hour < 7:
        if hour < 1:
            next_hour = 1
        elif hour < 4:
            next_hour = 4
        else:
            next_hour = 7
    else:
        next_hour = (hour + 1) % 24
        
    next_dt = now_cst.replace(hour=next_hour, minute=0, second=0, microsecond=0)
    if next_hour <= hour:
        next_dt += timedelta(days=1)
        
    log_file = os.path.join(DATA_DIR, "maintenance.log")
    recent_logs = []
    if os.path.exists(log_file):
        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
                recent_logs = [l.strip() for l in lines[-15:] if l.strip()]
        except Exception:
            pass
            
    return {
        "status": "active",
        "timer_enabled": True,
        "schedule_rule": "中国时间 07:00 前每 3 小时 (01:00, 04:00)；07:00 后每 1 小时 (07:00 ~ 23:00)",
        "current_time_cst": now_cst.strftime("%Y-%m-%d %H:%M:%S CST"),
        "next_run_cst": next_dt.strftime("%Y-%m-%d %H:%M:00 CST"),
        "recent_logs": recent_logs
    }

@app.post("/api/maintenance/run-now")
async def run_maintenance_now():
    try:
        from maintenance import run_maintenance
        report = run_maintenance(force=True)
        await broadcaster.broadcast("🛠️ 已成功执行一次全维服务器健康维护与自愈巡检", "SUCCESS")
        return {"status": "ok", "report": report}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/accounts/delete")
async def delete_account(req: AccountDeleteRequest):
    manager.delete_account(req.email)
    await broadcaster.broadcast(f"已删除账号: {req.email}", "INFO")
    return {"status": "ok"}

@app.post("/api/accounts/delete-batch")
async def delete_accounts_batch(req: AccountDeleteBatchRequest):
    deleted_count = manager.delete_batch(req.emails)
    await broadcaster.broadcast(f"已批量删除 {deleted_count} 个选定账号", "INFO")
    return {"status": "ok", "deleted_count": deleted_count}

@app.post("/api/accounts/clear")
async def clear_accounts_api(req: AccountClearRequest):
    scope_names = {
        "all": "全部账号 (归档至历史已测库后清库)",
        "tested": "所有已测试账号",
        "failed": "所有登录失败/异常账号",
        "wrong_password": "所有密码错误账号"
    }
    deleted_count = manager.clear_accounts(req.scope or "all")
    scope_desc = scope_names.get(req.scope, req.scope)
    await broadcaster.broadcast(f"已将 {deleted_count} 个现有账号全量归档保存至【历史已测库 (永久记住邮箱/ID)】，并从活跃工作区清空！", "SUCCESS")
    return {
        "status": "ok", 
        "deleted_count": deleted_count, 
        "remaining": len(manager.accounts),
        "history_vault_count": len(manager.history_vault)
    }

@app.post("/api/accounts/requeue-failed-to-tail")
async def requeue_failed_to_tail(force_all: bool = False):
    """将抖动/异常账号重新加入队尾（支持自动修复历史 Execution context 误伤账号）"""
    proxies = get_cliproxy_pool()
    reset_count = 0
    locked_count = 0
    for acc in manager.accounts:
        st = acc.get("status")
        msg = acc.get("message", "")
        is_context_bug = "context was destroyed" in msg.lower() or "navigation" in msg.lower()
        if st not in ["正常活跃", "密码错误"]:
            curr_jitter = acc.get("jitter_count", 0)
            # 终态不可由普通 requeue 复活；上下文错误只能记录为人工复核候选，不能清零 strike。
            if curr_jitter < 3 and not force_all:
                acc["status"] = "未检测"
                acc["lock_until"] = 0
                acc["locked_by"] = ""
                acc["last_failure_category"] = acc.get("failure_category") or "other_failed"
                acc["reset_reason"] = "operator_requeue"
                acc["reset_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                acc["message"] = "已排入队尾使用新引擎重试"
            else:
                locked_count += 1
                if is_context_bug:
                    acc["reset_review_required"] = True
                if proxies:
                    acc["proxy"] = random.choice(proxies)
                reset_count += 1

    manager.save_data()
    await broadcaster.broadcast(
        f"🔁 指令执行：已将 {reset_count} 户异常/误伤账号移至队尾重试；已锁定 {locked_count} 户明确异常号！", 
        "SUCCESS"
    )
    return {"success": True, "reset_count": reset_count, "locked_count": locked_count}


@app.get("/api/accounts/history")
async def get_history_accounts():
    return {
        "total_archived": len(manager.history_vault),
        "history": list(manager.history_vault.values())
    }

@app.get("/api/orders")
async def get_orders(email: Optional[str] = None):
    if email:
        acc = next((a for a in manager.accounts if a.get("email", "").lower() == email.lower()), None)
        o_list = manager.orders_cache.get(email.lower(), manager.orders_cache.get(email, [])) if acc else manager.orders_cache.get(email, [])
        if not o_list and acc:
            o_list = acc.get("orders", []) or []
        sorted_orders = sorted(o_list, key=lambda x: str(x.get("order_date") or x.get("date") or ""), reverse=True)
        return {"email": email, "orders": sorted_orders}
    
    all_orders = []
    for a in manager.accounts:
        acc_email = a.get("email", "")
        o_list = manager.orders_cache.get(acc_email.lower(), manager.orders_cache.get(acc_email, [])) or a.get("orders", []) or []
        for item in o_list:
            if isinstance(item, dict):
                item_copy = dict(item)
                item_copy["account_email"] = acc_email
                item_copy["order_id"] = item.get("order_number") or item.get("order_id") or item.get("order_no") or "-"
                item_copy["order_date"] = item.get("order_date") or item.get("date") or "-"
                item_copy["shop_name"] = item.get("shop_name") or item.get("shop") or "-"
                item_copy["items_summary"] = item.get("items_desc") or item.get("item_name") or item.get("product_name") or "-"
                price_val = item.get("price_yen") if ("price_yen" in item and item.get("price_yen") not in [None, ""]) else item.get("price") or item.get("total_amount") or 0
                item_copy["total_price"] = price_val
                item_copy["payment_method"] = item.get("card_info") or item.get("payment_method") or "-"
                item_copy["shipping_status"] = item.get("shipping_status") or item.get("status") or "已下单"
                item_copy["tracking_number"] = item.get("tracking_no") or item.get("tracking_number") or "-"
                all_orders.append(item_copy)
                
    sorted_all = sorted(all_orders, key=lambda x: str(x.get("order_date") or ""), reverse=True)
    return {"orders": sorted_all, "total": len(sorted_all)}

@app.post("/api/check-single")
async def check_single_account(req: AccountActionRequest, background_tasks: BackgroundTasks):
    if task_status["is_running"]:
        raise HTTPException(status_code=400, detail="后台已有任务正在运行，请稍候！")

    async def run_single():
        task_status["is_running"] = True
        task_status["current_account"] = req.email
        task_status["stop_requested"] = False
        task_status["start_time"] = get_cst_now_str()
        await broadcaster.broadcast(f"【单账号执行】开始检测: {req.email} (无头模式: {req.headless})...", "INFO")
        
        loop = asyncio.get_event_loop()
        ok, msg = await loop.run_in_executor(
            None, 
            manager.process_account, 
            req.email, 
            req.force_browser_login, 
            req.headless,
            broadcaster.sync_broadcast
        )
        
        level = "SUCCESS" if ok else "ERROR"
        await broadcaster.broadcast(f"[{req.email}] 处理完成: {msg}", level)
        task_status["is_running"] = False
        task_status["current_account"] = ""

    background_tasks.add_task(run_single)
    return {"status": "started", "message": f"已启动账号 {req.email} 的检测流程"}

def get_cluster_config():
    """从环境变量或内置安全映射表加载 4 节点集群配置"""
    raw = os.getenv("RAKUTEN_CLUSTER_CONFIG", "")
    if raw:
        try:
            cfg = json.loads(raw)
            if isinstance(cfg, list) and len(cfg) > 0:
                return cfg
        except Exception:
            pass
    # 默认 4 节点集群拓扑
    return [
        {
            "id": "Node_1",
            "ip": "38.76.206.7",
            "py": "/opt/deepseek-suite/.venv/bin/python",
            "pwd": "39TF6xMH52yC",
            "master": "https://lt.samuraiguan.cloud",
            "part": 0,
            "dir": "forward"
        },
        {
            "id": "Node_2",
            "ip": "156.225.31.92",
            "py": "/opt/rakuten-hub/.venv/bin/python",
            "pwd": "39TF6xMH52yC",
            "master": "https://lt.samuraiguan.cloud",
            "part": 1,
            "dir": "forward"
        },
        {
            "id": "Node_3",
            "ip": "103.52.152.37",
            "py": "/opt/rakuten-hub/.venv/bin/python",
            "pwd": "39TF6xMH52yC",
            "master": "https://lt.samuraiguan.cloud",
            "part": 2,
            "dir": "forward"
        },
        {
            "id": "Node_4",
            "ip": "127.0.0.1",
            "py": "/opt/rakuten-hub/venv/bin/python3",
            "master": "http://127.0.0.1:8998",
            "part": 3,
            "dir": "reverse",
            "is_local": True
        }
    ]


def dispatch_cluster_workers_sync(concurrency_per_node: int = 20):
    cluster = get_cluster_config()
    for n in cluster:
        nid = n["id"]
        try:
            # 1. 本地 Node 4 守护直接通过进程拉起，无需 SSH
            if n.get("is_local") or n.get("ip") in ["127.0.0.1", "38.76.174.32", "localhost"]:
                subprocess.run(["pkill", "-9", "-f", f"cloud_worker.py.*--worker-id {nid}"], check=False)
                worker_py = n.get("py", sys.executable)
                cmd = [
                    worker_py, "/opt/rakuten-hub/cloud_worker.py",
                    "--master", n.get("master", "http://127.0.0.1:8998"),
                    "--worker-id", nid,
                    "--concurrency", str(concurrency_per_node),
                    "--partition", str(n.get("part", 0)),
                    "--total-partitions", "4",
                    "--direction", n.get("dir", "forward"),
                    "--mode", "deep"
                ]
                log_f = open(f"/opt/rakuten-hub/worker_{nid}.log", "a", encoding="utf-8")
                subprocess.Popen(cmd, stdout=log_f, stderr=subprocess.STDOUT)
                logging.info(f"✅ Local {nid} Worker launched with concurrency={concurrency_per_node}")
                continue

            # 2. 远程节点通过 SSH 调度
            import paramiko
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            connect_kwargs = {"timeout": 10}
            if n.get("ssh_key_path") and os.path.exists(n["ssh_key_path"]):
                connect_kwargs["key_filename"] = n["ssh_key_path"]
            elif n.get("pwd"):
                connect_kwargs["password"] = n["pwd"]
            
            ssh.connect(n["ip"], port=22, username=n.get("ssh_user", "root"), **connect_kwargs)
            ssh.exec_command(f"pkill -9 -f 'cloud_worker.py.*--worker-id {nid}' || true")
            cmd_str = f"nohup {n['py']} /opt/rakuten-hub/cloud_worker.py --master {n['master']} --worker-id {nid} --concurrency {concurrency_per_node} --partition {n['part']} --total-partitions 4 --direction {n['dir']} --mode deep > /opt/rakuten-hub/worker_{nid}.log 2>&1 &"
            ssh.exec_command(cmd_str)
            ssh.close()
            logging.info(f"✅ Remote {nid} Worker dispatched via SSH with concurrency={concurrency_per_node}")
        except Exception as e:
            logging.error(f"Failed to launch worker on {nid}: {e}")

def stop_cluster_workers_sync():
    cluster = get_cluster_config()
    for n in cluster:
        nid = n["id"]
        try:
            if n.get("is_local") or n.get("ip") in ["127.0.0.1", "38.76.174.32", "localhost"]:
                subprocess.run(["pkill", "-9", "-f", f"cloud_worker.py.*--worker-id {nid}"], check=False)
                continue
            import paramiko
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            connect_kwargs = {"timeout": 5}
            if n.get("ssh_key_path") and os.path.exists(n["ssh_key_path"]):
                connect_kwargs["key_filename"] = n["ssh_key_path"]
            elif n.get("pwd"):
                connect_kwargs["password"] = n["pwd"]
            ssh.connect(n["ip"], port=22, username=n.get("ssh_user", "root"), **connect_kwargs)
            ssh.exec_command(f"pkill -9 -f 'cloud_worker.py.*--worker-id {nid}' || true")
            ssh.close()
        except Exception as e:
            logging.error(f"Failed to stop worker on {nid}: {e}")

@app.post("/api/check-batch")
async def check_batch_accounts(req: BatchCheckRequest, background_tasks: BackgroundTasks):
    if task_status["is_running"]:
        raise HTTPException(status_code=400, detail="后台已有任务正在运行，请稍候！")

    # 根据 filter_type 智能筛选待测账号
    all_accs = list(manager.accounts)
    if req.filter_type == "unchecked":
        target_accs = [a for a in all_accs if a.get("status") in ["未检测", "导入待测", None, ""]]
    elif req.filter_type == "active_only":
        target_accs = [a for a in all_accs if a.get("status") in ["正常活跃", "未检测", "导入待测"]]
    elif req.filter_type == "unchecked_and_retry":
        target_accs = [a for a in all_accs if a.get("status") in ["未检测", "导入待测", "异常待重试", "代理超时", "登录失败", None, ""]]
    elif req.filter_type == "failed":
        target_accs = [a for a in all_accs if a.get("status") in ["登录失败", "异常", "异常待重试", "代理超时", "需2FA验证码", "需滑块验证"]]
    elif req.filter_type == "selected" and req.selected_emails:
        target_accs = [a for a in all_accs if a.get("email") in req.selected_emails]
    else:
        target_accs = all_accs

    if not target_accs:
        raise HTTPException(status_code=400, detail="未匹配到符合条件的待检测账号！")

    # 如果是活跃重测/重试/清洗任务，将目标账号状态平滑重置为 "未检测" 并清空锁定与重试计数
    if req.filter_type in ["failed", "unchecked_and_retry", "active_only"]:
        for acc in target_accs:
            acc["status"] = "未检测"
            acc["jitter_count"] = 0
            acc["lock_until"] = 0
            acc["locked_by"] = ""
            acc["terminal"] = False
        manager.save_data()

    # 集群请求使用总并发语义；达到集群模式时固定为 4 节点 × 30 Worker。
    req_concurrency = max(1, min(CLUSTER_TOTAL_WORKERS, req.concurrency or 5))

    # 集群模式支持 120, 100, 80, 40, 20，达到集群模式时动态分配 per_node
    if req_concurrency >= 20:
        per_node = max(5, req_concurrency // 4)
        task_status["is_running"] = True
        task_status["concurrency"] = req_concurrency
        task_status["configured_concurrency"] = req_concurrency
        task_status["active_concurrency"] = 0
        task_status["expected_workers"] = req_concurrency
        task_status["stop_requested"] = False
        task_status["start_time"] = get_cst_now_str()
        task_status["total"] = len(target_accs)
        task_status["current"] = 0
        task_status["success_count"] = 0
        task_status["failed_count"] = 0
        task_status["start_active"] = sum(1 for a in manager.accounts if a.get("status") == "正常活跃")
        task_status["start_pending"] = len(target_accs)
        await asyncio.to_thread(dispatch_cluster_workers_sync, per_node)

        await broadcaster.broadcast(f"🚀 已向全网 4 台服务器下发指令（每台 {per_node} 个 Worker，总配置并发 {req_concurrency}）！", "SUCCESS")
        return {"status": "started", "total": len(target_accs), "concurrency": req_concurrency, "mode": "cluster"}

    actual_concurrency = min(req_concurrency, len(target_accs))

    task_status["is_running"] = True
    task_status["concurrency"] = actual_concurrency
    task_status["stop_requested"] = False
    task_status["start_time"] = get_cst_now_str()
    task_status["total"] = len(target_accs)
    task_status["current"] = 0
    task_status["success_count"] = 0
    task_status["failed_count"] = 0
    task_status["active_workers"] = {}
    task_status["current_account"] = ""

    async def run_batch():
        mode_text = "无头静默" if req.headless else "有头可视"
        await broadcaster.broadcast(
            f"🚀 开始批量并发检测 {len(target_accs)} 个账号（并发度: {actual_concurrency} 线程，模式: {mode_text}，基础间隔: {req.delay_sec}s）...", 
            "INFO"
        )

        queue = asyncio.Queue()
        for acc in target_accs:
            await queue.put(acc)

        loop = asyncio.get_event_loop()
        counter_lock = asyncio.Lock()

        async def worker(worker_id: int):
            worker_tag = f"Worker-{worker_id}"
            while not queue.empty():
                if task_status["stop_requested"]:
                    break
                try:
                    acc = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

                email = acc["email"]
                async with counter_lock:
                    task_status["active_workers"][worker_tag] = email
                    active_list = [f"[{w}] {em}" for w, em in task_status["active_workers"].items()]
                    task_status["current_account"] = " | ".join(active_list)

                await broadcaster.broadcast(
                    f"[{worker_tag}] 认领账号开始执行: {email}", 
                    "INFO"
                )

                def worker_log_cb(msg: str, level: str = "INFO"):
                    if ".png" in msg and ("快照" in msg or "截图" in msg):
                        parts = msg.split(":")
                        if len(parts) > 1:
                            snap_candidate = parts[-1].strip()
                            if snap_candidate.endswith(".png"):
                                task_status["latest_snapshot"] = snap_candidate
                    broadcaster.sync_broadcast(f"[{worker_tag}] {msg}", level)

                try:
                    try:
                        ok, msg = await asyncio.wait_for(
                            loop.run_in_executor(
                                worker_executor, 
                                manager.process_account, 
                                email, 
                                req.force_browser_login, 
                                req.headless,
                                worker_log_cb
                            ),
                            timeout=120.0
                        )
                    except asyncio.TimeoutError:
                        # 二次核验：底层线程在最后时刻是否已经顺利落盘
                        acc_check = manager.get_account(email)
                        if acc_check and acc_check.get("status") == "正常活跃":
                            ok = True
                            msg = acc_check.get("message") or "登录成功并现场提取订单"
                        else:
                            ok = False
                            msg = "账号检测严重超时 (120s)，已自动熔断释放"
                    except Exception as exc:
                        ok = False
                        msg = f"执行异常: {exc}"

                    async with counter_lock:
                        # 最终状态判定前再次核验真实落盘状态
                        acc_final = manager.get_account(email) or acc
                        final_status = acc_final.get("status", "")

                        if ok or final_status == "正常活跃":
                            task_status["current"] += 1
                            task_status["success_count"] += 1
                            await broadcaster.broadcast(f"[{worker_tag}] [{email}] ✅ {msg}", "SUCCESS")
                        else:
                            is_pwd_error = (final_status == "密码错误" or "正しくありません" in msg or "密码错误" in msg)
                            curr_jitter = acc.get("jitter_count", 0) + 1
                            acc["jitter_count"] = curr_jitter

                            if not is_pwd_error and curr_jitter < 3 and not task_status["stop_requested"]:
                                acc["message"] = f"⚠️ 抖动已移至队尾重试 (第{curr_jitter}/3次)"
                                manager.move_to_tail(email)
                                await queue.put(acc)
                                task_status["total"] += 1
                                await broadcaster.broadcast(
                                    f"[{worker_tag}] [{email}] ⚠️ 遭遇网络抖动/延迟（第{curr_jitter}/3次），已移至队尾重试！", 
                                    "WARNING"
                                )
                            else:
                                if curr_jitter >= 3 and not is_pwd_error:
                                    final_st = final_status if final_status in ["需2FA验证码", "需滑块验证", "需Passkey验证", "风控拦截"] else "登录失败"
                                    acc["status"] = final_st
                                    acc["message"] = f"已达3次重试上限，强制锁定终态: {msg[:40]}"
                                task_status["current"] += 1
                                task_status["failed_count"] += 1
                                await broadcaster.broadcast(f"[{worker_tag}] [{email}] ❌ {msg}", "ERROR")


                finally:
                    async with counter_lock:
                        if worker_tag in task_status["active_workers"]:
                            del task_status["active_workers"][worker_tag]
                        active_list = [f"[{w}] {em}" for w, em in task_status["active_workers"].items()]
                        task_status["current_account"] = " | ".join(active_list) if active_list else ""

                queue.task_done()

                # 动态休眠
                if not queue.empty() and not task_status["stop_requested"] and req.delay_sec > 0:
                    sleep_time = req.delay_sec + (0.3 * (worker_id % 3))
                    await asyncio.sleep(sleep_time)

        # 启动指定数量的并发 Worker 协程
        try:
            worker_tasks = [asyncio.create_task(worker(i + 1)) for i in range(actual_concurrency)]
            await asyncio.gather(*worker_tasks, return_exceptions=True)
        finally:
            task_status["is_running"] = False
            task_status["current_account"] = ""
            task_status["active_workers"] = {}

        if task_status["stop_requested"]:
            await broadcaster.broadcast("⚠️ 批量并发任务已由用户安全中断！", "WARNING")
        else:
            await broadcaster.broadcast(
                f"🏁 批量并发检测流程结束！总计: {task_status['current']}/{task_status['total']} | 成功: {task_status['success_count']} | 失败: {task_status['failed_count']}", 
                "SUCCESS"
            )
            # --------------------------------
            # 扫描结束后，立刻预生成带图报表并进行核对查重
            # --------------------------------
            await broadcaster.broadcast("⏳ 正在自动预生成全景带图报表并执行查重核对，请稍候...", "INFO")
            try:
                from csms_exporter import generate_csms_deliverable_excel as generate_excel_with_screenshots
                
                last_b = manager.get_last_import_batch() or {}
                time_part = last_b.get("import_time", "").replace(":", "").replace("-", "").replace(" ", "_")
                tag = f"预生成_{time_part}" if time_part else "预生成"
                
                # 在后台线程生成，避免阻塞
                file_path = await asyncio.to_thread(generate_excel_with_screenshots, target_accs, tag)
                report_msg = f"已生成统一 CSMS Excel: {file_path}"
                
                # 播报查重结果
                await broadcaster.broadcast(f"{report_msg}", "SUCCESS")
                
                # 构建下载链接广播
                await broadcaster.broadcast(f"📂 预生成完毕！您可以直接点击上方【下载带图报表】按钮获取最新数据，或在服务器 {file_path} 提取。", "SUCCESS")
                
            except Exception as e:
                import traceback
                logging.exception("Auto pre-generation failed")
                await broadcaster.broadcast(f"❌ 自动预生成报表失败: {e}", "ERROR")

    background_tasks.add_task(run_batch)
    return {"status": "started", "total": len(target_accs), "concurrency": actual_concurrency}

@app.post("/api/task/stop")
async def stop_task():
    task_status["stop_requested"] = True
    task_status["is_running"] = False
    await asyncio.to_thread(stop_cluster_workers_sync)
    await broadcaster.broadcast("⚠️ 正在向全网 4 台集群服务器下发全面停火/中断指令...", "WARNING")
    return {"status": "stopping", "message": "全集群中断指令已发送"}

_last_snap_scan_time = 0.0

@app.get("/api/status")
@app.get("/api/sync/heartbeat")
async def get_server_status_api():
    return {
        "status": "healthy",
        "build_id": BUILD_ID,
        "version": VERSION,
        "pid": os.getpid(),
        "started_at": SERVER_START_TIME,
        "timeout_seconds": DEFAULT_TASK_TIMEOUT,
        "accounts_total": len(manager.accounts),
        "orders_cached": sum(a.get("order_count", 0) for a in manager.accounts)
    }

def classify_account_status(a: dict) -> str:
    """
    对每个账号进行绝对排他、互斥的唯一状态归类。
    保证无交集、无重叠、无遗漏。
    枚举值：
    - 'pending': 待测
    - 'active': 正常活跃
    - 'wrong_password': 密码错误
    - 'account_locked': 官方封号锁定
    - 'two_factor_auth': 2FA验证码挑战
    - 'passkey_challenge': Passkey验证挑战
    - 'captcha_challenge': 人机滑块/风控拦截
    - 'proxy_timeout': 代理异常
    - 'network_timeout': 网络超时
    - 'order_error': 订单提取异常
    - 'other_failed': 基础登录失败 / 其他明确失败
    """
    fc = a.get("failure_category")
    if fc in [
        "wrong_password", "account_locked", "two_factor_auth", "passkey_challenge",
        "captcha_challenge", "proxy_timeout", "network_timeout", "order_error", "other_failed"
    ]:
        if a.get("status") == "正常活跃":
            return "active"
        if a.get("status") in ["未检测", "导入待测", "异常待重试", None, ""]:
            return "pending"
        return fc

    st = a.get("status") or ""
    msg = (a.get("message") or "").lower()

    if st in ["未检测", "导入待测", "异常待重试", ""] or not st:
        return "pending"
    if st == "正常活跃":
        return "active"
    if st == "密码错误" or "パスワードが正しくありません" in msg or "一致しません" in msg:
        return "wrong_password"
    if st in ["账号已冻结/锁定", "官方封号锁定"] or "アカウントをロック" in msg or "アカウントロック" in msg:
        return "account_locked"
    if st == "需Passkey验证" or "パスキー" in msg or "passkey" in msg:
        return "passkey_challenge"
    if st in ["需滑块验证", "风控拦截"] or "ロボット" in msg or "challenge" in msg or "画像認証" in msg:
        return "captcha_challenge"
    if st == "需2FA验证码" or "ワンタイム" in msg or "認証コード" in msg or "確認コード" in msg:
        return "two_factor_auth"
    if st in ["代理超时", "代理异常"] or "err_proxy" in msg or "代理" in st:
        return "proxy_timeout"
    if st == "网络超时" or "timeout" in msg or "timed out" in msg or "超时" in st:
        return "network_timeout"
    if st == "订单提取异常" or "订单" in st:
        return "order_error"
    return "other_failed"

@app.get("/api/task-status")
async def get_task_status():
    # 全局资产排他性统计（单次遍历，绝对互斥闭环）
    cat_counts = {
        "pending": 0, "active": 0, "wrong_password": 0, "account_locked": 0,
        "two_factor_auth": 0, "passkey_challenge": 0, "captcha_challenge": 0,
        "proxy_timeout": 0, "network_timeout": 0, "order_error": 0, "other_failed": 0
    }
    retrying_accounts = []  # 重试中账号（pending状态但有last_failure_category）
    
    for a in manager.accounts:
        cat = classify_account_status(a)
        cat_counts[cat] += 1
        # 识别重试中账号（脱敏哈希版本）
        if cat == "pending" and a.get("last_failure_category"):
            retrying_accounts.append({
                "email_hash": hashlib.sha256(a["email"].lower().encode('utf-8')).hexdigest(),
                "jitter_count": a.get("jitter_count", 0),
                "last_failure_category": a.get("last_failure_category"),
                "last_failure_code": a.get("last_failure_code"),
                "message_snippet": (a.get("message", "")[:40] if a.get("message") else "")
            })

    pending_count = cat_counts["pending"]
    active_count = cat_counts["active"]
    wrong_pwd_count = cat_counts["wrong_password"]
    locked_count = cat_counts["account_locked"]
    two_fa_count = cat_counts["two_factor_auth"]
    passkey_count = cat_counts["passkey_challenge"]
    captcha_count = cat_counts["captcha_challenge"]
    proxy_err_count = cat_counts["proxy_timeout"]
    network_err_count = cat_counts["network_timeout"]
    order_err_count = cat_counts["order_error"]
    other_fail_count = cat_counts["other_failed"]

    failed_total_count = (
        wrong_pwd_count + locked_count + two_fa_count + passkey_count +
        captcha_count + proxy_err_count + network_err_count + order_err_count +
        other_fail_count
    )

    now_ts = time.time()
    cleaned_nodes = {}
    total_len = len(manager.accounts)
    chunk_size = (total_len + 3) // 4 if total_len > 0 else 0

    # 聚合汇总 Node 1, 2, 3, 4 多线程状态与分盘统计
    for i in [1, 2, 3, 4]:
        pfx = f"Node_{i}"
        start_i = (i - 1) * chunk_size
        end_i = min(start_i + chunk_size, total_len)
        part_accs = manager.accounts[start_i:end_i] if start_i < total_len else []

        node_cats = {k: 0 for k in cat_counts}
        for a in part_accs:
            node_cats[classify_account_status(a)] += 1
        node_pending = node_cats["pending"]

        part_stats = {
            "total": len(part_accs),
            "pending": node_pending,
            "active": node_cats["active"],
            "wrong_password": node_cats["wrong_password"],
            "account_locked": node_cats["account_locked"],
            "two_factor_auth": node_cats["two_factor_auth"],
            "passkey_challenge": node_cats["passkey_challenge"],
            "captcha_challenge": node_cats["captcha_challenge"],
            "proxy_timeout": node_cats["proxy_timeout"],
            "network_timeout": node_cats["network_timeout"],
            "order_error": node_cats["order_error"],
            "other_failed": node_cats["other_failed"],  # 仅真正未识别的失败
            "failed_total": sum(v for k, v in node_cats.items() if k not in ["active", "pending"])
        }




        # 结构化节点 ID 匹配：优先使用注册字段，兼容旧记录但不做模糊前缀匹配
        def match_node_id(worker_key: str, worker: dict, node_num: int) -> bool:
            node_id = worker.get("node_id")
            if node_id:
                return str(node_id).casefold() == pfx.casefold()
            normalized = str(worker_key).replace(" ", "_").replace("-", "_")
            import re
            match = re.fullmatch(r"node_?(\d+)(?:_.*)?", normalized, re.IGNORECASE)
            return bool(match and int(match.group(1)) == node_num)
        
        matching = [w for w_key, w in cluster_nodes_state.items() if match_node_id(w_key, w, i)]
        if matching:
            active_threads = [m for m in matching if now_ts - m.get("last_seen_ts", 0) <= 60 and m.get("status") == "RUNNING"]
            tot_comp = sum(m.get("completed_count", 0) for m in matching)
            tot_phones = sum(m.get("phone_count", 0) for m in matching)
            running_accs = [m.get("current_account") for m in active_threads if m.get("current_account") and m.get("current_account") != "--"]
            
            if active_threads:
                cleaned_nodes[pfx] = {
                    "worker_id": pfx,
                    "status": "RUNNING",
                    "threads_count": len(active_threads),
                    "current_account": " | ".join(running_accs[:2]) + (f" (+{len(running_accs)-2})" if len(running_accs) > 2 else ""),
                    "completed_count": tot_comp,
                    "phone_count": tot_phones,
                    "partition": matching[0].get("partition", f"{i}/4"),
                    "part_stats": part_stats,
                    "last_seen": datetime.now().strftime("%H:%M:%S")
                }
            else:
                cleaned_nodes[pfx] = {
                    "worker_id": pfx,
                    "status": "IDLE",
                    "threads_count": 0,
                    "current_account": "--",
                    "completed_count": tot_comp,
                    "phone_count": tot_phones,
                    "partition": matching[0].get("partition", f"{i}/4"),
                    "part_stats": part_stats,
                    "last_seen": matching[0].get("last_seen", "--")
                }
        else:
            cleaned_nodes[pfx] = {
                "worker_id": pfx,
                "status": "IDLE",
                "threads_count": 0,
                "current_account": "--",
                "completed_count": 0,
                "phone_count": 0,
                "partition": f"{i}/4",
                "part_stats": part_stats,
                "last_seen": "--"
            }

    # 动态智能聚合实际进度，确保多服务器集群汇报实时投射到前端看板
    active_worker_threads = sum(node.get("threads_count", 0) for node in cleaned_nodes.values() if node.get("status") == "RUNNING")
    if active_worker_threads > 0 and not task_status.get("is_running"):
        task_status["is_running"] = True
        task_status["active_concurrency"] = active_worker_threads
        task_status["concurrency"] = active_worker_threads
        if not task_status.get("total") or task_status.get("total") == 0:
            task_status["total"] = pending_count + sum(m.get("completed_count", 0) for m in cluster_nodes_state.values())
    elif active_worker_threads == 0 and len(task_status.get("active_workers", {})) == 0:
        task_status["is_running"] = False
        task_status["active_concurrency"] = 0
        task_status["current"] = 0
        task_status["total"] = 0
        task_status["success_count"] = 0
        task_status["failed_count"] = 0
        task_status["current_account"] = ""

    task_status["active_concurrency"] = active_worker_threads
    if task_status.get("is_running"):
        tot_comp = sum(m.get("completed_count", 0) for m in cluster_nodes_state.values())
        if tot_comp > task_status.get("current", 0):
            task_status["current"] = tot_comp
        tot_target = task_status.get("total", 0)
        if tot_target > 0:
            diff_p = max(0, tot_target - pending_count)
            if diff_p > task_status.get("current", 0):
                task_status["current"] = diff_p
        start_act = task_status.get("start_active")
        if start_act is not None:
            new_active = max(0, active_count - start_act)
            curr = task_status.get("current", 0)
            succ = min(curr, new_active)
            task_status["success_count"] = succ
            task_status["failed_count"] = max(0, curr - succ)
        else:
            task_status["start_active"] = active_count
            task_status["success_count"] = 0
            task_status["failed_count"] = task_status.get("current", 0)




    return {
        **task_status,

        "build_id": BUILD_ID,
        "version": VERSION,
        "pid": os.getpid(),
        "started_at": SERVER_START_TIME,
        "timeout_seconds": DEFAULT_TASK_TIMEOUT,
        "cluster_config": {
            "node_count": CLUSTER_NODE_COUNT,
            "workers_per_node": CLUSTER_WORKERS_PER_NODE,
            "expected_total_workers": CLUSTER_TOTAL_WORKERS,
            "configured_concurrency": task_status.get("configured_concurrency", 1),
            "active_concurrency": active_worker_threads
        },
        "cluster_nodes": cleaned_nodes,
        "global_stats": {
            "total": len(manager.accounts),
            "pending": pending_count,
            "pending_breakdown": {
                "pure_pending": max(0, pending_count - len(retrying_accounts)),  # 防止负数
                "retrying": len(retrying_accounts)
            },
            "active": active_count,
            "failed_total": failed_total_count,
            "failed_breakdown": {
                "wrong_password": wrong_pwd_count,
                "account_locked": locked_count,
                "two_factor_auth": two_fa_count,
                "passkey_challenge": passkey_count,
                "captcha_challenge": captcha_count,
                "proxy_timeout": proxy_err_count,
                "network_timeout": network_err_count,
                "order_error": order_err_count,
                "other_failed": other_fail_count
            },
            "wrong_password": wrong_pwd_count,
            "account_locked": locked_count,
            "two_factor_auth": two_fa_count,
            "proxy_timeout": proxy_err_count,
            "other_failed": other_fail_count,
            "history_vault_count": len(manager.history_vault),
            "retrying_accounts_count": len(retrying_accounts)
        },
        "retrying_accounts_sample": retrying_accounts[:10] if len(retrying_accounts) <= 100 else []

    }

@app.get("/api/screenshots/{filename}")
async def get_screenshot(filename: str):
    # Resolve inside the screenshot directory; reject traversal and directories.
    root = os.path.realpath(SCREENSHOTS_DIR)
    file_path = os.path.realpath(os.path.join(root, filename))
    if os.path.commonpath([root, file_path]) != root or not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="截图不存在")
    return FileResponse(file_path, media_type="image/png")

@app.post("/api/worker/upload_screenshot")
async def upload_worker_screenshot(file: UploadFile = File(...)):
    """接收远程 Worker 回传的双重现场快照 (订单页 + 个人信息页)"""
    try:
        filename = os.path.basename(file.filename)
        # 安全清洗文件名，防止目录穿越
        filename = re.sub(r'[^a-zA-Z0-9_\-\.@]', '_', filename)
        if not filename.endswith(".png") and not filename.endswith(".jpg"):
            filename += ".png"
            
        target_path = os.path.join(SCREENSHOTS_DIR, filename)
        content = await file.read()
        with open(target_path, "wb") as f:
            f.write(content)
        return {"success": True, "filename": filename, "size": len(content)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存截图失败: {e}")

@app.get("/api/export/excel")
async def export_excel(scope: Optional[str] = "all", batch_id: Optional[str] = None, emails: Optional[str] = None):
    from csms_exporter import generate_csms_deliverable_excel
    parsed_emails = None
    if emails:
        try:
            parsed_emails = json.loads(emails) if emails.startswith("[") else [e.strip() for e in emails.split(",") if e.strip()]
        except Exception:
            parsed_emails = [e.strip() for e in emails.split(",") if e.strip()]

    target_accs = manager.get_accounts_by_scope(scope=scope or "all", batch_id=batch_id, emails=parsed_emails)
    
    if scope == "last_batch":
        last_b = manager.get_last_import_batch() or {}
        time_part = last_b.get("import_time", "").replace(":", "").replace("-", "").replace(" ", "_")
        tag = f"最近批次_{time_part}_{len(target_accs)}户" if time_part else f"最近批次_{len(target_accs)}户"
    elif scope == "batch" and batch_id:
        tag = f"批次_{batch_id}_{len(target_accs)}户"
    elif scope == "selected":
        tag = f"已选_{len(target_accs)}户"
    else:
        tag = f"全量_{len(target_accs)}户"

    try:
        file_path = await asyncio.to_thread(generate_csms_deliverable_excel, target_accs, tag)
    except Exception as exc:
        logging.exception("Excel export failed")
        raise HTTPException(status_code=500, detail=f"Excel 导出失败: {exc}") from exc

    import urllib.parse
    base_name = os.path.basename(file_path)
    encoded_name = urllib.parse.quote(base_name)
    headers = {
        "Content-Disposition": f"attachment; filename=\"{encoded_name}\"; filename*=UTF-8''{encoded_name}",
        "Access-Control-Expose-Headers": "Content-Disposition, X-Filename",
        "X-Filename": encoded_name
    }
    return FileResponse(file_path, headers=headers, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/api/export/csv")
async def export_csv(scope: Optional[str] = "all", batch_id: Optional[str] = None, emails: Optional[str] = None):
    parsed_emails = None
    if emails:
        try:
            parsed_emails = json.loads(emails) if emails.startswith("[") else [e.strip() for e in emails.split(",") if e.strip()]
        except Exception:
            parsed_emails = [e.strip() for e in emails.split(",") if e.strip()]

    target_accs = manager.get_accounts_by_scope(scope=scope or "all", batch_id=batch_id, emails=parsed_emails)

    if scope == "last_batch":
        last_b = manager.get_last_import_batch() or {}
        time_part = last_b.get("import_time", "").replace(":", "").replace("-", "").replace(" ", "_")
        tag = f"最近批次_{time_part}_{len(target_accs)}户" if time_part else f"最近批次_{len(target_accs)}户"
    elif scope == "batch" and batch_id:
        tag = f"批次_{batch_id}_{len(target_accs)}户"
    elif scope == "selected":
        tag = f"已选_{len(target_accs)}户"
    else:
        tag = f"全量_{len(target_accs)}户"

    file_path = manager.export_all_orders_to_csv(target_accounts=target_accs, export_tag=tag)
    import urllib.parse
    base_name = os.path.basename(file_path)
    encoded_name = urllib.parse.quote(base_name)
    headers = {
        "Content-Disposition": f"attachment; filename=\"{encoded_name}\"; filename*=UTF-8''{encoded_name}",
        "Access-Control-Expose-Headers": "Content-Disposition, X-Filename",
        "X-Filename": encoded_name
    }
    return FileResponse(file_path, headers=headers, media_type="text/csv")


cluster_nodes_state = {}

@app.post("/api/sync/heartbeat")
@app.get("/api/sync/heartbeat")
async def sync_heartbeat():
    return {"status": "ok", "service": "rakuten_manager"}

@app.get("/api/status")
async def compatibility_status():
    """统一监控状态接口，兼容分布式多节点集群实时监控。"""
    now_ts = time.time()
    stats = {}
    active_workers = {}
    pending = 0
    locked = 0
    for acc in manager.accounts:
        status = acc.get("status", "未检测")
        stats[status] = stats.get(status, 0) + 1
        if (acc.get("lock_until", 0) or 0) > now_ts:
            locked += 1
            worker = acc.get("locked_by", "unknown")
            active_workers[worker] = active_workers.get(worker, 0) + 1
        if status in ["未检测", "导入待测", "异常待重试"]:
            pending += 1
    total = len(manager.accounts)
    completed = total - pending - locked
    
    # 清理超时离线的节点状态 (超过 60 秒未活动的节点标记为 IDLE)
    cleaned_nodes = {}
    for w_id, w_info in cluster_nodes_state.items():
        time_diff = now_ts - w_info.get("last_seen_ts", 0)
        node_copy = dict(w_info)
        if time_diff > 60:
            node_copy["status"] = "IDLE"
            node_copy["current_account"] = "--"
        else:
            node_copy["status"] = "RUNNING"
        cleaned_nodes[w_id] = node_copy

    return {
        "total": total,
        "completed": max(0, completed),
        "pending": pending,
        "locked": locked,
        "progress_pct": round(max(0, completed) / max(1, total) * 100, 1),
        "stats": stats,
        "active_workers": active_workers,
        "cluster_nodes": cleaned_nodes,
        "task": task_status,
    }

@app.get("/api/queue")
async def compatibility_queue():
    """返回当前未锁定的待测队列。"""
    now_ts = time.time()
    queue = [
        {"email": a.get("email", ""), "status": a.get("status", "未检测")}
        for a in manager.accounts
        if a.get("status", "未检测") in ["未检测", "导入待测", "异常待重试"]
        and (a.get("lock_until", 0) or 0) <= now_ts
    ]
    return {"queue": queue, "total": len(queue)}

# =========================================================================
# 分布式 Worker 协同调度接口 (支持：静态分段硬隔离 与 双向动态原子锁)
# =========================================================================
@app.get("/api/worker/claim")
async def worker_claim_account(
    worker_id: str = "worker", 
    direction: str = "forward",
    partition_index: Optional[int] = None,
    total_partitions: Optional[int] = None
):
    now_ts = time.time()
    direction = (direction or "forward").lower()
    
    # 1. 只允许认领当前待测账号；没有待测账号时必须返回空，禁止回退到历史已测全库。
    pending_list = [
        a for a in manager.accounts
        if classify_account_status(a) == "pending"
        and now_ts > (a.get("lock_until") or 0)
    ]
    target_base = pending_list
    
    # 2. 如果开启了分段硬隔离 (例如分成 4 份)
    if total_partitions and total_partitions > 1 and partition_index is not None:
        p_idx = max(0, min(partition_index, total_partitions - 1))
        total_len = len(target_base)
        chunk_size = (total_len + total_partitions - 1) // total_partitions
        start_i = p_idx * chunk_size
        end_i = min(start_i + chunk_size, total_len)
        acc_list = target_base[start_i:end_i]
    else:
        acc_list = target_base

    # 按照方向排序遍历
    if direction == "reverse":
        acc_list = list(reversed(acc_list))

        
    found_acc = None
    for acc in acc_list:
        status = acc.get("status", "未检测")
        lock_until = acc.get("lock_until", 0)
        if status in ["未检测", "导入待测", "异常待重试"] and now_ts > lock_until:
            found_acc = acc
            break

    # 本分区无可用账号时执行受控 Work-Stealing，仅从未锁定的全局待测池借调。
    stole_from_partition = False
    if not found_acc and len(target_base) > len(acc_list):
        for acc in target_base:
            if acc not in acc_list:
                found_acc = acc
                stole_from_partition = True
                break

    if found_acc:
        acc = found_acc
        # 锁定 5 分钟 (300 秒)
        acc["lock_until"] = now_ts + 300
        acc["locked_by"] = worker_id
        manager.save_data()
            
        # 记录集群节点状态
        if worker_id not in cluster_nodes_state:
            cluster_nodes_state[worker_id] = {
                    "worker_id": worker_id,
                    "node_id": worker_id.split("_T", 1)[0].replace(" ", "_") if "_T" in worker_id else worker_id.replace(" ", "_"),
                    "thread_id": worker_id.split("_T", 1)[1] if "_T" in worker_id else worker_id,
                    "completed_count": 0,
                    "phone_count": 0,
                }
        cluster_nodes_state[worker_id].update({
            "status": "RUNNING",
                "current_account": acc["email"],
                "partition": f"{partition_index + 1}/{total_partitions}" if total_partitions else "all",
                "last_seen_ts": now_ts,
                "last_seen": datetime.now().strftime("%H:%M:%S")
        })

        # 返回全局剩余待测数，并记录是否发生跨分区借调。
        remaining = sum(1 for item in manager.accounts if classify_account_status(item) == "pending" and now_ts > (item.get("lock_until") or 0))
        part_info = f" [分区 {partition_index + 1}/{total_partitions}]" if total_partitions else ""
        await broadcaster.broadcast(f"[{worker_id}]{part_info} 成功认领账号: {acc['email']}" + (" [WORK_STEAL]" if stole_from_partition else ""), "STEP")
        return {
                "success": True,
                "account": {
                    "email": acc["email"],
                    "password": acc.get("password", ""),
                    "proxy": acc.get("proxy", "")
                },
                "remaining": remaining,
                "partition": f"{partition_index + 1}/{total_partitions}" if total_partitions else "all",
                "work_steal": stole_from_partition,
                "remaining_global": remaining
            }
            
    return {"success": False, "message": "该分区分派完毕或全量已完成", "remaining": 0}

def get_cliproxy_pool():
    p_file = os.path.join(DATA_DIR, "cliproxy_raw.txt")
    if os.path.exists(p_file):
        try:
            with open(p_file, "r", encoding="utf-8") as f:
                return [line.strip() for line in f if line.strip()]
        except Exception:
            pass
    return []

@app.post("/api/worker/report")
async def worker_report_result(req: Request):
    data = await req.json()
    email = data.get("email", "").strip()
    status = data.get("status", "登录失败")
    message = data.get("message", "")
    worker_id = data.get("worker_id", "remote_worker")
    
    acc = next((a for a in manager.accounts if a["email"].lower() == email.lower()), None)
    if acc:
        # 1. 严格遵照 3 次重试上限防死锁铁律 (3-Strike Cap Invariant)：
        # 任何非“正常活跃”且非“密码错误”的账号，最多移至队尾重试 3 次；
        # 达到 3 次后强制固化为终态（需2FA验证码/登录失败/风控拦截），绝对严禁无限移回队尾！
        is_abnormal_or_jitter = (status != "正常活跃" and status != "密码错误")

        # 官方封号锁定无论第几次，立即固化终态，绝不放回队尾！
        if status in ["账号已冻结/锁定", "官方封号锁定"] or "ロック" in message:
            acc["status"] = "账号已冻结/锁定"
            acc["failure_category"] = "account_locked"
            acc["failure_code"] = "ACCOUNT_LOCKED"
            acc["terminal"] = True
            acc["message"] = f"官方封号冻结: {message[:40]}"
            acc["lock_until"] = 0
            acc["locked_by"] = ""
            acc["last_check"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            manager.save_data()
            task_status["current"] = task_status.get("current", 0) + 1
            task_status["failed_count"] = task_status.get("failed_count", 0) + 1
            await broadcaster.broadcast(f"[{worker_id}] 🛑 账号 {email} 确认为官方封号锁定，强制落盘终态，不再重试！", "WARNING")
            return {"success": True, "action": "finalized_locked"}

        if is_abnormal_or_jitter:
            curr_jitter = acc.get("jitter_count", 0) + 1
            acc["jitter_count"] = curr_jitter

            if curr_jitter >= 3:
                # 满 3 次直接落盘终态，必须保留确切的原始失败类型，绝对禁止全部压扁成“登录失败”！
                valid_failure_statuses = [
                    "需2FA验证码", "需滑块验证", "需Passkey验证", "风控拦截",
                    "代理异常", "网络超时", "账号已冻结/锁定", "页面结构异常", "订单提取异常", "密码错误"
                ]
                final_st = status if status in valid_failure_statuses else "登录失败"
                acc["status"] = final_st
                acc["terminal"] = True
                acc["failure_category"] = (
                    "two_factor_auth" if "2FA" in final_st else
                    "captcha_challenge" if ("滑块" in final_st or "风控" in final_st) else
                    "passkey_challenge" if "Passkey" in final_st else
                    "account_locked" if ("冻结" in final_st or "锁定" in final_st) else
                    "proxy_timeout" if "代理" in final_st else
                    "network_timeout" if "超时" in final_st else
                    "order_error" if "订单" in final_st else
                    "other_failed"
                )
                acc["failure_code"] = (
                    "2FA_CHALLENGE" if "2FA" in final_st else
                    "CAPTCHA_CHALLENGE" if ("滑块" in final_st or "风控" in final_st) else
                    "PASSKEY_REQUIRED" if "Passkey" in final_st else
                    "ACCOUNT_LOCKED" if ("冻结" in final_st or "锁定" in final_st) else
                    "PROXY_TIMEOUT" if "代理" in final_st else
                    "NETWORK_TIMEOUT" if "超时" in final_st else
                    "ORDER_EXTRACTION_ERROR" if "订单" in final_st else
                    "LOGIN_FAILED"
                )
                acc["message"] = f"已达3次重试上限，强制锁定终态 [{final_st}]: {message[:40]}"
                acc["lock_until"] = 0
                acc["locked_by"] = ""
                acc["last_check"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                manager.save_data()

                # 推进任务失败计数
                task_status["current"] = task_status.get("current", 0) + 1
                task_status["failed_count"] = task_status.get("failed_count", 0) + 1

                if worker_id in cluster_nodes_state:
                    cluster_nodes_state[worker_id]["current_account"] = "--"
                    cluster_nodes_state[worker_id]["last_seen_ts"] = time.time()

                await broadcaster.broadcast(
                    f"[{worker_id}] 🛑 账号 {email} 达3次上限，强制锁定终态 [{final_st}]，不再移入队尾！",
                    "WARNING"
                )
                return {"success": True, "action": "finalized_after_3_strikes"}


            # 未满 3 次，放入队尾继续重试
            acc["status"] = "未检测"
            acc["last_failure_category"] = data.get("failure_category") or "other_failed"
            acc["last_failure_code"] = data.get("failure_code") or "LOGIN_FAILED"
            acc["message"] = f"异常移至队尾重试(第{curr_jitter}/3次): {message[:40]}"
            acc["lock_until"] = 0
            acc["locked_by"] = ""
            # 自动轮换新代理
            proxies = get_cliproxy_pool()
            if proxies:
                acc["proxy"] = random.choice(proxies)

            # 物理移至该分区的队尾，让出当前席位给后续正常账号
            try:
                curr_idx = manager.accounts.index(acc)
                total_len = len(manager.accounts)
                chunk_size = (total_len + 3) // 4
                p_idx = curr_idx // chunk_size
                is_reverse = "reverse" in worker_id.lower() or "Node_4" in worker_id

                if is_reverse:
                    start_i = p_idx * chunk_size
                    if curr_idx != start_i:
                        manager.accounts.pop(curr_idx)
                        manager.accounts.insert(start_i, acc)
                else:
                    end_i = min((p_idx + 1) * chunk_size, total_len)
                    if curr_idx < end_i - 1:
                        manager.accounts.pop(curr_idx)
                        manager.accounts.insert(end_i - 1, acc)
            except Exception as e:
                logging.warning(f"Reorder jitter account error: {e}")

            manager.save_data()

            if worker_id in cluster_nodes_state:
                cluster_nodes_state[worker_id]["current_account"] = "--"
                cluster_nodes_state[worker_id]["last_seen_ts"] = time.time()

            await broadcaster.broadcast(
                f"[{worker_id}] ⚠️ 账号 {email} 遇异常，已移至队尾排队 (第{curr_jitter}/3次，换新代理)", 
                "WARNING"
            )
            return {"success": True, "action": "moved_to_tail"}


        # 正常流程更新
        acc["status"] = status
        acc["message"] = message
        acc["last_check"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        acc["lock_until"] = 0
        acc["tested_by"] = worker_id
        acc["terminal"] = (status != "正常活跃")
        
        # 统一分类器标签写入（绝对互斥闭环）
        if status == "正常活跃":
            # 正常活跃账号清空失败分类
            acc.pop("failure_category", None)
            acc.pop("failure_code", None)
        elif status == "密码错误":
            acc["failure_category"] = "wrong_password"
            acc["failure_code"] = "WRONG_PASSWORD"
        else:
            # 其他状态通过分类器统一判定
            inferred_cat = classify_account_status(acc)
            if inferred_cat not in ["pending", "active"]:
                acc["failure_category"] = inferred_cat
                acc["failure_code"] = {
                    "wrong_password": "WRONG_PASSWORD",
                    "account_locked": "ACCOUNT_LOCKED",
                    "two_factor_auth": "2FA_CHALLENGE",
                    "passkey_challenge": "PASSKEY_REQUIRED",
                    "captcha_challenge": "CAPTCHA_CHALLENGE",
                    "proxy_timeout": "PROXY_TIMEOUT",
                    "network_timeout": "NETWORK_TIMEOUT",
                    "order_error": "ORDER_EXTRACTION_ERROR",
                    "other_failed": "LOGIN_FAILED"
                }.get(inferred_cat, "LOGIN_FAILED")
        
        # 深度信息更新
        for field in [
            "phone", "last_name", "first_name", "last_name_kana", "first_name_kana",
            "birthday", "gender", "zipcode", "address", "card_info",
            "order_count", "total_spent", "orders",
            "login_screenshot", "orders_screenshot", "profile_screenshot"
        ]:
            if field in data and data[field] is not None:
                acc[field] = data[field]
                
        manager.save_data()
        
        # 更新集群节点统计
        if worker_id not in cluster_nodes_state:
            cluster_nodes_state[worker_id] = {
                "worker_id": worker_id,
                "node_id": worker_id.split("_T", 1)[0].replace(" ", "_") if "_T" in worker_id else worker_id.replace(" ", "_"),
                "thread_id": worker_id.split("_T", 1)[1] if "_T" in worker_id else worker_id,
                "completed_count": 0,
                "phone_count": 0,
            }
        cluster_nodes_state[worker_id]["completed_count"] = cluster_nodes_state[worker_id].get("completed_count", 0) + 1
        if acc.get("phone"):
            cluster_nodes_state[worker_id]["phone_count"] = cluster_nodes_state[worker_id].get("phone_count", 0) + 1
        cluster_nodes_state[worker_id]["last_seen_ts"] = time.time()
        cluster_nodes_state[worker_id]["last_seen"] = datetime.now().strftime("%H:%M:%S")
        cluster_nodes_state[worker_id]["current_account"] = "--"
        
        # 实时推进全局 task_status 进度，使前端进度看板实时更新
        task_status["current"] = task_status.get("current", 0) + 1
        if status == "正常活跃":
            task_status["success_count"] = task_status.get("success_count", 0) + 1
        else:
            task_status["failed_count"] = task_status.get("failed_count", 0) + 1

        ph_disp = f" | 手机: {acc.get('phone')}" if acc.get("phone") else ""

        nm_disp = f" | 姓名: {acc.get('last_name', '')} {acc.get('first_name', '')}".strip() if (acc.get("last_name") or acc.get("first_name")) else ""
        await broadcaster.broadcast(
            f"[{worker_id}] 汇报完成: {email} -> {status}{ph_disp}{nm_disp} ({message})", 
            "SUCCESS" if status == "正常活跃" else "WARNING"
        )
        return {"success": True}
    return {"success": False, "message": "未找到该账号"}


@app.websocket("/ws/logs")
async def websocket_endpoint(websocket: WebSocket):
    await broadcaster.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        broadcaster.disconnect(websocket)
    except Exception:
        broadcaster.disconnect(websocket)

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_path = os.path.join(TEMPLATES_DIR, "index.html")
    with open(index_path, "r", encoding="utf-8") as f:
        content = f.read()
    return HTMLResponse(content=content)


if __name__ == "__main__":
    import uvicorn
    print("=" * 65)
    print(" Rakuten Japan 多账号订单协议中枢启动中 (极速轻量 v2.0)")
    print(" Web 控制台: http://127.0.0.1:8998")
    print("=" * 65)
    uvicorn.run(app, host="0.0.0.0", port=8998, log_level="warning")
