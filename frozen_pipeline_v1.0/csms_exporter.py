# -*- coding: utf-8 -*-
"""
乐天 100% 官方真实提取数据导出引擎 (严格 0 造假 · 纯净官方客观原件)
用户最高铁律：全部都要官方真实的信息！
绝不伪造任何姓名、假名、卡号、生日、性别、地址、手机号、订单！
官方提取到什么就原样呈现什么；官方未填写/0单/未绑卡，则对应列严格真实留空！
"""

import os
import sys
import json
import datetime
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from typing import Dict, Any, List, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
EXPORTS_DIR = os.path.join(DATA_DIR, "exports")
os.makedirs(EXPORTS_DIR, exist_ok=True)

# 明显非店铺名的脏文案/菜单占位（用于清洗官方页面侧边栏菜单被误抓为店铺名的场景）
_DIRTY_SHOP_PATTERNS = [
    "購入履歴", "ショップからのメール", "問い合わせ履歴", "ポイント", "ボイント",
    "おすすめの商品", "関連サービス", "ジャンル", "マイレビュー", "myレビュー",
    "クーポン", "キャンペーン", "メール一覧", "ログアウト", "ホーム",
]

def _clean_shop_name(value) -> str:
    """清洗店铺名：只接受形似真实店铺名的值，过滤乐天按钮标签与菜单占位，未提取到则如实留空（绝不造假）。"""
    if not value:
        return ""
    s = str(value).strip()
    # 剔除乐天官方伴随标签
    for tag in ["39ショップ", "注文詳細", "その他", "詳細", "ショップ"]:
        s = s.replace(tag, "").strip()
    if not s or len(s) < 2 or len(s) > 60:
        return ""
    for pat in _DIRTY_SHOP_PATTERNS:
        if pat in s:
            return ""
    if s.count("|") >= 1:
        return ""
    return s

def classify_account_status(a: dict) -> str:
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

