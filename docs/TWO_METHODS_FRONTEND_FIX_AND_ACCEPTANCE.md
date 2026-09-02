# 前端完整操作接入：两种修复方法与完整验收流程

版本：1.0
目标：保留现有作战室前端外观，让用户从前端完成“上传账号/代理 → 选择线程 → 启动 → 监控 → 截图查看 → 导出老板16列 Excel”。真实登录和采集只能在远程服务器执行。

## 固定规则

```text
前端：https://lt.samuraiguan.cloud/
Node 4：唯一 Master
Node 1~3：Worker
本地：只部署、下载、验收
真实浏览器：远程 Worker 执行
每个账号最多3笔订单
登录成功后必须继续资料和订单采集
没有数据：字段留空
页面访问失败：记录 failed，不得写成 empty
技术异常：不得写成密码错误
```

禁止：

```text
使用最近一次批次
使用全局 manager.accounts 作为当前结果
使用全局 orders_cache 混批
Worker 自己生成另一份 Excel
下载失败复制本地文件冒充 Web 下载
前端继续调用无 batch_id 的旧全局接口
```

---

# 方法一：保留作战室外观，前端改接新 Batch API（推荐）

## 适用

```text
想保留现有界面和操作习惯
允许修改前端 JavaScript
希望彻底消除旧全局状态
```

## 一、目标架构

```text
浏览器前端
    ↓
https://lt.samuraiguan.cloud/
    ↓
Node 4 Master server.py
    ↓ batch_id + SQLite
Node 1~3 Worker
    ↓
远程 extractor.py + Chromium
    ↓
同一 batch_id/results.json + manifest
    ↓
Node 4 唯一 exporter
    ↓
同一 batch_id/output.xlsx
```

Node 4 只做 Master，不同时作为业务 Worker，避免统计和调度混淆。

## 二、后端必须实现的接口

### 1. 健康检查

```http
GET /health
```

必须返回：

```json
{
  "status": "ok",
  "version": "rewrite-v1",
  "role": "master",
  "db_path": "..."
}
```

### 2. 创建批次

```http
POST /api/batches
```

请求：

```json
{
  "accounts": [
    {
      "account_id": "001",
      "email": "...",
      "password": "...",
      "proxy": "..."
    }
  ],
  "source_label": "web_upload",
  "settings": {
    "worker_count": 3,
    "concurrency_per_worker": 1,
    "order_limit": 3
  }
}
```

返回：

```json
{
  "batch_id": "BATCH-...",
  "status": "CREATED",
  "input_account_count": 8,
  "order_limit": 3
}
```

密码和代理密码不能写入普通日志、截图、前端 localStorage 或最终审计报告。

### 3. 启动批次

```http
POST /api/batches/{batch_id}/start
```

服务端必须：

```text
确认批次存在
确认未有其他运行批次冲突
保存线程配置
启动/唤醒 Node 1~3 Worker
状态改为 RUNNING
返回 worker 分配结果
```

不能只返回 `RUNNING` 而不启动 Worker。

### 4. 查询批次

```http
GET /api/batches/{batch_id}
```

返回必须包含：

```json
{
  "batch_id": "...",
  "status": "RUNNING",
  "input_account_count": 8,
  "processed_count": 3,
  "pending_count": 5,
  "success_count": 2,
  "wrong_password_count": 1,
  "challenge_count": 0,
  "technical_retryable_count": 0,
  "profile_failed_count": 0,
  "orders_failed_count": 0,
  "order_count": 4,
  "workers": []
}
```

### 5. 批次结果

```http
GET /api/batches/{batch_id}/results.json
GET /api/batches/{batch_id}/manifest.json
```

所有结果必须带：

```text
batch_id
account_id
worker_id
attempt_id
login_status
profile_status
orders_status
overall_status
```

### 6. 截图

```http
GET /api/batches/{batch_id}/screenshots/{relative_path}
```

路径必须限制在当前 batch 目录内，禁止目录穿越。

### 7. 导出

```http
POST /api/batches/{batch_id}/export
GET /api/batches/{batch_id}/export.xlsx
```

规则：

```text
COMPLETED 才允许最终导出
RUNNING/QUEUED 返回409
PARTIAL 只能导出诊断包
导出的结果必须来自该 batch_id
```

## 三、前端修改内容

保留现有：

```text
HTML布局
四节点卡片
状态拨盘
日志窗口
账号Tab
订单Tab
截图窗口
```

重写/替换：

```text
旧全局变量
旧 /api/task-status 轮询
旧 /api/accounts
旧 /api/orders
旧 /api/export/excel?scope=last_batch
旧 last_batch 逻辑
旧全局截图路径
```

