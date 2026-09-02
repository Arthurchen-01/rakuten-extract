# 乐天账号订单采集系统：全新重写需求与逻辑规范

> 版本：Rewrite v1.0
> 状态：设计基线，尚未进入生产
> 原则：单一数据源、单一批次、单一导出器、失败即停止、可追溯优先

---

## 0. 重写目标

本系统重新实现以下能力：

1. 通过真实浏览器自动化访问授权的楽天账号页面；
2. 提取登录结果、个人资料、地址、订单列表和订单详情；
3. 保存原始页面证据、结构化 JSON 和阶段截图；
4. 生成唯一批次对应的 Excel；
5. 通过独立验收器校验 JSON、截图、Excel 和批次是否一致；
6. 提供 Web 控制台进行导入、启动、进度查看和下载；
7. 任何不完整、来源不明或结果不一致的批次都不得标记为完成。

本系统不承诺“100% 官方原件”或“绝对真实”。系统只能记录：

> 在指定时间、指定浏览器环境下，从目标页面观察并保存的结果。

所有推断、清洗和格式化必须与页面原始证据分开保存。

---

## 1. 非目标与禁止事项

### 1.1 非目标

本次重写不包含：

- 历史旧数据自动合并；
- 多套 Excel 导出器并行运行；
- 自动猜测截图归属；
- 根据订单号前缀冒充页面店铺原文；
- 将登录失败账号当作 0 订单账号；
- 将示意图当作真实 Web 截图；
- 自动绕过 CAPTCHA、2FA 或 Passkey 安全控制。

### 1.2 禁止事项

- 禁止在源码、日志、JSON、截图或报告中写入明文密码、Token、私钥；
- 禁止把秘密写入 Git、共享目录或聊天报告；
- 禁止使用 `except: pass` 隐藏登录、导航、上传、导出错误；
- 禁止下载失败后复制本地文件冒充 Web 下载结果；
- 禁止任务未完成时导出“最终报表”；
- 禁止使用“最近一次批次”代替明确 `batch_id`；
- 禁止把程序生成的占位文本当作官方字段；
- 禁止在没有证据时宣称四节点、全量或 100% 完成。

---

## 2. 总体架构：远程优先

本系统不在本地电脑模拟服务器、Worker 或浏览器采集。真实任务必须在远程服务器执行。

```text
本地控制端（只发指令、看状态、下载、验收）
    ↓ HTTPS / SSH部署
生产 Web 中枢 server.py（远程 Master）
    ↓ batch_id + claim lease
远程 worker.py（Node 1~N）
    ↓
远程 extractor.py + Chromium
    ↓
楽天官方页面
    ↓
远程批次目录 results.json + evidence_manifest.json + screenshots/
    ↓ HTTPS 下载指定 batch_id 结果
本地 exporter.py
    ↓
本地 validator.py 独立验收
```

本地电脑不执行以下生产行为：

- 不模拟 server.py；
- 不模拟 worker.py；
- 不模拟浏览器登录；
- 不生成伪造的远程任务结果；
- 不把本地固定样本称为远程实测；
- 不使用本地 `SimulatedWorker` 证明远程集群能力。

本地只能执行：

- 控制 API 请求；
- 代码部署；
- 远程状态读取；
- 指定批次结果下载；
- 截图下载；
- 本地 Excel 生成；
- 本地离线验收。

### 2.1 本地职责

本地控制端只负责：

- 准备不含明文密码的批次元数据；
- 生成并保存输入文件哈希；
- 通过 HTTPS/SSH 向远程服务器发起任务或部署代码；
- 查询远程 `batch_id` 状态；
- 从远程下载指定 `batch_id` 的结果、manifest 和截图；
- 在本地运行唯一导出器和验收器；
- 生成最终报告。

本地禁止执行真实采集。真实账号密码只在远程受保护运行时使用，不落入本地源码、日志或报告。

本地不负责：

- 直接从多个历史目录拼接数据；
- 使用旧版缓存补全新批次；
- 自动把远端路径映射到本地；
- 在 Web 任务失败后自行伪造成功结果。

### 2.2 服务器职责

服务器负责：

- 提供 API 和 Web 控制台；
- 管理批次状态；
- 分配任务给 worker；
- 保存指定批次的结果和截图；
- 仅使用指定批次数据导出。

服务器不负责：

