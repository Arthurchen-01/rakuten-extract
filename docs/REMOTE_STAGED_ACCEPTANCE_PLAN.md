# 远程分阶段真实验收计划

## 目标

验证真实远程链路：

```text
前端 → Node 4 Master → Worker → 远程 Chromium → 结果/截图 → Excel
```

每个阶段必须通过后才能进入下一阶段。

## 固定业务规则

```text
真实采集只在远程服务器执行
本地只负责控制、下载、验收
每批一个 batch_id
每户最多3笔订单
登录成功后必须继续资料和订单
页面没有数据就留空
页面访问失败必须标记 failed
技术异常不能标记密码错误
```

## 阶段 0：Node 4 Master 单独验证

### 操作

```text
启动唯一 Master
检查端口8998
检查生产域名
检查版本和角色
```

### 必须确认

```text
http://127.0.0.1:8998/health → version=rewrite-v1, role=master
https://lt.samuraiguan.cloud/health → 同版本、同角色
Node 4只有一个Master进程
Master工作目录为rewrite_v1/master
旧Master不再占用8998
```

### 失败处理

任一项失败：停止，不启动 Worker。

## 阶段 1：一个账号、一个 Worker

### 配置

```text
Node 1：1个Worker
并发：1
账号：1户
```

### 流程

```text
前端或控制端创建batch
Node 1 claim
登录
保存登录截图
登录成功后复用Cookie访问资料页
保存资料截图
访问订单页
保存订单列表截图
最多提取3笔订单
上传截图
回报结果
Master写入结果
导出Excel
本地验收
```

### 必须产出

```text
batch.json
results.json
evidence_manifest.json
截图
output.xlsx
audit.json
run.log
```

### 通过标准

```text
账号数=1
结果数=1
batch_id全链路一致
claim/report合法
登录状态有证据
资料状态与页面一致
订单状态与页面一致
订单数<=3
order_count=len(orders)
资料字段正确进入老板Excel
资料没有则留空
失败不是伪造空数据
无占位符
截图哈希正确
Excel可打开
```

## 阶段 2：四台服务器分别单独测试

### 配置

```text
Node 1：1户，1并发
Node 2：1户，1并发
Node 3：1户，1并发
Node 4：只做Master
```

四户必须使用一个新 batch_id，或明确四个独立 batch_id；推荐使用一个批次。

### 必须确认

```text
Node 1有claim/report
Node 2有claim/report
Node 3有claim/report
Node 4记录Master自身状态
每个Worker的worker_id唯一
每个Worker实际加载rewrite-v1
每台Worker都有结果或结构化失败
```

### 通过标准

```text
4个输入账号
4个结果
4个账号不重复、不丢失
同一batch_id
每个节点至少完成1户
结果/截图/Excel一致
技术异常没有变成密码错误
前端显示与Master一致
```

任一节点没有真实 claim/report：阶段失败，不能进入并发测试。

## 阶段 3：四个 Worker 一起运行

### 配置

```text
Node 1：1个Worker，1并发
Node 2：1个Worker，1并发
Node 3：1个Worker，1并发
Node 4：1个Worker或只做Master，必须提前固定
总并发：4
账号：4户
```

推荐 Node 4 继续只做 Master，四个业务账号分给 Node 1~3 时需明确总数；如果要测试四节点业务，则 Node 4 必须明确运行 `worker_id=node-4`，且不能与 Master 统计混淆。

### 必须确认

```text
4个Worker同时在线
4个worker_id唯一
4个账号只能被认领一次
没有重复claim
没有迟到report覆盖
心跳正常
进度持续增长
```

### 通过标准

```text
批次输入数=4
处理数=4
结果数=4
订单总数等于四个结果订单数组之和
每户订单<=3
截图manifest完整
Excel订单和资料逐字段一致
Web下载Excel与同batch_id结果一致
validator=PASS
```

## 阶段 4：扩大前的小批量

只有阶段 3 通过才允许：

```text
10户 → 50户 → 100户
```

每一批独立生成：

```text
batch_id
results.json
manifest
output.xlsx
audit.json
```

## 自动停止条件

任何阶段出现以下情况，立即停止：

```text
前端账号数与Master不一致
Master结果数与输入不一致
JSON与Excel不一致
截图缺失或哈希不一致
同一账号重复claim
错误batch_id回报
技术异常被标为密码错误
任务进度不增长
Web下载文件与本地文件不一致
资料访问失败被写成profile_empty
登录失败被写成0订单
```

## 每阶段必须由机器输出

```json
{
  "phase": 1,
  "batch_id": "...",
  "expected_accounts": 1,
  "actual_results": 1,
  "workers": ["node-1"],
  "orders": 0,
  "screenshots": 0,
  "validator": "PASS",
  "next_phase_allowed": true,
  "failures": []
}
```

没有机器输出，不接受口头“完成”。

## 用户只需要确认

每个阶段只看：

```text
账号数对不对
结果数对不对
资料是否进入Excel
订单是否最多3笔
截图是否存在
验收是否PASS
是否允许下一阶段
```

## 禁止直接执行

在阶段 1~3 未全部通过前，不得执行：

```text
30线程/节点
120总并发
547户
9858户
全量大盘
```
