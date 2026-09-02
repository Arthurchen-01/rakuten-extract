# 乐天历史真实抓取经验与重写依据

版本：Experience Record v1.0
用途：给新系统的 extractor、worker、exporter 和 validator 使用
范围：记录过去实际走过的页面路径、浏览器行为、字段来源、失败经验和验证要求

> 本文件是技术经验记录，不是当前生产通过证明。不得写入账号密码、Cookie、Token、SSH 凭证或完整个人敏感信息。

---

## 1. 目标业务规则

对每个输入账号：

```text
尝试登录
→ 登录成功后保留当前浏览器 Cookie/Session
→ 继续访问会员资料
→ 继续访问购买履历
→ 最多深入抓取 3 笔订单详情
→ 每个阶段保存截图
→ 有字段就填写，无字段留空
→ 页面失败与页面无数据必须区分
```

注意：

```text
登录成功 ≠ 资料成功
登录成功 ≠ 订单成功
未登录 ≠ 0订单
技术超时 ≠ 密码错误
```

每个账号最多导出 3 笔订单是业务限制，不是缺陷。

必须分开记录：

```text
total_history_order_count  页面显示/识别的历史订单数
scraped_order_count        实际进入详情并成功落盘的订单数
order_count                最终导出的订单数，必须等于 len(orders)
order_limit                固定为 3
```

---

## 2. 过去使用过的页面路径

### 2.1 订单中心/购买履历入口

历史实际使用过：

```text
https://order.my.rakuten.co.jp/
https://order.my.rakuten.co.jp/?page=myorder
https://order.my.rakuten.co.jp/?scid=myr_popular_purchasehist
https://order.my.rakuten.co.jp/purchase-history/order-list
```

经验：

- `order.my.rakuten.co.jp` 是购买履历的主要业务域；
- 从 `my.rakuten.co.jp` 跳转订单中心时可能触发统一 SSO；
- `?page=myorder` 和 `purchase-history/order-list` 属于订单入口/列表入口；
- 入口 URL 能打开不代表已登录；必须检查登录态和页面内容；
- 不要把 URL 中含 `rakuten.co.jp` 作为登录成功的唯一条件。

### 2.2 统一 SSO

历史遇到过：

```text
login.account.rakuten.com
#/sign_in/webauthn
```

可能流程：

```text
输入用户 ID
→ Enter
→ Passkey 页面
→ 选择「パスワードを使用する」
→ 密码输入框
→ 输入密码
→ Enter
→ 返回业务页面或错误/2FA页面
```

已经观察到的按钮/文案：

```text
パスワードを使用する
スキップしてログイン
メールアドレスをご確認ください
ユーザIDまたはパスワードが正しくありません
パスワードが正しくありません
ワンタイムパスワード
認証コード
2段階認証
確認コード
```

规则：

- Passkey 不能自动绕过；只允许页面明确提供密码切换按钮时执行页面点击；
- 2FA 没有合法跳过入口时，标记 `two_factor`，不猜测成功；
- `スキップしてログイン` 只有页面真实存在时才能点击；
- 页面按钮不存在时不能强行调用 JS 假造通过；
- 登录错误必须以官方页面文案和截图为证据。

### 2.3 会员资料页

历史使用过：

```text
https://member.id.rakuten.co.jp/r/info.html
https://my.rakuten.co.jp/
```

不同账号、不同时间可能出现不同域名或页面结构。新系统必须记录：

```text
最终 URL
页面标题
抓取时间
页面截图
关键 DOM 选择器命中情况
```

不能仅依赖整页正则。

### 2.4 地址和会员信息

历史可能提取：

```text
姓、名
姓假名、名假名
生日
性别
地址
电话
卡片品牌和后四位
```

页面无值时写：

```text
""
```

页面打不开或 DOM 解析失败时写：

```text
字段值：""
profile_status："failed"
errors：记录技术原因
```

不能把失败写成 `empty`，也不能把空页面写成成功完整。

