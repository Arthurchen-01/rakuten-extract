# 前端完整接入新系统：三种实施方案与验收标准

版本：1.0
目标：保留现有作战室前端外观，接入远程 Rewrite v1 Master、四节点 Worker、统一 batch_id、老板 16 列 Excel。

## 一、固定业务规则

```text
前端：https://lt.samuraiguan.cloud/
Node 4：唯一 Master
Node 1~4：真实远程 Worker
本地：只负责控制、下载、验收
真实浏览器：只能在远程 Worker 执行
每个账号最多导出3笔订单
登录成功后必须继续提取资料和订单
资料/订单没有：留空
资料/订单访问失败：标记失败，不能伪装成空
技术异常：不能标记为密码错误
```

最终用户操作必须是：

```text
上传账号与代理
→ 选择线程
→ 创建批次
→ 启动
→ 查看实时进度
→ 等待完成
→ 下载 Excel
```

## 二、三种方案总览

| 方案 | 做法 | 推荐程度 | 适用情况 |
|---|---|---:|---|
| A | 旧作战室 UI + 新 API 适配层 | ★★★★★ | 想保留现有界面，改动最少 |
| B | 旧作战室 UI + 后端兼容旧 API | ★★☆☆☆ | 只适合短期过渡，不适合作为最终架构 |
| C | 保留视觉风格，重写新的 batch 前端 | ★★★★☆ | 旧前端代码太乱、维护成本过高 |

AI 必须选择一种方案后执行。不得同时实现 A、B、C。

---

# 方案 A：旧作战室 UI + 新 API 适配层（推荐）

## A1. 核心思路

保留现有：

```text
quarantine_legacy_20260901/templates/index.html
quarantine_legacy_20260901/static/
```

只修改前端 JavaScript 的数据请求，不恢复旧后端业务逻辑。

前端所有数据都绑定：

```text
current_batch_id
```

## A2. 实施步骤

### 第 1 步：复制前端，不改原件

远程 Master 新目录：

```text
/opt/rakuten-hub/rewrite_v1/master/templates/index.html
/opt/rakuten-hub/rewrite_v1/master/static/
```

原始 UI 先保存 SHA-256。

### 第 2 步：改前端 API

前端只允许调用：

```http
POST /api/batches
POST /api/batches/{batch_id}/start
GET  /api/batches/{batch_id}
GET  /api/batches/{batch_id}/results.json
GET  /api/batches/{batch_id}/manifest.json
POST /api/batches/{batch_id}/export
GET  /api/batches/{batch_id}/export.xlsx
WS   /ws/logs?batch_id={batch_id}
```

前端禁止调用：

```http
/api/accounts
/api/orders
/api/task-status
/api/run-task
/api/export/excel?scope=last_batch
/download/latest.xlsx
```

### 第 3 步：上传账号和代理

上传后前端解析为：

```json
{
  "accounts": [
    {
      "account_id": "001",
      "email": "运行时数据",
      "password": "运行时数据",
      "proxy_ref": "代理引用"
    }
  ],
  "source_label": "web_upload"
}
```

服务器返回：

```json
{
  "batch_id": "...",
  "status": "CREATED",
  "input_account_count": 8
}
```

账号密码不得写入日志、浏览器 localStorage、截图或普通结果 JSON。

### 第 4 步：线程设置

前端提交：

```json
{
  "worker_count": 4,
  "concurrency_per_worker": 1,
  "order_limit": 3
}
```

服务器强制限制：

```text
worker_count >= 1
concurrency_per_worker >= 1
总并发不能超过服务器配置上限
order_limit 固定为3
```

### 第 5 步：启动

点击开始后：

```http
POST /api/batches/{batch_id}/start
```

返回：

```json
{
  "batch_id": "...",
  "status": "RUNNING"
}
```

### 第 6 步：轮询与日志

页面每 3 秒请求：

```http
GET /api/batches/{batch_id}
```

WebSocket 使用：

```text
/ws/logs?batch_id=...
```

只显示当前批次日志，不能显示旧批次全局日志。

### 第 7 步：导出

只有：

```text
status == COMPLETED
```

才启用导出按钮。

导出流程：

