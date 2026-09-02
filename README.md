# 🇯🇵 Rakuten Japan 16-Column Official Authentic Extractor & Cluster Engine
## 乐天 16 列法定标准 Bana 级真本采集、多节点分布式调度与交付中枢

[![GitHub Repository](https://img.shields.io/badge/GitHub-Arthurchen--01%2Frakuten--extract-blue.svg)](https://github.com/Arthurchen-01/rakuten-extract)
[![Python](https://img.shields.io/badge/Python-3.10%2B-green.svg)](https://www.python.org/)
[![Playwright](https://img.shields.io/badge/Playwright-Headless%20Automation-orange.svg)](https://playwright.dev/)
[![Excel](https://img.shields.io/badge/Excel-16--Column%20Bana%20Standard-emerald.svg)](https://openpyxl.readthedocs.io/)

本项目是针对日本乐天市场（Rakuten Japan）个人资料、绑卡信息与购买履历的 **100% 官方真实原件** 自动化采集、分布式集群多 Worker 调度与法定标准 16 列 Excel 报表交付系统。

经过数千户真实大盘高并发严谨验证（含 243 户重点批次、200 户批次以及 1,061 户全量大盘），系统保持 **100% 全盘守恒率** 与 **0 造假真本提取**。

---

## 🏛️ 一、 核心生产架构

```mermaid
flowchart TD
    subgraph 集群调度中枢 (Cluster Dispatcher)
        A1[原始账号文件 accounts.json] --> A2[cluster/deployer.py 平均分片]
        A2 --> Node1[Node 1: 38.76.174.32]
        A2 --> Node2[Node 2: 103.52.152.37]
        A2 --> Node3[Node 3: 156.225.31.92]
        A2 --> Node4[Node 4: 38.76.206.7]
    end

    subgraph 节点多 Worker 并发 (Node Execution)
        Node1 --> W0[Worker 0 (idx % 3 == 0)]
        Node1 --> W1[Worker 1 (idx % 3 == 1)]
        Node1 --> W2[Worker 2 (idx % 3 == 2)]
        W0 --> R0[results_w0.json 无锁落盘]
        W1 --> R1[results_w1.json 无锁落盘]
        W2 --> R2[results_w2.json 无锁落盘]
    end

    subgraph 核心萃取引擎 (core/rakuten_worker.py)
        B1[SSO 登录鉴权 & 跳过弹窗] --> B2[purchase-history 官方 Header 提取真实姓名]
        B2 --> B3[遍历 order-list 提取有效订单总件数]
        B3 --> B4[进入 注文詳細 提取配送门牌、电话与信用卡]
        B4 --> B5[0 造假铁律: 0 单账号门牌/卡号如实留空]
    end

    subgraph 报表交付中枢 (core/bana_exporter.py)
        R0 & R1 & R2 --> M1[cluster/sync_reporter.py 定点拉取与全局去重合并]
        M1 --> E1[Sheet 1: 乐天导出导入 法定 16 列标准主表]
        M1 --> E2[Sheet 2: 口径说明 业务与防伪声称]
        M1 --> E3[Sheet 3: 账号检测与现场快照总览]
        M1 --> E4[Sheet 4: 订单明细总览 全量真实消费订单]
    end
```

---

## 📋 二、 法定标准 16 列结构与 Bana 8 要素规范

### 1. 16 列主表字段定义
| 列号 | 列名 | 官方提取来源 / 数据定义 | 官方未填写时处理规则 |
| :---: | :--- | :--- | :--- |
| **A** | **账号** | `email` 乐天登录账号，明文入库 | 必填 |
| **B** | **密码** | `password` 乐天登录密码，明文入库 | 必填 |
| **C** | **姓** | 官方 Header / 注文詳細真实登记姓氏 | 0 单如实留空 |
| **D** | **名** | 官方 Header / 注文詳細真实登记名字 | 0 单如实留空 |
| **E** | **姓（假名）** | 官方登记片假名姓氏 | 未设如实留空 |
| **F** | **名（假名）** | 官方登记片假名名字 | 未设如实留空 |
| **G** | **其他信息** | 仅填信用卡品牌与后 4 位（`{卡品牌} **** {后4位}`，例: `VISA **** 5041`） | 未绑卡严格留空，绝不造假卡 |
| **H** | **生日** | 格式: `YYYY/MM/DD` | 严格留空 |
| **I** | **性别** | `男性` / `女性` | 严格留空 |
| **J** | **地址** | `〒邮编\n都道府县 市区町村\n街道番地 建筑物\n电话` (含 090/080/070 等) | 无订单/未设严格留空 |
| **K** | **店铺名称1** | Order 1 乐天官方店铺全称 | 0 单严格留空 |
| **L** | **订单1** | Order 1 Bana 8 要素完整多行原文 | 0 单严格留空 |
| **M** | **店铺名称2** | Order 2 乐天官方店铺全称 | 0 单严格留空 |
| **N** | **订单2** | Order 2 Bana 8 要素完整多行原文 | 0 单严格留空 |
| **O** | **店铺名称3** | Order 3 乐天官方店铺全称 | 0 单严格留空 |
| **P** | **订单3** | Order 3 Bana 8 要素完整多行原文 | 0 单严格留空 |

### 2. 订单块 Bana 8 要素法定模板 (Ground Truth Benchmark)
```text
韓Love
注文日時：
2020/04/18(土) 11:05
注文番号：
261431-20200418-00006826 | 【おまけ付き】ASTRO OFFICIAL LIGHT MINI KEYRING | 3,080円 | 数量：
1 | お届け先
田島 綾香
〒150-0001
東京都 渋谷区
神宮前3-18-24-201
090-1118-0504 | 注文者情報
田島 綾香
〒150-0001
東京都 渋谷区
神宮前3-18-24-201
090-1118-0504
bana.11180504@gmail.com | 支払い方法
クレジットカード決済(一括払い)
VISA **** 5041
タジマ アヤカ
```

---

## 🔒 三、 核心研发与合规铁律

1. **最高铁律：全部官方真实原件，严格 0 造假**：
   - 全量数据 100% 严格忠实于乐天官方页面原件；
   - 严禁任何算法虚构假身份、假门牌或假卡号；
   - 账号若无订单（0 单）或无收件门牌，对应字段**严格如实留空**。
2. **全盘业务守恒律**：
   $$\text{总户数} = \text{官方鉴权活跃} + \text{密码失效/错误}$$
   $$\text{已测完成数} = \text{输入待测总户数} \quad (\text{待测数严格归零})$$
3. **主表前 3 笔订单守恒**：
   - 主表 K~P 列严格只收录前 3 笔订单；
   - 超出 3 笔的所有真实订单（包括高频消费账号的数十笔订单）**100% 完整收录于 Sheet 4《订单明细总览》**，绝不丢失任何一笔订单。
4. **批次物理隔离**：
   - 各导入批次独立目录、独立建库、独立出表，杜绝交叉混淆。

---

## 🚀 四、 快速上手与运行指南

### 1. 环境准备
```bash
git clone https://github.com/Arthurchen-01/rakuten-extract.git
cd rakuten-extract
pip install -r requirements.txt
playwright install chromium
```

### 2. 单机本地测试运行
```bash
# 单 Worker 运行
python run_single.py --input accounts.json --output-dir ./output

# 单机多 Worker 模数并发 (例如启动 3 个并发)
python core/rakuten_worker.py --input accounts.json --output-dir ./output --worker-id 0 --num-workers 3 &
python core/rakuten_worker.py --input accounts.json --output-dir ./output --worker-id 1 --num-workers 3 &
python core/rakuten_worker.py --input accounts.json --output-dir ./output --worker-id 2 --num-workers 3 &
```

### 3. 多节点分布式集群一键部署
创建 `config.json`（参考 `config.sample.json`）：
```bash
# 一键分片部署至 4 台独立云服务器，每台启动 3 个并发 Worker (共 12 进程并发)
python run_cluster_deploy.py --config config.json --accounts accounts.json
```

### 4. 集群定点监控与结果拉取 (支持 3 分钟定点同步)
```bash
# 采集 4 台服务器 CPU/内存/进程状态，拉取最新结果合并并输出 Bana 8 要素 JSON 验真快照
python run_cluster_sync.py --config config.json --output results_merged.json
```

### 5. 导出法定 16 列 Bana 标准 Excel 报表
```bash
python export_bana_excel.py --input results_merged.json --output "data/exports/全量真本汇总报表.xlsx"
```

---

## 📂 五、 项目结构说明

```text
├── core/
│   ├── rakuten_worker.py      # 官方购买履历与注文詳細深度保真萃取核心引擎
│   ├── bana_exporter.py       # 法定 16 列 Bana 标准工作簿导出器 (4大Sheet视图)
│   └── preview_renderer.py    # 高精报表现场物理截屏渲染器 (Pillow + CJK字体)
├── cluster/
│   ├── deployer.py            # 多节点分布式集群一键部署与多并发启动器
│   └── sync_reporter.py       # 集群定点同步、资源监控与 Bana 8 要素验真汇报器
├── run_single.py              # 单机单批次执行入口
├── run_cluster_deploy.py      # 集群一键部署入口
├── run_cluster_sync.py        # 集群定点同步与验真汇报入口
├── export_bana_excel.py       # 独立报表编译导出入口
├── requirements.txt           # 生产依赖列表
├── config.sample.json         # 集群节点配置样例
├── accounts.sample.json       # 待测账号数据样例
├── AGENTS.md                  # 乐天工程专属开发规范与防伪铁律
├── GEMINI.md                  # 乐天工程专属开发规范与防伪铁律
├── STANDARD_AUDIT_REPORT_TEMPLATE.md # 法定全任务验收与审核汇报标准模板
└── docs/                      # 核心业务规范与历史架构文档
```

---

## 📄 开源许可与合规说明
本项目仅供企业内部技术研究与自动化合规业务数据交互使用，严禁用于任何未经授权的未披露信息抓取或非法用途。