---

## 3. 页面交互经验

### 3.1 浏览器上下文

历史使用 Playwright Chromium：

```text
headless Chromium
locale：ja-JP
timezone：Asia/Tokyo
viewport：约 1280x800 或 1440x900
```

可能使用过：

```text
--no-sandbox
--disable-infobars
--disable-dev-shm-usage
--lang=ja-JP
```

新系统必须记录运行环境，但不能把伪装浏览器指纹当作登录成功证据。

### 3.2 Cookie/Session

要求：

```text
同一个账号使用同一个 BrowserContext
登录后不关闭 context
先访问资料和订单页面
全部阶段完成后再关闭 context
```

禁止：

```text
登录后新建没有 Cookie 的 page/context
用另一个账号的 context
把 Cookie 写入普通日志或 JSON
```

最终结果不保存 Cookie 原文，只记录：

```text
session_verified：true/false
context_id：非敏感内部 ID
```

### 3.3 广告/追踪请求

过去曾配置过对以下第三方域名请求的拦截：

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

这只是网络请求拦截，不等于删除页面广告 DOM。

风险：

- 不能使用全量宽泛拦截误伤业务资源；
- 每次拦截必须记录 URL、域名、原因；
- 拦截后必须检查关键页面元素仍存在；
- 页面业务数据缺失时，先关闭拦截做 A/B 对比；
- 商品标题中的促销词不等于页面广告，不能全局删除。

建议新系统默认：

```text
仅拦截明确第三方统计域名
保留楽天业务域名和未知资源
```

---

## 4. 登录结果分类

### 4.1 可确认账号/人工挑战状态

只有有页面证据时使用：

```text
wrong_password
account_locked
two_factor
passkey
captcha
```

证据至少包括：

```text
官方文案
最终 URL
错误/挑战截图
发生阶段
```

### 4.2 技术状态

以下不得判为密码错误：

```text
页面导航超时
SSO 重定向超时
用户输入框未出现
密码框未出现
页面空白
DOM 结构变化
Playwright TimeoutError
Target closed
浏览器崩溃
代理连接失败
DNS/TCP失败
截图保存失败
截图上传失败
Master 回报失败
```

统一分类：

```text
technical_retryable
technical_final
```

重试达到上限也不能改成 `wrong_password`。

### 4.3 账号状态与资料状态分离

推荐结构：

```json
{
  "login_status": "verified",
  "profile_status": "complete|empty|failed|unknown",
  "orders_status": "complete|no_orders|failed|unknown",
  "technical_status": "ok|retryable|final",
  "overall_status": "active|partial|wrong_password|two_factor|technical_retryable|technical_final"
}
```

如果登录成功但资料页访问失败：

```text
login_status：verified
profile_status：failed
orders_status：unknown
overall_status：partial
```

如果登录成功且订单页明确显示无订单：

```text
login_status：verified
orders_status：no_orders
orders：[]
```

只有这时才能说“确认无订单”。

---

## 5. 订单抓取经验

### 5.1 页面订单列表

历史问题：

- 用 `body.innerText` 全页正则容易抓到导航、提示和广告；
- 订单编号可能重复出现在页面多个位置；
- 订单卡片可能有“おすすめの商品”等外围区域；
- 页面显示总数和实际详情入口数量可能不同；
- 旧逻辑曾用 `[:3]`，这符合当前业务最多 3 单规则，但必须显式记录上限。

新规则：

```text
先定位订单列表容器
再定位订单卡片
每个卡片单独提取订单号、日期、店铺候选和详情链接
最多选择3个稳定订单详情链接
```

不允许：

```text
从全页第一个“店/ショップ/ストア”文本猜店铺
从全页任意数字猜金额
用默认“楽天市场”填店铺
```

### 5.2 订单详情

每笔最多 3 笔，但每笔都需要：