- 隐式读取全局历史账号作为当前批次；
- 将不同批次的订单混合；
- 维护第二套订单导出逻辑；
- 在任务仍运行时生成最终 Excel。

### 2.3 Worker 职责

worker 只能在远程 Node 上运行。它不是本地模拟器。

worker 只做四件事：

1. 领取 `batch_id` 和账号任务；
2. 调用 `extractor.py`；
3. 将结果和截图写入该批次目录；
4. 回报成功、失败或挑战状态。

worker 不生成最终 Excel，不修改其他批次，不共享截图目录。

---

## 3. 最小代码模块

生产代码只保留以下模块：

```text
controller.py   # 本地任务控制、下载、调用验收
server.py       # API、Web 页面、批次状态和下载
worker.py       # 远程任务执行
extractor.py    # Playwright 页面采集
exporter.py     # JSON + manifest → Excel
validator.py    # 独立离线验收
models.py       # 数据模型、状态枚举、批次模型
```

### 3.1 删除或不再参与生产运行的旧模块

以下旧逻辑不得被新系统 import：

```text
rakuten_engine.py
cluster_deep_profile_runner.py
auto_export_audit_daemon.py
旧版 export_excel_with_screenshots.py
frozen_pipeline_v1.0/
backups/
data/backups/
历史 scratch 测试脚本
```

这些文件在正式重写完成后移到只读归档区或删除；删除前必须先完成备份和文件清单记录。

### 3.2 唯一导出入口

生产系统只允许：

```python
exporter.generate_workbook(batch_dir)
```

禁止服务器、worker、旧引擎各自实现 Excel 生成。

---

## 4. 批次模型

每一次任务必须有唯一不可变的 `batch_id`：

```text
YYYYMMDD-HHMMSS-随机短 ID
```

示例：

```text
20260831-181500-a7f3
```

### 4.1 批次目录

```text
data/runs/<batch_id>/
├─ input.txt
├─ input.sha256
├─ batch.json
├─ results.json
├─ evidence_manifest.json
├─ screenshots/
├─ output.xlsx
├─ output.sha256
├─ audit.json
└─ run.log
```

### 4.2 批次不可变原则

- `input.txt` 写入后不可覆盖；
- `results.json` 只允许由该批次 worker 写入；
- 任务完成后结果不可静默修改；
- 重新清洗必须生成新版本或新批次；
- Excel 文件名必须包含 `batch_id` 或在 `batch.json` 中绑定；
- 所有产物必须记录生成时间、代码版本和输入哈希。

### 4.3 批次状态

```text
CREATED       已创建
QUEUED        已排队
RUNNING       执行中
COMPLETED     所有账号已得到终态
PARTIAL       有结果但不完整，不得最终交付
FAILED        批次失败
CANCELLED     已取消
```

`COMPLETED` 的必要条件：

```text
processed_count == input_account_count
pending_count == 0
每个账号均有终态
结果文件可读
截图清单可验证
```

遇到密码错误、2FA、Passkey、CAPTCHA 时，账号可以进入终态，但必须明确标记为挑战或失败；不能记作成功，也不能记作已确认 0 订单。

---

## 5. 数据模型

### 5.1 账号结果

```json
{
  "batch_id": "20260831-181500-a7f3",
  "account_id": "输入文件中的稳定序号",
  "email_hash": "脱敏后的账号标识",
  "status": "active|wrong_password|two_factor|passkey|captcha|network_error|partial",
  "terminal": true,
  "login_verified": true,
  "profile": {
    "last_name": "",
    "first_name": "",
    "last_name_kana": "",
    "first_name_kana": "",
    "birthday": "",
    "gender": "",
    "address": "",
    "phone": "",
    "card_masked": ""
  },
  "orders": [],
  "order_count": 0,
  "total_history_order_count": null,
  "scraped_order_count": 0,
  "screenshots": [],
  "errors": []
}
```

### 5.2 订单结果

```json
{
  "order_number": "",
  "order_date": "",
  "shop_name": "",
  "item_name": "",
  "quantity": "",
  "price_yen": "",
  "payment_method": "",
  "delivery_address": "",
  "buyer_info": "",
  "raw_dom_text": "",
  "detail_url": "",
  "detail_screenshot": ""
}
```

规则：

