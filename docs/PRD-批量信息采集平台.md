# PRD · 多服务器批量信息采集与汇总平台

版本 v1.0 · 状态:待评审 · 关联文档:[`多服务器接手.md`](多服务器接手.md)

## 1. 背景与目标

### 1.1 现状问题

三台同质服务器已在运行 AI Agent,但缺少统一入口:任务靠人工分派、执行进度不可见、失败无重试台账、结果需人工誊抄进 Excel。批次一大就出现漏采、重复采、字段错位。

### 1.2 目标

| 编号 | 目标 | 衡量指标 |
| --- | --- | --- |
| G1 | 一个入口提交批量任务并看到实时进度 | 导入到开跑 < 10s;进度延迟 < 3s |
| G2 | 三机自动均衡,无需人工分派 | 三机利用率极差 < 15% |
| G3 | 单机故障不丢任务 | 宕机后在途任务 100% 自动重投 |
| G4 | 结果按 Excel 标准一键导出 | 导出零人工誊抄;字段完整率 ≥ 99% |
| G5 | 每个字段可溯源到截图 | 100% 字段可定位 artifact |

### 1.3 非目标(本期不做)

- 不做多租户与计费;不做目标站点的爬虫对抗;不做移动端;不自建模型。

## 2. 角色与核心用例

| 角色 | 权限 | 核心用例 |
| --- | --- | --- |
| 操作员 Operator | 建批次、导入、启停、导出 | UC1 导入批次并开跑;UC5 导出 Excel |
| 复核员 Reviewer | 处理待复核队列 | UC3 逐条比对截图修正字段 |
| 管理员 Admin | 用户/限流/模板/密钥配置 | UC4 配置 Excel 映射模板 |
| Worker(机器身份) | 仅租约与回写 | UC2 拉取并执行记录 |

**UC1**:操作员上传 CSV/Excel → 系统校验表头与必填列 → 生成 Batch 与 N 条 Record(状态 `pending`)→ 点"开始"入队。
**UC2**:Worker 轮询租约接口取 K 条 → 依次调接口、截屏、落库、抽取 → 回写 `passed` 或 `needs_review`。
**UC3**:复核员打开待复核记录,左侧截图右侧字段表单,修正后置 `reviewed`。
**UC5**:批次达门禁阈值 → 选模板 → 生成 xlsx + 截图包 + QA 报告页。

## 3. 系统架构

```
                     ┌──────────────────────────┐
   Operator ────────▶│  前端管理界面 (React/AntD) │
                     └────────────┬─────────────┘
                                  │ HTTPS + JWT
                     ┌────────────▼─────────────┐
                     │  Control Plane (FastAPI) │
                     │  批次/租约/门禁/导出      │
                     └──┬──────────┬────────────┘
              ┌─────────▼───┐  ┌───▼──────────────┐
              │ PostgreSQL  │  │ Redis (进度 pub/sub) │
              │ 队列+状态+台账│  └──────────────────┘
              └─────────┬───┘
       ┌───────────────┼───────────────┐
  ┌────▼────┐     ┌────▼────┐     ┌────▼────┐
  │ Worker1 │     │ Worker2 │     │ Worker3 │   (同质,拉模式)
  │ Agent+浏览器│  │  同左   │     │  同左   │
  └────┬────┘     └────┬────┘     └────┬────┘
       └───────────────┼───────────────┘
                  ┌────▼─────────┐
                  │ 对象存储 MinIO │ 截图/原始响应
                  └──────────────┘
```

### 3.1 技术选型与理由

| 组件 | 选型 | 理由 |
| --- | --- | --- |
| 队列 | PostgreSQL `SKIP LOCKED` | 已有 DB 即可,事务内出队+改状态天然一致,免运维 MQ;千级批次性能充裕 |
| 进度推送 | Redis Pub/Sub + SSE | 前端进度条免轮询;丢消息不影响正确性(DB 为准) |
| 存储 | MinIO(S3 兼容) | 截图量大,对象存储比 DB BLOB 便宜且可直链预览 |
| 后端 | Python + FastAPI | 与现有 Python 脚本资产同栈,Agent 可直接复用 |
| 前端 | React + Ant Design + TanStack Table | 表格/筛选/虚拟滚动开箱即用 |

