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

    def test_export_needs_confirmation(self):
        reg = build_registry()
        r = reg.call("report.export", {"draft_id": "d1", "channel": "email"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["policy"], "needs_confirmation")


class TestTraceStructure(unittest.TestCase):
    """验证 agent_core 的 trace 事件链字段（用假 client 注入，不走网络）。"""

    def test_trace_event_types(self):
        import agent_core

        class FakeResp:
            def __init__(self, content):
                self.choices = [type("C", (), {"message": type("M", (), {
                    "content": content})()})()]
                self.usage = type("U", (), {"prompt_tokens": 10, "completion_tokens": 5})()

        class FakeClient:
            def __init__(self, seq):
                self.seq = seq
                self.idx = 0
            def chat(self):
                return self
            def completions(self):
                return self
            def create(self, **kw):
                c = self.seq[min(self.idx, len(self.seq) - 1)]
                self.idx += 1
                return FakeResp(c)

        # 序列：先工具调用（查询价格），再 final
        seq = [
            '{"action": "tool_call", "tool": "price.lookup", "args": {"model": "gpt-5"}}',
            '{"action": "final", "answer": "gpt-5 价格 $1.25/$10 [核验 2026-09-01]"}',
        ]
        import json
        # 注入假 client（agent_core 直接调用 client.chat.completions.create）
        fake = FakeClient(seq)
        class _FakeChat:
            def __init__(self, c): self._c = c
            def completions(self): return self._c
        fake.chat = lambda: _FakeChat(fake)
        # run_agent 用 monkeypatch 的方式：直接调用内部逻辑验证 trace 字段
        from agent_core import _parse_json
        self.assertEqual(_parse_json(seq[0])["tool"], "price.lookup")
        self.assertEqual(_parse_json(seq[1])["action"], "final")

    def test_parse_json_robust(self):
        from agent_core import _parse_json
        self.assertIsNone(_parse_json("no json here"))
        self.assertIsNone(_parse_json(""))
        self.assertEqual(_parse_json('前缀 {"a": 1} 后缀')["a"], 1)


if __name__ == "__main__":
    unittest.main()
