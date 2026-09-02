# 乐天系统唯一业务逻辑总文件

版本：MASTER LOGIC v1.0
用途：从零重造系统时的唯一业务、采集、存储、调度、导出和验收依据
状态：逻辑基线，不代表所有模块已经实现

> 重要：本文件只记录业务逻辑、已知页面经验、数据契约和验收规则，不保存账号密码、Cookie、Token、SSH 凭证或真实个人敏感数据。

---

# 1. 系统最终目标

用户通过生产前端完成：

```text
上传账号和代理
→ 选择线程
→ 启动任务
→ 查看四节点进度
→ 查看账号状态和截图
→ 等待任务完成
→ 导出老板规定的 Excel
```

真实工作必须发生在远程服务器：

```text
生产前端
→ Node 4 Master
→ Node 1~3 Worker
→ 远程 Chromium/Playwright
→ 楽天官方页面
→ 远程结果和截图
→ Node 4 统一保存
→ 前端查看/下载
→ 本地独立验收
```

本地电脑只负责：

```text
代码编辑
远程部署
发起任务
查看状态
下载批次结果
运行验收
```

本地不模拟真实登录，不模拟远程 Worker，不把本地假数据当作远程结果。

---

# 2. 系统角色和部署关系

## 2.1 前端

生产地址：

```text
https://lt.samuraiguan.cloud/
```

前端只负责界面和操作，不直接登录楽天，不直接写结果。

前端必须围绕一个明确的：

```text
batch_id
```

所有账号、订单、状态、截图和 Excel 都必须属于同一个 `batch_id`。

## 2.2 Node 4 Master

职责：

```text
提供前端 API
创建批次
保存输入账号
管理任务状态
原子分配账号
接收 Worker 心跳
接收 Worker 结果
接收截图
保存 SQLite/批次目录
生成唯一 Excel
提供批次下载
```

Node 4 默认只做 Master，不同时做业务 Worker，除非明确配置并单独统计。

## 2.3 Node 1~3 Worker

职责：

```text
连接 Node 4
领取一个 batch_id 下的账号任务
建立独立浏览器上下文
调用 extractor
保存阶段截图
上传截图
回报结构化结果
心跳续租
```

Worker 不生成另一份最终 Excel，不直接改其他批次，不写全局订单缓存。

## 2.4 本地验收端

本地只读取从远程下载的：

```text
results.json
evidence_manifest.json
screenshots/
output.xlsx
audit.json
```

本地验收不得读取历史缓存来补字段。

---

# 3. 一次任务的完整生命周期

```text
1. 前端上传账号/密码/代理
2. Master 创建唯一 batch_id
3. Master 保存输入哈希和批次配置
4. 前端选择 Worker 数和并发数
5. 前端启动该 batch_id
6. Worker 向 Master claim 账号
7. Master 发放 claim_id 和租约
8. Worker 在远程执行浏览器采集
9. Worker 上传阶段截图和 manifest
10. Worker 回报账号结果
11. Master 校验 batch_id/account_id/claim_id/worker_id
12. Master 事务写入结果
13. Master 更新批次计数
14. 所有账号终态后，批次变 COMPLETED 或 PARTIAL
15. 前端读取同一 batch_id
16. 完成后生成并下载同一 batch_id 的 Excel
17. 本地 validator 独立验收
```

任何一步失败必须留下结构化错误，不能静默继续为成功。

---

# 4. 批次和数据目录

每次任务独立保存：

```text
data/runs/<batch_id>/
├─ input.secure
├─ input.sha256
├─ batch.json
├─ results.json
├─ evidence_manifest.json
├─ screenshots/<account_id>/
├─ output.xlsx
├─ output.sha256
├─ audit.json
└─ run.log
```

禁止：

```text
使用最近一次批次
跨批次混合账号、订单、截图
读取全局 manager.accounts 作为当前结果
读取全局 orders_cache 补当前订单
覆盖旧批次 results.json
下载失败时复制其他 Excel 冒充下载结果
```

批次状态：

```text
CREATED
QUEUED
RUNNING
COMPLETED
PARTIAL
FAILED
CANCELLED
```

`COMPLETED` 必须满足：

```text
已处理账号数 == 输入账号数
没有待处理账号
每个账号都有终态
results.json 可读
manifest 可读
必需截图哈希可验证
```

---

# 5. 输入文件和老板 Excel 模板

老板模板为 16 列：