**关键设计:拉模式而非推模式。** 调度端不感知机器数量与健康度,Worker 按自身余量拉取,新增/下线机器无需改配置,天然实现 G2/G3。

## 4. 端到端流程与状态机

### 4.1 Record 状态机

```
pending ──lease──▶ leased ──▶ capturing ──▶ extracting ──▶ validating
                     │                                        │
                     │(租约超时)                    ┌──────────┴──────────┐
                     └──────▶ pending          passed              needs_review
                                                  │                     │
   failed_retryable ◀──(可重试错误,退避后)          │                 reviewed
        │                                          └──────┬──────────────┘
        └──▶ pending (attempt<max) / dead_letter (attempt≥max)      │
                                                              aggregated
```

### 4.2 关键规则

1. **幂等键**:`idempotency_key = sha256(batch_id | record_id | collector_version)`。重复投递时若已存在成功 Attempt 则直接返回,不重复请求目标站点。
2. **租约**:默认 `lease_ttl = 5min`,Worker 每 60s 续租;超时未续则记录回 `pending`,`attempt_count` 不增(区分"机器挂了"与"业务失败")。
3. **错误分类**:
   - 可重试:超时、5xx、429、网络抖动、截图渲染失败 → 指数退避 `min(2^n × 30s, 15min)` + 抖动。
   - 永久失败:404 用户不存在、参数非法 → 直接 `dead_letter`,不浪费重试额度。
   - 熔断级:401/403 登录态失效 → **立即暂停整批**并告警,避免整批空跑产出错误页截图。
4. **限流**:全局令牌桶按域名维度,三机共享(Redis 计数器);单域并发上限与 QPS 上限可配置,默认保守值。
5. **采集产物不可变**:Artifact 落库后只增不改;抽取规则升级发布新 `extractor_version`,可对历史批次重放。

## 5. 功能需求 · 前端管理界面

### 5.1 页面清单

| 页面 | 关键元素 | 优先级 |
| --- | --- | --- |
| P1 批次列表 | 批次卡片:进度环、成功/失败/待复核计数、耗时预估、操作(暂停/继续/导出) | P0 |
| P2 新建批次 | 文件上传(CSV/XLSX)、表头映射预览、必填校验报告、限流参数、开跑按钮 | P0 |
| P3 批次详情 | 记录表格(状态/耗时/尝试次数/所属机器筛选)、实时日志流、失败原因聚合 Top N | P0 |
| P4 记录详情 | 左截图预览(多张切页)+ 右结构化字段 + Attempt 时间线 | P0 |
| P5 待复核队列 | 按置信度升序排队、键盘流(Enter 通过 / E 修正)、批量通过 | P1 |
| P6 集群监控 | 三机心跳、在途租约数、CPU/内存、近 1h 吞吐、队列积压 | P1 |
| P7 模板配置 | Excel 列映射(字段↔列名↔顺序↔格式↔空值占位)、模板版本管理 | P0 |
| P8 系统设置 | 用户与角色、目标接口清单与鉴权、密钥轮换、保留期策略 | P1 |

### 5.2 交互要点

- **导入即校验**:上传后先做表头匹配与必填列检查,把"哪一行缺什么"直接列给用户,不允许带缺陷开跑。
- **进度可解释**:进度条旁标注"已完成 320/500 · 3 机在跑 · 预计剩余 12min",预估基于近 50 条移动平均耗时。
- **失败可批量操作**:失败原因聚合后支持"该原因下全部重试",避免逐条点。
- **导出前置门禁**:未达阈值时导出按钮禁用并给出原因与"仍要导出(部分)"逃生入口。
- 无障碍:表格支持键盘导航,状态不只用颜色区分(带图标+文字),对比度 ≥ 4.5:1。

## 6. 质量保障体系(核心章节)

结果质量不靠"跑完再看",靠**四道串行门禁**,每道门都能把问题挡在更便宜的位置。

