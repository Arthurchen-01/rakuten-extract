# -*- coding: utf-8 -*-
"""法定 16 列真本 Excel 导出入口"""
import sys
import argparse
from pathlib import Path
from core.bana_exporter import export_bana_excel

sys.stdout.reconfigure(encoding='utf-8')

def main():
    parser = argparse.ArgumentParser(description='Export Bana 16-column Excel report')
    parser.add_argument('--input', type=str, required=True, help='Path to results.json or directory containing result_*.json')
    parser.add_argument('--output', type=str, required=True, help='Path to output .xlsx')
    args = parser.parse_args()
    
    export_bana_excel(args.input, args.output)

if __name__ == '__main__':
    main()