```text
A 账号
B 密码
C 姓
D 名
E 姓（假名）
F 名（假名）
G 其他信息/卡号
H 生日
I 性别
J 地址
K 店铺名称1
L 订单1
M 店铺名称2
N 订单2
O 店铺名称3
P 订单3
```

业务规则：

```text
每个账号最多导出3笔订单
没有资料：对应字段留空
没有订单：订单槽位留空
页面访问失败：字段留空，但状态标失败
绝不生成默认姓名、商品、金额、数量或支付方式
```

密码列是否出现在交付 Excel，必须由用户选择：

```text
内部运行输入：可包含密码，必须受保护
对外交付：默认脱敏或留空
```

---

# 6. 真实浏览器采集流程

## 6.1 登录入口

历史使用过的入口：

```text
https://grp02.id.rakuten.co.jp/rms/nid/loginfwd
https://member.id.rakuten.co.jp/rms/nid/menufwd
https://order.my.rakuten.co.jp/
https://order.my.rakuten.co.jp/?page=myorder
https://order.my.rakuten.co.jp/?scid=myr_popular_purchasehist
https://order.my.rakuten.co.jp/purchase-history/order-list
https://my.rakuten.co.jp/
https://member.id.rakuten.co.jp/r/info.html
```

入口可变时，以实际最终 URL 和页面标识为准，不能只看 URL。

## 6.2 登录步骤

```text
打开登录入口
→ 等待登录表单
→ 输入账号
→ 提交/Enter
→ 判断密码页、Passkey、2FA、错误页
→ 如页面真实存在「パスワードを使用する」，点击它
→ 等待密码框
→ 输入密码
→ 提交/Enter
→ 等待最终页面
→ 保存登录结果截图
```

登录成功必须同时满足：

```text
不在登录网关
页面 URL 属于预期业务页
页面存在可靠登录后标识
Cookie/Session 已建立
没有密码错误/2FA/Passkey/CAPTCHA文案
```

不能仅凭：

```text
没有抛异常
URL含rakuten.co.jp
页面加载完成
```

判定成功。

## 6.3 SSO/Passkey/2FA

历史遇到过：

```text
login.account.rakuten.com
#/sign_in/webauthn
パスキーを確認できませんでした
パスワードを使用する
スキップしてログイン
本人連絡先の選択
```

已观察到的认证文案：

```text
メールアドレスをご確認ください
ユーザIDまたはパスワードが正しくありません
ユーザID・パスワードが一致しません
パスワードが違います
ワンタイムパスワード
認証コード
2段階認証
確認コード
```

规则：

```text
可以处理页面真实提供的正常密码切换
不能绕过2FA、CAPTCHA、Passkey安全挑战
不能调用JS伪造页面没有的按钮
不能把挑战当密码错误
```

## 6.4 Cookie/Context

登录成功后必须保持同一 BrowserContext：

```text
同一 context 登录
→ 访问资料页
→ 访问地址/卡片页
→ 访问订单页
→ 保存所有截图
→ 最后关闭 context
```

不能登录后新建无 Cookie 的 context，不能跨账号复用 context。

---

# 7. 登录后强制业务流程

这是最重要的业务规则：

```text
只要登录成功并获得有效 Cookie
→ 必须继续访问会员资料
→ 必须继续访问购买履历
→ 必须保存资料截图和订单截图
```

## 7.1 会员资料

必须尝试读取：

```text
姓
名
姓假名
名假名
生日
性别
地址
电话
卡片品牌和后四位
```

来源只能是：

```text
会员资料页 DOM
地址簿 DOM
会员卡片页 DOM
```

订单收件人不是会员资料来源。

## 7.2 购买履历

必须尝试读取：

```text
历史订单数（如果页面显示）
订单号
订单日期
店铺
商品
数量
金额
支付方式
收件人/地址
订购人信息
```

最多进入 3 个订单详情：

```text
order_limit = 3
```

必须记录：

```text
total_history_order_count
scraped_order_count
order_count
```

并满足：

```text
order_count == scraped_order_count == len(orders)
order_count <= 3
```

---

# 8. 资料状态和订单状态

不能只使用一个笼统 `active`。

必须分别记录：

```text
login_status
profile_status
orders_status
technical_status
overall_status
```

## 8.1 资料状态

```text
pending
complete
empty
failed
unknown
skipped
```

含义：

```text
complete：资料页正常打开并完成字段解析
empty：页面明确显示该字段未设置/未填写
failed：页面打不开、SSO失败、DOM解析失败、超时
unknown：证据不足，不能判断
skipped：登录未成功，按流程不能访问
```

