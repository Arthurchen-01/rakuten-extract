# 远程新系统实施与验收手册

版本：Remote Rewrite v1.0
状态：执行手册，不代表当前生产已经通过

## 0. 核心规则

```text
本地电脑：只控制、部署、下载、验收
Node 4：唯一 Master
Node 1~4：Worker，只执行真实浏览器任务
前端：https://lt.samuraiguan.cloud/
每次任务：一个 batch_id
最终 Excel：只来自该 batch_id
```

禁止：

- 本地模拟真实登录；
- 混用旧批次、旧缓存、旧 Excel；
- Worker 自己生成最终 Excel；
- 任务未完成就导出；
- 技术异常改成密码错误；
- 下载失败时复制本地文件冒充 Web 文件；
- 把 2FA、Passkey、CAPTCHA 当作账号失效；
- 在源码、日志和报告写入明文密码。

用户业务规则：每个账号最多导出 3 笔订单。必须记录 `total_history_order_count` 和 `scraped_order_count`，但最多只落盘 3 笔详情。

---

## 1. 固定目录与模块

远程 Master：

```text
/opt/rakuten-hub/rewrite_v1/master/
  server.py
  db.py
  models.py
  exporter.py
  validator.py
```

远程 Worker：

```text
/opt/rakuten-hub/rewrite_v1/worker/
  worker.py
  extractor.py
  models.py
```

远程批次：

```text
/opt/rakuten-hub/rewrite_v1/runs/<batch_id>/
  batch.json
  input.secure
  results.json
  evidence_manifest.json
  screenshots/<account_id>/
  output.xlsx
  audit.json
  run.log
```

本地控制与验收：

```text
letian/rewrite_control/
  controller.py
  download_run.py
  validator.py
```

旧程序先移动到只读隔离区，不直接删除：

```text
/opt/rakuten-hub/quarantine/<timestamp>/
```

前端暂不删除；前端保留，但只能改为调用新 batch API。

---

## 2. 第一步：冻结旧系统

执行人：运维脚本，不手工杀进程。

先记录：

```text
ps -ef
systemctl list-units --type=service
supervisorctl status
crontab -l
ss -lntp
```

保存为：

```text
pre_cutover_runtime_<timestamp>.json
```

必须确认每台机器：

```text
旧 server.py 的 PID
旧 cloud_worker.py 的 PID
旧 cluster_aggregator_daemon.py 的 PID
旧启动入口
监听端口
```

在没有保存这份清单前，不得删除或停止旧程序。

---

## 3. 第二步：部署新代码

本地只上传完整新版本，不再只上传 3 个零散文件。

必须上传：

```text
Master：server.py、db.py、models.py、exporter.py、validator.py
Worker：worker.py、extractor.py、models.py
```

每个文件部署后记录：

```text
本地 SHA-256
远端 SHA-256
远端文件大小
远端修改时间
```

必须额外记录运行版本：

```text
rewrite_version = rewrite-v1
code_manifest_sha256 = ...
```

禁止把密码作为命令行参数或写进脚本。凭证只通过远程受保护运行时注入。

---

## 4. 第三步：启动唯一 Master

Node 4 只允许一个 Master：

```text
systemd service：rakuten-rewrite-master.service
工作目录：/opt/rakuten-hub/rewrite_v1/master
启动模块：server:app
端口：8998
```

启动后必须检查：

```text
systemctl status rakuten-rewrite-master
curl http://127.0.0.1:8998/health
```

健康响应必须包含：

```json
{
  "status": "ok",
  "version": "rewrite-v1",
  "role": "master",
  "db_path": "..."
}
```

若返回旧版字段、404、端口被旧程序占用，立即停止，不启动 Worker。

生产域名必须单独检查：

```text
https://lt.samuraiguan.cloud/health
```

生产域名响应中的版本必须与 Node 4 本机响应一致。只要不一致，就说明反向代理没有切到新 Master。