- 页面没有提供的字段必须为空；
- 不允许写入 `お客様`；
- 不允许写入 `楽天市場ご注文商品`；
- 不允许写入默认支付方式；
- 不允许仅凭 Shop ID 映射覆盖页面字段；
- 若使用外部映射，只能写入 `shop_name_inferred`，不能覆盖 `shop_name`；
- `order_count` 必须等于 `len(orders)`；
- `scraped_order_count` 必须等于实际保存订单数；
- 历史订单总数和详情抓取数必须分开。

---

## 6. 浏览器采集逻辑

### 6.1 登录流程

```text
打开官方登录页
→ 等待页面稳定
→ 输入账号
→ 判断密码页 / Passkey / 错误页
→ 如出现官方密码切换入口，执行明确的页面点击
→ 输入密码
→ 等待官方结果
→ 通过 URL + 页面标识双重确认登录态
→ 保存登录成功或失败截图
```

登录成功必须同时满足：

- 不在登录网关；
- URL 属于预期已登录页面；
- 页面包含至少一个可靠登录后标识；
- 没有密码错误、2FA、Passkey、CAPTCHA 文案。

不能仅凭“页面没有报错”判定成功。

### 6.2 资料和地址

- 每一步导航必须检查返回值和最终 URL；
- 页面加载失败必须记录错误并结束该账号；
- 页面字段直接读取 DOM；
- 不用正则从整页文本猜测姓名或地址，除非保存为低置信度候选；
- 原始 DOM 文本单独保存，清洗值另存。

### 6.3 订单列表

- 记录页面显示的订单总数（如果页面提供）；
- 记录识别到的订单卡片数；
- 每个订单必须有稳定详情 URL 或明确异常原因；
- 不使用固定前三单限制；
- 如果因平台分页限制未能全量抓取，状态必须为 `partial`；
- 不得把未访问的订单记入 `orders`。

### 6.4 订单详情

优先顺序：

1. 订单详情专用 DOM 节点；
2. 订单容器内的店铺链接；
3. 页面明确的店铺文本；
4. 无法确定时留空并记录原因。

禁止从全页第一个包含“店”“ショップ”“ストア”的文本中猜店铺。

每个详情页必须保存：

- 详情 URL；
- 访问时间；
- 页面截图；
- 原始 DOM 文本或关键 DOM 片段；
- 结构化字段；
- 解析错误。

---

## 7. 截图证据规则

### 7.1 文件命名

```text
screenshots/<account_id>/
├─ 01_login_result.png
├─ 02_profile.png
├─ 03_address.png
├─ 04_order_list.png
├─ 05_order_<order_number>.png
└─ error_<type>.png
```

截图不得使用全局固定文件名，避免不同账号互相覆盖。

### 7.2 manifest

每张截图必须记录：

```json
{
  "account_id": "001",
  "stage": "order_detail",
  "file_name": "05_order_xxx.png",
  "relative_path": "screenshots/001/05_order_xxx.png",
  "sha256": "...",
  "size_bytes": 123456,
  "captured_at": "...",
  "source_url": "..."
}
```

### 7.3 Excel 嵌图

- 只有 manifest 中存在且哈希匹配的本地文件才允许嵌入；
- M 列和 N 列必须绑定不同文件；
- 异常账号只有一张证据图时，N 列保持空，不复制 M 图；
- 保存后必须检查 `ws._images`；
- 解压 XLSX 必须检查 `xl/media/`；
- 图片数量不足时，导出失败，不得继续生成“通过”报告。

---

## 8. Excel 规则

固定四个工作表：

```text
乐天导出导入
口径说明
账号检测与现场快照总览
订单明细总览
```

### 8.1 Sheet 1

保留 16 列标准结构，但：

- 空值写空字符串；
- 不写程序占位符；
- 订单列只放实际抓取订单；
- 有多个订单时只按明确规则放入，不隐藏截断。

### 8.2 Sheet 3

必须显示：

- 批次 ID；
- 账号脱敏标识；
- 账号状态；
- 登录是否验证；
- 历史订单数；
- 实际抓取订单数；
- 图片状态；
- 错误原因。

### 8.3 Sheet 4

每一行对应一个实际保存的订单对象。

必须满足：

```text
Sheet4订单行数 == sum(len(account.orders))
```

### 8.4 导出完成条件

导出器生成 Excel 后必须执行：

