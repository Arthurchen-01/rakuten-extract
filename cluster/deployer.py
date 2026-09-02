# -*- coding: utf-8 -*-
"""
Multi-Node Distributed Cluster Deployer
4 台 / 多台独立云节点集群部署工具
支持多 Worker 模数并发调度与账号物理分片
"""
import sys
import os
import json
import socket
import paramiko
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

def deploy_cluster(nodes_config, accounts_file, remote_run_dir="/opt/rakuten_run", workers_per_node=3, bind_ip=None):
    with open(accounts_file, 'r', encoding='utf-8') as f:
        all_accounts = json.load(f)
        
    total = len(all_accounts)
    num_nodes = len(nodes_config)
    chunk_size = (total + num_nodes - 1) // num_nodes
    
    print("=" * 85)
    print(f"🚀 集群部署启动: 共 {total} 户账号 | 分发至 {num_nodes} 台独立云服务器 | 每台机启动 {workers_per_node} 个并发 Worker")
    print("=" * 85)
    
    worker_script_path = Path(__file__).resolve().parent.parent / "core" / "rakuten_worker.py"
    
    for idx, node in enumerate(nodes_config):
        part_accounts = all_accounts[idx * chunk_size : (idx + 1) * chunk_size]
        print(f"\n📦 正在部署 {node['id']} ({node['host']}) - 分配 {len(part_accounts)} 户...")
        
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
            
            sftp = ssh.open_sftp()
            ssh.exec_command(f"mkdir -p {remote_run_dir}")
            
            # 传输 Worker 脚本与分片账号
            remote_worker = f"{remote_run_dir}/rakuten_worker.py"
            remote_accs = f"{remote_run_dir}/accounts.json"
            sftp.put(str(worker_script_path), remote_worker)
            
            with sftp.open(remote_accs, 'w') as rf:
                rf.write(json.dumps(part_accounts, ensure_ascii=False, indent=2))
            sftp.close()
            
            # 清理旧进程并启动 workers_per_node 个新并发
            ssh.exec_command(f"pkill -9 -f 'rakuten_worker.py'; rm -f {remote_run_dir}/results_w*.json")
            
            python_bin = node.get('python', '/opt/rakuten-hub/venv/bin/python')
            for w_id in range(workers_per_node):
                cmd = f"nohup {python_bin} {remote_worker} --input {remote_accs} --output-dir {remote_run_dir} --worker-id {w_id} --num-workers {workers_per_node} > {remote_run_dir}/worker_{w_id}.log 2>&1 &"
                ssh.exec_command(cmd)
                
            stdin, stdout, stderr = ssh.exec_command("ps aux | grep 'rakuten_worker.py' | grep -v grep | wc -l")
            cnt = stdout.read().decode().strip()
            print(f"  └─ 节点启动完毕！活跃并发 Worker 数: {cnt} / {workers_per_node}")
            trans.close()
        except Exception as e:
            print(f"  ❌ 节点 {node['id']} 部署异常: {e}")
            
    print("\n" + "=" * 85)
    print("🎉 全集群部署指令发送完毕！")
    print("=" * 85)