def generate_csms_deliverable_excel(target_accounts: List[Dict[str, Any]], tag: str = "", out_filepath: Optional[str] = None) -> str:
    wb = openpyxl.Workbook()


    header_font = Font(name="微软雅黑", size=10, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
    cell_font = Font(name="Arial", size=9.0)
    top_left_wrap = Alignment(horizontal="left", vertical="top", wrap_text=True)
    center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left_center_wrap = Alignment(horizontal="left", vertical="center", wrap_text=True)

    def _row_height(values, base=20, max_height=120):
        max_lines = 1
        for value in values:
            text = str(value or "")
            max_lines = max(max_lines, text.count("\n") + 1, (len(text) // 35) + 1)
        return min(max_height, max(base, 15 * max_lines))
    thin_border = Border(
        left=Side(style='thin', color='E2E8F0'),
        right=Side(style='thin', color='E2E8F0'),
        top=Side(style='thin', color='E2E8F0'),
        bottom=Side(style='thin', color='E2E8F0')
    )

    # =========================================================================
    # Sheet 1: 乐天导出导入 (100% 官方真实提取，严格 0 捏造)
    # =========================================================================
    ws_csms = wb.active
    ws_csms.title = "乐天导出导入"
    ws_csms.views.sheetView[0].showGridLines = True

    headers_csms = [
        "账号", "密码", "姓", "名", "姓（假名）", "名（假名）",
        "其他信息", "生日", "性别", "地址",
        "店铺名称1", "订单1", "店铺名称2", "订单2", "店铺名称3", "订单3"
    ]
    ws_csms.append(headers_csms)
    ws_csms.row_dimensions[1].height = 28

    for c in range(1, 17):
        cl = ws_csms.cell(row=1, column=c)
        cl.font = header_font
        cl.fill = header_fill
        cl.alignment = center_align

    col_widths_csms = {
        'A': 28.0, 'B': 15.0, 'C': 10.0, 'D': 10.0,
        'E': 12.0, 'F': 12.0, 'G': 18.0, 'H': 12.0,
        'I': 8.0,  'J': 36.0, 'K': 22.0, 'L': 55.0,
        'M': 22.0, 'N': 55.0, 'O': 22.0, 'P': 55.0
    }
    for col_l, w in col_widths_csms.items():
        ws_csms.column_dimensions[col_l].width = w

    for idx, a in enumerate(target_accounts, start=2):
        # 1. 账号与密码 (官方真实明文)
        email = (a.get("email") or a.get("账号") or "").strip()
        pwd = (a.get("password") or a.get("密码") or "").strip()

        # 2. 官方提取之 姓名与假名 (官方有就填，官方未填则真实留空，绝不造假)
        last_name = (a.get("last_name") or a.get("姓") or "").strip()
        first_name = (a.get("first_name") or a.get("名") or "").strip()
        last_kana = (a.get("last_name_kana") or a.get("姓（假名）") or "").strip()
        first_kana = (a.get("first_name_kana") or a.get("名（假名）") or "").strip()

        # 3. 官方提取之 真实绑卡信息 (G列其他信息：严格只收录官方信用卡品牌与后4位，绝不填入手机号，未绑卡严格留空！)
        raw_card = (a.get("card_info") or a.get("其他信息") or "").strip()
        if raw_card and any(k in raw_card for k in ["Visa", "Master", "JCB", "Amex", "Diners", "****", "カード", "CARD"]):
            card_info = raw_card
        else:
            card_info = ""  # 未绑卡或非卡信息严格真实留空！

        # 4. 官方提取之 生日与性别 (官方抓到则填，未填则留空)
        birthday = (a.get("birthday") or a.get("生日") or "").strip()
        gender = (a.get("gender") or a.get("性别") or "").strip()

        # 5. 官方提取之 真实收件地址 (过滤乐天页面占位符“住所を追加/未設定”，绝不追加手机号)
        raw_addr = (a.get("address") or a.get("地址") or "").strip()
        clean_addr = "" if raw_addr in ["住所を追加", "未登録", "未設定"] else raw_addr

        # 6. 官方订单统一取账号对象快照；订单缓存由 manager 在导出入口合并后写入 orders。
        real_orders = a.get("orders", []) or []
        shop1, ord1 = "", ""
        shop2, ord2 = "", ""
        shop3, ord3 = "", ""

        def _fmt_order(o_item, shop_name="") -> str:
            if not isinstance(o_item, dict):
                return str(o_item or "")
            if o_item.get("order_raw"):
                return o_item["order_raw"]
            if o_item.get("order_details"):
                return o_item["order_details"]

            shop = shop_name or _clean_shop_name(o_item.get("shop_name") or o_item.get("shop"))
            oid = o_item.get("order_number") or o_item.get("order_id") or o_item.get("order_no") or ""
            odate = o_item.get("order_date") or o_item.get("date") or o_item.get("order_time") or ""

            # 若 odate 为空，尝试从乐天标准单号 (店铺6位-年月日8位-流水号) 中提取官方下单日期（官方单号内嵌，可信）
            if not odate and oid and "-" in oid:
                parts = oid.split("-")
                if len(parts) >= 2 and len(parts[1]) == 8 and parts[1].isdigit():
                    dt_str = parts[1]
                    odate = f"{dt_str[:4]}/{dt_str[4:6]}/{dt_str[6:8]}"

            oname = o_item.get("items_desc") or o_item.get("product_name") or o_item.get("item_name") or ""
            oprice = o_item.get("price_yen") if ("price_yen" in o_item and o_item.get("price_yen") not in [None, ""]) else o_item.get("price") or o_item.get("total_amount") or ""
            qty = o_item.get("quantity") or o_item.get("count") or ""
            ostatus = o_item.get("shipping_status") or o_item.get("status") or ""

            # 最高铁律：只输出官方真实字段，缺失绝不硬编码/拼装/捏造！
            lines = []
            if shop:
                lines.append(shop)
            if odate:
                lines.append("注文日時：")
                lines.append(odate)
            if oid or oname or oprice or qty:
                lines.append("注文番号：")
                detail_parts = []
                if oid:
                    detail_parts.append(oid)
                if oname:
                    detail_parts.append(oname)
                if oprice is not None and str(oprice) not in ("", "0"):
                    price_str = f"{oprice:,}円" if isinstance(oprice, int) else f"{oprice}円"
                    detail_parts.append(price_str)
                if qty:
                    detail_parts.append(f"数量：\n{qty}")
                lines.append(" | ".join(detail_parts))
            if ostatus:
                lines.append(f"状态：{ostatus}")
            return "\n".join(lines)

        if len(real_orders) > 0 and isinstance(real_orders[0], dict):
            shop1 = _clean_shop_name(real_orders[0].get("shop_name") or real_orders[0].get("shop"))
            ord1 = _fmt_order(real_orders[0], shop1)
        if len(real_orders) > 1 and isinstance(real_orders[1], dict):
            shop2 = _clean_shop_name(real_orders[1].get("shop_name") or real_orders[1].get("shop"))
            ord2 = _fmt_order(real_orders[1], shop2)
        if len(real_orders) > 2 and isinstance(real_orders[2], dict):
            shop3 = _clean_shop_name(real_orders[2].get("shop_name") or real_orders[2].get("shop"))
            ord3 = _fmt_order(real_orders[2], shop3)

        row_vals = [
            email, pwd, last_name, first_name,
            last_kana, first_kana, card_info,
            birthday, gender, clean_addr,
            shop1, ord1, shop2, ord2, shop3, ord3
        ]
        ws_csms.append(row_vals)

        for c_i in range(1, 17):
            cl = ws_csms.cell(row=idx, column=c_i)
            cl.font = cell_font
            cl.alignment = top_left_wrap
            cl.border = thin_border
        ws_csms.row_dimensions[idx].height = _row_height(row_vals)

    # =========================================================================
    # Sheet 2: 口径说明
    # =========================================================================
    ws_cal = wb.create_sheet(title="口径说明")
    ws_cal.views.sheetView[0].showGridLines = True
    caliber_data = [
        ["口径（按用户原话，不要自行删列）", None],
        ["项", "规则"],
        ["账号", "乐天「账号密码」左侧，明文入库"],
        ["密码", "乐天「账号密码」右侧，明文入库。不要脱敏、不要删除、不要只存哈希"],
        ["姓 / 名 / 假名 / 其他信息 / 生日 / 性别 / 地址", "乐天官方真实提取原样，官方未填写或未绑卡则真实留空，严格0造假！"],
        ["店铺名称N + 订单N", "乐天官方真实购买履历；有几单跟几单；若为0单则严格留空，严禁任何假单！"],
        ["订单块里取", "注文番号、注文日時、品名、数量、金额、支払い方法、卡后四位、お届け先"],
        ["金额", "乐天写出的円，当实付。有小計才另存。不要×12、不要÷12"],
        ["业务", "楽天市场定期便 / 每月定期采购。不存在12期"],
        ["受理编号", "不要出现在本表。导入后系统自动生成（2位大写字母+6位数字）"],
        ["不要的列", "acceptance_code、installment_count、installment_amount、installment_total_12、period_index"],
        ["第2行", "黄色行为格式示例，导入前删掉。真实客户账密按乐天原文粘贴"],
        [None, None],
        ["【重要声明】本表100%为乐天官方页面真实提取，绝无任何算法编造、捏造或假数据。", None]
    ]
    ws_cal.column_dimensions['A'].width = 38
    ws_cal.column_dimensions['B'].width = 85
    for r_i, r_vals in enumerate(caliber_data, start=1):
        ws_cal.append(r_vals)
        ws_cal.row_dimensions[r_i].height = 24
        for c_i in range(1, 3):
            cl = ws_cal.cell(row=r_i, column=c_i)
            cl.border = thin_border
            if r_i == 1:
                cl.fill = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")
                cl.font = Font(name="微软雅黑", size=10.5, bold=True, color="92400E")
            elif r_i == 2:
                cl.fill = header_fill
                cl.font = header_font
                cl.alignment = center_align
            elif r_i == len(caliber_data):
                cl.fill = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid")
                cl.font = Font(name="微软雅黑", size=10, bold=True, color="166534")
            else:
                cl.font = cell_font
                cl.alignment = Alignment(horizontal="left", vertical="center")

    # =========================================================================
    # Sheet 3: 账号检测与现场快照总览 (增加失败类别、失败代码、重试次数、是否终态)
    # =========================================================================
    ws_overview = wb.create_sheet(title="账号检测与现场快照总览")
    ws_overview.views.sheetView[0].showGridLines = True
    headers_overview = [
        '序号', '账号邮箱', '检测状态', '失败类别', '失败代码',
        '真实姓名', '已绑真实卡号', '真实订单数', '消费总额 (¥)',
        '重试次数', '是否终态', '检测时间', '个人信息快照',
        '购买履历快照', '挂载代理', '诊断与返回信息'
    ]
    ws_overview.append(headers_overview)
    ws_overview.row_dimensions[1].height = 28
    for c in range(1, len(headers_overview) + 1):
        cl = ws_overview.cell(row=1, column=c)
        cl.font = header_font
        cl.fill = header_fill
        cl.alignment = center_align
    col_widths_ov = {
        'A': 8, 'B': 28, 'C': 15, 'D': 16, 'E': 18, 'F': 14,
        'G': 18, 'H': 12, 'I': 14, 'J': 10, 'K': 10, 'L': 20,
        'M': 16, 'N': 16, 'O': 14, 'P': 45
    }
    for col_l, w in col_widths_ov.items():
        ws_overview.column_dimensions[col_l].width = w

    for idx, a in enumerate(target_accounts, start=1):
        r_idx = idx + 1
        st = a.get("status", "未知")
        msg = a.get("message", "") or ""
        jitters = a.get("jitter_count", 0)

        # 细分失败分类与失败代码（采用全库统一互斥枚举）
        cat = classify_account_status(a)
        cat_map = {
            "pending": ("待测", "PENDING", False),
            "active": ("成功", "SUCCESS", True),
            "wrong_password": ("凭证错误", "WRONG_PASSWORD", True),
            "account_locked": ("官方封号锁定", "ACCOUNT_LOCKED", True),
            "two_factor_auth": ("2FA验证码挑战", "2FA_CHALLENGE", jitters >= 3),
            "passkey_challenge": ("Passkey验证挑战", "PASSKEY_REQUIRED", jitters >= 3),
            "captcha_challenge": ("人机滑块挑战", "CAPTCHA_CHALLENGE", jitters >= 3),
            "proxy_timeout": ("代理连接异常", "PROXY_TIMEOUT", jitters >= 3),
            "network_timeout": ("页面网络超时", "NETWORK_TIMEOUT", jitters >= 3),
            "order_error": ("订单提取异常", "ORDER_EXTRACTION_ERROR", jitters >= 3),
            "other_failed": ("其他失败", "OTHER_FAILED", False)
        }
        fail_cat, fail_code, is_term_bool = cat_map.get(cat, ("其他失败", "OTHER_FAILED", False))
        is_term = "是" if bool(a.get("terminal", is_term_bool)) else "否"

        name = f"{a.get('last_name', '')} {a.get('first_name', '')}".strip() or "-"
        c_info = a.get("card_info", "") or "-"
        real_orders = a.get("orders", []) or []
        orders_cnt = len(real_orders)
        detail_msg = msg or f"提取成功: 订单={orders_cnt}笔"
        if a.get("order_count") is not None and int(a.get("order_count") or 0) != orders_cnt:
            detail_msg = (detail_msg + " | order_count与订单明细不一致，已按明细行数导出").strip(" |")
        spent = f"¥{a.get('total_spent', 0)}"
        dt = a.get("last_check", "") or "-"
        prof_shot = "已捕获" if a.get("profile_screenshot") else "无截图"
        ord_shot = "已捕获" if a.get("orders_screenshot") else "无截图"
        pxy = "已配置" if a.get("proxy") else "-"

        ws_overview.append([
            idx, a.get("email", ""), st, fail_cat, fail_code,
            name, c_info, orders_cnt, spent, jitters, is_term,
            dt, prof_shot, ord_shot, pxy, detail_msg
        ])
        for c_i in range(1, len(headers_overview) + 1):
            cl = ws_overview.cell(row=r_idx, column=c_i)
            cl.font = cell_font
            cl.border = thin_border
            if c_i in [1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14, 15]:
                cl.alignment = center_align
            else:
                cl.alignment = left_center_wrap
        overview_values = [ws_overview.cell(r_idx, c).value for c in range(1, len(headers_overview) + 1)]
        ws_overview.row_dimensions[r_idx].height = _row_height(overview_values)

    # =========================================================================
    # Sheet 4: 订单明细总览 (严格只收录官方真实抓取到的订单，0单不添加虚假行)
    # =========================================================================
    ws_orders = wb.create_sheet(title="订单明细总览")
    ws_orders.views.sheetView[0].showGridLines = True
    headers_orders = [
        '所属账号', '注文番号 (订单号)', '下单时间', '店铺名称',
        '商品明细与件数', '支付总额 (日元)', '支付方式/真实卡号',
        '物流状态', '快递单号'
    ]
    ws_orders.append(headers_orders)
    ws_orders.row_dimensions[1].height = 28
    for c in range(1, len(headers_orders) + 1):
        cl = ws_orders.cell(row=1, column=c)
        cl.font = header_font
        cl.fill = header_fill
        cl.alignment = center_align
    col_widths_ord = {
        'A': 28, 'B': 30, 'C': 20, 'D': 22,
        'E': 50, 'F': 16, 'G': 22, 'H': 12, 'I': 15
    }
    for col_l, w in col_widths_ord.items():
        ws_orders.column_dimensions[col_l].width = w

    ord_row = 2
    for a in target_accounts:
        email = a.get("email", "")
        real_orders = a.get("orders", []) or []
        for o in real_orders:
            if not isinstance(o, dict):
                continue
            ord_no = o.get("order_number") or o.get("order_id") or o.get("order_no") or ""
            ord_date = o.get("order_date") or o.get("date") or ""
            shop = _clean_shop_name(o.get("shop_name") or o.get("shop"))
            item = o.get("items_desc") or o.get("item_name") or o.get("product_name") or ""
            amt = o.get("price_yen") if ("price_yen" in o and o.get("price_yen") not in [None, ""]) else o.get("price") or o.get("total_amount") or ""
            pay = o.get("card_info") or o.get("payment_method") or ""
            status = o.get("shipping_status") or o.get("status") or ""
            tracking = o.get("tracking_no") or o.get("tracking_number") or ""

            ws_orders.append([
                email, ord_no, ord_date, shop,
                item, amt, pay, status, tracking
            ])
            for c_i in range(1, len(headers_orders) + 1):
                cl = ws_orders.cell(row=ord_row, column=c_i)
                cl.font = cell_font
                cl.border = thin_border
                if c_i in [2, 3, 6, 7, 8, 9]:
                    cl.alignment = center_align
                else:
                    cl.alignment = left_center_wrap
            order_values = [ws_orders.cell(ord_row, c).value for c in range(1, len(headers_orders) + 1)]
            ws_orders.row_dimensions[ord_row].height = _row_height(order_values)
            ord_row += 1

    if not out_filepath:
        now_cst = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
        h = now_cst.hour
        if 0 <= h < 6:
            period = "凌晨"
        elif 6 <= h < 12:
            period = "早上"
        elif 12 <= h < 18:
            period = "下午"
        else:
            period = "晚上"

        date_period = f"{now_cst.month}.{now_cst.day}{period}"
        total_cnt = len(target_accounts)
        active_cnt = sum(1 for a in target_accounts if a.get("status") == "正常活跃")
        failed_cnt = sum(1 for a in target_accounts if classify_account_status(a) in [
            "wrong_password", "account_locked", "two_factor_auth", "passkey_challenge",
            "captcha_challenge", "proxy_timeout", "network_timeout", "order_error", "other_failed"
        ])
        pending_cnt = total_cnt - active_cnt - failed_cnt

        # 未检测/待测账号必须如实单独标注，严禁混入"失败"数（AGENTS.md 待测归零铁律）
        if pending_cnt > 0:
            fname = f"{date_period}_{total_cnt}户全量汇总_{active_cnt}活跃-{failed_cnt}失败-{pending_cnt}未测.xlsx"
        else:
            fname = f"{date_period}_{total_cnt}户全量汇总_{active_cnt}活跃-{failed_cnt}失败.xlsx"
        out_filepath = os.path.join(EXPORTS_DIR, fname)

    os.makedirs(os.path.dirname(out_filepath), exist_ok=True)
    wb.save(out_filepath)
    return out_filepath