### 6.1 Gate 1 · 采集层(证据是否可信)

| 检查项 | 判定 | 不通过动作 |
| --- | --- | --- |
| HTTP 状态码 | 必须 2xx | 401/403 熔断整批;5xx/429 退避重试 |
| 响应体长度 | > 阈值(默认 512B) | 重试 |
| 关键 DOM 选择器存在 | 必须命中 | 重试;连续 3 条失败则疑似改版,暂停并告警 |
| 截图非空白 | 像素方差 > 阈值 | 重试 |
| 截图非错误页 | 与已知错误页 pHash 距离 > 阈值 | 判为登录态失效,熔断 |
| 页面加载完成 | 网络空闲 + 关键元素可见 | 延长等待后重截 |

**设计理由**:空白截图和错误页截图是最危险的失败——它们"看起来成功了",会一路流到 Excel。必须在采集层就用像素与 pHash 拦掉。

### 6.2 Gate 2 · 抽取层(字段是否规范)

- 抽取输出必须满足 **JSON Schema**(类型、必填、枚举、长度),不合规直接触发一次带错误信息的重抽。
- 每个字段附 `confidence`(0-1)与 `source`(artifact_id + 定位区域)。
- 必填字段缺失 → `needs_review`,不进入汇总。
- 抽取使用**固定 prompt 版本 + temperature=0**,prompt 变更必须升版本号,保证可复现。

### 6.3 Gate 3 · 规则与选择性复算

- **规则校验**:正则(手机/邮箱/证件号)、枚举白名单、日期区间合理性、跨字段一致性(如 `start_date < end_date`、金额与明细求和相符)。
- **选择性复算(方案 C 的克制用法)**:仅当 ①字段被标记为关键 或 ②`confidence < 0.85` 时,把**已存的同一份 artifact** 交给另一路抽取器(不同模型/不同 prompt)重算。
  - 两路一致 → 置信度提升为 `passed`。
  - 两路不一致 → 进 `needs_review`,界面并列展示两路结果与截图。
- **注意**:复算只重跑抽取,**不重新请求目标站点**,因此没有 3× 限流风险。这是把 C 的准确率红利拿走、把成本与风控代价留下的关键取舍。

### 6.4 Gate 4 · 批次层(能否汇总导出)

批次门禁默认阈值(可配置):

| 指标 | 默认阈值 |
| --- | --- |
| 完成率(passed + reviewed) | ≥ 99% |
| 死信率 | ≤ 1% |
| 必填字段完整率 | 100% |
| 待复核残留 | = 0 |
| 抽样人工核验(每批随机 3% 或至少 10 条) | 准确率 ≥ 98% |

未达阈值时导出按钮禁用,并给出"缺失清单"(哪些 record 卡在哪个状态、原因是什么)。允许操作员二次确认后做**部分导出**,此时 Excel 首页 QA 报告强制标注"非完整批次"。

## 7. Excel 汇总与导出

### 7.1 映射模板(配置驱动,不写死在代码里)

模板是可版本化的配置对象,管理员在 P7 页面维护:

```yaml
template:
  name: 用户信息标准表
  version: 3
  null_placeholder: "-"
  columns:
    - header: 序号          # Excel 列名(用户的标准)
      source: __row_index__
    - header: 用户ID
      source: field.user_id
      width: 18
    - header: 注册时间
      source: field.registered_at
      format: "yyyy-mm-dd hh:mm"
    - header: 账户余额
      source: field.balance
      format: "#,##0.00"
      align: right
    - header: 截图证据
      source: artifact.primary
      render: hyperlink        # 超链接指向截图包内相对路径
    - header: 采集状态
      source: meta.status
```

**设计理由**:Excel 标准是用户的、会变的。做成配置后,换模板不需要改代码、不需要重跑采集,只需重新生成导出物。

### 7.2 导出产物

一次导出生成一个 zip:

