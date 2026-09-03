"""B1 工具层与 Agent 循环的纯函数单测（无网络）。
运行：python -m unittest discover -s tests
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import build_registry, BLACKLIST  # noqa: E402


class TestToolSchema(unittest.TestCase):
    def setUp(self):
        self.reg = build_registry()

    def test_required_missing(self):
        r = self.reg.call("price.lookup", {})
        self.assertFalse(r["ok"])
        self.assertIn("缺少必填参数", r["error"])

    def test_wrong_type_string(self):
        r = self.reg.call("price.lookup", {"model": 123})
        self.assertFalse(r["ok"])
        self.assertIn("应为字符串", r["error"])

    def test_wrong_type_number(self):
        r = self.reg.call("cost.estimate", {"model": "gpt-5", "dau": "十万"})
        self.assertFalse(r["ok"])
        self.assertIn("应为整数", r["error"])

    def test_enum_out_of_range(self):
        r = self.reg.call("report.export", {"draft_id": "d1", "channel": "wechat"})
        self.assertFalse(r["ok"])
        self.assertIn("不在允许值内", r["error"])

    def test_minimum_bound(self):
        r = self.reg.call("cost.estimate", {"model": "gpt-5", "dau": -1})
        self.assertFalse(r["ok"])
        self.assertIn("小于下限", r["error"])

    def test_unknown_tool(self):
        r = self.reg.call("not.a.tool", {})
        self.assertFalse(r["ok"])
        self.assertIn("未知工具", r["error"])

    def test_unknown_param(self):
        r = self.reg.call("price.lookup", {"model": "gpt-5", "hack": True})
        self.assertFalse(r["ok"])
        self.assertIn("未知参数", r["error"])


class TestBlacklist(unittest.TestCase):
    def test_blacklist_contains_refund(self):
        self.assertIn("refund.create", BLACKLIST)

    def test_blacklist_rejected(self):
        reg = build_registry()
        r = reg.call("refund.create", {"amount": 100})
        self.assertFalse(r["ok"])
        self.assertEqual(r["policy"], "blacklist")
        self.assertIn("拒绝执行", r["error"])

    def test_blacklist_not_in_registry(self):
        reg = build_registry()
        self.assertNotIn("refund.create", reg.list_names())


class TestPriceLookup(unittest.TestCase):
    def test_known_model(self):
        reg = build_registry()
        r = reg.call("price.lookup", {"model": "deepseek-v4-flash"})
        self.assertTrue(r["ok"])
        self.assertEqual(r["data"]["input_per_million"], 0.44)
        self.assertEqual(r["data"]["output_per_million"], 1.32)

    def test_unknown_model(self):
        reg = build_registry()
        r = reg.call("price.lookup", {"model": "gpt-99"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["policy"], "not_found")
        self.assertIn("未找到", r["error"])

    def test_verified_date_present(self):
        reg = build_registry()
        r = reg.call("price.lookup", {"model": "claude-sonnet-4"})
        self.assertEqual(r["data"]["verified_date"], "2026-09-01")


class TestCostEstimate(unittest.TestCase):
    def test_known_calculation(self):
        reg = build_registry()
        # DAU 1万 × 渗透率 0.3 × 5次/天 × 30天 = 45万次
        # gpt-5: 600/1e6*1.25 + 250/1e6*10 = 0.00075+0.0025 = 0.00325/次
        r = reg.call("cost.estimate", {"model": "gpt-5", "dau": 10000})
        self.assertTrue(r["ok"])
        self.assertEqual(r["data"]["monthly_calls"], 450000)
        self.assertAlmostEqual(r["data"]["monthly_cost_usd"], 450000 * 0.00325, delta=1)

    def test_zero_dau(self):
        reg = build_registry()
        r = reg.call("cost.estimate", {"model": "gpt-5", "dau": 0})
        self.assertTrue(r["ok"])
        self.assertEqual(r["data"]["monthly_cost_usd"], 0.0)

    def test_unknown_model_in_estimate(self):
        reg = build_registry()
        r = reg.call("cost.estimate", {"model": "nope", "dau": 10})
        self.assertFalse(r["ok"])


class TestReportTools(unittest.TestCase):
    def test_draft_reversible(self):
        reg = build_registry()
        r = reg.call("report.draft", {"title": "选型报告"})
        self.assertTrue(r["ok"])
        self.assertEqual(r["data"]["status"], "draft")

    def test_export_dry_run_receipt(self):
        """B2：report.export 的闸门在 agent_core 层（risk=high）；
        直接调 handler 是 dry-run，返回回执且不真实外发。"""
        reg = build_registry()
        r = reg.call("report.export", {"draft_id": "d1", "channel": "email"})
        self.assertTrue(r["ok"])
        self.assertEqual(r["data"]["status"], "dry_run_export")
        self.assertIn("EXPORT-SIM-", r["data"]["receipt"])

    def test_export_risk_is_high(self):
        reg = build_registry()
        self.assertEqual(reg.get_risk("report.export"), "high")
        self.assertEqual(reg.get_risk("price.lookup"), "low")
        self.assertEqual(reg.get_risk("report.draft"), "medium")


class TestTraceStructure(unittest.TestCase):
    """用假 client 真正跑 run_agent，断言 trace 事件链（Reviewer 🔴-1：原测试是虚假覆盖）。"""

    class FakeMsg:
        def __init__(self, content, reasoning_content=None):
            self.content = content
            self.reasoning_content = reasoning_content

    class FakeResp:
        def __init__(self, content, usage):
            self.choices = [type("C", (), {"message": TestTraceStructure.FakeMsg(content)})()]
            self.usage = type("U", (), {"prompt_tokens": usage[0], "completion_tokens": usage[1]})()

    class FakeCompletions:
        def __init__(self, owner):
            self._owner = owner

        def create(self, **kw):
            seq = self._owner.seq
            i = min(self._owner.idx, len(seq) - 1)
            self._owner.idx += 1
            return TestTraceStructure.FakeResp(seq[i], (10, 5))

    class FakeChat:
        def __init__(self, owner):
            self._owner = owner
            self.completions = TestTraceStructure.FakeCompletions(owner)

    class FakeClient:
        def __init__(self, seq):
            self.seq = seq
            self.idx = 0
            self.chat = TestTraceStructure.FakeChat(self)

    def test_agent_loop_trace_chain(self):
        import agent_core

        # 序列：查价格 → 成本估算 → 最终回答
        seq = [
            '{"action": "tool_call", "tool": "price.lookup", "args": {"model": "gpt-5"}}',
            '{"action": "tool_call", "tool": "cost.estimate", "args": {"model": "gpt-5", "dau": 1000}}',
            '{"action": "final", "answer": "gpt-5 月成本约 $9.75（核验 2026-09-01）"}',
        ]
        r = agent_core.run_agent(self.FakeClient(seq), "测算 gpt-5 月成本 DAU 1000")
        self.assertEqual(r["status"], "succeeded")
        self.assertIn("9.75", r["answer"])

        # trace 事件链必须包含：task → model_turn → tool_call ×2 → final_result
        types = [ev["type"] for ev in r["trace"]]
        self.assertEqual(types[0], "task")
        self.assertIn("model_turn", types)
        self.assertEqual(types.count("tool_call"), 2)
        self.assertEqual(types[-1], "final_result")
        # 工具调用事件必须带 policy 与结果摘要
        tool_evs = [ev for ev in r["trace"] if ev["type"] == "tool_call"]
        self.assertEqual(tool_evs[0]["tool"], "price.lookup")
        self.assertEqual(tool_evs[0]["ok"], True)
        self.assertEqual(tool_evs[0]["policy"], "allowed")

    def test_budget_turns_blocked(self):
        import agent_core
        seq = ['{"action": "tool_call", "tool": "price.lookup", "args": {"model": "gpt-5"}}']
        r = agent_core.run_agent(self.FakeClient(seq), "任务", max_turns=1)
        self.assertEqual(r["status"], "blocked")
        self.assertEqual(r["turns"], 1)
        policies = [ev.get("policy") for ev in r["trace"]]
        self.assertIn("budget_turns", policies)

    def test_blacklist_in_trace(self):
        import agent_core
        # 模型尝试调黑名单工具 → trace 记录 blacklist 策略
        seq = [
            '{"action": "tool_call", "tool": "refund.create", "args": {"amount": 100}}',
            '{"action": "final", "answer": "不应到达这里"}',
        ]
        r = agent_core.run_agent(self.FakeClient(seq), "尝试退款")
        tool_evs = [ev for ev in r["trace"] if ev["type"] == "tool_call"]
        self.assertEqual(tool_evs[0]["ok"], False)
        self.assertEqual(tool_evs[0]["policy"], "blacklist")

    def test_plain_text_final_answer(self):
        """B1 修复：模型输出非 JSON 纯文本时按最终回答处理，不整体 failed（Verifier 复验抓到的模式）。"""
        import agent_core
        seq = ['gpt-5 月成本约 $9.75，deepseek-v4-flash 约 $2.77，核验日期 2026-09-01。']
        r = agent_core.run_agent(self.FakeClient(seq), "测算成本")
        self.assertEqual(r["status"], "succeeded")
        self.assertIn("9.75", r["answer"])
        self.assertEqual(r["trace"][-1]["type"], "final_result")

    def test_empty_output_fails(self):
        import agent_core
        seq = ['']
        r = agent_core.run_agent(self.FakeClient(seq), "任务")
        self.assertEqual(r["status"], "failed")

    def test_confirmation_gate_high_risk_no_callback(self):
        """高风险工具无回调 → needs_confirmation + 确认卡（AC1/AC2）。"""
        import agent_core
        seq = [
            '{"action": "tool_call", "tool": "report.export", "args": {"draft_id": "d1", "channel": "email"}}',
        ]
        r = agent_core.run_agent(self.FakeClient(seq), "导出报告")
        self.assertEqual(r["status"], "needs_confirmation")
        card = r.get("card", {})
        for field in ("action", "object", "scope", "consequence", "reversible", "deny_path"):
            self.assertIn(field, card, f"确认卡缺少字段 {field}")
        # trace 记录 waiting_approval 策略
        policies = [ev.get("policy") for ev in r["trace"]]
        self.assertIn("waiting_approval", policies)

    def test_confirmation_gate_approved(self):
        """用户批准 → 执行 dry-run 并拿到回执，最终 succeeded（AC1）。"""
        import agent_core
        seq = [
            '{"action": "tool_call", "tool": "report.export", "args": {"draft_id": "d1", "channel": "email"}}',
            'gpt-5 报告已导出，回执 EXPORT-SIM-XXX（dry-run）',
        ]
        decisions = []
        r = agent_core.run_agent(self.FakeClient(seq), "导出报告",
                                 confirm_callback=lambda card: decisions.append(True) or True)
        self.assertEqual(r["status"], "succeeded")
        self.assertEqual(decisions, [True])
        policies = [ev.get("policy") for ev in r["trace"]]
        self.assertIn("approved", policies)
        # dry-run 回执应出现在工具结果里
        tool_evs = [ev for ev in r["trace"] if ev["type"] == "tool_call"]
        self.assertIn("EXPORT-SIM-", tool_evs[0]["result_summary"])

    def test_confirmation_gate_denied_cancelled(self):
        """用户拒绝 → cancelled，且不执行副作用（AC1/AC4）。"""
        import agent_core
        seq = [
            '{"action": "tool_call", "tool": "report.export", "args": {"draft_id": "d1", "channel": "email"}}',
        ]
        r = agent_core.run_agent(self.FakeClient(seq), "导出报告",
                                 confirm_callback=lambda card: False)
        self.assertEqual(r["status"], "cancelled")
        # 拒绝后不应有已执行的 tool_call 事件（副作用未发生）
        tool_evs = [ev for ev in r["trace"] if ev["type"] == "tool_call"]
        self.assertEqual(len(tool_evs), 0)
        policies = [ev.get("policy") for ev in r["trace"]]
        self.assertIn("cancelled", policies)

    def test_low_risk_no_confirmation(self):
        """只读工具自动执行，不触发确认（AC6）。"""
        import agent_core
        seq = [
            '{"action": "tool_call", "tool": "price.lookup", "args": {"model": "gpt-5"}}',
            'gpt-5 价格 $1.25/$10',
        ]
        called = []
        r = agent_core.run_agent(self.FakeClient(seq), "查价格",
                                 confirm_callback=lambda card: called.append(card) or True)
        self.assertEqual(r["status"], "succeeded")
        self.assertEqual(called, [], "只读工具不应触发确认回调")
        policies = [ev.get("policy") for ev in r["trace"]]
        self.assertNotIn("waiting_approval", policies)

    def test_medium_risk_no_confirmation(self):
        """可逆写入（草稿）自动执行，不触发确认（AC6）。"""
        import agent_core
        seq = [
            '{"action": "tool_call", "tool": "report.draft", "args": {"title": "报告"}}',
            '草稿已生成',
        ]
        called = []
        r = agent_core.run_agent(self.FakeClient(seq), "生成草稿",
                                 confirm_callback=lambda card: called.append(card) or True)
        self.assertEqual(r["status"], "succeeded")
        self.assertEqual(called, [], "medium 风险工具不应触发确认回调")
        policies = [ev.get("policy") for ev in r["trace"]]
        self.assertNotIn("waiting_approval", policies)

    def test_budget_cost_blocked(self):
        """费用触顶 → blocked（AC3：budget_cost 路径）。"""
        import agent_core
        seq = [
            '{"action": "tool_call", "tool": "price.lookup", "args": {"model": "gpt-5"}}',
            'gpt-5 价格 $1.25/$10',
        ]
        r = agent_core.run_agent(self.FakeClient(seq), "任务", max_cost=0.000001)
        self.assertEqual(r["status"], "blocked")
        policies = [ev.get("policy") for ev in r["trace"]]
        self.assertIn("budget_cost", policies)

    def test_denied_after_prior_low_risk_no_replay(self):
        """多轮场景：用户先批准 low 工具执行，后拒绝 high 工具 →
        cancelled 且被拒工具无执行事件（AC4：不重放，覆盖多工具序列）。"""
        import agent_core
        seq = [
            '{"action": "tool_call", "tool": "price.lookup", "args": {"model": "gpt-5"}}',
            '{"action": "tool_call", "tool": "report.export", "args": {"draft_id": "d1", "channel": "email"}}',
        ]
        decisions = []
        def cb(card):
            decisions.append(card["action"])
            return card["action"] != "report.export"  # 拒绝 export
        r = agent_core.run_agent(self.FakeClient(seq), "任务", confirm_callback=cb)
        self.assertEqual(r["status"], "cancelled")
        self.assertEqual(decisions, ["report.export"], "low 工具不应触发回调，只有 export 触发")
        tool_evs = [ev for ev in r["trace"] if ev["type"] == "tool_call"]
        self.assertEqual(len(tool_evs), 1, "只应有 price.lookup 执行；export 被拒未执行")
        self.assertEqual(tool_evs[0]["tool"], "price.lookup")
        policies = [ev.get("policy") for ev in r["trace"]]
        self.assertIn("cancelled", policies)

    def test_confirm_callback_exception_handled(self):
        """回调抛异常不穿透 run_agent（Reviewer 🟡-8）。"""
        import agent_core
        seq = [
            '{"action": "tool_call", "tool": "report.export", "args": {"draft_id": "d1", "channel": "email"}}',
        ]
        def bad_cb(card):
            raise RuntimeError("回调崩溃")
        r = agent_core.run_agent(self.FakeClient(seq), "任务", confirm_callback=bad_cb)
        self.assertEqual(r["status"], "failed")

    def test_card_fields_complete(self):
        """确认卡六要素逐字段断言（AC2）。"""
        import agent_core
        seq = [
            '{"action": "tool_call", "tool": "report.export", "args": {"draft_id": "d1", "channel": "email"}}',
        ]
        r = agent_core.run_agent(self.FakeClient(seq), "导出", confirm_callback=None)
        card = r["card"]
        self.assertEqual(card["action"], "report.export")
        self.assertIn("d1", card["object"])
        self.assertIn("dry-run", card["scope"])
        self.assertIn("模拟", card["consequence"])
        self.assertIs(card["reversible"], False)
        self.assertIn("拒绝", card["deny_path"])

    def test_approved_trace_records_dry_run(self):
        """approved 后 trace 中应出现 dry-run 回执（AC1 完整链路）。"""
        import agent_core
        seq = [
            '{"action": "tool_call", "tool": "report.export", "args": {"draft_id": "d1", "channel": "email"}}',
            '已导出',
        ]
        r = agent_core.run_agent(self.FakeClient(seq), "导出", confirm_callback=lambda c: True)
        self.assertEqual(r["status"], "succeeded")
        tool_evs = [ev for ev in r["trace"] if ev["type"] == "tool_call"]
        self.assertEqual(tool_evs[0]["tool"], "report.export")
        self.assertIn("EXPORT-SIM-", tool_evs[0]["result_summary"])
        policies = [ev.get("policy") for ev in r["trace"]]
        self.assertIn("approved", policies)

    def test_parse_json_robust(self):
        from agent_core import _parse_json
        self.assertIsNone(_parse_json("no json here"))
        self.assertIsNone(_parse_json(""))
        self.assertEqual(_parse_json('前缀 {"a": 1} 后缀')["a"], 1)


if __name__ == "__main__":
    unittest.main()
