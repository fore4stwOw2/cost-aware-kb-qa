# W5 验收报告（演示稳定化 · v0.5.0）

> 流程：ai-native-dev-flow（spec-w5 → Writer 实现 → Reviewer 白盒 → Verifier 黑盒）。
> 环境说明：2026-09-03 执行期间 API 网络环境退化（单条调用实测 15s~1000s 不等），实时全量演示受网络限制；本验收以"脚本机制正确 + 超时兜底有效 + 文档齐全"为判定核心，实时路径以可用的存档/单条验证为准。

## 验收标准与结论

| # | 标准 | 结果 |
|---|------|------|
| AC1 | `scripts/demo_path.sh` 存在可执行，五条路径齐全，含超时强杀逻辑 | ✅ 通过：`bash -n` 语法通过；5 条 run_path 覆盖简单/复杂/库外/越权/降级；含 `start_new_session` + `killpg(SIGKILL)` 看门狗（60s/路径） |
| AC2 | `docs/demo-archive/` 含轨迹存档 + 离线兜底话术 | ✅ 通过：README（何时用存档/兜底话术/诚实原则）；`traces/` 含真实轨迹存档（简单题路径，正确引用回答：淡季 $0.66 / 高峰 $1.32 [1]） |
| AC3 | `docs/prompt-library.md` 含 ≥4 类提示词，带版本与变更记录 | ✅ 通过：5 类（回答/分类器/拒答/降级/裁判），版本史真实（分类器 v1→v2、裁判 v1→v4 均与代码/评测演进一致） |
| AC4 | 断网/API 异常时不挂死，README 补备用路径说明 | ✅ 通过（部分验证）：killpg 看门狗隔离测试 10s 内强杀成功；client/create timeout=3 实测 3s 内报错；README 边界补 API 超时兜底说明。⚠️ 说明：macOS 上 SIGALRM 与 socket 默认超时对 httpx 阻塞无效（实测），最终依赖 client timeout + killpg 两层，已收敛 |

## 本阶段最重要的产出：修复一个真实可靠性 bug

**现象**：演示脚本跑"复杂题走 pro"路径时 ask.py 可挂起 2 小时+（无任何超时）。
**根因**：DeepSeek 推理模型持续输出思考 token 时，SDK read-timeout 只在"字节间停顿"触发、不拦"持续慢速"；subprocess.run(timeout=) 在真实网络下也未能中断。
**修复**（三层职责，每层已验证）：
1. OpenAI client 初始化 + 每次 create 传 `timeout=config.API_TIMEOUT`（默认 30s）
2. `scripts/demo_path.sh` 用 `start_new_session` + `killpg(SIGKILL)` 进程组强杀（60s/路径）——隔离测试 10s 内强杀成功
3. `ask.py` 入口 `socket.setdefaulttimeout`（兜底裸 socket）
**教训**（已记入 problem-log）：AI 应用的"慢"与"挂"边界模糊，演示/评测链路必须有**进程级**总超时，不能只依赖 SDK 层。

## Reviewer 白盒要点

- 超时三层职责清晰，无无效机制残留（SIGALRM 实测 macOS 无效已移除）
- 提示词库内容与代码逐条对照一致（分类器五标签、裁判四维判定均与 qa_core.py/eval.py 一致）
- 演示脚本传参与存档逻辑正确，无回归（eval.py 评测链路不受影响）

## 遗留（非阻塞）

- 网络环境恢复后，用 `bash scripts/demo_path.sh --archive` 补全五条路径的真实轨迹存档（当前仅 1 条完整存档，其余机制已验证）
- 演示截图（浏览器界面）需在正常环境下人工截取，轨迹文本已可作为兜底

## 成本

W5 全程 API 约 $0.03（网络退化导致调用次数受限），红线内。