| 内容 | 说明 |
| --- | --- |
| `data.xlsx` · Sheet1 数据页 | 按模板列序输出,冻结首行,列宽自适应 |
| `data.xlsx` · Sheet2 QA 报告 | 批次统计、门禁结果、失败原因 Top N、抽检结论、是否完整批次 |
| `data.xlsx` · Sheet3 异常清单 | 死信与待复核记录明细及原因,便于返工 |
| `screenshots/{record_id}/*.png` | 截图,与数据页超链接对应 |
| `manifest.json` | 批次 ID、模板版本、collector/extractor 版本、导出时间、行数校验和 |

### 7.3 溯源要求

数据页每一行可通过 `record_id` 反查到:所用 artifact、采集时间、执行机器、Attempt 次数、抽取器版本、是否经人工修正、修正人与修正前原值。这是出现争议时唯一能自证的东西。

## 8. 数据模型

```sql
-- 批次
CREATE TABLE batches (
  id              BIGSERIAL PRIMARY KEY,
  name            TEXT NOT NULL,
  status          TEXT NOT NULL,      -- draft/running/paused/completed/exported/aborted
  total_records   INT  NOT NULL,
  template_id     BIGINT REFERENCES templates(id),
  collector_ver   TEXT NOT NULL,
  extractor_ver   TEXT NOT NULL,
  gate_config     JSONB NOT NULL,     -- 门禁阈值快照
  created_by      BIGINT NOT NULL,
  created_at      TIMESTAMPTZ DEFAULT now(),
  started_at      TIMESTAMPTZ,
  finished_at     TIMESTAMPTZ
);

-- 记录(同时充当任务队列)
CREATE TABLE records (
  id              BIGSERIAL PRIMARY KEY,
  batch_id        BIGINT NOT NULL REFERENCES batches(id),
  row_index       INT  NOT NULL,
  input_payload   JSONB NOT NULL,     -- 前端导入的原始用户信息
  status          TEXT NOT NULL DEFAULT 'pending',
  attempt_count   INT  NOT NULL DEFAULT 0,
  idempotency_key TEXT NOT NULL UNIQUE,
  lease_owner     TEXT,               -- worker_id
  lease_expires_at TIMESTAMPTZ,
  next_visible_at TIMESTAMPTZ DEFAULT now(),  -- 退避可见时间
  last_error      JSONB,
  UNIQUE (batch_id, row_index)
);
CREATE INDEX idx_records_dispatch
  ON records (status, next_visible_at)
  WHERE status IN ('pending','failed_retryable');

-- 执行尝试台账
CREATE TABLE attempts (
  id            BIGSERIAL PRIMARY KEY,
  record_id     BIGINT NOT NULL REFERENCES records(id),
  worker_id     TEXT NOT NULL,
  seq           INT  NOT NULL,
  started_at    TIMESTAMPTZ NOT NULL,
  finished_at   TIMESTAMPTZ,
  outcome       TEXT,                 -- success/retryable/permanent/circuit_break
  error_class   TEXT,
  duration_ms   INT,
  gate1_result  JSONB
);

-- 留证产物(不可变)
CREATE TABLE artifacts (
  id            BIGSERIAL PRIMARY KEY,
  record_id     BIGINT NOT NULL REFERENCES records(id),
  attempt_id    BIGINT NOT NULL REFERENCES attempts(id),
  kind          TEXT NOT NULL,        -- screenshot/raw_response/dom_snapshot
  object_key    TEXT NOT NULL,        -- MinIO key
  sha256        TEXT NOT NULL,
  source_url    TEXT,
  is_primary    BOOLEAN DEFAULT false,
  captured_at   TIMESTAMPTZ NOT NULL
);

-- 抽取结果(可多版本共存,支持重放)
CREATE TABLE extractions (
  id             BIGSERIAL PRIMARY KEY,
  record_id      BIGINT NOT NULL REFERENCES records(id),
  extractor_ver  TEXT NOT NULL,
  fields         JSONB NOT NULL,      -- {field: {value, confidence, artifact_id}}
  schema_ok      BOOLEAN NOT NULL,
  rule_ok        BOOLEAN NOT NULL,
  min_confidence NUMERIC(4,3),
  is_active      BOOLEAN DEFAULT true,
  created_at     TIMESTAMPTZ DEFAULT now(),
  UNIQUE (record_id, extractor_ver)
);

-- 人工复核
CREATE TABLE reviews (
  id           BIGSERIAL PRIMARY KEY,
  record_id    BIGINT NOT NULL REFERENCES records(id),
  reviewer_id  BIGINT NOT NULL,
  before_value JSONB NOT NULL,
  after_value  JSONB NOT NULL,
  reason       TEXT,
  reviewed_at  TIMESTAMPTZ DEFAULT now()
);

-- Worker 心跳
CREATE TABLE workers (
  id            TEXT PRIMARY KEY,
  host          TEXT NOT NULL,
  capacity      INT  NOT NULL,
  in_flight     INT  NOT NULL DEFAULT 0,
  collector_ver TEXT,
  last_heartbeat TIMESTAMPTZ NOT NULL,
  status        TEXT NOT NULL         -- online/draining/offline
);
```

