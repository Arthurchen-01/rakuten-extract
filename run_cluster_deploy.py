# -*- coding: utf-8 -*-
"""
分布式集群一键部署脚本
用法：python run_cluster_deploy.py --config config.json --accounts accounts.json
"""
import json
import argparse
from cluster.deployer import deploy_cluster

def main():
    parser = argparse.ArgumentParser(description='Deploy accounts to multi-node cluster')
    parser.add_argument('--config', type=str, default='config.json', help='Cluster nodes config')
    parser.add_argument('--accounts', type=str, default='accounts.json', help='Accounts file')
    args = parser.parse_args()
    
    with open(args.config, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
        
    deploy_cluster(
        nodes_config=cfg['nodes'],
        accounts_file=args.accounts,
        remote_run_dir=cfg.get('remote_run_dir', '/opt/rakuten_run'),
        workers_per_node=cfg.get('workers_per_node', 3),
        bind_ip=cfg.get('bind_ip')
    )

if __name__ == '__main__':
    main()
