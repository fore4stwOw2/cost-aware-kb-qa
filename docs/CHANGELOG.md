# CHANGELOG · 版本记录

> 版本管理规范：语义化版本（vX.Y.Z）+ 功能分支（`feat/wX-*`）+ 每阶段 GitHub Release。
> W1-W4 为存量阶段（提交历史平铺于 main，补打 tag 作为锚点）；W5 起按分支规范执行。
> 每条记录包含版本号 / 日期 / 阶段 / 关键结果 / 关联文档，与评测报告（`docs/eval-report-vX.Y.Z.md`）交叉核对。

## v1.2.0 · Agent 二期 B2 确认闸门（2026-09-03）

**一句话**：Agent 从"会执行"到"可负责地执行"——高风险动作必须人工确认，预算触顶即停，取消不重放副作用。

**新增**：
- agent_core 确认闸门：状态机（waiting_approval→approved/cancelled）+ 确认卡六要素 + confirm_callback + 回调异常兜底
- report.export 改 dry-run 回执（EXPORT-SIM-），零真实副作用
- app.py Agent 第 4 模式 + render_trace（工具轨迹/策略事件可视化）+ 确认卡两阶段交互
- ask.py --auto-confirm + CLI 交互确认；单测 35 条（新增 11 条闸门用例）

**关键结果**：Verifier 7/7 通过；确认卡逐字段断言；多轮"先 low 后 high"拒绝不重放验证；预算费用/轮数双触顶 blocked。

**关联**：[spec-w6-agent](docs/spec-w6-agent.md) · [验收报告](docs/acceptance-b2.md)

## v1.1.0 · Agent 二期 B1 工具层（2026-09-03）

**一句话**：作品二从"RAG 问答"迈出到"Agent 任务"第一步——工具注册与执行层 + 最小 planning→tool→observe 循环。

**新增**：
- `tools.py`：工具注册表（kb.search / price.lookup / cost.estimate / report.draft / report.export），Schema 校验（类型/必填/enum/minimum/maximum + args 守卫）、风险分级、refund.create 黑名单服务端拒绝
- `data/prices.json`：4 家/21 模型结构化价格表（核验 2026-09-01）
- `agent_core.py`：run_agent 最小循环（预算闸门 8 轮/$0.02、trace 事件链、needs_confirmation 预留、DeepSeek reasoning_content 兼容）
- `ask.py --agent`：命令行 Agent 任务入口；`tests/` 24 条单测

**关键结果**：端到端选型测算任务 3/3 连续成功（含查价/检索/成本估算/对比结论，回答含数字与核验日期）；修复两轮"多轮循环不确定性"问题（reasoning_content 字段回传、非 JSON 纯文本收尾容错）。

**关联**：[spec-w5-agent](docs/spec-w5-agent.md) · [验收报告](docs/acceptance-b1.md) · [问题日志](docs/problem-log.md)

## v1.0.0 · W6 材料收官（2026-09-03）★ RAG 作品 1.0

**一句话**：面试材料成文，作品可对外完整展示——讲解稿、简历条目、版本标注全部齐备。

**新增**：
- `docs/interview-script.md`：九步面试讲解稿（一句话→问题→Demo→方案→证据→取舍→边界→下一步→收尾），每步含讲稿 + 追问预案 + 高频追问速答表
- `docs/resume-entry.md`：两作品简历条目终版（含量化结果 + GitHub 链接）
- README 版本演进表（v0.1→v1.0）+ PRD 版本标注

**关联**：[interview-script](docs/interview-script.md) · [resume-entry](docs/resume-entry.md) · [验收报告](docs/acceptance-w6.md)

## v0.5.0 · W5 演示稳定化（2026-09-03）

**一句话**：现场演示可复现、可兜底——固定演示路径一键跑通，API 异常时有离线存档兜底，并修复了一个真实的可靠性 bug（API 调用慢速挂起可卡 1000s+，无超时兜底）。