## 8.2 订单状态

```text
pending
complete
no_orders
failed
partial
unknown
skipped
```

含义：

```text
complete：订单页正常，已按最多3单规则完成抓取
no_orders：订单页明确显示没有订单
failed：订单页访问/解析失败
partial：知道有订单但详情不完整
skipped：登录未成功
```

## 8.3 整体状态

```text
active
active_profile_empty
profile_failed
orders_failed
incomplete
wrong_password
two_factor
passkey
captcha
account_locked
technical_retryable
technical_final
cancelled
```

推荐判定：

```text
登录失败 → 对应认证/技术状态
登录成功 + 资料complete + 订单complete/no_orders → active
登录成功 + 资料empty + 订单complete/no_orders → active_profile_empty
登录成功 + 资料failed → profile_failed
登录成功 + 订单failed → orders_failed
网络/代理/浏览器/DOM错误 → technical_retryable 或 technical_final
```

不能因为订单成功就无条件写 `active`。

---

# 9. 错误分类和不误杀规则

## 9.1 账号层错误

只有官方页面出现明确证据时使用：

```text
wrong_password
account_locked
```

必须保存：

```text
页面文案
最终URL
登录错误截图
```

## 9.2 挑战状态

```text
two_factor
passkey
captcha
```

这些不是账号失效，只表示需要额外人工/设备验证。

## 9.3 技术错误

以下全部不得改成密码错误：

```text
输入框未出现
密码框未出现
SSO跳转超时
页面加载超时
代理失败
DNS/TCP失败
HTTP 502/504
浏览器崩溃
Target closed
DOM结构变化
解析失败
截图失败
截图上传失败
Master回报失败
```

分类为：

```text
technical_retryable
technical_final
```

即使重试耗尽，也不能改写成 `wrong_password`。

---

# 10. 页面和 DOM 抓取规则

## 10.1 资料

优先：

```text
专用label/value DOM
字段专用id/class
表单value
明确可见字段
```

不优先使用整页正则。

历史问题：

```text
整页正文误抓
资料页跨域SSO未处理
字段名不一致：birth_date/birthday
嵌套profile_data与顶层字段不一致
姓名按前两个字符切分
```

姓名必须从页面明确的姓/名节点读取，不能使用：

```python
full_name[:2]
full_name[2:]
```

## 10.2 店铺

优先检查订单容器内：

```text
.shopName
.shop_name
.shop-name
.shop_header
.shop_info a
[class*="shopName"]
[class*="shop-name"]
```

再检查订单容器内专属店铺链接：

```text
a[href*="rakuten.co.jp/"]
```

过滤：

```text
買い物かご
購入履歴
ショップからのメール
お知らせ
閲覧履歴
お気に入り
ヘルプ
利用規約
個人情報
注文詳細
問い合わせ
39ショップ
ポイント
```

禁止从全页首个包含以下字样的文本猜店铺：

```text
店
ショップ
ストア
```

Shop ID 映射如有需要，只能写：

```text
shop_name_inferred
inference_source
```

不能覆盖页面真实 `shop_name`。

## 10.3 商品、数量、金额

必须从订单卡片/详情容器的专用 DOM 读取。

禁止默认值：

```text
楽天市場店舗
購入商品
0円
1
```

页面没有值时：

```text
""
```

商品标题里的这些词可能是官方商品标题的一部分，不能全局删除：

```text
送料無料
楽天1位
期間限定
ポイント10倍
```

---

# 11. 订单原文和结构化数据

每笔订单保留结构化对象：

```json
{
  "batch_id": "...",
  "account_id": "...",
  "order_number": "",
  "order_date": "",
  "shop_name": "",
  "item_name": "",
  "quantity": "",
  "price_yen": "",
  "payment_method": "",
  "delivery_recipient": "",
  "delivery_address": "",
  "buyer_info": "",
  "detail_url": "",
  "detail_screenshot": "",
  "raw_dom_text": ""
}
```

规则：

```text
页面没有字段 → 空字符串
页面访问失败 → 空字符串 + failed状态 + errors
禁止生成默认姓名、商品、金额、数量、支付方式
```

`order_raw_bana` 或订单文本块如果需要生成，只能标记为：

```text
基于官方字段重新格式化的导出文本
```

不能称为未经修改的官方原文，除非原始 DOM 文本另行保存。

---

# 12. 截图和证据

## 12.1 必须截图

登录成功账号：