```text
order_number
order_date
shop_name
item_name
quantity
price_yen
payment_method（页面有则填，无则空）
delivery_address（页面有则填，无则空）
buyer_info（页面有则填，无则空）
detail_url
detail_screenshot
raw_dom_text 或关键 DOM 原文片段
```

字段来源优先级：

```text
订单详情容器内专用 DOM
订单容器内店铺链接
订单商品表格
明确 label/value 结构
最后才是受限的容器内文本解析
```

### 5.3 店铺名称

历史已见问题：

```text
页面横幅含“店舗/当店”被误认为店铺
买い物かご、購入履歴等导航被误认为店铺
Shop ID 静态映射覆盖了页面真实文本
```

新规则：

```text
优先 .shopName、.shop_name、.shop-name、.shop_info a
检查订单容器内 a[href*="rakuten.co.jp/"]
读取 innerText、aria-label、title、img alt
过滤导航、按钮、提示和订单号
无法确认时留空并写 shop_parse_error
```

Shop ID 映射只能保存为：

```text
shop_name_inferred
inference_source：shop_id_mapping
```

不得覆盖：

```text
shop_name
```

### 5.4 商品名和促销词

商品标题可能真实包含：

```text
送料無料
楽天1位
期間限定
ポイント10倍
```

不能因为出现这些词就删除整行。

应从订单商品 DOM 读取完整标题，保存：

```text
item_name_raw
item_name_clean（如确有明确外围 UI 污染才清洗）
```

不能用：

```text
楽天市場ご注文商品
購入商品
```

作为默认商品名。

### 5.5 金额和数量

金额应只从订单详情的金额字段读取：

```text
price_yen_raw
price_yen_normalized
```

没有金额：

```text
price_yen：""
```

不能用：

```text
0円
```

作为默认值，除非页面真实显示 0 円。

数量应只从数量字段读取：

```text
quantity：""
```

不能默认写 `1`，除非页面真实显示数量 1。

---

## 6. 个人资料字段经验

### 6.1 不要只用全页正则

旧逻辑曾使用：

```text
フリガナ + 正则
生日 + 正则
电话号码 + 正则
〒 + 正则
```

问题：

- 页面提示或地址簿其他内容可能被抓到；
- DOM 结构变化后字段为空但错误被吞掉；
- 字段别名不一致：`birth_date`、`birthday`；
- 嵌套 `profile_data` 与顶层字段曾不一致，导致 Excel 姓名为空。

新系统必须统一模型：

```text
profile.last_name
profile.first_name
profile.last_name_kana
profile.first_name_kana
profile.birthday
profile.gender
profile.address
profile.phone
profile.card_masked
```

导出器只读取统一的 `profile` 对象，不在多个历史字段名之间隐式猜测。

### 6.2 空值和失败

页面没有填写：

```text
profile_status：empty 或 complete_with_empty_fields
字段：""
```

页面请求/解析失败：

```text
profile_status：failed
字段：""
errors：结构化错误
```

不能把两者都写成：

```text
profile_status：complete
```

---

## 7. 截图和证据经验

### 7.1 必要截图

登录失败或挑战账号：

```text
登录结果/错误页截图
```

登录成功账号：

```text
登录成功截图
个人资料页截图
订单列表截图
最多3笔订单详情截图
```

如果页面明确无订单，也要保存：

```text
订单列表截图
```

### 7.2 文件命名

```text
screenshots/<batch_id>/<account_id>/
  01_login_result.png
  02_profile.png
  03_order_list.png
  04_order_001_detail.png
  05_order_002_detail.png
  06_order_003_detail.png
```

不能使用全局固定文件名：

```text
step1.png
step2.png
```

避免账号之间覆盖。

### 7.3 manifest

每张图片记录：

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

远程绝对路径不能直接写入本地最终结果。

### 7.4 上传

Worker 上传失败必须：

```text
记录 UPLOAD_ERROR
账号或批次不能伪装为完整
不显示“已捕获（云端）”作为替代
```

---

## 8. Master/Worker 经验

### 8.1 统一任务协议