前端只维护一个状态对象：

```javascript
const state = {
  batchId: null,
  status: "IDLE",
  total: 0,
  processed: 0,
  accounts: [],
  orders: [],
  workers: [],
  screenshots: []
};
```

用户操作：

```text
1. 上传账号/代理文件
2. 前端预览账号数
3. 选择 Worker 数和并发数
4. 点击开始
5. 保存返回的 batch_id
6. 每3秒查询 /api/batches/{batch_id}
7. 查看当前批次账号/订单/截图
8. COMPLETED 后启用导出
```

前端线程控件建议只允许：

```text
Worker数：1~4
每Worker并发：1~5
总并发：服务端限制
订单上限：固定3，不允许前端修改
```

## 四、远程部署顺序

### 第1步：Node 4

部署：

```text
server.py
db.py
models.py
exporter.py
validator.py
templates/index.html
static/
```

启动唯一服务：

```text
rakuten-rewrite-master.service
```

确认：

```text
systemctl status rakuten-rewrite-master
curl http://127.0.0.1:8998/health
curl https://lt.samuraiguan.cloud/health
```

两个健康响应的 `version` 和 `role` 必须一致。

### 第2步：Node 1~3

部署：

```text
worker.py
extractor.py
models.py
```

每个节点使用 systemd 常驻 Worker，等待任务，不由用户每次手工 SSH 启动。

Worker 必须向 Node 4 报告：

```text
worker_id
version
PID
loaded_module_path
last_heartbeat
```

### 第3步：停止旧调度入口

只停止旧楽天相关服务：

```text
旧 server.py
旧 cloud_worker.py
旧 cluster_aggregator_daemon.py
旧楽天 runner
```

不要杀掉与楽天无关的业务服务。

旧文件移到：

```text
/opt/rakuten-hub/quarantine_legacy/<timestamp>/
```

## 五、方法一验收

### A. Master

```text
[ ] Node 4 /health 返回 rewrite-v1
[ ] 生产域名 /health 返回同一版本
[ ] 8998 只有一个 Master
[ ] 当前服务 cwd 为 rewrite_v1/master
[ ] 旧楽天 Master 不运行
```

### B. 前端上传

```text
[ ] 上传1户显示1户
[ ] 上传3户显示3户
[ ] 上传8户显示8户
[ ] 返回唯一 batch_id
[ ] 代理配置进入批次
[ ] 密码不出现在日志和页面 localStorage
```

### C. 线程

```text
[ ] 选择1线程实际保存配置
[ ] 选择3 Worker实际出现3个worker_id
[ ] Worker并发不超过服务端限制
[ ] Node 4不重复作为业务Worker
```

### D. 单户真实测试

```text
[ ] Node 1 claim
[ ] Node 1 heartbeat
[ ] 登录截图
[ ] 资料截图
[ ] 订单列表截图
[ ] 登录成功后继续资料和订单
[ ] 最多3笔订单
[ ] 无资料字段为空
[ ] 无订单字段为空
[ ] 资料访问失败标profile_failed
[ ] 订单访问失败标orders_failed
[ ] 技术异常不标wrong_password
[ ] results.json写入同一batch_id
[ ] manifest路径、大小、哈希一致
[ ] Excel 16列正确
[ ] Excel姓名/资料与JSON一致
[ ] Excel订单与JSON一致
```

### E. 3户跨节点

```text
[ ] Node 1、2、3各领取1户
[ ] 3个worker_id
[ ] 1个batch_id
[ ] 3个结果
[ ] 3个账号无重复/丢失
[ ] 3个节点均有日志和回报
[ ] Excel与JSON一致
```

### F. 8户四节点

```text
[ ] Node 1~3均有真实claim/report
[ ] Node 4只做Master
[ ] 8个账号结果齐全
[ ] batch_id全部一致
[ ] 订单数每户不超过3
[ ] 技术异常与密码错误分开
[ ] 前端显示与Master一致
[ ] Web下载Excel与results.json一致
[ ] 图片manifest与Excel一致
```

通过后才能扩大到：

```text
10户 → 50户 → 100户 → 500户 → 全量
```

---

# 方法二：保留前端旧 JavaScript，由新后端兼容旧接口

## 适用

```text
不想立刻改旧前端代码
希望先快速恢复原作战室操作
```

这是过渡方案，不是长期推荐方案。

## 一、核心思路

旧前端继续调用：

```http
/api/task-status
/api/accounts
/api/orders
/api/run-task
/api/export/excel
/ws/logs
```

但新 Master 内部必须把这些请求转换成新批次系统：

