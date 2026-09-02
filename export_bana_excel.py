# -*- coding: utf-8 -*-
"""法定 16 列真本 Excel 导出入口"""
import sys
import json
import argparse
from pathlib import Path
from core.bana_exporter import export_bana_excel

def main():
    parser = argparse.ArgumentParser(description='Export Bana 16-column Excel report')
    parser.add_argument('--input', type=str, required=True, help='Path to results.json')
    parser.add_argument('--output', type=str, required=True, help='Path to output .xlsx')
    args = parser.parse_args()
    
    with open(args.input, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    export_bana_excel(data, args.output)

if __name__ == '__main__':
    main()
