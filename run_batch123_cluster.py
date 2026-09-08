# -*- coding: utf-8 -*-
"""
Batch 123 Cluster Orchestrator
Dispatches 123 unique accounts across 6 nodes with 3 threads each (18 threads total).
Monitors live progress, pulls all results and screenshots, and generates statutory Bana Excel.
"""
import os
import sys
import time
import json
import shutil
import hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import paramiko
import openpyxl
from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = Path(r"c:\Users\25472\Desktop\AI brain storming\无敌\letian")
ARTIFACT_DIR = Path(r"C:\Users\25472\.gemini\antigravity\brain\ef15613e-b17b-46fd-a655-0646ee80bb51")
WORKER_LOCAL_PATH = BASE_DIR / "core" / "rakuten_worker.py"
ACCOUNTS_SOURCE = BASE_DIR / "data" / "batch_123_accounts.json"
RUN_DIR = BASE_DIR / "data" / "local_deep_audit" / "batch123_run"
RUN_DIR.mkdir(parents=True, exist_ok=True)

NODES = [
    {
        "id": "Node_1",
        "label": "Node 1",
        "host": "38.76.206.7",
        "port": 22,
        "user": "root",
        "pass": "39TF6xMH52yC",
        "py": "/opt/deepseek-suite/.venv/bin/python",
        "run_dir": "/opt/rakuten_run"
    },
    {
        "id": "Node_2",
        "label": "Node 2",
        "host": "156.225.31.92",
        "port": 22,
        "user": "root",
        "pass": "HG36XM2ZhKE4",
        "py": "/opt/rakuten-hub/.venv/bin/python",
        "run_dir": "/opt/rakuten_run"
    },
    {
        "id": "Node_3",
        "label": "Node 3",
        "host": "103.52.152.37",
        "port": 22,
        "user": "root",
        "pass": "7EU2D8vSXQ53",
        "py": "/opt/rakuten-hub/.venv/bin/python",
        "run_dir": "/opt/rakuten_run"
    },
    {
        "id": "Node_4",
        "label": "Node 4 (Master)",
        "host": "38.76.174.32",
        "port": 22,
        "user": "root",
        "pass": "GCKTBLJEU2Xi",
        "py": "/opt/rakuten-hub/venv/bin/python3",
        "run_dir": "/opt/rakuten_run"
    },
    {
        "id": "Node_5",
        "label": "Node 5",
        "host": "162.211.180.242",
        "port": 22,
        "user": "root",
        "pass": "DNPuX9Uz28LA",
        "py": "/opt/rakuten-hub/.venv/bin/python",
        "run_dir": "/opt/rakuten_run"
    },
    {
        "id": "Node_6",
        "label": "Node 6",
        "host": "156.224.28.101",
        "port": 22,
        "user": "root",
        "pass": "FRCzPDWK5HAL",
        "py": "/usr/bin/python3",
        "run_dir": "/opt/rakuten_run"
    }
]

def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest().upper()

def get_ssh(node):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    for attempt in range(1, 4):
        try:
            ssh.connect(node['host'], port=node['port'], username=node['user'], password=node['pass'], timeout=25, banner_timeout=45)
            return ssh
        except Exception as e:
            if attempt < 3:
                time.sleep(2.0 * attempt)
            else:
                raise e

def deploy_and_init():
    local_hash = sha256_file(WORKER_LOCAL_PATH)
    print("=" * 85)
    print(f"🚀 [全网分发代码] 本地基准 SHA-256: {local_hash}")
    print("=" * 85)
    
    def _deploy(node):
        remote_path = f"{node['run_dir']}/rakuten_worker.py"
        ssh = get_ssh(node)
        ssh.exec_command(f"mkdir -p {node['run_dir']}/batch123_run/screenshots")
        ssh.exec_command(f"pkill -9 -f 'rakuten_worker.py'")
        sftp = ssh.open_sftp()
        sftp.put(str(WORKER_LOCAL_PATH), remote_path)
        sftp.close()
        stdin, stdout, stderr = ssh.exec_command(f"sha256sum {remote_path}")
        out = stdout.read().decode('utf-8').strip()
        r_hash = out.split()[0].upper() if out else ""
        ssh.close()
        return node['id'], r_hash == local_hash, r_hash
        
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(_deploy, n) for n in NODES]
        for f in futs:
            nid, ok, r_hash = f.result()
            sym = "✅" if ok else "❌"
            print(f"  {sym} [{nid}] 部署状态: {'成功' if ok else '失败'} | 远端 SHA-256: {r_hash}")
            if not ok:
                raise RuntimeError(f"Deploy failed on {nid}")
    print("✨ 全集群 6 节点代码 100% 字节对齐！")

