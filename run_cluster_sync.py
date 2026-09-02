# -*- coding: utf-8 -*-
"""
分布式集群定点同步与 Bana 8 要素验真汇报脚本
用法：python run_cluster_sync.py --config config.json --output results.json
"""
import json
import argparse
from cluster.sync_reporter import sync_and_report_cluster

def main():
    parser = argparse.ArgumentParser(description='Sync results and report cluster status')
    parser.add_argument('--config', type=str, default='config.json', help='Cluster nodes config')
    parser.add_argument('--output', type=str, default='results.json', help='Local merged results path')
    args = parser.parse_args()
    
    with open(args.config, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
        
    sync_and_report_cluster(
        nodes_config=cfg['nodes'],
        local_results_file=args.output,
        remote_run_dir=cfg.get('remote_run_dir', '/opt/rakuten_run'),
        bind_ip=cfg.get('bind_ip')
    )

if __name__ == '__main__':
    main()
