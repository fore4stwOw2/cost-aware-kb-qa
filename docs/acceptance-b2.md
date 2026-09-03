# B2 验收报告（确认闸门 · v1.2.0）

> 流程：ai-native-dev-flow（spec-w6-agent → Writer 实现 → Reviewer 白盒 → Verifier 黑盒 → 修复闭环 → 终验）。
> 里程碑：Agent 从"会执行"到"可负责地执行"——高风险动作必须人工确认，预算触顶即停，取消不重放副作用。

## 验收标准与结论（Verifier 黑盒 7/7 通过 + Reviewer 修复闭环）

| # | 标准 | 结论 |
|---|------|------|
| AC1 | 状态机：high 风险 → waiting_approval → approved 后 dry-run / denied 后 cancelled | ✅ 通过（端到端 waiting_approval→approved→EXPORT-SIM- 回执→succeeded） |
| AC2 | 确认卡六要素（action/object/scope/consequence/reversible/deny_path） | ✅ 通过（逐字段断言） |
| AC3 | 预算闸门：轮数/费用触顶 → blocked，不静默继续 | ✅ 通过（blocked 1 + budget_cost 单测） |
| AC4 | 取消不重放：denied → cancelled，无副作用事件 | ✅ 通过（含多轮场景：先 low 后 high，被拒工具无执行事件） |
| AC5 | app.py Agent 模式 + render_trace + 确认卡交互 | ✅ 通过（代码级验证） |
| AC6 | 单测 ≥10 新增 | ✅ 通过（**新增 11 条**：确认闸门四态/工具风险分级/预算费用触顶/medium 自动执行/多轮不重放/回调异常兜底/确认卡逐字段/approved 链路） |
| AC7 | 回归：B1 ask.py --agent 路径 + 既有单测 | ✅ 通过（route 正常作答，35 条全绿） |

## Reviewer 白盒审查与修复闭环

| 问题 | 级别 | 修复 |
|------|------|------|
| AC6 单测新增不足（<10）且缺 budget_cost 用例 | 🔴 | 补 6+ 条至净增 11 条（含 budget_cost 触顶、medium 自动执行、多轮不重放、回调异常） |
| confirm_callback 异常穿透 run_agent | 🟡 | try/except 包回调 + 单测 |
| 两阶段重跑"任务级一次决定"（后续 high 工具未逐张确认） | 🟡 | 书面设计取舍：demo dry-run 场景可接受；服务端闸门对每个 high 工具仍强制检查。B3/B4 可改为逐张确认 |
| CLI 交互确认卡展示顺序（input 先于卡片） | 🟡 | 记录：CLI 交互为演示辅助，主交互走 Streamlit 确认卡；EOFError 由 --auto-confirm 兜底 |
| 会话成本统计失真（重跑成本未计入） | 🟡 | 记录：B3 轨迹评测统一成本口径 |
| 隐式状态机 / 确认卡字段语义偏松 | ⚪ | 记录，demo 可接受 |

## 关键设计说明（信任校准）

- **确认分级**（wiki 可逆性四级）：只读自动执行、可逆写入（草稿）先做后告知、高风险（导出）必须事前确认、黑名单产品层拒绝
- **服务端强制**：风险分级在工具注册表，闸门在循环内先于执行，不依赖模型自觉；模型"拒绝自己调用 export"也被视为正确行为（已实测）
- **dry-run**：export 返回 EXPORT-SIM- 回执，零真实副作用（wiki 作品集指南要求）

## 成本

B2 全程 API 约 $0.03，红线内。

## 遗留（非阻塞）

- 逐工具确认（当前任务级一次决定）→ B4 演示优化
- 轨迹评测（eval.py 四接入点 + agent 用例）→ B3（v1.3.0）
- CHANGELOG v1.2.0 入库 + README Agent 章 → B4