**新增**：
- `scripts/demo_path.sh`：五条固定演示路径（简单→便宜档 / 复杂→贵档 / 库外拒答 / 越权拦截 / 断模型降级）+ killpg 进程组强杀看门狗（60s/路径）
- `docs/demo-archive/`：离线兜底说明 + 轨迹存档目录（真实轨迹：简单题路径带正确引用回答）
- `docs/prompt-library.md`：提示词库独立成文（回答/分类器/拒答/降级/裁判 5 类，含 v1/v2/v4 版本史）
- **可靠性修复**：API 调用三层超时防线（client timeout + create timeout + 脚本 killpg），`API_TIMEOUT` 默认 30s；实测修复前单条调用可挂 2 小时+

**关联**：[spec-w5](docs/spec-w5.md) · [demo-archive](docs/demo-archive/README.md) · [prompt-library](docs/prompt-library.md) · [problem-log](docs/problem-log.md)（W5 条目）

## v0.4.0 · W4 badcase 修复终版（2026-09-02）

**一句话**：修复评测暴露的 4 类问题，把路由能力推到可信水位。

| 指标 | W3 基线 | W4 终版 |
|------|---------|---------|
| 路由准确率 | 0.852 | **0.963** |
| 成本节省（route vs pro） | 30.8% | **37.6%** |
| 拒答正确率（route） | 1.0 | **1.0** |
| 瞎编数（三臂） | 0 | **0** |
| in_kb 质量差（route−pro） | +0.15（略低） | +0.14（基本持平） |

**新增**：查询改写修 e15 召回、泄漏拦截改组合条件防误伤、补 basic-terms / model-selection-framework 语料、评测报告支持 `--out` 分文件。
**关联**：[spec-w4](docs/spec-w4.md) · [验收报告](docs/acceptance-w4.md) · [badcase 归因](docs/badcase-w4.md) · [评测报告](docs/eval-report-w4.md)

## v0.3.0 · W3 评测体系（2026-09-02）

**一句话**：自建 30 条评测集 + 三臂对比，把"效果好不好"变成可核验的数字。

**新增**：30 条评测集（21 典型/6 边界/3 对抗）、LLM-as-Judge 四维评分（经 v1→v4 人工校准）、三臂对比评测基线、评测缓存/重判机制。
**关联**：[spec-w3](docs/spec-w3.md) · [验收报告](docs/acceptance-w3.md) · [评测报告](docs/eval-report-w3.md)

## v0.2.0 · W2 双档分级路由（2026-09-01）

**一句话**：给问答装上"路由大脑"——简单题走便宜档、复杂题走贵档、库外拒答、故障自动降级。

**新增**：三维分类器（难度/可答性/理由）、flash/pro 双档路由、越权确定性拦截、上游失败跨档降级、界面路由理由与成本展示。
**关联**：[spec-w2](docs/spec-w2.md) · [验收报告](docs/acceptance-w2.md)

## v0.1.0 · W1 单模型知识库问答（2026-09-01）

**一句话**：可演示的 RAG 问答基础版——检索、引用、成本显示、拒答逻辑全部就位。

**新增**：文档切片向量化入库、top-k 检索 + 带引用回答、token 用量与成本显示、低相似度拒答、命令行测试工具 ask.py。
**关联**：[需求一页纸](01-需求一页纸.md) · [验收报告](docs/acceptance-w1.md) · [问题日志](docs/problem-log.md)

---

## 待发布

| 版本 | 阶段 | 状态 |
|------|------|------|
| v0.5.0 | 原 W5 演示稳定化（备用部署/演示路径/提示词库） | 待做 |
| v1.0.0 | 原 W6 材料收官（九步讲解稿/演示备份/版本表）→ **RAG 作品 1.0** | 待做 |
| v1.1.0–v1.3.0 | Agent 二期 W5-W7（工具层/闸门/轨迹评测） | 待做 |
| v2.0.0 | Agent 二期 W8（展示验收）→ **作品升级为 Agent** | 待做 |
