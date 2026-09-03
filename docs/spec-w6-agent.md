# W6-Agent 需求简报 + 验收标准（确认闸门 · v1.2.0）

> ai-native-dev-flow 第 0-2 步产物。目标：给 B1 的 Agent 循环装上"人机信任闸门"——高风险动作必须人工确认、预算触顶即停、取消不重放副作用。
> 对应版本：v1.2.0 ｜ 分支：feat/w6-agent-gates

## 需求简报

- **目标**：B1 已能跑通任务循环；B2 让它"可负责地完成任务"——对高风险工具调用强制人工确认，并在界面（Streamlit）呈现任务卡、工具轨迹与确认卡。
- **范围内**：
  1. `agent_core.py` 扩展：状态机（created→planning→running_tool→observing→waiting_approval→succeeded/blocked/cancelled）+ 确认卡数据（动作/对象/数据范围/后果/可撤销性）+ approve/deny 入口 + 预算触顶 blocked + 取消不重放
  2. `app.py`：Agent 第 4 模式（侧边栏 radio）+ `render_trace`（轨迹可视化：每步工具/参数/结果/状态）+ 确认卡交互（st.form 确认/拒绝按钮）
  3. `tests/`：状态机转移、确认卡字段、budget blocked、cancel 不重放 等单测
- **范围外**：轨迹评测（B3）；README Agent 章（B4）；多轮记忆/长任务持久化
- **决策记录**：
  - `CONFIRMED` 确认分级（wiki 可逆性四级）：只读（low）自动执行；可撤销写入（medium，草稿）先做后告知+可撤销；难撤销/对外副作用（high，export）**必须事前确认**；高风险拒做（如直接调黑名单）产品层拒绝
  - `ASSUMED` 确认卡六要素：动作 / 对象 / 数据范围 / 后果 / 可撤销性 / 拒绝入口（拒绝→cancelled，不得换工具偷偷重试）
  - `ASSUMED` 预算：模型调用轮数 ≤8 或费用 ≤$0.02，先到先停 → blocked，向用户说明"已完成/未完成/下一步"

## 状态机（写进 agent_core）

```
created → planning → running_tool → observing
running_tool 分支：
  工具 low/medium → observing（继续循环）
  工具 high（如 report.export）→ waiting_approval
    → approved → 执行（dry-run）→ observing → succeeded
    → denied → cancelled（不重放副作用）
  预算触顶（轮数/费用）→ blocked
observing → 下一轮 planning 或 succeeded（模型输出 final）
```

## 验收标准

| # | 标准（独立可判定） |
|---|------|
| AC1 | 状态机：run_agent 返回结构含 status ∈ {succeeded, blocked, needs_confirmation, cancelled, failed}；high 风险工具触发 waiting_approval（返回 needs_confirmation + confirmation 卡数据），approved 后执行、denied 后 cancelled |
| AC2 | 确认卡六要素：needs_confirmation 返回含 action/object/scope/consequence/reversible/deny_path 字段 |
| AC3 | 预算闸门：轮数/费用触顶 → blocked，trace 记录 policy_check，不静默继续 |
| AC4 | 取消不重放：denied 后状态为 cancelled，且 trace 中无该工具的已执行副作用事件（export 未执行） |
| AC5 | app.py Agent 模式：侧边栏第 4 选项；`render_trace` 展示工具轨迹（工具名/参数摘要/结果/状态）；确认卡出现"确认/拒绝"按钮且交互后状态正确流转 |
| AC6 | 单测 ≥10 新增：状态机转移（waiting_approval→approved/denied）、确认卡字段完整、budget blocked、cancel 不重放、low 风险自动执行不弹确认 |
| AC7 | 回归：B1 的 ask.py --agent 路径不受影响（端到端 succeeded），24 条既有单测仍通过 |