```text
旧接口请求
    ↓
session → batch_id 映射
    ↓
新 SQLite 批次数据
    ↓
新 Worker
    ↓
新 results.json
    ↓
新 exporter
```

旧接口不能再读取：

```text
manager.accounts
orders_cache
last_batch
历史 Excel
```

## 二、接口转换规则

### `/api/run-task`

收到旧前端启动请求后：

```text
解析账号、密码、代理和线程配置
创建新 batch_id
保存 session_batch_id
启动 Node 1~3 Worker
返回 batch_id
```

### `/api/task-status`

必须返回旧前端需要的字段，同时带新批次号：

```json
{
  "batch_id": "...",
  "is_running": true,
  "total": 8,
  "current": 3,
  "pending": 5,
  "success_count": 2,
  "failed_count": 1,
  "cluster_nodes": {
    "Node_1": {
      "status": "RUNNING",
      "threads_count": 1,
      "part_stats": {
        "total": 3,
        "pending": 1,
        "active": 1,
        "wrong_password": 1,
        "failed_total": 1
      }
    }
  }
}
```

`part_stats` 必须根据当前 `batch_id` 的账号结果计算，不能填固定 0 或硬编码 927。

### `/api/accounts`

返回当前 session 对应批次的账号结果：

```text
session没有batch_id → 409
batch不存在 → 404
不能返回全局账号列表
```

### `/api/orders`

返回当前 session 对应批次的订单：

```text
只读取该batch_id
不读取历史orders_cache
```

### `/api/export/excel`

```text
从session找到batch_id
batch未完成 → 409
batch完成 → 调用唯一新exporter
```

没有 session/batch_id 时不得使用最近批次。

## 三、方法二验收

### 兼容接口

```text
[ ] 旧前端所有请求都被记录
[ ] 每个请求都能关联batch_id
[ ] 无batch_id请求返回409
[ ] 不读取manager.accounts作为结果源
[ ] 不读取orders_cache作为结果源
[ ] 不使用last_batch
[ ] task-status的part_stats不是固定0
[ ] part_stats总数等于当前batch账号数
[ ] /api/accounts与当前batch一致
[ ] /api/orders与当前batch一致
```

### 业务流程

```text
[ ] 旧前端上传1户成功
[ ] 旧前端上传3户成功
[ ] 旧前端选择线程生效
[ ] 点击启动能唤醒Worker
[ ] 页面状态随当前batch更新
[ ] 登录成功继续资料和订单
[ ] 最多3笔订单
[ ] 没有资料真实留空
[ ] 没有订单真实留空
[ ] 技术错误不变成密码错误
[ ] 导出与JSON一致
[ ] Web下载Excel含正确截图
```

### 风险门槛

只要发现以下任意一项，方法二停止：

```text
旧接口直接读旧缓存
旧接口使用last_batch
前端显示批次与Excel批次不同
part_stats需要硬编码才能显示
旧API修改新批次状态失败
```

此时切换方法一。

---

# 两种方法如何选择

## 推荐选择方法一，如果：

```text
愿意修改前端 JavaScript
希望彻底清理旧数据链
希望长期稳定维护
```

## 可选择方法二，如果：

```text
必须马上保留旧前端
只做短期过渡
能接受兼容层的维护成本
```

## 不允许的做法

```text
一半前端调用新API，一半调用旧API
一部分账号走新batch，一部分写旧缓存
前端显示新状态，Excel读取旧数据
同时启动旧aggregator和新Worker
```

---

# 最终统一验收命令逻辑

每次验收必须按指定 `batch_id` 执行：

```text
1. GET /api/batches/{batch_id}
2. GET /api/batches/{batch_id}/results.json
3. GET /api/batches/{batch_id}/manifest.json
4. 下载 {batch_id}.xlsx
5. 本地 validator 校验
6. 比较前端展示数据与 results.json
7. 比较 Excel 与 results.json
8. 检查图片实体与 manifest
```

必须满足：

```text
账号数：前端 = Master = JSON = Excel
订单数：前端 = JSON = Excel
状态数：前端 = Master = JSON
截图数：manifest = 实体文件 = Excel媒体
批次号：全链路一致
```

## 最终通过标准

```text
PASS：全部必检项通过
PARTIAL：结果存在但有未完成/未验证项，不得交付
FAIL：至少一项数据或链路不一致
BLOCKED：需要人工处理2FA/Passkey/CAPTCHA或凭证问题
```

AI 完成后只能输出：

```text
选择的方法
修改文件
部署节点
batch_id
机器验收输出
失败项
是否允许下一阶段
```

不能只说：

```text
已经完成
全部打通
100%通过
```
