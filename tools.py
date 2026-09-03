"""
Agent 工具层（B1）：工具注册表 + 服务端 Schema 校验 + 风险分级 + 黑名单拒绝。
原则（wiki guardrails-and-agent-security）：
- 鉴权与参数校验必须在服务端执行，不依赖模型自觉（模型决定调用 ≠ 已授权）
- 黑名单工具任何调用一律拒绝并记入 trace
- 只读/可逆/不可逆 三级风险标记，供 B2 确认闸门使用
"""
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import config

RISK_LOW = "low"        # 只读
RISK_MEDIUM = "medium"  # 可逆写入（草稿）
RISK_HIGH = "high"      # 不可逆/对外副作用（需人工确认）

BLACKLIST = {"refund.create"}


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict          # JSON Schema 子集：properties/required/types/enum
    risk: str
    side_effect: str            # none / draft / dry_run_export
    idempotent: bool
    handler: Callable[[dict], dict]
    deny_reason: str = ""


def _validate(schema: dict, args: dict) -> str | None:
    """返回错误信息；None 表示通过。"""
    props = schema.get("properties", {})
    for req in schema.get("required", []):
        if req not in args:
            return f"缺少必填参数: {req}"
    for key, val in args.items():
        spec = props.get(key)
        if spec is None:
            return f"未知参数: {key}"
        if spec.get("type") == "string" and not isinstance(val, str):
            return f"参数 {key} 应为字符串"
        if spec.get("type") == "number":
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                return f"参数 {key} 应为数字"
            if "minimum" in spec and val < spec["minimum"]:
                return f"参数 {key} 小于下限 {spec['minimum']}"
        if spec.get("type") == "integer":
            if not isinstance(val, int) or isinstance(val, bool):
                return f"参数 {key} 应为整数"
            if "minimum" in spec and val < spec["minimum"]:
                return f"参数 {key} 小于下限 {spec['minimum']}"
        if "enum" in spec and val not in spec["enum"]:
            return f"参数 {key} 不在允许值内: {spec['enum']}"
    return None


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_names(self) -> list[str]:
        return sorted(self._tools.keys())

    def schemas_for_llm(self) -> list[dict]:
        """给 LLM 的工具描述（不含 handler）。"""
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
                "risk": t.risk,
                "side_effect": t.side_effect,
            }
            for t in self._tools.values()
        ]

    def call(self, name: str, args: dict) -> dict:
        """服务端执行入口：黑名单/存在性/Schema 三重校验后才到 handler。
        返回统一结果结构，trace 可直接记录。"""
        if name in BLACKLIST:
            return {"ok": False, "error": f"工具 {name} 在黑名单中，拒绝执行（服务端策略）",
                    "policy": "blacklist"}
        tool = self._tools.get(name)
        if tool is None:
            return {"ok": False, "error": f"未知工具: {name}", "policy": "unknown_tool"}
        err = _validate(tool.input_schema, args)
        if err:
            return {"ok": False, "error": f"参数校验失败: {err}", "policy": "schema"}
        try:
            result = tool.handler(args)
        except Exception as e:
            return {"ok": False, "error": f"工具执行异常: {e}", "policy": "handler_error"}
        if result is None:  # handler 返回 None = 业务失败（如查无此模型）
            return {"ok": False, "error": f"{name}: 未找到请求的对象（参数需修正）", "policy": "not_found"}
        if isinstance(result, dict) and result.get("policy") == "needs_confirmation":
            return {"ok": False, "error": result.get("error", "需人工确认"),
                    "policy": "needs_confirmation"}
        return {"ok": True, "data": result, "policy": "allowed"}


# ---------- 数据源 ----------
_PRICES = None


def _load_prices() -> dict:
    global _PRICES
    if _PRICES is None:
        path = Path(config.ROOT) / "data" / "prices.json"
        _PRICES = json.loads(path.read_text(encoding="utf-8"))
    return _PRICES


# ---------- 工具实现 ----------
def _kb_search(args: dict) -> dict:
    import qa_core
    index = qa_core.load_index()
    embedder = qa_core.load_embedder()
    refs = qa_core.retrieve(index, embedder, args["query"], top_k=args.get("top_k", 3))
    return {"refs": [{"source": r["source"], "score": round(r["score"], 3),
                      "snippet": r["text"][:200]} for r in refs]}