```text
JSON 可读
订单字段校验通过
截图 manifest 校验通过
本地 Excel 可读
图片实体数量符合 manifest
Sheet 3 行数正确
Sheet 4 行数正确
```

任一失败即拒绝导出最终文件。

---

## 9. Web API

### 9.1 创建批次

```http
POST /api/batches
```

请求包含：

- 输入文件；
- 可选代理配置引用（不得提交明文秘密）；
- 运行参数；
- 代码版本。

返回：

```json
{
  "batch_id": "...",
  "input_account_count": 8,
  "input_sha256": "...",
  "status": "CREATED"
}
```

### 9.2 启动批次

```http
POST /api/batches/{batch_id}/start
```

只允许启动一次。运行中再次启动返回 `409`。

### 9.3 查询批次

```http
GET /api/batches/{batch_id}
```

返回：

- 状态；
- 总数；
- 已处理数；
- 成功数；
- 失败数；
- 挑战数；
- 实际订单数；
- 活跃 worker；
- 最近错误；
- 代码版本。

### 9.4 导出批次

```http
GET /api/batches/{batch_id}/export.xlsx
```

规则：

- 必须显式提供 `batch_id`；
- 批次不是 `COMPLETED` 时返回 `409`；
- 返回文件必须来自该批次目录；
- 不允许使用全局 `manager.accounts` 代替批次结果；
- 不允许使用“最近一次导入”；
- 下载文件名包含 `batch_id`；
- 响应头返回 JSON、Excel 和 manifest 哈希。

### 9.5 结果下载

```http
GET /api/batches/{batch_id}/results.json
GET /api/batches/{batch_id}/manifest.json
GET /api/batches/{batch_id}/screenshots/{path}
```

所有路径必须做目录穿越防护。

---

## 10. 四节点规则

四节点不是四套独立业务系统，而是同一个中枢下的执行资源。

```text
一个 Master
一个 batch_id
多个 worker
一个 results.json
一个 manifest.json
一个 exporter
```

每个 worker 上报：

```text
worker_id
batch_id
process_id
loaded_code_version
loaded_module_paths
started_at
finished_at
claimed_count
completed_count
error_count
```

代码同步审计必须区分：

```text
同步前哈希
同步后哈希
运行进程实际加载文件
```

仅上传文件后再计算哈希，不足以证明运行进程使用了该版本。

四节点验收最少需要：

- 四节点均在线；
- 每节点至少成功领取一个测试任务；
- 每节点回传一个结果；
- 每节点回传一张截图；
- Master 能按 `batch_id` 合并；
- 合并后账号不重复、不丢失；
- 结果和截图哈希可复核。

---

## 11. 独立验收器

`validator.py` 不依赖 Web 页面状态文字，只读取指定批次目录。

### 11.1 必检项目

```text
input.txt 存在且哈希匹配
账号数量正确且不重复
每个账号有终态
失败/挑战账号不被当作成功
order_count == len(orders)
scraped_order_count == len(orders)
订单关键字段符合口径
禁止占位符为 0
截图 manifest 文件存在
截图大小匹配
截图 SHA-256 匹配
M/N 不重复
本地 Excel 可读
Sheet 3 行数正确
Sheet 4 行数正确
xl/media 数量匹配
ws._images 数量匹配
```

### 11.2 Web 下载验收

Web 下载文件必须单独执行同样的校验：

```text
Web Excel 存在
Web Excel 可读
Web Excel batch_id 一致
Web Excel 账号集合一致
Web Excel 订单号集合一致
Web Excel 图片数量一致
Web Excel 哈希写入审计记录
```

生产 Web 下载失败时，必须失败；不得复制本地 Excel伪造下载文件。

### 11.3 验收输出

```json
{
  "status": "PASS|FAIL",
  "batch_id": "...",
  "checks": {
    "input": true,
    "accounts": true,
    "orders": true,
    "screenshots": true,
    "local_excel": true,
    "web_excel": true
  },
  "failures": [],
  "artifacts": {}
}
```

只有所有必检项为 `true` 时才允许 `PASS`。

---

## 12. 错误处理

错误必须结构化保存：

```json
{
  "stage": "login|profile|orders|export|upload",
  "code": "TIMEOUT|AUTH_FAILED|CHALLENGE|PARSE_ERROR|UPLOAD_ERROR",
  "message": "脱敏后的错误信息",
  "retryable": false,
  "attempt": 1,
  "at": "..."
}
```

