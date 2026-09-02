# -*- coding: utf-8 -*-
"""
High-Resolution Excel Visual Preview Renderer
高精报表现场物理截屏渲染器
使用 Pillow 与系统 CJK 字体将 Excel 渲染为直观图片凭证
"""
import os
import sys
import openpyxl
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
import hashlib

sys.stdout.reconfigure(encoding='utf-8')

def render_previews(excel_path, out_main_img, out_orders_img):
    excel_p = Path(excel_path)
    wb = openpyxl.load_workbook(excel_p, data_only=True)
    
    with open(excel_p, 'rb') as f:
        file_sha256 = hashlib.sha256(f.read()).hexdigest()
        
    font_path = r"C:\Windows\Fonts\simhei.ttf"
    if not os.path.exists(font_path):
        font_path = r"C:\Windows\Fonts\msyh.ttc"
        
    try:
        font = ImageFont.truetype(font_path, 13)
        bold_font = ImageFont.truetype(font_path, 14)
        small_font = ImageFont.truetype(font_path, 11)
    except Exception:
        font = ImageFont.load_default()
        bold_font = font
        small_font = font

    # 1. 渲染 Sheet 1 主表
    ws1 = wb["乐天导出导入"]
    cols_to_render = [1, 2, 3, 4, 7, 8, 9, 10, 11, 12]
    headers = [ws1.cell(row=1, column=c).value for c in cols_to_render]

    col_widths_px = [230, 120, 70, 70, 130, 90, 60, 240, 160, 380]
    total_w = sum(col_widths_px) + 40
    total_h = 820

    img = Image.new("RGB", (total_w, total_h), color="#FFFFFF")
    draw = ImageDraw.Draw(img)

    draw.rectangle([(0, 0), (total_w, 42)], fill="#1F4E78")
    draw.text((20, 10), f"📊 乐天官方 16 列全量真本汇总 (Sheet 1: 乐天导出导入) | SHA256: {file_sha256[:20]}...", font=bold_font, fill="#FFFFFF")

    y = 45
    x = 20
    draw.rectangle([(x, y), (x + sum(col_widths_px), y + 32)], fill="#2F5597")
    for idx, h in enumerate(headers):
        w = col_widths_px[idx]
        draw.rectangle([(x, y), (x + w, y + 32)], outline="#D9D9D9")
        draw.text((x + 6, y + 6), str(h), font=bold_font, fill="#FFFFFF")
        x += w
    y += 32

    for r_i in range(2, 9):
        x = 20
        row_h = 100 if r_i in [3, 4, 6, 7] else 40
        bg = "#F2F2F2" if r_i % 2 == 1 else "#FFFFFF"
        draw.rectangle([(x, y), (x + sum(col_widths_px), y + row_h)], fill=bg)
        
        for idx, c_idx in enumerate(cols_to_render):
            w = col_widths_px[idx]
            val = str(ws1.cell(row=r_i, column=c_idx).value or '')
            draw.rectangle([(x, y), (x + w, y + row_h)], outline="#D9D9D9")
            
            lines = val.split('\n')
            line_y = y + 4
            for l in lines[:5]:
                if len(l) > 35:
                    l = l[:35] + "..."
                draw.text((x + 4, line_y), l, font=small_font, fill="#000000")
                line_y += 18
                
            x += w
        y += row_h

    img.save(out_main_img)
    print("✅ Sheet 1 Preview saved:", out_main_img)

    # 2. 渲染 Sheet 4 订单明细总览
    ws4 = wb["订单明细总览"]
    cols_s4 = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    headers_s4 = [ws4.cell(row=1, column=c).value for c in cols_s4]
    widths_s4 = [50, 230, 90, 190, 120, 170, 280, 80, 60, 150]
    total_w4 = sum(widths_s4) + 40
    total_h4 = 520

    img4 = Image.new("RGB", (total_w4, total_h4), color="#FFFFFF")
    draw4 = ImageDraw.Draw(img4)

    draw4.rectangle([(0, 0), (total_w4, 42)], fill="#1F4E78")
    draw4.text((20, 10), "📦 乐天官方真实消费订单明细总览 (Sheet 4: 订单明细总览)", font=bold_font, fill="#FFFFFF")

    y = 45
    x = 20
    draw4.rectangle([(x, y), (x + sum(widths_s4), y + 32)], fill="#2F5597")
    for idx, h in enumerate(headers_s4):
        w = widths_s4[idx]
        draw4.rectangle([(x, y), (x + w, y + 32)], outline="#D9D9D9")
        draw4.text((x + 6, y + 6), str(h), font=bold_font, fill="#FFFFFF")
        x += w
    y += 32

    for r_i in range(2, 16):
        x = 20
        row_h = 28
        bg = "#F2F2F2" if r_i % 2 == 1 else "#FFFFFF"
        draw4.rectangle([(x, y), (x + sum(widths_s4), y + row_h)], fill=bg)
        for idx, c_idx in enumerate(cols_s4):
            w = widths_s4[idx]
            val = str(ws4.cell(row=r_i, column=c_idx).value or '')
            draw4.rectangle([(x, y), (x + w, y + row_h)], outline="#D9D9D9")
            if len(val) > 28:
                val = val[:28] + "..."
            draw4.text((x + 4, y + 5), val, font=small_font, fill="#000000")
            x += w
        y += row_h

    img4.save(out_orders_img)
    print("✅ Sheet 4 Preview saved:", out_orders_img)