---

## 5. 第四步：启动一个 Worker

先只部署 Node 1：

```text
worker_id：node-1
master_url：http://<Node4>:8998
concurrency：1
```

Worker 启动后必须每隔固定时间发送：

```text
heartbeat(batch_id, worker_id)
```

Worker 只处理：

```text
claim
extract
upload evidence
report
```

Worker 不生成 Excel。

必须检查 Worker 健康信息：

```text
worker_id
batch_id
loaded_code_version
loaded_module_path
PID
last_heartbeat
```

---

## 6. 第五步：真实单账号 Smoke Test

只使用一个已授权测试账号，由远程 Node 1 执行。

流程：

```text
本地创建 batch_id
→ 上传受保护账号输入到 Node 4
→ Node 1 claim
→ 远程 Chromium 打开楽天登录页
→ 输入账号
→ 保存登录阶段截图
→ 登录成功后保留 Cookie
→ 访问个人资料页并截图
→ 访问订单列表并截图
→ 最多进入 3 笔订单详情
→ 上传截图到同一 batch_id
→ 回报结构化结果
→ Node 4 写 results.json 和 manifest
→ Node 4 生成 output.xlsx
→ 本地下载完整批次目录
→ 本地 validator 验收
```

成功登录后的强制规则：

```text
必须继续访问资料页
必须继续访问订单页
资料存在就填写
资料不存在就留空
订单存在就最多填写3笔
没有订单就留空并写 orders_status=no_orders
页面访问失败就写 profile_status/orders_status=failed
不能把失败写成“没有数据”
```

单户必须产出：

```text
results.json
manifest.json
登录截图
资料截图
订单列表截图
订单详情截图（如果存在订单）
output.xlsx
audit.json
```

单户通过条件：

```text
batch_id 全部一致
login_status 正确
profile_status 与页面证据一致
orders_status 与页面证据一致
order_count == scraped_order_count == len(orders)
最多3笔订单
没有占位符
截图文件存在且哈希一致
Excel 16列结构正确
Excel 字段与 JSON 一致
```

单户失败时只修一个模块，禁止直接扩大到 3 户。

---

## 7. 状态判定规则

### 账号明确状态

只有页面出现官方证据时使用：

```text
wrong_password
account_locked
 two_factor
passkey
captcha
```

### 技术状态

以下全部属于技术异常：

```text
输入框未出现
密码框未出现
页面导航超时
代理失败
浏览器崩溃
DOM 解析失败
截图保存失败
截图上传失败
Master 回报失败
```

分类为：

```text
technical_retryable
technical_final
```

不能改成 `wrong_password`。

### 完整状态

```text
login_status
profile_status
orders_status
technical_status
overall_status
```

例如：

```json
{
  "login_status": "verified",
  "profile_status": "empty",
  "orders_status": "no_orders",
  "technical_status": "ok",
  "overall_status": "active"
}
```

如果资料页访问失败：

```json
{
  "login_status": "verified",
  "profile_status": "failed",
  "orders_status": "unknown",
  "overall_status": "partial"
}
```

不能把第二种写成 `active`。

---

## 8. 第六步：3 户测试

前提：单户通过。

配置：

```text
Node 1：1户
Node 2：1户
Node 3：1户
Node 4：不承载业务 Worker，保持 Master
```

每台 Worker 并发必须为 1。

验收：

```text
3 个 batch claim
3 个 Worker ID
3 份账号结果
截图均归属正确账号
没有重复 claim
没有跨批次回报
Web/Node4 显示同一 batch_id
Web 下载 Excel 与本地下载 Excel一致
```

任何一个节点没有真实回报，就不能进入 8 户测试。

---

## 9. 第七步：8 户四节点测试

前提：单户和 3 户通过。

配置：

```text
Node 1：2户，concurrency=1
Node 2：2户，concurrency=1
Node 3：2户，concurrency=1
Node 4：2户或只做Master，必须预先固定规则
```