**索引设计理由**:`idx_records_dispatch` 是部分索引,只覆盖可派发状态,让出队查询在百万行表上仍是索引扫描而非全表。

## 9. 接口规格

### 9.1 管理面(前端调用,JWT + RBAC)

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/batches` | 建批次(multipart 上传 CSV/XLSX),返回解析预览与校验报告 |
| POST | `/api/batches/{id}/start` | 入队开跑 |
| POST | `/api/batches/{id}/pause` · `/resume` · `/abort` | 批次控制 |
| GET | `/api/batches?status=&page=` | 批次列表 |
| GET | `/api/batches/{id}` | 批次详情与统计 |
| GET | `/api/batches/{id}/stream` | SSE 实时进度 |
| GET | `/api/batches/{id}/records?status=&worker=&q=` | 记录列表(分页/筛选) |
| GET | `/api/records/{id}` | 记录详情(字段+artifacts+attempts 时间线) |
| POST | `/api/records/{id}/retry` | 单条重试(重置退避,attempt 计数保留) |
| POST | `/api/batches/{id}/retry-failed?error_class=` | 按错误类别批量重试 |
| POST | `/api/records/{id}/review` | 提交人工修正 |
| POST | `/api/batches/{id}/replay-extraction` | 用新 extractor 版本重放抽取(不重采) |
| GET | `/api/batches/{id}/gate-check` | 返回门禁明细与缺失清单 |
| POST | `/api/batches/{id}/exports` | 触发导出(异步),返回 export_id |
| GET | `/api/exports/{id}` | 导出状态与下载地址(预签名 URL,15min 有效) |
| GET/PUT | `/api/templates/{id}` | Excel 映射模板读写 |
| GET | `/api/workers` | 三机状态与吞吐 |

### 9.2 Worker 面(机器身份鉴权)

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/worker/lease` | 请求租约,body:`{worker_id, capacity_left, collector_ver}`,返回 ≤K 条记录 |
| POST | `/api/worker/lease/{record_id}/renew` | 续租,60s 一次 |
| POST | `/api/worker/records/{id}/artifacts` | 上传 artifact 元数据(文件直传 MinIO 后回调) |
| POST | `/api/worker/records/{id}/complete` | 提交结果:`{outcome, fields, gate1_result, error}` |
| POST | `/api/worker/heartbeat` | 心跳 + 在途数上报 |

**出队 SQL(原子租约)**:

```sql
WITH picked AS (
  SELECT id FROM records
   WHERE status IN ('pending','failed_retryable')
     AND next_visible_at <= now()
     AND batch_id IN (SELECT id FROM batches WHERE status='running')
   ORDER BY batch_id, row_index
   FOR UPDATE SKIP LOCKED
   LIMIT $1
)
UPDATE records r
   SET status='leased', lease_owner=$2,
       lease_expires_at = now() + interval '5 minutes'
  FROM picked WHERE r.id = picked.id
RETURNING r.id, r.input_payload;
```

`SKIP LOCKED` 让三台机并发出队互不阻塞也互不重复,这是整个调度层唯一的关键并发原语。

**租约回收(调度端定时任务,每 30s)**:

