# 🇯🇵 Rakuten Japan 16-Column Official Authentic Profile & Order Extractor (乐天 16 列法定标准 Bana 级真本采集与交付引擎)

[![GitHub Repository](https://img.shields.io/badge/GitHub-Arthurchen--01%2Frakuten--extract-blue.svg)](https://github.com/Arthurchen-01/rakuten-extract)
[![Python](https://img.shields.io/badge/Python-3.10%2B-green.svg)](https://www.python.org/)
[![Playwright](https://img.shields.io/badge/Playwright-Headless%20Automation-orange.svg)](https://playwright.dev/)
[![Excel](https://img.shields.io/badge/Excel-16--Column%20Bana%20Standard-emerald.svg)](https://openpyxl.readthedocs.io/)

本项目是针对日本乐天市场（Rakuten Japan）个人资料、绑卡信息与购买履历的 **100% 官方真实原件** 深度自动化采集与法定标准 16 列 Excel 报表交付系统。

---

## 🏛️ 一、 核心架构与模块分工

```mermaid
flowchart TD
    subgraph 环节 1: 核心提取引擎 (rakuten_deep_profile_extractor.py)
        A1[SSO 登录鉴权] --> A2[addresses/jp 提取邮编/都道府县/番地/手机号]
        A2 --> A3[personal-information 提取姓名/假名/卡号/生日/性别]
        A3 --> A4[order-list 识别历史有效订单总数]
        A4 --> A5[深入 Order 1~3 详情页提取 Bana 8 要素多行原件]
    end

    subgraph 环节 2: 数据结构化与多节点调度 (cluster_deep_profile_runner.py)
        A5 --> B1[标准结构化字典: email, phone, card_info, orders...]
        B1 --> B2[原子持久化落盘至 data/accounts_profile_deep.json]
        B2 --> B3[实时心跳更新 live_profile_progress.json]
    end

    subgraph 环节 3: 法定标准 16 列导出器 (csms_exporter.py)
        B3 --> C1[16 列严格结构对齐]
        C1 --> C2[K~P 列: 店铺名称 1~3 + 订单 1~3 Bana 8 要素]
        C2 --> C3[wrap_text=True 顶端左对齐自适应行高排版]
        C3 --> C4[🏆 生成图二标准命名交付级 Excel 报表]
    end
```

---

## 📋 二、 法定标准 16 列结构与 Bana 8 要素规范

### ① 16 列字段法定定义与处理规范
| 列号 | 列名 | 提取规则 / 数据定义 | 官方未填写时处理规则 |
| :---: | :--- | :--- | :--- |
| **A** | **账号** | `email` 乐天登录账号，明文入库 | 必填 |
| **B** | **密码** | `password` 乐天登录密码，明文入库 | 必填 |
| **C** | **姓** | `last_name` (personal-information 官方真实提取) | 严格留空，0 伪造 |
| **D** | **名** | `first_name` (personal-information 官方真实提取) | 严格留空，0 伪造 |
| **E** | **姓（假名）** | `last_name_kana` (全角片假名真实提取) | 严格留空，0 伪造 |
| **F** | **名（假名）** | `first_name_kana` (全角片假名真实提取) | 严格留空，0 伪造 |
| **G** | **其他信息** | 仅填信用卡品牌与后 4 位（`{卡品牌} **** {后4位}`，例: `VISA **** 9857`） | 未绑卡严格留空 |
| **H** | **生日** | 格式: `YYYY/MM/DD` | 严格留空 |
| **I** | **性别** | `男性` / `女性` | 严格留空 |
| **J** | **地址** | `〒邮编\n都道府县 市区町村\n番地 建筑物\n手机号` | 过滤脏占位符，未设则留空 |
| **K** | **店铺名称1** | Order 1 乐天官方店铺全称 | 0 单留空 |
| **L** | **订单1** | Order 1 Bana 8 要素完整多行原文 | 0 单留空 |
| **M** | **店铺名称2** | Order 2 乐天官方店铺全称 | 0 单留空 |
| **N** | **订单2** | Order 2 Bana 8 要素完整多行原文 | 0 单留空 |
| **O** | **店铺名称3** | Order 3 乐天官方店铺全称 | 0 单留空 |
| **P** | **订单3** | Order 3 Bana 8 要素完整多行原文 | 0 单留空 |

### ② 订单块 Bana 8 要素法定排版样例 (Ground Truth Benchmark)
```text
グルメソムリエ楽天市場店
注文日時：
2024/01/31(水) 17:34
注文番号：
271121-20240131-0430637458 | 豚腸（直径30-32mm）天然腸ケーシング | 880円 | 数量：
1 | お届け先
那須野 倫史
〒133-0056
東京都 江戸川区
南小岩3-14-15-101
090-2871-6682 | 注文者情報
那須野 倫史
〒133-0056
東京都 江戸川区
南小岩3-14-15-101
090-2871-6682
tnasuno187@gmail.com | 支払い方法
クレジットカード決済(一括払い)
VISA **** 9857
トモフミ ナスノ
```

---

## 🚀 三、 快速上手与运行指南

### 1. 环境准备
```bash
# 克隆仓库
git clone https://github.com/Arthurchen-01/rakuten-extract.git
cd rakuten-extract

# 安装依赖
pip install -r requirements.txt

# 安装 Playwright 浏览器内核
playwright install chromium
```

### 2. 单账号 / 小批量深度测试
```bash
# 运行单账号慢速全流程实测
python rakuten_deep_profile_extractor.py --email "user@example.com" --password "pass123"
```

### 3. 全集群高并发批量实跑与自动出表
```bash
# 启动多线程批量提取与 Excel 导出
python cluster_deep_profile_runner.py --input accounts.json --workers 5
```

---

## 🔒 四、 核心原则与开发铁律

1. **Slow-First 慢速工程学与 0 盲猜**：任何页面操作必须等待受控 DOM 完全加载与渲染，杜绝盲目修改选择器或并发抢跑。
2. **100% 官方真实原件**：绝不通过算法捏造任何假姓名、假卡号、假地址或假订单。官方未填写的字段严格留空。
3. **不可变冻结版本**：已在 `frozen_pipeline_v1.0/` 目录下完成首批交付逻辑的物理快照与 SHA-256 存证。