Claim 响应必须统一：

```json
{
  "claim_id": "...",
  "batch_id": "...",
  "account_id": "...",
  "account_data": {
    "email": "运行时注入，不落盘",
    "password": "运行时注入，不落盘",
    "proxy_ref": "..."
  },
  "lease_seconds": 180
}
```

Worker 必须从：

```text
task.account_data
```

读取账号运行数据。

不能一会儿使用：

```text
task.email
```

一会儿使用：

```text
task.account_data.email
```

### 8.2 Report 响应

Worker 回报必须包含：

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
orders
screenshots
errors
```

Master 只接受：

```text
当前有效 claim_id
当前 batch_id
当前 account_id
```

旧 Worker 迟到回报不能覆盖新结果。

### 8.3 租约和心跳

长任务必须支持：

```text
claim
heartbeat
lease renewal
report
```

Worker 正常工作但尚未完成时不能因固定超时被重复领取。

### 8.4 单写入者

Worker 不直接改最终 JSON。

推荐：

```text
Worker → Master API → Master SQLite事务 → results.json/manifest
```

避免多个 Worker 同时写同一个 JSON 造成覆盖和丢结果。

---

## 9. Web 前端经验

前端必须绑定明确的：

```text
batch_id
```

所有页面数据来自同一批次：

```text
GET /api/batches/{batch_id}
GET /api/batches/{batch_id}/results.json
GET /api/batches/{batch_id}/manifest.json
GET /api/batches/{batch_id}/export.xlsx
```

不再使用：

```text
最近一次导入
全局 manager.accounts
全局 orders_cache
/api/task-status 无 batch_id
```

前端必须显示：

```text
当前 batch_id
总账号数
已完成数
成功数
密码明确错误数
2FA/Passkey/CAPTCHA数
技术异常数
资料不完整数
订单不完整数
实际订单数
```

任务未完成时：

```text
导出按钮禁用
API 返回 409
```

不能让前端显示：

```text
任务完成
```

而后端仍有未处理账号。

---

## 10. Excel 经验

老板模板是导入/交付视图，保留 16 列：

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
资料有值就填
资料没有就空
订单最多3笔
没有订单就空
技术失败不写成0订单
禁止程序默认姓名、商品和支付方式
```

另外保留结构化订单表用于审计。

Excel 必须从同一个 `results.json` 生成，不能读取旧缓存。

生成后检查：

```text
Sheet 1 账号数量
Sheet 4 订单数量
逐笔订单号
逐笔店铺
逐笔商品
逐笔数量
逐笔金额
图片对象数量
xl/media 数量
```

---

## 11. 过去出现过的典型错误与对应修复

| 过去错误 | 根因 | 新系统处理 |
|---|---|---|
| 活跃账号无姓名 | status 无条件写成功；资料异常被吞 | 分离 login/profile/overall；资料字段门禁 |
| 订单店铺为空 | 全页正则误抓横幅后清空 | 订单容器 DOM 优先；无法确认留空 |
| Excel 和 Web 订单不同 | 本地 JSON 与 Web manager.accounts 分叉 | 统一 batch_id/results.json |
| Web Excel 0订单 | 任务未完成就导出 | 完成状态门禁，未完成返回409 |
| Excel 没图片 | 远端路径未下载到本地 | manifest + 下载 + 哈希校验 |
| 4节点互相覆盖 | 内存 claim 或多个调度器 | Master SQLite + claim lease + 单写入者 |
| 技术异常变密码错误 | 模糊字符串二次分类 | 结构化 failure_code，技术状态独立 |
| 订单统计64对15 | 历史总数与实际详情数混用 | 三个订单计数字段分离 |
| 3笔限制被误报为缺失 | 业务上限未记录 | order_limit=3，明确说明截断 |
| 图片重复绑定 | 缺图时复用另一列图片 | 缺失就空，禁止复制 |
| 生产跑旧代码 | 只覆盖磁盘文件，旧进程未重启 | 版本目录 + systemd + 运行时模块路径检查 |
| 前端“最近批次”错误 | 没有显式 batch_id | 所有请求必须带 batch_id |
| 报告哈希对不上 | 文件被覆盖，多版本混放 | 每批独立目录，immutable manifest |
| 广告清洗损伤业务字段 | 宽泛网络拦截或全局关键词删除 | 仅第三方请求；订单容器内提取 |
| 资料/订单空被当作无数据 | 页面访问失败和真实空页面混淆 | empty 与 failed 分开 |