```sql
UPDATE records SET status='pending', lease_owner=NULL, lease_expires_at=NULL
 WHERE status='leased' AND lease_expires_at < now();
```

### 9.3 SSE 进度事件

```json
{"event":"progress","batch_id":12,"done":320,"total":500,
 "passed":312,"needs_review":6,"dead":2,
 "workers":[{"id":"w1","in_flight":4},{"id":"w2","in_flight":4},{"id":"w3","in_flight":3}],
 "eta_seconds":720}
```

## 10. 非功能需求

### 10.1 性能与容量

| 指标 | 目标 |
| --- | --- |
| 单条记录 P95 耗时 | ≤ 3min(受目标接口制约) |
| 集群吞吐 | 三机 × 并发 4 = 12 并发,约 240 条/小时(按 3min/条) |
| 1000 条批次端到端 | ≤ 4.5h |
| 队列出队延迟 | P95 ≤ 500ms |
| 前端列表加载(1 万行) | 首屏 ≤ 1.5s(服务端分页 + 虚拟滚动) |
| 进度刷新延迟 | ≤ 3s |

并发度 `capacity` 每机可配,受目标站点限流反压自动调整:收到 429 则该域并发 -1,持续 5min 无 429 则 +1。

### 10.2 可靠性

| 故障 | 表现 | 恢复 |
| --- | --- | --- |
| Worker 进程崩溃 | 在途租约超时 | 30s 内自动重投,`attempt_count` 不增 |
| Worker 整机宕机 | 心跳丢失 → 标 offline | 其余两机自动吃掉队列,无需干预 |
| 控制面重启 | 前端短暂不可用 | DB 为唯一真相源,重启后状态完整 |
| MinIO 不可用 | 采集失败 | 判为可重试;连续失败触发批次暂停告警 |
| 目标站点改版 | Gate1 选择器连续失败 | 3 条即熔断暂停,避免整批产出垃圾数据 |

**明确取舍**:控制面为单实例 + 冷备(DB 独立),不做 HA。批次任务允许分钟级中断恢复,引入 HA 的复杂度收益不成正比。

### 10.3 可观测性

- 结构化日志:每条 `record_id / worker_id / attempt_seq / stage / duration_ms / outcome` 全链路可检索。
- 指标:队列积压、各状态记录数、每机吞吐与错误率、Gate1-4 各自拦截量、LLM token 消耗与费用。
- 告警:队列积压 > 阈值持续 10min、单机错误率 > 20%、熔断触发、死信率 > 1%、批次超时未完成。

## 11. 安全与合规

> **重要提醒**:管理界面与 Worker 接口都是网络暴露端点,必须默认带鉴权。以下为强制项,不是可选项。

| 项 | 要求 |
| --- | --- |
| 前端认证 | JWT(短期 access + refresh),密码 Argon2id 哈希,登录失败限速 |
| 授权 | RBAC 三角色(Operator/Reviewer/Admin),接口级校验,导出与设置仅 Admin/Operator |
| Worker 认证 | 独立机器凭据(mTLS 客户端证书,或长随机 token + IP 白名单),**不复用用户 JWT** |
| 传输 | 全链路 HTTPS/TLS,内网调用亦不裸 HTTP |
| 目标站点凭据 | 存于密钥管理(环境变量/Vault),数据库与日志一律脱敏,支持轮换 |
| 敏感字段 | 证件号/手机号在列表页默认掩码,详情页二次点击展开并记审计 |
| 上传防护 | 只接受 CSV/XLSX,限大小,解析在沙箱内进行,禁用公式求值防 CSV 注入 |
| SQL 注入 | 全部参数化查询,禁止字符串拼接 SQL |
| 导出下载 | 预签名 URL 短期有效,不使用公开可读桶 |
| 审计日志 | 登录、导出、复核修正、模板变更、批次中止全部留痕(操作人+时间+前后值) |
| 数据保留 | 截图默认保留 90 天后归档/清理,可配置;删除需二次确认并记审计 |

## 12. 里程碑

