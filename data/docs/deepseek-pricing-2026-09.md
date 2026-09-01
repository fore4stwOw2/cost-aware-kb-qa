# DeepSeek API 定价

来源: https://api-docs.deepseek.com/quick_start/pricing
抓取日期: 2026-09-01

DeepSeek API 兼容 OpenAI/Anthropic 两种调用格式。当前模型：deepseek-v4-flash（更新至 V4-Flash-0731）、deepseek-v4-pro（更新至 V4-Pro-0813）、deepseek-v4-flash-vision-exp（实验版，支持图片输入）。

## 文本 token 定价（每百万 token，美元）

| 模型 | 输入-缓存命中 | 输入-缓存未命中 | 输出 |
|------|--------------|----------------|------|
| deepseek-v4-flash | 淡季 $0.007 / 高峰 $0.014 | 淡季 $0.22 / 高峰 $0.44 | 淡季 $0.66 / 高峰 $1.32 |
| deepseek-v4-pro | 淡季 $0.022 / 高峰 $0.044 | 淡季 $0.66 / 高峰 $1.32 | 淡季 $1.98 / 高峰 $3.96 |
| deepseek-v4-flash-vision-exp | 淡季 $0.007 / 高峰 $0.014 | 淡季 $0.22 / 高峰 $0.44 | 淡季 $0.66 / 高峰 $1.32 |

## 分时段计价

- 高峰时段：UTC 周一至周五 01:00–04:00 和 06:00–10:00；其余为淡季
- 淡季价格为高峰的一半（50% 折扣）

## 思考模式

- v4 系列模型支持 thinking 开关与 reasoning_effort 参数（如 high）
- 思考与非思考模式价格相同，但开启思考会消耗额外输出 token（不可见但仍计费）

## 其他

- v4-flash 并发限制 2500，v4-pro 为 500
- vision-exp 的图片按尺寸折算为 token，与文本一起按输入计费
- 官方声明价格可能调整，以定价页最新信息为准
