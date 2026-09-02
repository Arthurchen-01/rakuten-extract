# 乐天采集系统重写全景知识基线与业务规则真本 (Knowledge Base & Asset Manifest)

> **版本**：v1.0 (Clean Baseline)  
> **生效时间**：2026-09-01  
> **适用范围**：乐天日本电商自动化登录、个人资料提取、历史订单抓取、老板 16 列导出与机械验收。  
> **核心原则**：**代码可删，逻辑不灭，原始证据不丢，失败案例长存**。

---

## 1. 业务逻辑与 5 大核心资产分类

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        5 大必须永久保留的核心资产                       │
├────────────────────────────────────────────────────────────────────────┤
│ 1. 业务逻辑规范: SYSTEM_REWRITE_SPEC.md, REMOTE_REWRITE_RUNBOOK.md      │
│ 2. 原始输入模板: CSMS_乐天定期便_导入表_已填_iPhone17_20260826_完整会员资料版.xlsx │
│ 3. 真实页面证据: data/remote_audit_runs/ (物理截图、HAR、HTML 原文)      │
│ 4. 原始结构化结果: results.source.json, evidence_manifest.json, output.xlsx │
│ 5. 失败案例与测试夹具: data/rewrite_test_snapshot/fixtures/ (15组独立用例) │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 老板 16 列法定 Excel 字段映射与 DOM 抓取路径规范

| 列号 | 列名 | 业务定义与空值规则 | DOM 选择器 / 抓取数据源 | 示例数据 |
| :---: | :--- | :--- | :--- | :--- |
| **A (01)** | `账号` | 乐天会员登录邮箱，明文入库 | 输入源 / `acc['email']` | `nao7641@hotmail.com` |
| **B (02)** | `密码` | 乐天会员密码（由导入表决定，导出可根据脱敏要求留空） | 输入源 / `acc['password']` | `mugineko` |
| **C (03)** | `姓` | 真实姓名之“姓”，无资料严格留空 | `#user-name-kanji .last-name` / Profile DOM | `堀菜` |
| **D (04)** | `名` | 真实姓名之“名”，无资料严格留空 | `#user-name-kanji .first-name` / Profile DOM | `穂子` |
| **E (05)** | `姓（假名）` | 片假名之“姓”，无资料严格留空 | `#user-name-kana .last-name` / Profile DOM | `ホリナ` |
| **F (06)** | `名（假名）` | 片假名之“名”，无资料严格留空 | `#user-name-kana .first-name` / Profile DOM | `ホコ` |
| **G (07)** | `其他信息` | 仅存放信用卡品牌与后4位（`{品牌} **** {后4位}`），未绑卡严格留空 | `member.rakuten.co.jp/card` / Profile Card | `VISA **** 5041` |
| **H (08)** | `生日` | 出生年月日（`YYYY/MM/DD`），未设置严格留空 | `#birthdate` / Profile DOM | `1994/05/04` |
| **I (09)** | `性别` | `男性` / `女性`，未设置严格留空 | `#gender` / Profile DOM | `女性` |
| **J (10)** | `地址` | 过滤脏占位符（`未登録/未設定/住所を追加`），真实地址原样保留（含邮编、省市区、电话） | `#address-view` / Profile DOM | `〒150-0001
東京都 渋谷区
090-1118-0504` |
| **K (11)** | `店铺名称1` | 第 1 笔订单官方店铺名称，无订单留空 | `.order-item:nth-child(1) .shop-name` | `ロゴスペットサイト` |
| **L (12)** | `订单1` | 第 1 笔订单完整原文块（含注文番号、注文日、商品名、实付金额、お届け先、注文者情報） | `.order-item:nth-child(1) .order-detail` | 完整原文块 |
| **M (13)** | `店铺名称2` | 第 2 笔订单官方店铺名称，无第2单留空 | `.order-item:nth-child(2) .shop-name` | `ロゴスペットサイト` |
| **N (14)** | `订单2` | 第 2 笔订单完整原文块 | `.order-item:nth-child(2) .order-detail` | 完整原文块 |
| **O (15)** | `店铺名称3` | 第 3 笔订单官方店铺名称，无第3单留空 | `.order-item:nth-child(3) .shop-name` | `けーすらんど` |
| **P (16)** | `订单3` | 第 3 笔订单完整原文块（每户最多抓取 3 笔） | `.order-item:nth-child(3) .order-detail` | 完整原文块 |

---

## 3. 状态分类、页面特征与证据规则