不使用高并发压测。

必须验证：

```text
8 个 account_id 不重复
8 个结果全部属于同一 batch_id
每个节点都有 claim 和 report
结果总数等于8
订单最多每户3笔
技术异常不变成密码错误
前端状态与 Master 状态一致
Web 下载的 Excel 与 batch results 一致
```

通过后才允许把每节点并发提高到 2，再重复验收。

---

## 10. Excel 模板规则

老板模板固定保留 16 列：

```text
账号
密码
姓
名
姓假名
名假名
其他信息/卡号
生日
性别
地址
店铺1
订单1
店铺2
订单2
店铺3
订单3
```

规则：

```text
资料没有 → 空白
没有订单 → 对应订单槽位空白
最多订单3笔
订单文本不得生成默认姓名、默认商品、默认支付方式
```

另外生成结构化审计表：

```text
account_id
order_number
order_date
shop_name
item_name
quantity
price_yen
payment_method
source_screenshot
```

老板 16 列是导入/交付视图，结构化表是审计视图，两者数据必须来自同一个 JSON。

---

## 11. 每次验收必须执行的机器检查

```text
输入账号数量
结果账号数量
唯一 account_id
batch_id 一致
状态字段合法
资料状态与资料字段一致
订单状态与订单数组一致
order_count == scraped_order_count == len(orders)
每户最多3笔订单
禁止占位符为0
截图文件存在
截图大小一致
截图 SHA-256 一致
Excel 可读取
Excel 16列正确
Excel 订单字段逐单一致
Web 下载文件存在
Web 下载文件与本地结果一致
```

最终输出只允许：

```text
PASS
PARTIAL
FAIL
BLOCKED
```

AI 的长篇解释不是证据。

---

## 12. 旧程序隔离

在新系统通过 8 户测试前：

```text
旧程序：保留但停止被生产入口调用
前端：保留
旧 server：停止
旧 cloud_worker：停止
旧 aggregator：停止
旧 daemon：停止
```

旧文件移动到：

```text
/opt/rakuten-hub/quarantine/<timestamp>/
```

保留前端文件，但修改前端 API 地址为：

```text
/api/batches/{batch_id}
/api/batches/{batch_id}/status
/api/batches/{batch_id}/export.xlsx
```

不再使用：

```text
/api/accounts
/api/orders
/api/task-status
/api/export/excel?scope=last_batch
```

这些旧接口可以暂时保留兼容，但生产前端不得调用。

---

## 13. 批量运行门槛

只有满足全部条件才允许批量：

```text
Node 4 新 Master 健康
Node 1~4 新 Worker 版本一致
单户通过
3户跨节点通过
8户四节点通过
Web页面与Master同一batch_id
Web下载Excel通过
本地下载Excel通过
JSON/Excel/截图manifest一致
没有技术异常被归入密码错误
旧调度器未被调用
```

批量递进：

```text
10户
50户
100户
500户
全量
```

每一档都必须生成独立 batch_id 和 audit.json。

任何一档出现：

```text
前端与后端数量不一致
Excel与JSON不一致
截图缺失
技术异常激增
密码错误比例异常
```

立即停止，不得扩大规模。

---

## 14. 当前明确结论

当前可以做：

```text
远程单户真实 Smoke Test
```

当前不可以做：

```text
四节点大盘
高并发
全量任务
旧系统和新系统同时抢任务
```

当前新系统是否正式可批量，必须由以下顺序决定：

```text
远程单户 PASS
→ 3户跨节点 PASS
→ 8户四节点 PASS
→ 10户 PASS
→ 50户 PASS
→ 100户 PASS
→ 500户 PASS
→ 全量
```

任何报告没有对应批次目录、结果文件、manifest、Excel 和机器验收输出，都只能视为过程消息，不能视为通过证明。
