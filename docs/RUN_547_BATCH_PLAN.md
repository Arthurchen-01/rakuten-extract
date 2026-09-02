# 547 户运行计划（只允许远程执行）

输入文件：

```text
C:\Users\25472\Downloads\Telegram Desktop\lt-success-new3_去重复_文本对比.txt
```

输入哈希：

```text
3DEC720378C4CE2CB33DB266E0514ECE975E741E2388FB286CC3712E69C5F119
```

输入规模：547 条非空记录，格式统一为 `账号----密码`。

## 运行档位

```text
5户校准批：远程Node 1，1并发
10户确认批：远程Node 1，最多2并发
20户稳定批：Node 1~2，最多3总并发
50户观察批：Node 1~3，最多4总并发
之后每批50户，直到剩余完成
```

## 每批必须执行

```text
创建唯一 batch_id
输入文件/切片哈希
远程执行
记录每个账号终态
记录每个技术错误
保存截图 manifest
生成 Excel
下载批次包
本地 validator 验收
```

## 批次之间的放行条件

```text
5户通过 → 才能10户
10户通过 → 才能20户
20户通过 → 才能50户
50户连续两个通过 → 才能继续50户
```

## 自动停止条件

```text
连续5户技术异常
最近10户技术异常>=30%
同一代理连续3次异常
任一截图上传失败
任一结果回报失败
前端/后端/JSON/Excel数量不一致
batch_id不一致
密码错误无官方错误截图
```

## 不误杀规则

```text
密码明确错误 → wrong_password
2FA → two_factor
Passkey → passkey
CAPTCHA → captcha
页面/代理/浏览器/DOM错误 → technical_retryable 或 technical_final
```

技术异常不得计入密码错误。

## 每批验收摘要

```text
total
processed
active
wrong_password（有官方页面证据）
two_factor
passkey
captcha
technical_retryable
technical_final
profile_empty
profile_failed
orders_no_orders
orders_failed
order_count
screenshot_count
validator_result
```

## 重要限制

```text
本计划不启动任务
本计划不修改远程代码
本计划不删除旧程序
本计划只是运行顺序和门禁
```