def _price_lookup(args: dict) -> dict | None:
    data = _load_prices()
    model = args["model"].lower()
    if model not in data["models"]:
        return None  # registry 会把 None 转成 ok=False
    m = data["models"][model]
    return {
        "model": model, "provider": m["provider"],
        "input_per_million": m["input"], "output_per_million": m["output"],
        "note": m.get("note", ""), "verified_date": data["meta"]["verified_date"],
    }


def _cost_estimate(args: dict) -> dict | None:
    """月成本估算：DAU × 渗透率 × 人均日调用 × 30 × (输入token×单价 + 输出token×单价)。"""
    data = _load_prices()
    model = args["model"].lower()
    if model not in data["models"]:
        return None
    m = data["models"][model]
    dau = args["dau"]
    penetration = args.get("penetration", 0.3)
    calls_per_user_day = args.get("calls_per_user_day", 5)
    input_tokens = args.get("input_tokens", 600)
    output_tokens = args.get("output_tokens", 250)
    days = args.get("days", 30)
    monthly_calls = dau * penetration * calls_per_user_day * days
    cost = monthly_calls * (
        input_tokens / 1e6 * m["input"] + output_tokens / 1e6 * m["output"]
    )
    return {
        "model": model, "monthly_calls": round(monthly_calls),
        "monthly_cost_usd": round(cost, 2),
        "unit_cost_usd": round(input_tokens / 1e6 * m["input"] + output_tokens / 1e6 * m["output"], 6),
        "verified_date": data["meta"]["verified_date"],
    }


def _report_draft(args: dict) -> dict:
    """生成选型报告草稿（可逆，不对外）。B1 先返回结构化草稿骨架。"""
    return {
        "draft_id": f"draft-{abs(hash(args.get('title', ''))) % 100000}",
        "title": args.get("title", "模型选型报告"),
        "status": "draft",
        "note": "草稿已生成，可编辑/撤销；导出需人工确认（B2 实现）",
    }


def _report_export(args: dict) -> dict:
    """高风险工具：B1 阶段返回需确认，实际导出在 B2 经确认卡后 dry-run。"""
    return {"ok": False, "error": "导出需人工确认（确认闸门在 B2 实现），本次未执行任何外发",
            "policy": "needs_confirmation"}


def build_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(Tool(
        name="kb.search",
        description="在知识库中检索与问题相关的文档片段（只读，返回带来源与相似度的片段）",
        input_schema={"type": "object", "required": ["query"],
                      "properties": {"query": {"type": "string"},
                                     "top_k": {"type": "integer", "minimum": 1}}},
        risk=RISK_LOW, side_effect="none", idempotent=True, handler=_kb_search,
    ))
    reg.register(Tool(
        name="price.lookup",
        description="查询指定模型的每百万 token 价格（只读，返回输入/输出单价与核验日期）",
        input_schema={"type": "object", "required": ["model"],
                      "properties": {"model": {"type": "string"}}},
        risk=RISK_LOW, side_effect="none", idempotent=True, handler=_price_lookup,
    ))
    reg.register(Tool(
        name="cost.estimate",
        description="按 DAU/渗透率/人均调用/输入输出 token 估算某模型的月度成本（只读，纯计算）",
        input_schema={"type": "object", "required": ["model", "dau"],
                      "properties": {
                          "model": {"type": "string"},
                          "dau": {"type": "integer", "minimum": 0},
                          "penetration": {"type": "number", "minimum": 0, "maximum": 1},
                          "calls_per_user_day": {"type": "number", "minimum": 0},
                          "input_tokens": {"type": "integer", "minimum": 1},
                          "output_tokens": {"type": "integer", "minimum": 1},
                          "days": {"type": "integer", "minimum": 1},
                      }},
        risk=RISK_LOW, side_effect="none", idempotent=True, handler=_cost_estimate,
    ))
    reg.register(Tool(
        name="report.draft",
        description="生成模型选型报告草稿（可逆，不对外发送，可编辑可撤销）",
        input_schema={"type": "object", "required": ["title"],
                      "properties": {"title": {"type": "string"},
                                     "content": {"type": "string"}}},
        risk=RISK_MEDIUM, side_effect="draft", idempotent=True, handler=_report_draft,
    ))
    reg.register(Tool(
        name="report.export",
        description="导出选型报告（高风险：模拟对外发送，必须人工确认后 dry-run 执行）",
        input_schema={"type": "object", "required": ["draft_id"],
                      "properties": {"draft_id": {"type": "string"},
                                     "channel": {"type": "string", "enum": ["email", "share_link"]}}},
        risk=RISK_HIGH, side_effect="dry_run_export", idempotent=False, handler=_report_export,
    ))
    return reg