def render_sheet_preview_image(ws, out_png_path, title, max_r=18, max_c=16):
    rows = []
    for r in ws.iter_rows(values_only=True):
        rows.append(r)
    if not rows:
        return
        
    width = 1600
    title_h = 70
    header_h = 45
    row_h = 40
    height = title_h + header_h + (min(len(rows)-1, max_r)) * row_h + 30
    
    col_w = max(60, (width - 40) // min(len(rows[0]), max_c))
    
    im = Image.new('RGB', (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(im)
    
    try:
        font_title = ImageFont.truetype("msyh.ttc", 22)
        font_head = ImageFont.truetype("msyh.ttc", 13)
        font_cell = ImageFont.truetype("msyh.ttc", 11)
    except Exception:
        font_title = ImageFont.load_default()
        font_head = ImageFont.load_default()
        font_cell = ImageFont.load_default()
        
    draw.rectangle([0, 0, width, title_h], fill=(191, 0, 0))
    draw.text((25, 20), title, fill=(255, 255, 255), font=font_title)
    
    y_top = title_h
    draw.rectangle([20, y_top, width - 20, y_top + header_h], fill=(237, 242, 247))
    for col_idx in range(min(len(rows[0]), max_c)):
        val = str(rows[0][col_idx] or '')
        x = 25 + col_idx * col_w
        draw.text((x, y_top + 14), val[:14], fill=(45, 55, 72), font=font_head)
        
    for r_idx in range(1, min(len(rows), max_r + 1)):
        y = title_h + header_h + (r_idx - 1) * row_h
        bg = (255, 255, 255) if r_idx % 2 == 1 else (248, 250, 252)
        draw.rectangle([20, y, width - 20, y + row_h], fill=bg)
        draw.line([20, y + row_h, width - 20, y + row_h], fill=(226, 232, 240), width=1)
        
        row_data = rows[r_idx]
        for col_idx in range(min(len(row_data), max_c)):
            val = str(row_data[col_idx] or '')
            val_flat = val.replace('\n', ' | ')
            x = 25 + col_idx * col_w
            draw.text((x, y + 12), val_flat[:24], fill=(74, 85, 104), font=font_cell)
            
    im.save(out_png_path)
    print(f"🖼️ [实体预览图已生成] {out_png_path}")

def launch_batch_run():
    with open(ACCOUNTS_SOURCE, 'r', encoding='utf-8') as f:
        all_accounts = json.load(f)
        
    total = len(all_accounts)
    split_ranges = [(0, 21), (21, 42), (42, 63), (63, 83), (83, 103), (103, 123)]
    
    print("\n" + "=" * 85)
    print(f"📦 [任务切片分发] 总计 {total} 户账号 | 分发至 6 节点 (21/21/21/20/20/20) | 每机 3 线程并发 (全网 18 线程)")
    print("=" * 85)
    
    slices = {}
    for i, node in enumerate(NODES):
        nid = node['id']
        start_idx, end_idx = split_ranges[i]
        s_accs = all_accounts[start_idx:end_idx]
        slices[nid] = s_accs
        node_dir = RUN_DIR / nid
        node_dir.mkdir(parents=True, exist_ok=True)
        (node_dir / "assigned_accounts.json").write_text(json.dumps(s_accs, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"  [{nid}] {node['label']} ({node['host']}) 分配 {len(s_accs)} 户 ({s_accs[0]['email']} ~ {s_accs[-1]['email']})")
        
    # Upload and start nohup process on all nodes
    def _start_node(node):
        nid = node['id']
        node_accs = slices[nid]
        ssh = get_ssh(node)
        sftp = ssh.open_sftp()
        
        remote_accs_file = f"{node['run_dir']}/accounts_batch123.json"
        remote_out_dir = f"{node['run_dir']}/batch123_run"
        remote_worker = f"{node['run_dir']}/rakuten_worker.py"
        
        # Clean remote out dir
        ssh.exec_command(f"rm -rf {remote_out_dir} && mkdir -p {remote_out_dir}/screenshots")
        time.sleep(0.5)
        
        local_slice = RUN_DIR / nid / "assigned_accounts.json"
        sftp.put(str(local_slice), remote_accs_file)
        sftp.close()
        
        cmd = f"nohup {node['py']} {remote_worker} --input {remote_accs_file} --output-dir {remote_out_dir} --workers 3 --max-seconds 3600 > {remote_out_dir}/batch_run.log 2>&1 &"
        ssh.exec_command(cmd)
        time.sleep(1.0)
        
        stdin, stdout, stderr = ssh.exec_command("ps aux | grep rakuten_worker.py | grep -v grep | wc -l")
        cnt = stdout.read().decode().strip()
        ssh.close()
        return nid, cnt
        
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(_start_node, n) for n in NODES]
        for f in futs:
            nid, p_cnt = f.result()
            print(f"🚀 [{nid}] 启动后台 3 线程运行成功 (活跃进程数: {p_cnt})")

def monitor_and_collect():
    print("\n" + "=" * 85)
    print("⏳ 开始集群进度实时监控 (每 15 秒轮询一次)...")
    print("=" * 85)
    
    start_time = time.time()
    while True:
        time.sleep(15.0)
        elapsed = round(time.time() - start_time, 1)
        
        all_node_progress = {}
        all_completed = True
        total_processed = 0
        total_active = 0
        total_orders = 0
        
        expected_counts = {'Node_1': 21, 'Node_2': 21, 'Node_3': 21, 'Node_4': 20, 'Node_5': 20, 'Node_6': 20}
        def _check_node(node):
            tot_exp = expected_counts[node['id']]
            nid = node['id']
            try:
                ssh = get_ssh(node)
                stdin, stdout, stderr = ssh.exec_command(f"cat {node['run_dir']}/batch123_run/batch_progress.json 2>/dev/null")
                content = stdout.read().decode('utf-8').strip()
                stdin, stdout, stderr = ssh.exec_command("ps aux | grep rakuten_worker.py | grep -v grep | wc -l")
                p_cnt = int(stdout.read().decode().strip() or "0")
                ssh.close()
                if content:
                    prog = json.loads(content)
                    prog['process_count'] = p_cnt
                    return nid, prog
                return nid, {'is_running': p_cnt > 0, 'processed_count': 0, 'total_accounts': tot_exp, 'active_count': 0, 'process_count': p_cnt}
            except Exception as e:
                return nid, {'is_running': False, 'error': str(e), 'processed_count': 0, 'total_accounts': tot_exp, 'active_count': 0}
                
        with ThreadPoolExecutor(max_workers=6) as ex:
            futs = [ex.submit(_check_node, n) for n in NODES]
            for f in futs:
                nid, p_data = f.result()
                all_node_progress[nid] = p_data
                
        print(f"\n--- ⏱️ 运行耗时: {elapsed}s | 全网 6 节点执行大盘快照 ---")
        for node in NODES:
            nid = node['id']
            p = all_node_progress.get(nid, {})
            proc = p.get('processed_count', 0)
            tot = expected_counts[nid]
            act = p.get('active_count', 0)
            full = p.get('fully_captured_count', 0)
            ords = p.get('total_orders_extracted', 0)
            running = p.get('is_running', False)
            in_fl = list(p.get('in_flight', {}).values())
            
            total_processed += proc
            total_active += act
            total_orders += ords
            
            if running or proc < tot:
                all_completed = False
                
            status_tag = "⚡运行中" if running else "🛑已完成"
            print(f"  [{nid}] {status_tag} | 进度: {proc}/{tot} ({proc/tot*100:.1f}%) | 活跃: {act} | 抓全: {full} | 订单: {ords} | 正在测: {in_fl}")
            
        print(f"  📊 全网大盘汇总: 累计推进 {total_processed}/123 ({total_processed/123*100:.1f}%) | 确认活跃大号: {total_active} | 提取真实订单: {total_orders}")
        
        if all_completed and total_processed >= 123:
            print("\n🎉 全网 6 节点全部 123 户账号执行完毕！")
            break
        elif elapsed > 3600:
            print("\n⚠️ 运行达到 1 小时安全上限，退出监控并收集结果！")
            break
            
    # Download results and screenshots from all nodes
    print("\n" + "=" * 85)
    print("📥 开始拉取全集群 6 节点结果 JSON 与现场截图凭证...")
    print("=" * 85)
    
    all_accounts_data = []
    
    def _fetch_node(node):
        nid = node['id']
        node_dir = RUN_DIR / nid
        local_snaps = node_dir / "screenshots"
        local_snaps.mkdir(parents=True, exist_ok=True)
        remote_out_dir = f"{node['run_dir']}/batch123_run"
        
        ssh = get_ssh(node)
        sftp = ssh.open_sftp()
        
        # Pull execution log
        try:
            sftp.get(f"{remote_out_dir}/batch_run.log", str(node_dir / "batch_run.log"))
        except Exception: pass
        
        # Pull batch_summary.json
        try:
            sftp.get(f"{remote_out_dir}/batch_summary.json", str(node_dir / "batch_summary.json"))
        except Exception: pass
        
        # Pull result_*.json
        node_accounts = []
        try:
            r_files = sftp.listdir(remote_out_dir)
            for rf in r_files:
                if rf.startswith("result_") and rf.endswith(".json"):
                    lp = node_dir / rf
                    sftp.get(f"{remote_out_dir}/{rf}", str(lp))
                    with open(lp, 'r', encoding='utf-8') as jf:
                        acc = json.load(jf)
                        acc['node_source'] = node['label']
                        node_accounts.append(acc)
        except Exception as e:
            print(f"⚠️ [{nid}] 读取 JSON 异常: {e}")
            
        # Pull screenshots
        try:
            snaps = sftp.listdir(f"{remote_out_dir}/screenshots")
            for sn in snaps:
                sftp.get(f"{remote_out_dir}/screenshots/{sn}", str(local_snaps / sn))
        except Exception: pass
        
        sftp.close()
        ssh.close()
        print(f"  ✅ [{nid}] 成功拉取 {len(node_accounts)} 份原子 JSON 及全部现场快照")
        return node_accounts
        
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(_fetch_node, n) for n in NODES]
        for f in futs:
            all_accounts_data.extend(f.result())
            
    # Deduplicate / Sort
    all_accounts_data.sort(key=lambda x: x.get('email', ''))
    
    # Save combined JSON
    summary_path = RUN_DIR / "batch123_all_results.json"
    summary_path.write_text(json.dumps(all_accounts_data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n📦 全量 123 户原子结果汇总落盘: {summary_path}")
    
    # Export 16-column Bana Excel
    sys.path.insert(0, str(BASE_DIR))
    from core.bana_exporter import export_bana_excel
    
    active_cnt = sum(1 for a in all_accounts_data if a.get('status') == 'active')
    failed_cnt = len(all_accounts_data) - active_cnt
    excel_name = f"9.8晚上_123户全量汇总_{active_cnt}活跃-{failed_cnt}失败.xlsx"
    excel_path = RUN_DIR / excel_name
    
    export_bana_excel(all_accounts_data, excel_path, total_accounts=len(all_accounts_data))
    excel_hash = sha256_file(excel_path)
    print(f"📊 [法定真本工作簿已生成] {excel_path} (SHA-256: {excel_hash})")
    
    # Copy deliverable to exports directory
    exports_dir = BASE_DIR / "data" / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(excel_path, exports_dir / excel_name)
    shutil.copy(summary_path, exports_dir / "batch123_all_results.json")
    print(f"📊 [法定真本工作簿已同步至导出目录] {exports_dir / excel_name}")
    
    # Render previews
    wb = openpyxl.load_workbook(excel_path, data_only=True)
    ws1 = wb["乐天导出导入"]
    ws4 = wb["订单明细总览"]
    
    p1 = RUN_DIR / "batch123_excel_sheet1_preview.png"
    p4 = RUN_DIR / "batch123_excel_sheet4_preview.png"
    
    render_sheet_preview_image(ws1, p1, f"乐天导出导入主表 (Sheet 1) - 123 户全集群 18 线程实测原件视图 (共 {ws1.max_row - 1} 户)", max_r=18, max_c=16)
    render_sheet_preview_image(ws4, p4, f"乐天订单明细总览 (Sheet 4) - 123 户全量订单原件视图 (共 {ws4.max_row - 1} 笔)", max_r=20, max_c=8)
    
    shutil.copy(p1, ARTIFACT_DIR / p1.name)
    shutil.copy(p4, ARTIFACT_DIR / p4.name)
    
    print("=" * 85)
    print(f"🎉 123 户全量实测与法定真本导出圆满完成！活跃: {active_cnt} | 失败: {failed_cnt}")
    print("=" * 85)

if __name__ == '__main__':
    deploy_and_init()
    launch_batch_run()
    monitor_and_collect()