```text
登录结果
会员资料页
订单列表页
最多3笔订单详情页
```

登录失败/挑战账号：

```text
官方错误或挑战页面
```

明确无订单账号：

```text
订单列表页，证明页面显示无订单
```

## 12.2 文件路径

```text
screenshots/<batch_id>/<account_id>/
  01_login_result.png
  02_profile.png
  03_order_list.png
  04_order_001_detail.png
  05_order_002_detail.png
  06_order_003_detail.png
```

不能使用跨账号共享的固定文件名。

## 12.3 manifest

每张截图记录：

```json
{
  "batch_id": "...",
  "account_id": "...",
  "stage": "profile",
  "relative_path": "screenshots/001/02_profile.png",
  "sha256": "...",
  "size_bytes": 123,
  "captured_at": "...",
  "source_url": "..."
}
```

本地导出前必须验证：

```text
文件存在
文件非空
字节数一致
SHA-256一致
属于当前batch_id/account_id
```

缺图不能复制另一张图顶替。

---

# 13. Master/Worker 协议

## 13.1 Claim

```json
{
  "batch_id": "...",
  "account_id": "...",
  "claim_id": "...",
  "worker_id": "...",
  "lease_seconds": 180,
  "account_data": "运行时受保护数据"
}
```

Worker 必须从明确的 `account_data` 读取运行数据，不能一会儿读顶层、一会儿读嵌套字段。

## 13.2 Heartbeat

长任务必须发送：

```text
batch_id
account_id
claim_id
worker_id
进度
时间
```

租约未过期且心跳正常时，不能让其他 Worker 重复领取。

## 13.3 Report

回报必须包含：

```text
batch_id
account_id
claim_id
worker_id
attempt_id
login_status
profile_status
orders_status
technical_status
overall_status
profile_data
orders
screenshots
errors
```

Master 必须拒绝：

```text
错误batch_id
错误account_id
错误claim_id
错误worker_id
过期claim
重复回报
```

结果只能由 Master 单点写入数据库和结果文件。

---

# 14. Excel 导出

唯一导出入口：

```text
exporter(results.json, evidence_manifest.json, screenshots, batch_id)
```

老板 16 列映射：

```text
profile.last_name → C
profile.first_name → D
profile.last_name_kana → E
profile.first_name_kana → F
profile.card_masked → G
profile.birthday → H
profile.gender → I
profile.address + phone → J
orders[0:3].shop_name → K/M/O
orders[0:3].formatted_block → L/N/P
```

导出器禁止：

```text
读取旧orders_cache
读取其他批次
用订单收件人覆盖profile
生成默认字段
用不存在的截图路径显示已捕获
```

输出至少包含：

```text
乐天导出导入
口径说明
账号检测与现场快照总览
订单明细总览
```

导出后验证：

```text
Excel账号数 == results账号数
Excel订单数 == results订单数
Excel C~J == profile字段
Excel订单字段 == orders字段
图片对象数量 == manifest要求
xl/media数量 == 实际嵌图数量
```

---

# 15. 前端操作和显示

## 15.1 用户操作

```text
上传账号/代理
→ 预览数量
→ 选择Worker数量/线程
→ 创建batch
→ 点击启动
→ 查看进度
→ 查看账号状态
→ 查看截图
→ 完成后导出
```

## 15.2 前端必须显示

```text
batch_id
总账号数
已完成数
待处理数
运行中数
active数
active_profile_empty数
profile_failed数
orders_failed数
wrong_password数
2FA数
Passkey数
CAPTCHA数
technical_retryable数
technical_final数
订单数
截图数
```

不使用只有三类的：

```text
活跃
失败
异常
```

## 15.3 导出按钮

```text
CREATED/QUEUED/RUNNING/PARTIAL → 禁止最终导出
COMPLETED → 允许导出
```

前端显示的数字必须来自同一 `batch_id`，不能分别调用：

```text
一个全局任务接口
一个旧账号列表接口
一个旧订单缓存接口
一个最近批次导出接口
```

---

# 16. 广告和第三方请求

历史曾拦截过：

```text
google-analytics.com
googletagmanager.com
doubleclick.net
criteo.net
criteo.com
yjtag.jp
ad-delivery.net
facebook.net
clarity.ms
datadoghq
sentry.io
```

这只是网络请求拦截，不代表页面广告 DOM 已被删除。

新系统规则：

```text
只拦截明确第三方统计/广告请求
不拦截楽天业务域名
记录被拦截URL和原因
拦截后检查关键业务DOM
页面字段缺失时做关闭拦截的A/B对比
```