```http
POST /api/batches/{batch_id}/export
GET  /api/batches/{batch_id}/export.xlsx
```

## A3. 方案 A 验收

### 前端验收

```text
[ ] 打开生产域名显示原作战室 UI
[ ] 上传8户后显示8户
[ ] 返回明确batch_id
[ ] 选择线程后配置被保存
[ ] 点击开始后显示RUNNING
[ ] 页面只轮询当前batch_id
[ ] 旧批次不会出现在当前结果中
[ ] 任务未完成时导出按钮禁用
[ ] 完成后可以下载指定batch_id Excel
```

### 数据验收

```text
[ ] Master batch_id == Worker batch_id
[ ] results.json账号数 == 上传账号数
[ ] 每个账号只有一个最终结果
[ ] order_count == len(orders)
[ ] 每户订单数 <= 3
[ ] 资料失败不显示为资料为空
[ ] 技术异常不显示为密码错误
```

### Excel 验收

```text
[ ] Excel包含老板16列
[ ] JSON姓名/假名/生日/性别/地址/卡号逐项进入Excel
[ ] JSON订单号/店铺/商品/数量/金额逐项进入Excel
[ ] 没有资料字段保持空白
[ ] 没有订单保持空白
[ ] 没有占位符
[ ] 图片来自同一batch_id
[ ] xl/media数量与manifest一致
```

### 通过门槛

```text
前端8户上传成功
→ 1个batch_id
→ 4个Worker均有回报
→ JSON与Excel逐字段一致
→ Web下载文件与本地下载文件一致
→ validator PASS
```

---

# 方案 B：新后端兼容旧 API（不推荐）

## B1. 核心思路

保留现有前端 JavaScript，不改前端调用方式，在新 Master 增加兼容路由：

```http
/api/accounts
/api/orders
/api/task-status
/api/run-task
/api/export/excel
```

这些旧接口内部必须转换到新 `batch_id` 系统，不能继续读取旧全局缓存。

## B2. 实施步骤

### 第 1 步：旧 API 只做适配

旧接口收到请求后必须：

```text
创建或查找明确 batch_id
调用新 batch 服务
返回新 batch 数据
```

禁止直接读取：

```text
manager.accounts
orders_cache
last_batch
历史 Excel
```

### 第 2 步：建立 session → batch_id 映射

服务端保存：

```json
{
  "frontend_session_id": "...",
  "batch_id": "..."
}
```

每个前端会话只能操作自己的批次。

### 第 3 步：旧接口返回新字段

即使保留旧接口，也必须返回：

```json
{
  "batch_id": "...",
  "status": "RUNNING",
  "total": 8,
  "processed": 3,
  "orders": 7
}
```

### 第 4 步：兼容导出

旧请求：

```http
GET /api/export/excel
```

必须从 session 映射到明确 batch_id，再执行新导出器。

没有 session/batch_id 时必须返回：

```text
409 Missing batch_id
```

不能使用最近批次。

## B3. 方案 B 风险

```text
旧 API 很多，容易恢复旧 bug
前端看起来不用改，但后台兼容代码会变复杂
容易再次出现全局状态和批次混用
长期维护成本高
```

## B4. 方案 B 验收

```text
[ ] 旧前端所有请求都被记录
[ ] 每个请求都能追溯到batch_id
[ ] 没有请求读取旧全局缓存
[ ] 没有请求使用last_batch
[ ] 旧API导出的Excel与新API完全一致
[ ] 无batch_id请求返回409
[ ] 任务未完成时旧导出接口也返回409
[ ] 旧接口错误不会改变新批次结果
```

只要发现任一旧接口绕过 batch_id，方案 B 失败，应改选方案 A 或 C。

---

# 方案 C：保留视觉风格，重写新的 Batch 前端

## C1. 核心思路

保留原作战室的：

```text
颜色
布局
四节点卡片
实时日志区域
状态统计
账号列表
订单列表
截图区域
```

但重写前端 JavaScript 和页面状态管理，不复用旧页面的请求函数。

## C2. 实施步骤

### 第 1 步：保留视觉资源

允许复用：

```text
CSS颜色
图标
布局
字体
静态图片
```

不复用：

