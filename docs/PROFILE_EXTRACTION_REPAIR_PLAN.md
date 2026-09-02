# 547户资料缺失修复计划

目标：保留已有订单结果，每户最多3单；只补修登录成功账号的会员资料，不重新破坏已有数据。

## 一、先接受当前事实

当前批次应按以下事实处理：

```text
总账号：547
登录验证成功：306
明确密码错误：54
不完整/技术问题：187
订单：828
成功登录账号中，会员资料真正完整：6
成功登录账号中，资料缺失或资料访问失败：300
```

`active` 不能再表示“资料完整”。它最多表示登录或订单流程成功。

## 二、禁止的错误修法

不能做：

```text
用订单收件人姓名覆盖会员资料姓名
用订单地址覆盖会员中心地址而不标来源
用Shop ID映射冒充页面店铺原文
用默认支付方式补卡号
把profile empty和profile failed混为一类
把登录成功但资料失败标成完整active
```

订单页面和会员资料页面是两个不同证据来源。

## 三、正确数据模型

账号结果必须同时保留：

```json
{
  "login_status": "verified",
  "profile_status": "complete|empty|failed|unknown",
  "orders_status": "complete|no_orders|failed|unknown",
  "technical_status": "ok|retryable|final",
  "overall_status": "active_profile_complete|active_profile_empty|profile_failed|orders_failed|wrong_password|technical_retryable|technical_final",
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
  "profile_sources": [],
  "orders": [],
  "order_limit": 3,
  "total_history_order_count": null,
  "scraped_order_count": 0
}
```

资料字段必须带来源：

```json
{
  "field": "last_name",
  "value": "...",
  "source": "member_profile_dom",
  "source_url": "...",
  "selector": "...",
  "screenshot": "..."
}
```

订单收件人另存：

```text
order.delivery_recipient
order.delivery_address
order.buyer_info
```

不得写回 `profile.last_name`，除非页面明确证明二者相同，并且仍保留来源。

## 四、修复顺序

### P0：冻结已有订单

1. 复制当前 `results.source.json`；
2. 订单字段不重新抓、不覆盖；
3. 为每个账号生成新的 `profile_repair_attempt_id`；
4. 只补写 `profile` 和 `profile_status`；
5. 失败结果另存，不覆盖原始结果。

### P1：修状态判定

规则：

```text
login verified + profile complete + orders complete
→ active_profile_complete

login verified + profile empty（页面明确显示未填写）+ orders complete
→ active_profile_empty

login verified + profile 页面访问/解析失败
→ profile_failed

login verified + orders 页面访问/解析失败
→ orders_failed

官方密码错误文案
→ wrong_password

代理、网络、浏览器、DOM超时
→ technical_retryable 或 technical_final
```

只有官方页面明确提供密码错误证据时，才能标 `wrong_password`。

### P2：修复同一Cookie下的资料页访问

登录成功后必须复用同一个 BrowserContext：

```text
登录
→ 保留context/cookie
→ 访问资料页
→ 访问地址/卡片页
→ 访问订单页
→ 关闭context
```

资料页如果再次跳转到官方 SSO：

```text
使用同一context完成正常的登录页面流程
```

不得：

```text
新建无Cookie context
调用内部接口伪造登录
绕过2FA、CAPTCHA或Passkey
把跳转失败记成资料为空
```

登录后每一步必须记录：

```text
最终URL
页面标题
关键DOM是否存在
截图路径
错误类型
```

### P3：资料页面提取

按页面真实 DOM 选择器提取，不从全页正文猜：

```text
姓名汉字
姓名假名
生日
性别
地址
电话
卡片品牌/后四位
```

选择器必须按优先级配置，并记录命中选择器：

```text
label/value结构
字段专用id/class
表单value
页面可见文本
```

页面明确没有填写：

```text
profile_status=empty
字段=""
```

页面没有加载、selector超时、跳转失败：

```text
profile_status=failed
字段=""
errors中记录原因
```

### P4：订单保持最多3单

订单逻辑保持用户规则：

```text
total_history_order_count = 页面识别总数（如有）
scraped_order_count = 实际详情成功数
order_count = len(orders)
order_limit = 3
```

必须满足：

```text
order_count == scraped_order_count
order_count <= 3
```

订单没有：

```text
orders_status=no_orders
orders=[]
```

订单页面失败：

```text
orders_status=failed
```

不能把两者混淆。

## 五、只重跑哪些账号

不要重跑全部547户。

第一轮只重跑：

```text
login_status=verified
且 profile_status=empty 或 profile_status=failed
```

数量约300户。

明确密码错误、2FA、技术失败账号暂不重跑资料页。

重跑时：

```text
保留原订单
只更新profile_attempt
不覆盖原始订单截图
失败保留原失败证据
```

## 六、Excel导出规则

老板16列仍按原模板：

```text
A 账号
B 密码
C 姓
D 名
E 姓假名
F 名假名
G 卡号/其他信息
H 生日
I 性别
J 地址
K/P 店铺和订单1~3
```

映射只能来自统一 `profile` 对象：

```text
profile.last_name → C
profile.first_name → D
profile.last_name_kana → E
profile.first_name_kana → F
profile.card_masked → G
profile.birthday → H
profile.gender → I
profile.address + profile.phone → J
```

禁止导出器混用：

```text
profile_data
顶层last_name
订单buyer_info
订单delivery_recipient
```

如果兼容历史字段，必须在进入导出器前先正规化为 `profile`，不能在Excel代码中到处猜字段。

## 七、验收标准

### 单账号

必须检查：

```text
登录截图存在
资料截图存在
订单列表截图存在
profile_status正确
profile字段与截图/DOM来源对应
orders_status正确
订单最多3笔
订单原有数据未被覆盖
Excel C~J与profile逐格一致
Excel订单字段与JSON逐格一致
```

### 5户修复批

```text
5户结果全部有attempt_id
原订单数量不变
资料成功、资料空、资料失败三类不混淆
技术异常不变成密码错误
Excel可打开
没有默认姓名、默认商品、默认支付方式
```

### 50户扩大前

```text
至少5户成功资料复采
至少1户明确资料为空
至少1户资料页技术失败
三类状态均被正确保存
前端展示与JSON一致
Excel与JSON一致
截图manifest全部通过
```

## 八、成功定义

只有以下才叫资料修复完成：

```text
登录成功账号均继续访问资料页
资料有值的账号进入profile
资料确实未填写的账号标empty并留空
资料页面失败的账号标failed并保留错误证据
Excel正确映射profile字段
原订单不丢失、不改变
```

不能用以下词代替成功：

```text
active数量增加
Excel有行
字段非空
验收器PASS
```

## 九、给AI的执行指令

```text
只修 profile 数据链和状态语义，不修改订单解析规则，不改变每户最多3单限制。
先读取 PROFILE_EXTRACTION_REPAIR_PLAN.md。
第一步只修改 models.py、extractor.py、exporter.py、validator.py。
必须保留原始 results.json，使用新的 profile_repair_attempt_id 保存补采结果。
不能用订单收件人覆盖会员资料。
不能绕过2FA、Passkey或CAPTCHA。
先做5户远程补采，再运行本地逐字段验收。
验收失败不得扩大到50户。
报告必须输出：原始资料状态、修复后资料状态、订单是否保持不变、截图数量、Excel字段一致性、失败原因。
不得只输出“PASS”或“已修复”。
```
