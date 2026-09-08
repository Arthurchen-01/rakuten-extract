# -*- coding: utf-8 -*-
"""
Multi-Node Periodic Sync & Bana JSON Audit Reporter
集群定点同步与 Bana 8 要素 JSON 验真汇报器
支持采集 CPU/内存负载、无锁结果聚合与实时控制台审计汇报
"""
import sys
import os
import json
import time
import socket
import paramiko
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

def sync_and_report_cluster(nodes_config, local_results_file, remote_run_dir="/opt/rakuten_run", total_expected=None, bind_ip=None):
    local_p = Path(local_results_file)
    local_p.parent.mkdir(parents=True, exist_ok=True)
    
    all_results = []
    node_stats = []
    
    for node in nodes_config:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            if bind_ip:
                sock.bind((bind_ip, 0))
            sock.settimeout(15)
            sock.connect((node['host'], node.get('port', 22)))
            trans = paramiko.Transport(sock)
            trans.connect(username=node['user'], password=node['pass'])
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh._transport = trans
            
            stdin, stdout, stderr = ssh.exec_command("top -bn1 | grep 'Cpu(s)' | awk '{print $2}'")
            cpu = stdout.read().decode('utf-8').strip()
            stdin, stdout, stderr = ssh.exec_command("free -m | awk 'NR==2{printf \"%.1f%% (%s/%s MB)\", $3*100/$2, $3, $2 }'")
            mem = stdout.read().decode('utf-8').strip()
            stdin, stdout, stderr = ssh.exec_command("ps aux | grep 'rakuten_worker.py' | grep -v grep | wc -l")
            procs = stdout.read().decode('utf-8').strip()
            
            node_stats.append({
                'id': node['id'],
                'host': node['host'],
                'cpu': cpu or '0.0',
                'mem': mem or '0.0%',
                'procs': procs or '0'
            })
            
            sftp = ssh.open_sftp()
            # 优先读取 batch_summary.json，若无则扫描单个 result_*.json
            has_summary = False
            try:
                with sftp.open(f"{remote_run_dir}/batch_summary.json", 'r') as sf:
                    summary_data = json.load(sf)
                    for item in summary_data:
                        item['node_source'] = node['id']
                    all_results.extend(summary_data)
                    has_summary = True
            except Exception:
                pass
                
            if not has_summary:
                stdin, stdout, stderr = ssh.exec_command(f"ls {remote_run_dir}/result_*.json {remote_run_dir}/results_w*.json 2>/dev/null")
                remote_files = stdout.read().decode('utf-8').split()
                for rf_path in remote_files:
                    try:
                        with sftp.open(rf_path, 'r') as rf:
                            part_data = json.load(rf)
                            if isinstance(part_data, list):
                                for item in part_data: item['node_source'] = node['id']
                                all_results.extend(part_data)
                            elif isinstance(part_data, dict):
                                part_data['node_source'] = node['id']
                                all_results.append(part_data)
                    except Exception:
                        pass
            sftp.close()
            trans.close()
        except Exception as e:
            node_stats.append({
                'id': node['id'],
                'host': node['host'],
                'cpu': 'ERR',
                'mem': 'ERR',
                'procs': '0'
            })

    seen = {}
    for r in all_results:
        em = r.get('email')
        if not em:
            continue
        if em not in seen or (r.get('order_count', 0) > seen[em].get('order_count', 0)):
            seen[em] = r
            
    final_list = sorted(list(seen.values()), key=lambda x: x.get('row_idx', 9999))
    
    with open(local_p, 'w', encoding='utf-8') as f:
        json.dump(final_list, f, ensure_ascii=False, indent=2)
        
    active_count = sum(1 for r in final_list if r.get('status') == 'active')
    fail_count = sum(1 for r in final_list if r.get('status') != 'active')
    total_orders = sum(r.get('order_count', 0) for r in final_list)
    tot = total_expected or len(final_list) or 1

    print("=" * 85)
    print(f"📊 【分布式集群 · 定点 Bana 8 要素 JSON 验真汇报】 @ {time.strftime('%H:%M:%S')}")
    print("=" * 85)
    print("🖥️ 【服务器物理资源与运行状态】:")
    for s in node_stats:
        status_icon = "🟢" if int(s['procs']) > 0 else "🏁"
        print(f"  {status_icon} {s['id']} ({s['host']}) | CPU: {s['cpu']}% | 内存: {s['mem']} | 活跃并发: {s['procs']}")

    print("-" * 85)
    pct = len(final_list) / tot * 100
    print(f"📈 【大盘总进度】已入库: {len(final_list)} / {tot} 户 ({pct:.1f}%) | 活跃: {active_count} | 失败: {fail_count} | 订单总数: {total_orders} 笔")
    print("-" * 85)
    
    active_samples = [r for r in final_list if r.get('status') == 'active' and r.get('order_count', 0) > 0]
    if active_samples:
        print("🔍 【最新入库大号真实 JSON 原文字段验真】:\n")
        for s in active_samples[-2:]:
            p = s.get('profile', {})
            ords = s.get('bana_orders', [])
            print(f"👉 账号: {s['email']} | 节点: {s.get('node_source', 'N/A')} | 状态: {s['status']} | 订单数: {s.get('order_count', 0)}")
            print(f"   ├─ 姓名: {p.get('full_name', '')}")
            print(f"   ├─ 门牌地址: {p.get('address', '').replace(chr(10), ' ')}")
            print(f"   ├─ 支付方式: {p.get('card_info', '')} | 持卡人: {p.get('card_holder', '')}")
            if ords:
                print(f"   └─ 订单1 Bana 完整块 (前 150 字符):\n      {repr(ords[0][:150])}")
            print()
    print("=" * 85)
    return final_list