```text
旧fetch函数
旧全局变量
旧轮询函数
旧last_batch逻辑
旧导出函数
```

### 第 2 步：建立单一前端状态

```javascript
const state = {
  batchId: null,
  status: "IDLE",
  total: 0,
  processed: 0,
  accounts: [],
  orders: [],
  screenshots: [],
  workers: []
}
```

所有页面组件只读取这个 state。

### 第 3 步：实现用户操作

```text
上传账号/代理
→ 创建batch
→ 选择线程
→ 启动batch
→ 轮询batch
→ 显示状态
→ 显示截图
→ 完成后导出
```

### 第 4 步：实现错误显示

前端必须显示：

```text
密码明确错误
需要2FA
需要Passkey
需要CAPTCHA
技术异常待重试
资料为空
资料提取失败
订单为空
订单提取失败
```

禁止只显示：

```text
失败
异常
活跃
```

### 第 5 步：实现批次导出

```text
batch.status != COMPLETED → 禁用导出
batch.status == COMPLETED → 显示下载
```

## C3. 方案 C 验收

```text
[ ] 新前端不调用任何旧API
[ ] 前端只有一个batch状态对象
[ ] 刷新页面后能恢复当前batch_id
[ ] 账号、订单、截图都按batch_id显示
[ ] 任务状态与结果状态一致
[ ] 线程配置实际传到Master
[ ] 任务未完成不能导出
[ ] Web下载Excel与batch results一致
[ ] 旧UI之外的旧逻辑没有被调用
```

## C4. 方案 C 适用条件

选择 C 的条件：

```text
旧前端超过2000行且请求逻辑混乱
旧接口无法安全兼容
愿意保留外观但接受前端代码重写
```

---

# 三种方案的统一远程验收流程

无论选择 A、B 或 C，都必须只在远程服务器执行真实采集。

## 阶段 0：Master

```text
Node 4启动唯一新Master
检查 /health 返回 rewrite-v1
检查生产域名与Node4版本一致
```

## 阶段 1：单户

```text
前端上传1户
选择并发1
启动
等待完成
下载结果
```

必须验证：

```text
登录截图
资料截图
订单截图
最多3笔订单
JSON字段
Excel字段
```

## 阶段 2：三节点

```text
Node 1：1户
Node 2：1户
Node 3：1户
Node 4：Master
```

必须满足：

```text
3个worker_id
1个batch_id
3个结果
没有重复认领
没有跨批次回报
```

## 阶段 3：四节点8户

```text
每节点2户
并发先设1
```

必须满足：

```text
8个账号结果
同一个batch_id
4个节点均有claim/report
Excel与JSON一致
截图manifest一致
```

## 阶段 4：扩大规模

```text
10户 → 50户 → 100户 → 500户 → 全量
```

任何一档出现以下情况，立即停止：

```text
前端账号数 != batch账号数
Excel订单数 != JSON订单数
截图缺失
技术异常被判成密码错误
任务状态停止增长
Web下载结果与本地结果不同
```

---

# AI 执行规则

AI 必须先回答：

```text
选择方案：A / B / C
选择理由：不超过5行
本次修改文件：明确列出
本次不修改文件：明确列出
本次远程部署节点：明确列出
本次验收命令：明确列出
```

然后才可以执行。

AI 不得：

```text
同时实现三种方案
自行扩大任务规模
自行删除旧程序
自行覆盖前端原件
用文字宣布PASS而没有机器结果
下载失败时复制本地Excel冒充Web下载
```

## AI 完成报告格式

```text
方案：A/B/C
修改文件：...
部署节点：...
批次ID：...
远程结果：...
本地验收：PASS/PARTIAL/FAIL
失败项：...
Web与本地Excel是否一致：是/否
是否允许进入下一阶段：是/否
```

## 最终推荐

优先顺序：

```text
首选 A：保留现有作战室，只改 API 接口
备选 C：旧前端过于混乱时重写前端逻辑
不建议 B：兼容旧 API 容易再次引入历史问题
```

当前第一步只允许：

```text
选择方案 A
远程 Node 4 + Node 1
真实单户测试
```

单户没有通过，不得测试 3 户、8 户或大盘。
