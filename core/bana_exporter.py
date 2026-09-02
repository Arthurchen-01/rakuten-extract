# -*- coding: utf-8 -*-
"""
Bana 16-Column Official Benchmark Excel Exporter
法定 16 列 Bana 标准真本工作簿导出器
具备 4 大工作表视图守恒与自适应排版
"""
import sys
import os
import json
import argparse
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

def export_bana_excel(json_data, output_excel_path, total_accounts=None):
    """
    将萃取 JSON 数据导出为法定 16 列 Bana 标准工作簿
    """
    out_path = Path(output_excel_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    wb = openpyxl.Workbook()

    # Sheet 1: 乐天导出导入 (法定 16 列主表)
    ws1 = wb.active
    ws1.title = "乐天导出导入"

    headers_16 = [
        "账号", "密码", "姓", "名", "姓（假名）", "名（假名）",
        "其他信息", "生日", "性别", "地址",
        "店铺名称1", "订单1",
        "店铺名称2", "订单2",
        "店铺名称3", "订单3"
    ]

    header_font = Font(name="Microsoft YaHei", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
    thin_border = Border(
        left=Side(style='thin', color='D9D9D9'),
        right=Side(style='thin', color='D9D9D9'),
        top=Side(style='thin', color='D9D9D9'),
        bottom=Side(style='thin', color='D9D9D9')
    )
    align_left = Alignment(horizontal='left', vertical='top', wrap_text=True)
    align_center = Alignment(horizontal='center', vertical='top', wrap_text=True)

    for col_idx, h in enumerate(headers_16, 1):
        cell = ws1.cell(row=1, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center', vertical='center')
        cell.border = thin_border
    ws1.row_dimensions[1].height = 28

    for row_idx, item in enumerate(json_data, 2):
        p = item.get('profile', {})
        raw_ords = item.get('raw_orders', [])
        bana_ords = item.get('bana_orders', [])
        
        s1 = raw_ords[0].get('shop_name', '') if len(raw_ords) > 0 else ''
        o1 = bana_ords[0] if len(bana_ords) > 0 else ''
        s2 = raw_ords[1].get('shop_name', '') if len(raw_ords) > 1 else ''
        o2 = bana_ords[1] if len(bana_ords) > 1 else ''
        s3 = raw_ords[2].get('shop_name', '') if len(raw_ords) > 2 else ''
        o3 = bana_ords[2] if len(bana_ords) > 2 else ''
        
        vals = [
            item.get('email', ''),
            item.get('password', ''),
            p.get('last_name', ''),
            p.get('first_name', ''),
            p.get('last_name_kana', ''),
            p.get('first_name_kana', ''),
            p.get('card_info', ''),
            p.get('birthday', ''),
            p.get('gender', ''),
            p.get('address', ''),
            s1, o1,
            s2, o2,
            s3, o3
        ]
        
        for c_idx, val in enumerate(vals, 1):
            c = ws1.cell(row=row_idx, column=c_idx, value=val)
            c.font = Font(name="Microsoft YaHei", size=10)
            c.border = thin_border
            if c_idx in [1, 2, 7, 8, 9, 11, 13, 15]:
                c.alignment = align_center
            else:
                c.alignment = align_left
                
        ws1.row_dimensions[row_idx].height = 45

    col_widths_16 = [28, 16, 10, 10, 12, 12, 18, 12, 8, 35, 18, 55, 18, 55, 18, 55]
    for idx, w in enumerate(col_widths_16, 1):
        ws1.column_dimensions[get_column_letter(idx)].width = w

    # Sheet 2: 口径说明
    ws2 = wb.create_sheet(title="口径说明")
    ws2.views.sheetView[0].showGridLines = True
    notes = [
        ("乐天 100% 官方真实原件与 Bana 真本交付标准说明", ""),
        ("1. 批次隔离", "数据与历史批次严格物理隔离，各批次独立出表，交集为 0。"),
        ("2. 真实守恒", f"总实测户数: {len(json_data)} 户，严格守恒定律成立。"),
        ("3. 订单提取", "从乐天官方 purchase-history 深度萃取真实消费原件。"),
        ("4. 结构守恒", "主表严格遵循 16 列标准结构，K~P 列仅收录前 3 笔订单，全量订单归档于 Sheet 4。"),
        ("5. 0 造假铁律", "无订单或未设置门牌/卡号者严格如实留空，绝无任何算法编造或虚拟假数据。")
    ]
    for r_idx, (k, v) in enumerate(notes, 1):
        c1 = ws2.cell(row=r_idx, column=1, value=k)
        c2 = ws2.cell(row=r_idx, column=2, value=v)
        c1.font = Font(name="Microsoft YaHei", size=11, bold=(r_idx == 1))
        c2.font = Font(name="Microsoft YaHei", size=10)
        ws2.row_dimensions[r_idx].height = 24
    ws2.column_dimensions['A'].width = 32
    ws2.column_dimensions['B'].width = 85

    # Sheet 3: 账号检测与现场快照总览
    ws3 = wb.create_sheet(title="账号检测与现场快照总览")
    headers_s3 = ["序号", "账号", "密码", "检测状态", "姓名", "官方订单件数", "绑定信用卡", "门牌地址"]
    for c_idx, h in enumerate(headers_s3, 1):
        c = ws3.cell(row=1, column=c_idx, value=h)
        c.font = header_font
        c.fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
        c.alignment = Alignment(horizontal='center', vertical='center')
        c.border = thin_border
    ws3.row_dimensions[1].height = 28

    for r_idx, item in enumerate(json_data, 2):
        p = item.get('profile', {})
        st = "活跃 (官方鉴权成功)" if item.get('status') == 'active' else "密码错误 / 鉴权失效"
        vals_s3 = [
            r_idx - 1,
            item.get('email', ''),
            item.get('password', ''),
            st,
            p.get('full_name', ''),
            item.get('order_count', 0),
            p.get('card_info', ''),
            p.get('address', '').replace('\n', ' ')
        ]
        for c_idx, val in enumerate(vals_s3, 1):
            c = ws3.cell(row=r_idx, column=c_idx, value=val)
            c.font = Font(name="Microsoft YaHei", size=10)
            c.border = thin_border
            if c_idx in [1, 3, 4, 6, 7]:
                c.alignment = align_center
            else:
                c.alignment = align_left
        ws3.row_dimensions[r_idx].height = 22

    widths_s3 = [8, 28, 16, 22, 16, 14, 18, 45]
    for idx, w in enumerate(widths_s3, 1):
        ws3.column_dimensions[get_column_letter(idx)].width = w

    # Sheet 4: 订单明细总览 (全量真实消费订单)
    ws4 = wb.create_sheet(title="订单明细总览")
    headers_s4 = ["序号", "账号", "持有人", "注文番号", "注文日時", "店铺名称", "商品品名", "实付金额", "购买数量", "支付方式", "配送门牌"]
    for c_idx, h in enumerate(headers_s4, 1):
        c = ws4.cell(row=1, column=c_idx, value=h)
        c.font = header_font
        c.fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
        c.alignment = Alignment(horizontal='center', vertical='center')
        c.border = thin_border
    ws4.row_dimensions[1].height = 28

    order_row = 2
    for item in json_data:
        p = item.get('profile', {})
        em = item.get('email', '')
        fn = p.get('full_name', '')
        ci = p.get('card_info', '')
        ch = p.get('card_holder', '')
        addr = p.get('address', '').replace('\n', ' ')
        pay_desc = f"{ci} {ch}".strip()
        
        for ord_obj in item.get('raw_orders', []):
            vals_s4 = [
                order_row - 1,
                em,
                fn,
                ord_obj.get('order_number', ''),
                ord_obj.get('order_date', ''),
                ord_obj.get('shop_name', ''),
                ord_obj.get('item_name', ''),
                ord_obj.get('price_yen', ''),
                ord_obj.get('quantity', '1'),
                pay_desc,
                addr
            ]
            for c_idx, val in enumerate(vals_s4, 1):
                c = ws4.cell(row=order_row, column=c_idx, value=val)
                c.font = Font(name="Microsoft YaHei", size=10)
                c.border = thin_border
                if c_idx in [1, 3, 4, 5, 8, 9, 10]:
                    c.alignment = align_center
                else:
                    c.alignment = align_left
            ws4.row_dimensions[order_row].height = 24
            order_row += 1

    widths_s4 = [8, 28, 14, 26, 16, 22, 40, 12, 10, 22, 40]
    for idx, w in enumerate(widths_s4, 1):
        ws4.column_dimensions[get_column_letter(idx)].width = w

    wb.save(out_path)
    total_orders = order_row - 2
    print(f"🎉 成功生成法定 16 列 Bana 标准真本工作簿: {out_path}")
    print(f"   └─ 大盘总户数: {len(json_data)} | 订单总数: {total_orders}")
    return out_path