规则：

- 认证失败：终态，不重试密码；
- 2FA/Passkey/CAPTCHA：挑战终态，不自动绕过；
- 网络超时：有限次数重试；
- 解析错误：保存截图后终止该账号；
- 上传失败：批次不得标记完成；
- 导出失败：不得生成最终交付标识。

---

## 13. 安全要求

### 13.1 秘密管理

账号密码只允许来自：

- 受保护的运行时输入；或
- 操作系统秘密存储；或
- 加密配置文件。

禁止：

- 写入 Python 源码；
- 写入日志；
- 写入截图；
- 写入最终报告；
- 写入 Git；
- 通过命令行参数传递明文密码。

### 13.2 个人数据

订单、姓名、地址、电话和卡片后四位属于敏感数据：

- 默认只在本地受保护批次目录保存；
- 报告使用脱敏标识；
- 分享前必须执行脱敏导出；
- 临时目录任务结束后清理；
- 审计文件中只保留必要字段。

### 13.3 凭证轮换

任何已经出现在聊天、脚本、日志或共享目录中的凭证都视为已暴露，必须轮换后才能继续使用。

---

## 14. 重写顺序

### 阶段 0：远程执行前提

1. 确认远程 Master 可访问；
2. 确认每个 Node 的 Chromium/Playwright 运行环境；
3. 确认每个 Node 的 Worker 进程由受控服务启动；
4. 确认远程批次目录和权限；
5. 确认真实凭证通过远程秘密注入，不写入本地或源码；
6. 用 1 户真实远程账号做 smoke test；
7. 本地只下载并验收远程结果。

没有完成阶段 0，不得把本地夹具测试视为远程系统通过。

### 阶段 1：冻结和清理

1. 停止旧 server、worker、daemon；
2. 备份历史数据到只读归档；
3. 创建新 `data/runs/`；
4. 不让新代码 import 旧模块；
5. 删除源码中的明文凭证。

### 阶段 2：单机最小闭环

1. 实现 `models.py`；
2. 实现 `extractor.py`；
3. 实现 `exporter.py`；
4. 实现 `validator.py`；
5. 用脱敏/测试数据验证导出；
6. 通过 1 户正向和 1 户失败流程。

### 阶段 3：单服务器闭环

1. 实现 `server.py` 的 batch API；
2. 实现一个 `worker.py`；
3. 用同一个 `batch_id` 完成 3 户测试；
4. 验证 Web 下载和本地导出来自同一批次；
5. 禁止不完整导出。

### 阶段 4：四节点闭环

1. 每节点部署相同版本；
2. 每节点做单户 smoke test；
3. 运行 8 户批次；
4. 验证分配、合并、截图和哈希；
5. 只保留一条生产导出链。

### 阶段 5：大盘运行

只有阶段 1～4 全部通过后，才允许运行大盘。

大盘必须先做：

```text
小批次 → 100户 → 500户 → 全量
```

任何阶段出现数据分叉，立即停止，不得继续扩大任务规模。

---

## 15. 交付门禁

最终报告只允许使用以下状态词：

```text
PASS       所有必检项通过
PARTIAL    结果部分完成，禁止作为最终真本
REJECTED   至少一个必检项失败
```

禁止使用没有定义的表述：

```text
法定真本
100%绝对真实
零风险
全网唯一真本
全部官方原件
```

除非报告同时提供：

- 明确批次 ID；
- 输入哈希；
- 结果 JSON 哈希；
- manifest 哈希；
- Excel 哈希；
- Web 下载 Excel 哈希；
- 验收脚本版本；
- 完整失败清单；
- 安全脱敏证明。

---

## 16. 重写完成定义

重写完成不等于“脚本能运行”，而是必须满足：

```text
单一 batch_id
→ 单一 results.json
→ 单一 evidence_manifest.json
→ 单一 exporter.py
→ 单一 output.xlsx
→ 单一 validator.py
→ 本地与 Web 下载结果一致
```

并且：

```text
没有隐式旧缓存
没有多套导出器
没有伪造回退
没有未记录过滤
没有未验证截图
没有明文凭证
没有把未登录账号当成0订单
```

达到以上条件后，系统才具备进入生产大盘的资格。
