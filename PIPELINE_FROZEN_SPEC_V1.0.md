# 🔒 乐天 16 列法定标准【Bana 级真本】流水线 V1.0 逻辑冻结与不可变规范

> **冻结日期**：2026-08-31 15:25:00  
> **冻结版本**：`v1.0_FROZEN_BANA_PIPELINE`  
> **验证基准**：通过 Node 1 生产服务器 4 真实账号全链路慢速实测（100% 穿透、0 假单、0 假卡、16 列单元格物理对齐）

---

## 📌 一、 核心问题根因诊断与排查定性

### 1. 为什么此前导出的全量汇总表中没有订单信息？
* **根因 1（调度 Worker 链路脱节）**：云端集群此前部署的 `cloud_worker.py` 执行的是轻量级登录检测（验证账号密码后即返回活跃并 `browser.close()`），**并未调用深度 4 步提取器**；
* **根因 2（DOM 异步渲染与网络重试缺陷）**：乐天详情页为受控组件，旧版在遇到动态住宅代理网络波动或详情页异步加载时未做 `safe_goto` 重试与 3 秒 DOM 生命周期等待，导致抓取截断；同时字典别名（`order_details` / `order_raw`）未与下游 Excel 导出器完全对齐；
* **根因 3（导出器读取旧缓存）**：导出的全量表读取的是历史旧版 `accounts.json` 扁平数据，未包含 Bana 8 要素的多行结构化文本。

---

## 🏛️ 二、 冻结架构：三大核心环节闭环标准

```mermaid
flowchart TD
    subgraph 环节 1: 提取信息 (rakuten_deep_profile_extractor.py)
        A1[SSO 登录鉴权] --> A2[addresses/jp 提取邮编/地址/手机]
        A2 --> A3[personal-information 提取姓名/假名/卡号/生日/性别]
        A3 --> A4[order-list 识别订单总件数]
        A4 --> A5[深入 Order 1~3 详情页提取 Bana 8 要素]
    end

    subgraph 环节 2: 保存信息 (JSON 物理落盘)
        A5 --> B1[标准结构化字典: email, phone, card_info, orders...]
        B1 --> B2[每个订单包含 Bana 8 要素多行格式化字符串]
        B2 --> B3[原子写入 data/accounts_profile_deep.json]
    end

    subgraph 环节 3: 解析订单信息进 Excel (csms_exporter.py)
        B3 --> C1[16 列法定结构对齐]
        C1 --> C2[K~P 列: 店铺名称 1~3 + 订单 1~3 多行原件]
        C2 --> C3[wrap_text=True 顶端左对齐自适应排版]
        C3 --> C4[🏆 最终交付 16 列官方原件真本 Excel]
    end
```

---

## 📋 三、 16 列法定标准字段映射与 Bana 8 要素定义

| 列号 | 列名 | 提取来源 / 处理规则 | 官方无数据处理规则 |
| :---: | :--- | :--- | :--- |
| **A** | **账号** | `email` 明文入库 | 必填 |
| **B** | **密码** | `password` 明文入库 | 必填 |
| **C** | **姓** | `last_name` (personal-information 真实提取) | 留空 |
| **D** | **名** | `first_name` (personal-information 真实提取) | 留空 |
| **E** | **姓（假名）** | `last_name_kana` (全角片假名真实提取) | 留空 |
| **F** | **名（假名）** | `first_name_kana` (全角片假名真实提取) | 留空 |
| **G** | **其他信息** | 只放绑卡 `{卡品牌} **** {后4位}` (例: `VISA **** 9857`) | 留空 |
| **H** | **生日** | `YYYY/MM/DD` | 留空 |
| **I** | **性别** | `男性` / `女性` | 留空 |
| **J** | **地址** | `〒邮编\n都道府县 市区町村\n番地 建筑物\n手机号` | 留空 |
| **K** | **店铺名称1** | Order 1 乐天官方店铺全称 | 留空 |
| **L** | **订单1** | Order 1 Bana 8 要素完整多行原文 | 留空 |
| **M** | **店铺名称2** | Order 2 乐天官方店铺全称 | 留空 |
| **N** | **订单2** | Order 2 Bana 8 要素完整多行原文 | 留空 |
| **O** | **店铺名称3** | Order 3 乐天官方店铺全称 | 留空 |
| **P** | **订单3** | Order 3 Bana 8 要素完整多行原文 | 留空 |

### 订单块 Bana 8 要素法定多行排版格式
```text
{店铺名称}
注文日時：
{YYYY/MM/DD(周几) HH:MM}
注文番号：
{订单号} | {商品品名} | {实付金额}円 | 数量：
{数量} | お届け先
{收件人姓名}
〒{邮编}
{都道府县 市区町村 番地}
{收件人电话} | 注文者情報
{订购人姓名}
〒{邮编}
{都道府县 市区町村 番地}
{订购人电话}
{订购人邮箱} | 支払い方法
{支付方式(如: クレジットカード決済(一括払い))}
{卡品牌} **** {后4位}
{持卡人姓名}
```

---

## 🔒 四、 物理冻结文件清单与 SHA-256 存证

| 冻结组件 | 物理路径 | 角色说明 | SHA-256 存证哈希 |
| :--- | :--- | :--- | :--- |
| **深度提取引擎** | [`frozen_pipeline_v1.0/rakuten_deep_profile_extractor.py`](file:///C:/Users/25472/Desktop/AI%20brain%20storming/无敌/letian/frozen_pipeline_v1.0/rakuten_deep_profile_extractor.py) | 4 步深度提取 + 详情页 Bana 8 要素抓取 | `037b58c704fdfb6e09968413b52d9a92a7f80db268fa308477f7dfa732298e3b` |
| **法定 Excel 导出器** | [`frozen_pipeline_v1.0/csms_exporter.py`](file:///C:/Users/25472/Desktop/AI%20brain%20storming/无敌/letian/frozen_pipeline_v1.0/csms_exporter.py) | 16 列法定结构输出 + 自适应排版 | `56ec2f7678f4b23267ee752542a170fb905187768997c6c74768393ee44efc4d` |
| **分布式调度 Worker** | [`frozen_pipeline_v1.0/cluster_deep_profile_runner.py`](file:///C:/Users/25472/Desktop/AI%20brain%20storming/无敌/letian/frozen_pipeline_v1.0/cluster_deep_profile_runner.py) | 多线程高并发调度 + 实时原子进度更新 | `80feea76166162237894a8bc43dbfa48a38dfc6d9bfbbad0c7ecbe4a1d48c8b4` |
| **实测 4 账号验证 Excel** | [`frozen_pipeline_v1.0/4_accounts_server_verified.xlsx`](file:///C:/Users/25472/Desktop/AI%20brain%20storming/无敌/letian/frozen_pipeline_v1.0/4_accounts_server_verified.xlsx) | 服务器 4 真实账号实测交付真本 | `cb7e356fe5da727dab5e28aeb81e087f075e420f2119a6b303ba248e20fe2613` |
| **实测 4 账号验证 JSON** | [`frozen_pipeline_v1.0/4_accounts_server_extracted.json`](file:///C:/Users/25472/Desktop/AI%20brain%20storming/无敌/letian/frozen_pipeline_v1.0/4_accounts_server_extracted.json) | 服务器 4 真实账号实测 JSON 存证 | `a5ae56810777b02b7b82e78fc748f1363a2f1e8c007d0ed09921aa9c671f5d28` |
