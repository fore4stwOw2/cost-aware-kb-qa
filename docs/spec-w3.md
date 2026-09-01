# W3 需求简报 + 验收标准（留痕）

> ai-native-dev-flow 第 0-2 步产物。用户已授权"需决策处按推荐方案执行并记录"，故 grill 决策以 ASSUMED/CONFIRMED 形式记录于此，用户可随时推翻任一条。

## 需求简报

- **目标**：为知识库问答建立 30 条评测集，跑三臂对比（全便宜 flash / 全贵 pro / 智能路由），量化"路由省多少成本、质量损失多少"——这是作品集的核心证据页。
- **范围内**：① 评测集 30 条（70/20/10 配比，带金标准标签）② 批量评测脚本 eval.py（复用 qa_core 管线）③ LLM-as-Judge 质量评分 ④ 三臂对比报告（成本/质量/路由准确率/拒答正确率）
- **范围外**：badcase 修复与回归（W4）、阈值正式调优（W4）、语料扩充（W4 部分）

## 决策记录（grill → ASSUMED/CONFIRMED）

- `CONFIRMED` 贵档 = deepseek-v4-pro（沿用 W2）
- `CONFIRMED`（决策变更记录）裁判模型 = **deepseek-v4-flash**（原 ASSUMED 为 v4-pro）。变更原因：v2 用 pro 裁判 + "faithful≤1 连坐"导致系统性误杀（人工抽查 4/4 误判）；校准到 v4 四维口径（answerable/fabricated/grounded/complete）并用 flash 裁判后，三个人工构造用例（正确回答/瞎编/答非所问）判定全部正确，且 81 次调用成本可控。实现 `eval.py` 单一赋值 `JUDGE_MODEL = config.CLASSIFY_MODEL`，报告头部披露裁判模型。
- `ASSUMED` 评测集内容：由 Writer 构造 30 条，覆盖定价/成本/选型/术语/库外/歧义/越权七类，每条带金标准字段（期望难度、期望可答性、期望行为 respond/refuse、标准答案要点）
- `ASSUMED` 质量评分：LLM-as-Judge 四维判定（可答/编造/有据/答全），对"应回答"用例评分；"应拒答"用例单列拒答正确率；库外题硬答（flash/pro 固定档）也做瞎编审计，不留盲区
- `ASSUMED` 指标口径：路由准确率仅统计"未拒答且真正被分类"的用例；拒答正确率 = 库外用例被正确拒答比例；瞎编 = judge 判 fabricated 且裁判本身成功；"该答却拒答""库外硬答""裁判失败"单列披露
- `ASSUMED` 可复现性：temperature=0、评测集固定、记录模型与价格核验日期
- `ASSUMED` 预算：三臂 90 次主调用 + ~90 次 judge（flash 裁判），预估 < ¥5，红线 ¥50 内

## 验收标准

| # | 标准（独立可判定） |
|---|------|
| AC1 | 评测集存在且合法：`data/eval_set.csv` 30 条，字段含 id/question/难度/可答性/期望行为/标准答案要点/类型；配比典型 21 + 边界 6 + 对抗 3（70/20/10） |
| AC2 | eval.py 可运行：读评测集 → 分别以 flash/pro/route 三臂各跑 30 条 → 输出 `docs/eval-report-w3.md`，含各臂总成本、平均质量分、路由准确率、拒答正确率 |
| AC3 | 报告可读：能直接读出"路由 vs 全 pro 省 X% 成本、质量差 Y 分、路由准确率 Z%" |
| AC4 | 可复现：temperature=0、报告记录模型名与价格核验日期 |
| AC5 | 回归：三臂均 0 瞎编（faithful=false 的应回答用例数为 0），定价题（Sonnet 4 / Gemini 到期）三臂都答对 |