| 状态标识 | 官方页面证据与特征 | 判定规则 | 截图要求 |
| :--- | :--- | :--- | :--- |
| `active` | 登录成功，Cookie 存在，能正常访问个人中心与订单页 | `login_status == "verified"` 且资料/订单抓取无网络阻断 | 3 张（登录态 + 资料页 + 订单页） |
| `wrong_password` | 页面明确出现红字：`ユーザID・パスワードが一致しません` | 官方认证失败，密码错误 | 1 张（登录错误提示截图） |
| `two_factor` | 页面要求输入短信或邮箱一次性验证码（`ワンタイムパスワード`） | 触碰 2FA / OTP 挑战 | 1 张（2FA 挑战页面截图） |
| `passkey` | 页面提示使用设备生物识别 / Passkey | 触碰 Passkey 挑战 | 1 张（Passkey 页面截图） |
| `captcha` | 出现 Cloudflare / Turnstile / 字符人机验证 | 触碰人机验证 | 1 张（验证码出现截图） |
| `technical_retryable` | 输入框加载超时、页面 502/504 抖动、代理网络超时 | 技术网络异常，可放队尾重试 | 1 张（现场异常截图） |
| `technical_final` | 超过最大重试次数仍由于网络/代理无法建立连接 | 技术终止异常，不可伪造成密码错误 | 1 张（现场最终异常截图） |

---

## 4. API 路由演进与彻底重构对比清单

| 模块 | 旧版混乱接口 (已废弃并隔离) | 新版干净单一源接口 (`rewrite_v1`) | 说明 |
| :--- | :--- | :--- | :--- |
| **健康检查** | `GET /health` (旧字段) | `GET /health` -> `{"status":"ok","version":"rewrite-v1","role":"master"}` | 统一版本与角色 |
| **创建任务** | `POST /api/accounts/import-batches` / `POST /api/run-task` | `POST /api/batches` -> `{"batch_id":"...", "accounts":[...]}` | 单一批次单源隔离 |
| **任务认领** | 内存字典争抢 / 静态分段 `cloud_worker` | `POST /api/batches/{batch_id}/claim` (原子租约锁定) | 支持 SQLite WAL 排他锁 |
| **租约心跳** | 无心跳导致死锁 | `POST /api/batches/{batch_id}/heartbeat` (超时自动回收) | 租约防悬挂 |
| **截图上传** | 跨批次混图 / 零散上传 | `POST /api/batches/{batch_id}/upload_screenshot` | 强制归属对应 batch 目录 |
| **结果回报** | `POST /api/worker-report` | `POST /api/batches/{batch_id}/report` (校验 claim_id) | 强校验防冒充 |
| **导出 Excel** | `GET /api/export/excel?scope=last_batch` (常取错缓存) | `POST /api/batches/{batch_id}/export` -> 生成指定 batch 的 `output.xlsx` | 未完成严禁导出 |
| **下载 Excel** | `GET /download/latest.xlsx` | `GET /api/batches/{batch_id}/export.xlsx` | 强关联 batch_id |

---

## 5. 集群 4 节点硬件、系统与运行参数配置

| 节点 | 公网 IP | 角色职责 | 运行环境路径 | 部署服务目录 |
| :--- | :--- | :--- | :--- | :--- |
| **Node 4** | `38.76.174.32` | **唯一 Master 中枢** / Web 看板 / 调度中心 | `/opt/rakuten-hub/venv/bin/python3` | `/opt/rakuten-hub/rewrite_v1/master`<br>systemd: `rakuten-rewrite-master` (端口: 8998) |
| **Node 1** | `38.76.206.7` | **真实 Worker 节点 1** | `/opt/deepseek-suite/.venv/bin/python` | `/opt/rakuten-hub/rewrite_v1/worker` |
| **Node 2** | `156.225.31.92` | **真实 Worker 节点 2** | `/opt/rakuten-hub/.venv/bin/python` | `/opt/rakuten-hub/rewrite_v1/worker` |
| **Node 3** | `103.52.152.37` | **真实 Worker 节点 3** | `/opt/rakuten-hub/.venv/bin/python` | `/opt/rakuten-hub/rewrite_v1/worker` |

---

## 6. 隔离归档目录真本路径

* **本地工作区隔离区**：`quarantine_legacy_20260901/`
* **Node 1~4 远程服务器隔离区**：`/opt/rakuten-hub/quarantine_legacy_20260901/`
* **唯一受保护生产目录**：`/opt/rakuten-hub/rewrite_v1/`
