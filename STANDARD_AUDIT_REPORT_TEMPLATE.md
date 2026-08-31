# 📋 Antigravity 法定全任务验收与审核汇报标准模板 (Standard Audit Reporting Template)

> **适用范围**：所有前台 UI 变更、看板监控、跑号出码、数据报表交付、性能调优、分布式调度与故障修复任务。  
> **执行铁律**：任何汇报必须严格按照以下六大核心模块逐项出具，**严禁省略任何模块，严禁空口宣布完成，必须提供确凿文件落盘、真实现场截屏、哈希对齐与底层 OS/API 证据**。

---

## 1. 📸 现场真实验证截屏与快照凭证 (Visual Evidence)
* **现场物理截屏内嵌展示**：
  `![现场运行/交付真实截屏](file:///本地截图绝对路径)`
* **截屏文件物理绝对路径**：`[文件名](file:///C:/Users/...)`
* **截屏文件 SHA-256**：`...`
* **同时刻后端 API 响应 SHA-256**：`...`
* **DOM 渲染指标 vs 后端 API 原始响应对齐表**：
  | 指标项 | 前端 DOM 显示值 | 后端 API 原始值 | 对齐判定 | 物理含义说明 |
  | :--- | :---: | :---: | :---: | :--- |
  | 目标总数 / 全盘总数 | ... | ... | ✅ 100% 对齐 | ... |
  | 已处理数 / 待测数 | ... | ... | ✅ 100% 对齐 | ... |
  | 成功数 / 正常活跃 | ... | ... | ✅ 100% 对齐 | ... |
  | 失败数 / 密码错误 | ... | ... | ✅ 100% 对齐 | ... |
  | 异常数 / 风控拦截 | ... | ... | ✅ 100% 对齐 | ... |

---

## 2. 🔍 核心问题排查定位与物理闭环整改 (Deep Root Cause & Physical Rectification)
针对用户提出的每一项质疑或系统 Bug，必须逐一拆解：
* **【问题项名称】**：
  * **现场还原与根因定位**：出示确凿代码文件行号、控制台报错或接口报文，彻底查清发生机理，严禁凭空盲猜；
  * **代码级物理整改**：详细列出修改文件绝对路径、修改前代码 vs 修改后代码（Diff 片段）；
  * **多节点一致性与哈希校验**：若涉及多节点/远端部署，必须提供本地与远端文件的 `MD5` / `SHA-256` 字节级比对结果，证明 100% 同步生效；
  * **不良代码彻底清除**：证明已物理删除伪造、占位或死循环代码（如 `grep` 检索结果为 0）。

---

## 3. ⚖️ 业务数据守恒律与底层数据源闭环 (Mathematical Invariants & Data Source Closure)
* **业务状态守恒方程**：
  * 列出严格的数学等式（如：`已处理 (curr) = 成功 (succ) + 失败 (fail)`，`全盘总数 = 待测 + 活跃 + 密错 + 异常`）；
  * 证明 `success_count <= current <= total`，绝不存在超额或逻辑矛盾。
* **批次物理隔离与交集证明**：
  * 必须提供输入批次与全量历史库的交集计算结果，断言交集数严格等于 `0`；
  * 证明全库唯一性（如唯一邮箱数 100%，重复邮箱数为 0）。
* **底层数据源审计原始文件**：
  * 提供落盘的原始审计 JSON 文件路径与 SHA-256，供用户逐条追溯底册。

---

## 4. 🖥️ 系统内核与运行时真核验证 (OS / Kernel / Runtime Verification)
严禁仅依赖前台文字显示，必须直击操作系统底层：
* **进程存活性与父进程状态**：PID、`PPid = 1`（已脱离终端孤儿收养守护，长期稳定常驻）；
* **操作系统内核级线程/任务数**：
  * 读取 `/proc/<PID>/status` 中的 `Threads: XX`；
  * 读取 `/proc/<PID>/task` 目录下的系统 Task 数量；
* **资源消耗与运行指标**：`VmRSS` 内存占用、CPU 占用率、端口监听状态；
* **多节点并发认领证据**：展示各 Worker 线程在各自分区互不重叠认领任务的真实日志流水。

---

## 5. 📂 全量相关文件物理绝对路径清单 (Comprehensive Physical Paths Inventory)
必须使用 Windows 本地绝对路径的可点击超链接格式 `[显示文本](file:///C:/Users/...)`，分门别类完整列出：

### ① 生产核心代码真本 (Production Code)
* `[server.py](file:///C:/Users/...)`：修改与功能说明
* `[templates/index.html](file:///C:/Users/...)`：修改与功能说明
* `[rakuten_deep_profile_extractor.py](file:///C:/Users/...)`：修改与功能说明
* `[export_excel_with_screenshots.py](file:///C:/Users/...)`：修改与功能说明

### ② 真实审计取证文件 (Audit Evidence Files)
* `[AUDIT_BATCH_DATA_SOURCES.json](file:///C:/Users/...)`：批次隔离与交集断言原始凭证
* `[AUDIT_FRONTEND_EVIDENCE.json](file:///C:/Users/...)`：前端渲染、API 响应与 Console/Network 抓包证据
* `[AUDIT_REPORT_YYYYMMDD_HHMM.md](file:///C:/Users/...)`：综合排查对账物理留痕报告
* `[现场真实验证截屏原件.png](file:///C:/Users/...)`：高清晰度现场物理截图

### ③ 全网唯一保留的法定真实交付报表 (Authentic Deliverables)
* `[批次1报表.xlsx](file:///C:/Users/...)`（附文件大小、SHA-256）
* `[批次2报表.xlsx](file:///C:/Users/...)`（附文件大小、SHA-256）

### ④ 对应业务规范与全局规则文件 (Rules & Specifications)
* `[全局规则 GEMINI.md](file:///C:/Users/...)`（附 SHA-256）
* `[工作区规则 AGENTS.md](file:///C:/Users/...)`（附 SHA-256）
* `[业务边界与验收规范.md](file:///C:/Users/...)`（附 SHA-256）

---

## 6. 🔒 安全合规与脱敏确认 (Security Compliance)
* **明文凭据阻断**：全篇报告与会话中 100% 阻断任何 SSH 密码、API Key、明文 Token、银行卡全号；
* **临时执行脚本物理销毁**：`scratch/` 等临时调试脚本已执行物理销毁（`Remove-Item -Force`），无残留风险；
* **网络与存储合规**：所有数据仅在受控内部管道与自建服务器间传输，杜绝第三方外泄。