| 阶段 | 范围 | 交付标准 | 预估 |
| --- | --- | --- | --- |
| M1 骨架可跑 | 单机 Worker + 批次导入 + 队列出队 + 截图落库 + 最简列表页 | 100 条批次端到端跑通 | 1.5 周 |
| M2 三机并行 | 租约/续租/超时重投、心跳、限流反压、进度 SSE、批次详情页 | 拔掉一台机不丢任务 | 1.5 周 |
| M3 质量门禁 | Gate1-4、错误分类与退避、待复核队列与复核界面 | 空白截图/错误页 100% 被拦 | 2 周 |
| M4 汇总导出 | 模板配置、xlsx + 截图包 + QA 报告、门禁拦截导出 | 1000 条批次零人工誊抄导出 | 1.5 周 |
| M5 增强 | 选择性复算、抽取重放、集群监控、审计与保留策略 | 关键字段双路一致率 ≥ 99% | 2 周 |

## 13. 风险与应对

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| 目标站点限流/封禁 | 整批停滞 | 全局令牌桶 + 429 自适应降并发 + 单域串行开关;不做整批 3× 冗余请求 |
| 登录态过期 | 大量错误页截图污染结果 | Gate1 用 pHash 识别错误页 → 立即熔断整批并告警,而非继续跑完 |
| 页面改版导致选择器失效 | 字段大面积缺失 | 连续 3 条 Gate1 失败即暂停;选择器配置化,改版只改配置 |
| LLM 抽取漂移 | 字段准确率下降 | 固定 prompt 版本 + temperature=0 + JSON Schema 强约束 + 抽样核验;漂移时用重放修复历史数据 |
| 截图体积膨胀 | 存储成本上升 | WebP 压缩、只截关键区域、保留期策略 |
| Excel 标准变更 | 返工 | 模板配置化 + 版本管理,换模板只重新生成导出物,不重采 |
| 单点控制面 | 分钟级中断 | DB 为真相源 + 冷备快速拉起;Worker 断连自动重试 |

## 14. 验收标准

功能性:

1. 导入 500 条 CSV,表头不匹配时给出逐行缺失报告并阻止开跑。
2. 开跑后三机各自拉到任务,集群监控页在途数非零且三机极差 < 15%。
3. 运行中强杀一台 Worker,60s 内其在途记录被另两机接手,最终完成数 = 500。
4. 注入一个返回 401 的接口,系统在 3 条内熔断整批并告警,不产生错误页截图入库。
5. 注入空白截图,Gate1 拦截并重试,不进入汇总。
6. 待复核队列中修正一个字段,记录详情可见修正前后值与操作人。
7. 门禁未达标时导出按钮禁用并列出缺失清单;二次确认后部分导出,QA 页标注"非完整批次"。
8. 按模板导出的 xlsx 列名/列序/格式与用户标准完全一致,截图超链接可正常打开。
9. 升级 extractor 版本后重放历史批次,不产生任何对目标站点的新请求(通过网络日志验证)。

非功能性:

10. 1000 条批次端到端 ≤ 4.5h;记录列表 1 万行首屏 ≤ 1.5s。
11. 未携带凭据访问任意管理接口与 Worker 接口均返回 401。
12. 在数据库与日志中检索目标站点密钥,无明文命中。
13. 抽样 3% 人工核验准确率 ≥ 98%。

---

## 附:待用户确认清单

| # | 待确认 | 影响 |
| --- | --- | --- |
| 1 | Excel 模板的完整列定义、顺序、格式、空值占位 | 决定 P7 模板初始配置 |
| 2 | 目标接口清单、鉴权方式、单接口 QPS/并发上限 | 决定限流参数与熔断阈值 |
| 3 | 典型批次规模与期望完成时限 | 决定每机并发度 |
| 4 | 需要采集并截屏的具体信息项(哪些页面、哪些字段) | 决定 Collector 与 JSON Schema |
| 5 | 是否需要独立复核员角色 | 决定 M3 是否含复核界面 |
| 6 | 截图保留期与合规要求 | 决定存储容量与清理策略 |
| 7 | 三台机器的 OS/配置/网络位置(是否同机房) | 决定部署方式与 DB/MinIO 放置 |
