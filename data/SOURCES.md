# 语料出处台账

> 规矩：`data/docs/` 里每篇文档都必须能在这张表里找到出处和日期。
> 面试和评测时被问"这个数字哪来的"，答案就在这张表里。

| 文件 | 来源 | 抓取日期 | 说明 |
|------|------|----------|------|
| model-landscape.md | https://github.com/archlizheng/AIPM-Wiki （docs/01-ai-basics/llm/model-landscape.md） | 2026-09-01 | 2026 模型盘点，数据核实至 2026-07；CC BY-NC-SA 4.0 |
| glossary.md | https://github.com/archlizheng/AIPM-Wiki （docs/01-ai-basics/glossary.md） | 2026-09-01 | AI 术语速查表；CC BY-NC-SA 4.0 |
| llm-cost-101.md | https://github.com/archlizheng/AIPM-Wiki （docs/02-pm-skills/cost-and-tech/llm-cost-101.md） | 2026-09-01 | token 成本测算入门；CC BY-NC-SA 4.0 |
| deepseek-pricing-2026-09.md | https://api-docs.deepseek.com/quick_start/pricing | 2026-09-01 | 官方定价页（英文版，美元计价），含分时段/缓存/思考模式计费 |
| openai-pricing-2026-09.md | https://platform.openai.com/docs/pricing | 2026-09-01 | 官方定价页文本 token 部分，含推理 token 计费规则与 embeddings |
| anthropic-pricing-2026-09.md | https://docs.anthropic.com/en/docs/about-claude/pricing | 2026-09-01 | 官方定价页，含长上下文加价、prompt caching、Batch 5 折 |
| gemini-pricing-2026-09.md | https://ai.google.dev/pricing | 2026-09-01 | 官方定价页，含 3.7 Flash 介绍价（2026-12-31 到期）与 Pro 长上下文分段计价 |
| basic-terms.md | 公开资料综合整理（token/上下文窗口/温度，内容与 AIPM-Wiki llm-cost-101、glossary 一致） | 2026-09-01 | 补术语缺口：原语料无 token/上下文窗口/温度定义，W4 修复语料空缺 badcase |

> 以上 3 篇是 W1 的**种子语料**，让项目当天就能跑起来。
> 接下来按 `02-语料收集清单.md` 抓取各家官方定价页/模型文档，每加一篇就在这张表登记一行。
> 合规红线：本台账和 data/docs/ 里不允许出现任何公司内部材料。
