# B1 验收报告（Agent 工具层 · v1.1.0）

> 流程：ai-native-dev-flow（spec-w5-agent → Writer 实现 → Reviewer 白盒 → Verifier 黑盒 → 两轮修复闭环 → 终验通过）。
> 里程碑：作品二从"RAG 问答"迈出到"Agent 任务"的第一步——工具注册与执行层 + 最小 planning→tool→observe 循环。

## 验收标准与结论（Verifier 终验 · 黑盒）

| # | 标准 | 结论 |
|---|------|------|
| AC1 | 工具注册表 ≥5 工具 + refund.create 黑名单服务端拒绝 | ✅ 通过（21 模型价格表 + 5 工具 + 黑名单实测拒绝） |
| AC2 | data/prices.json 含 ≥4 家 + 核验日期 | ✅ 通过（4 家/21 模型/2026-09-01） |
| AC3 | run_agent 端到端：planning→tool→observe + 回答 + trace | ✅ 通过（**3/3 连续 succeeded**，含查价/检索/成本估算/对比结论，回答含数字与核验日期） |
| AC4 | 预算闸门：轮数/成本触顶即 blocked | ✅ 通过（max_turns=1 → blocked；max_cost 触顶 → blocked + trace 记录） |
| AC5 | 单测 ≥15（Schema/黑名单/预算/trace 结构） | ✅ 通过（**24 条**，含真实注入 FakeClient 的 trace 断言） |
| AC6 | 回归：ask.py 问答链路不受影响 | ✅ 通过（简单题正常 route→flash） |

## 修复闭环（两轮，Verifier 独立复验抓到）

1. **第一轮失败（AC3 1/3）**：DeepSeek thinking 模式多轮对话要求历史 assistant 消息**始终携带 reasoning_content 字段**（空串也要）→ 修复 + `reasoning_effort=low` 降推理波动。Verifier 复验确认该问题消除。
2. **第二轮失败（AC3 1/3）**：收尾轮模型输出**非 JSON 纯文本**被整体判 failed → 修复：planner 提示词明确"最终回答用纯文本"，非 JSON 输出按最终回答处理。Verifier 终验 3/3 连续通过。

**方法论收获**（记入问题日志）：LLM 应用的多轮循环有两个"不确定性出口"——协议层（消息字段必须回传）与解析层（模型可能不按格式输出），两者都要在**生产路径**上容错，不能只靠提示词约束。这就是 Agent 和单轮问答的本质区别：单轮失败重试即可，多轮失败会带着整个 trace 一起失败。

## Reviewer 白盒要点

- 工具层：Schema 校验（类型/必填/enum/minimum/maximum + args 非 dict 守卫）、黑名单服务端强制、risk/side_effect 三级一致
- Agent 循环：预算闸门位置正确、tool_calls 协议合规（assistant 带 tool_calls + tool 回 tool_call_id + reasoning_content 回传）、trace 事件链完整
- 单测：trace 测试真实注入 FakeClient（修正了首版"虚假覆盖"问题）
- 无回归：qa_core 未动，eval.py 无依赖

## 成本

B1 全程 API 约 $0.05（多次端到端 + 复验），红线内。

## 遗留（非阻塞，进 B2/B3）

- 确认闸门（waiting_approval）与 Streamlit Agent 模式 UI → B2（v1.2.0）
- 轨迹评测（eval.py 四接入点 + agent 用例）→ B3（v1.3.0）
- needs_confirmation 状态已在 run_agent 预留（工具层已返回该 policy）
