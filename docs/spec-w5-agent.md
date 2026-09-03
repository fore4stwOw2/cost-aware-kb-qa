# W5-Agent 需求简报 + 验收标准（Agent 工具层 · v1.1.0）

> ai-native-dev-flow 第 0-2 步产物。目标：把作品二从"回答哪个模型划算"升级为"完成选型测算任务"的 Agent 第一步——工具注册与执行层 + 最小循环。
> 对应版本：v1.1.0 ｜ 分支：feat/w5-agent-tools

## 需求简报

- **目标**：建立 Agent 的工具层与最小执行循环（planning → tool → observe），产出结构化 trace（工具序列/每步成本/引用），为 B2 确认闸门、B3 轨迹评测打地基。
- **范围内**：
  1. `tools.py`：工具注册表（Schema 校验/风险分级/黑名单服务端拒绝）
  2. `data/prices.json`：从 4 篇定价 md 提炼的结构化价格表（含核验日期）
  3. `agent_core.py`：最小循环 `run_agent()`（无确认卡版），产出 trace 事件链
  4. `config.py`：AGENT_MODEL / AGENT_MAX_TURNS / AGENT_MAX_COST
  5. `tests/`：纯函数单测 ≥15（工具 Schema/黑名单/预算，无网络）
- **范围外**：确认卡与 waiting_approval（B2）；轨迹评测（B3）；UI Agent 模式（B2）；README Agent 章（B4）
- **决策记录**：
  - `CONFIRMED`（沿用已批准计划）Agent 任务 = 模型选型测算助手；工具地图 5+1（kb.search / price.lookup / cost.estimate 只读；report.draft 可逆；report.export 高风险需确认；refund.create 黑名单）
  - `ASSUMED` B1 阶段 report.draft/export 先注册工具但 export 直接返回"需人工确认（B2 实现）"，draft 生成草稿文本
  - `ASSUMED` AGENT_MODEL 默认用便宜档（成本可控，与作品二"成本敏感"主题一致）；预算 8 轮 / $0.02（PRD §6.3 已定）

## 工具契约（写进 tools.py 的每个工具）

| 字段 | 说明 |
|------|------|
| name | 动词命名（kb.search / price.lookup / cost.estimate / report.draft / report.export） |
| description | 能做/不能做一句话 |
| input_schema | 类型/必填/枚举/范围 |
| risk | low（只读）/ medium（可逆写入）/ high（不可逆，需确认） |
| side_effect | 无 / 生成草稿 / dry-run 模拟外发 |
| idempotent | 是否重复调用安全 |
| server_check | 服务端参数校验 + 黑名单拒绝（不依赖模型自觉） |

## 验收标准

| # | 标准（独立可判定） |
|---|------|
| AC1 | `tools.py` 存在：≥5 个工具注册（kb.search / price.lookup / cost.estimate / report.draft / report.export），每个含 name/description/input_schema/risk/side_effect/idempotent；`refund.create` 在黑名单，调用返回明确拒绝且不执行 |
| AC2 | `data/prices.json` 存在：含 ≥4 家（DeepSeek/OpenAI/Anthropic/Gemini）结构化价格（输入/输出/核验日期），`price.lookup` 能按模型名查到价格 |
| AC3 | `agent_core.run_agent()` 可执行：输入"帮我测算用 deepseek-v4-flash 做客服问答的月成本，DAU 1万"类任务，走 planning→tool→observe 循环，产出回答 + trace（含工具序列/每步成本/引用来源） |
| AC4 | 预算闸门：`AGENT_MAX_TURNS=8` / `AGENT_MAX_COST=$0.02` 触顶即 blocked，trace 记录"预算触顶"，不静默继续 |
| AC5 | 单测 ≥15：覆盖工具 Schema 校验（缺参/类型错/枚举外）、黑名单拒绝、预算计算、trace 结构 |
| AC6 | 回归：现有 ask.py 问答链路不受影响（跑 1 条简单题正常） |