不能因为商品标题包含：

```text
送料無料
楽天1位
期間限定
ポイント
```

就删除商品标题。

---

# 17. 历史问题总表

| 历史问题 | 根因 | 重造时必须避免 |
|---|---|---|
| Excel有订单但无姓名 | JSON嵌套 `profile_data`，导出器读顶层字段 | 统一 `profile` 模型，逐字段验收 |
| 306活跃但资料为空 | 订单成功就无条件 active | login/profile/orders 分离 |
| 技术异常被判密码错 | 错误文本二次模糊分类 | 结构化错误码 |
| 订单店铺为空/脏 | 全页正则抓横幅和导航 | 订单容器 DOM 优先 |
| 商品被广告词污染 | 全页 body 文本解析 | 商品专用 DOM |
| 订单数量不一致 | 历史总数和实际抓取数混用 | 三个计数字段分开 |
| Web与本地Excel不同 | Web读全局缓存，本地读独立JSON | 同一 batch_id/results |
| Web导出0订单 | 任务未完成就导出 | 完成门禁409 |
| Excel无图片 | 远程路径未下载/manifest不一致 | 下载后逐图验哈希 |
| 图片重复绑定 | 缺图时复用另一列 | 缺失就留空 |
| 多节点重复处理 | claim/租约不共享或迟到覆盖 | Master事务+claim_id |
| 旧新程序混跑 | 只覆盖磁盘不重启/多启动入口 | 单一systemd和运行时版本报告 |
| 前端统计不一致 | 多个接口读不同数据集合 | 所有接口绑定batch_id |
| 报告哈希对不上 | 文件覆盖、多版本混放 | 每批独立目录和manifest |
| 资料空和资料失败混淆 | 异常被吞或无页面证据 | empty/failed/unknown 分离 |
| 479MB Excel过大 | 高清截图全部嵌入 | Excel缩略图，高清图作为附件 |

---

# 18. 远程重造和验收顺序

```text
阶段0：停止旧任务，记录远程进程和服务
阶段1：部署唯一Master到Node4
阶段2：部署Worker到Node1
阶段3：1户真实远程测试
阶段4：本地下载并验收
阶段5：Node2单户
阶段6：Node3单户
阶段7：3户跨节点
阶段8：8户四节点
阶段9：10户
阶段10：50户
阶段11：100户
阶段12：500户
阶段13：全量
```

每个阶段都必须产生：

```text
batch_id
远程run.log
results.json
evidence_manifest.json
截图
output.xlsx
audit.json
```

任意阶段出现以下情况，停止扩大：

```text
前端与Master数量不同
JSON与Excel字段不同
技术异常被判密码错误
截图缺失或哈希不一致
任务状态不增长
Web Excel与本地Excel不同
```

---

# 19. AI 重造规则

每次 AI 只能实现一个模块，并先输出：

```text
本次模块
允许修改文件
禁止修改文件
输入数据
预期结果
机器验收命令
停止条件
```

AI 不得：

```text
同时修改登录、订单、前端、导出、部署
自己生成数据再自己宣称真实
自己生成报告再自己裁判
把计划写成完成
用固定数字填充统计
下载失败时复制其他文件
```

每次完成必须报告：

```text
修改了什么
实际运行了什么
生成了哪些文件
机器验收输出
失败项
是否允许下一模块
```

---

# 20. 最终完成定义

只有同时满足以下条件，系统才算完成：

```text
远程真实浏览器执行
登录成功后继续资料和订单
最多3笔订单
没有数据真实留空
失败和空值分开
所有截图有manifest和哈希
一个batch_id贯穿全链路
四节点结果不重复不丢失
前端显示同一批次
JSON与Excel逐字段一致
Web下载文件与本地验收结果一致
没有默认占位符
没有明文凭证泄漏
```

任何一项不满足，状态只能是：

```text
PARTIAL
FAIL
BLOCKED
```

不能使用：

```text
法定真本
100%全部真实
全部完成
```

---

# 21. 当前文件用途

今后所有 AI 开发指令必须先读取本文件：

```text
MASTER_BUSINESS_LOGIC.md
```

重造顺序：

```text
先 models
→ 再 validator
→ 再 exporter
→ 再 Master/Worker协议
→ 再远程 extractor
→ 再前端接线
→ 再四节点
```

本文件是逻辑总基线；代码可以删除和重写，但本文件、原始模板、真实证据和失败案例不能删除。