---

## 12. 未来可选升级项

这些不是当前最小版本必须实现，但必须预留接口：

1. Playwright `storage_state` 的加密临时保存；
2. 每个账号独立 BrowserContext 和临时目录；
3. 页面 DOM 关键节点快照，而不只是整页截图；
4. 字段级 `source_selector` 和 `source_text_hash`；
5. 订单详情链接稳定性检查；
6. 页面分页检测；
7. 页面显示总数与抓取数差异报警；
8. 代理健康评分和自动摘除；
9. 节点 CPU、内存、浏览器数量限流；
10. Worker 心跳与租约自动续期；
11. SQLite WAL 或 PostgreSQL；
12. 断点续跑；
13. 账号级幂等重试；
14. 失败分类统计置信度；
15. 页面 HTML 脱敏后保存；
16. 关键字段 OCR/DOM 双重抽样核验；
17. Web 下载文件与 results.json 订单集合比对；
18. 结果包签名；
19. 版本化 schema migration；
20. 只读审计报告生成器；
21. 账号输入和结果数据的加密存储；
22. 凭证通过 Secret Manager 注入；
23. 人工处理队列：2FA、Passkey、CAPTCHA；
24. 失败账号冷却时间，避免重复触发风控；
25. 多语言页面文案字典；
26. 选择器版本和页面结构指纹；
27. 数据质量分级：完整、部分、空、失败、未验证；
28. 可取消任务和优雅关闭浏览器；
29. 远程节点代码启动时自报告版本；
30. 全批次审计事件流。

---

## 13. 新 extractor 实现清单

真实页面采集器完成前必须逐项实现：

```text
[ ] 运行时接收凭证，不写入文件
[ ] 创建独立 BrowserContext
[ ] 访问订单入口
[ ] 输入账号并记录页面结果
[ ] 处理明确的密码切换按钮
[ ] 识别密码错误
[ ] 识别2FA
[ ] 识别Passkey
[ ] 识别人机验证
[ ] 识别技术异常
[ ] 登录成功双重确认
[ ] 保持同一 Cookie/Session
[ ] 保存登录截图
[ ] 访问资料页
[ ] 保存资料截图
[ ] 资料字段 DOM 提取
[ ] 资料空值与失败分离
[ ] 访问订单列表
[ ] 保存订单列表截图
[ ] 记录历史订单数（如果页面提供）
[ ] 识别订单卡片
[ ] 最多选择3笔订单
[ ] 访问每笔详情
[ ] 保存详情截图
[ ] 店铺 DOM 提取
[ ] 商品 DOM 提取
[ ] 数量 DOM 提取
[ ] 金额 DOM 提取
[ ] 支付方式 DOM 提取
[ ] 收件人与订购人 DOM 提取
[ ] 生成结构化结果
[ ] 生成阶段 manifest
[ ] 所有异常结构化记录
[ ] 关闭 context
```

---

## 14. 何时允许批量

只有以下全部通过：

```text
单账号成功
单账号资料为空
单账号无订单
单账号密码错误
单账号2FA
单账号技术超时
3账号跨节点
8账号四节点
前端显示同一 batch_id
Web下载与本地结果一致
Excel字段逐项一致
截图manifest哈希一致
```

才允许逐步扩大：

```text
10户 → 50户 → 100户 → 500户 → 全量
```

本文件没有证明任何远程批次通过，只是把历史经验和新系统实现要求固定下来。
