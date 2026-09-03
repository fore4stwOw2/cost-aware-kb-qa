"""
Agent 最小循环（B1）：planning → tool_call → tool_result → observe → final。
产出结构化 trace（工具序列/每步成本/引用/预算触顶），供 B2 确认闸门与 B3 轨迹评测复用。
原则：预算触顶即 blocked，不静默继续；黑名单/校验失败记入 trace 的 policy 字段。
"""
import json
import os
import re
import time
import uuid

from openai import OpenAI

import config
import qa_core
from tools import build_registry

# 规划提示词：要求模型每次输出严格 JSON——要么调用工具，要么给出最终回答。
# few-shot 固定格式，减少解析失败（wiki：planning 提示词用 few-shot 固定工具选择格式）
_PLANNER_PROMPT = """你是「模型选型测算助手」。用户给你一个选型/成本测算任务，你可以调用工具获取信息，最后给出带依据的回答。

每次只输出一行 JSON，二选一：
1) 需要更多信息时：
{"action": "tool_call", "tool": "<工具名>", "args": {...}}
2) 信息足够时：
{"action": "final", "answer": "<最终回答，必须引用工具返回的具体数字和来源>"}

可用工具：
{tools_json}

规则：
- 不要编造价格或数字，必须通过工具获取（price.lookup / cost.estimate / kb.search）
- 一次只调用一个工具，等待结果后再决定下一步
- 预算或轮数到顶时必须停止并给出"已完成/未完成"说明
- 只输出 JSON，不要输出其他文字"""


def _parse_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def run_agent(client: OpenAI, task: str, max_turns: int | None = None,
              max_cost: float | None = None) -> dict:
    """执行一次 Agent 任务。返回 {status, answer, trace, total_cost, turns}。
    status: succeeded / blocked（预算触顶）/ needs_confirmation（需人工确认）/ failed"""
    max_turns = config.AGENT_MAX_TURNS if max_turns is None else max_turns
    max_cost = config.AGENT_MAX_COST if max_cost is None else max_cost
    registry = build_registry()
    task_id = uuid.uuid4().hex[:8]
    t0 = time.time()
    trace: list[dict] = []
    total_cost = 0.0
    model = config.AGENT_MODEL

    trace.append({"type": "task", "task_id": task_id, "task": task,
                  "max_turns": max_turns, "max_cost": max_cost, "ts": t0})

    messages = [
        {"role": "system", "content": _PLANNER_PROMPT.replace(
            "{tools_json}", json.dumps(registry.schemas_for_llm(), ensure_ascii=False))},
        {"role": "user", "content": task},
    ]

    for turn in range(1, max_turns + 1):
        # ---- 预算闸门（进入下一轮前检查）----
        if total_cost >= max_cost:
            trace.append({"type": "policy_check", "policy": "budget_cost",
                          "detail": f"累计成本 ${total_cost:.4f} ≥ 上限 ${max_cost}"})
            return {"status": "blocked", "answer": None,
                    "trace": trace, "total_cost": round(total_cost, 4), "turns": turn - 1}

        # ---- 模型规划（失败重试一次，避免偶发网络/解析抖动） ----
        parsed = None
        content = ""
        reasoning_content = None
        usage = {"p": 0, "c": 0}
        last_err = None
        for _attempt in range(2):
            try:
                resp = client.chat.completions.create(
                    model=model, messages=messages, temperature=0,
                    timeout=config.API_TIMEOUT,
                    extra_body={"reasoning_effort": "low"},  # 降推理：省成本+减少 thinking 波动
                )
                msg = resp.choices[0].message
                content = msg.content or ""
                reasoning_content = getattr(msg, "reasoning_content", None)
                usage = {"p": resp.usage.prompt_tokens, "c": resp.usage.completion_tokens}
                parsed = _parse_json(content)
                if parsed is not None:
                    break
                last_err = "输出非 JSON，重试"
            except Exception as e:
                last_err = str(e)
        if parsed is None:
            trace.append({"type": "model_turn", "turn": turn, "error": last_err or "两次均失败"})
            return {"status": "failed", "answer": None,
                    "trace": trace, "total_cost": round(total_cost, 4), "turns": turn - 1}

        turn_cost = qa_core.calc_cost(model, usage["p"], usage["c"])
        total_cost += turn_cost
        trace.append({"type": "model_turn", "turn": turn, "model": model,
                      "tokens": usage, "cost": round(turn_cost, 6)})

        # ---- 最终回答 ----
        if parsed.get("action") == "final":
            answer = parsed.get("answer", "")
            trace.append({"type": "final_result", "turn": turn, "answer": answer[:200]})
            return {"status": "succeeded", "answer": answer,
                    "trace": trace, "total_cost": round(total_cost, 4), "turns": turn}

        # ---- 工具调用 ----
        if parsed.get("action") != "tool_call":
            trace.append({"type": "policy_check", "policy": "bad_action",
                          "detail": f"未知 action: {parsed.get('action')}"})
            return {"status": "failed", "answer": None,
                    "trace": trace, "total_cost": round(total_cost, 4), "turns": turn}

        tool_name = parsed.get("tool", "")
        args = parsed.get("args", {})
        try:
            result = registry.call(tool_name, args)
        except Exception as e:  # 工具执行异常不允许穿透 run_agent（Reviewer 🔴-2）
            result = {"ok": False, "error": f"工具执行异常: {e}", "policy": "handler_error"}
        trace.append({
            "type": "tool_call", "turn": turn, "tool": tool_name,
            "args_summary": json.dumps(args, ensure_ascii=False)[:200],
            "ok": result["ok"], "policy": result.get("policy", ""),
            "result_summary": json.dumps(result.get("data") or result.get("error"),
                                         ensure_ascii=False)[:300],
        })

        # 需人工确认：B1 无确认闸门，停止循环避免空耗预算（Reviewer 🟡-5）
        if result.get("policy") == "needs_confirmation":
            trace.append({"type": "policy_check", "policy": "needs_confirmation",
                          "detail": f"工具 {tool_name} 需人工确认（B2 实现），本次停止"})
            return {"status": "needs_confirmation", "answer": None,
                    "trace": trace, "total_cost": round(total_cost, 4), "turns": turn}

        # OpenAI 兼容协议：assistant 消息必须带 tool_calls，tool 消息回 tool_call_id
        tool_call_id = f"call_{task_id}_{turn}"
        assistant_msg = {
            "role": "assistant",
            "content": content,
            "reasoning_content": reasoning_content or "",  # DeepSeek thinking 模式：字段必须始终存在
            "tool_calls": [{
                "id": tool_call_id,
                "type": "function",
                "function": {"name": tool_name,
                             "arguments": json.dumps(args, ensure_ascii=False)},
            }],
        }
        messages.append(assistant_msg)
        messages.append({"role": "tool", "tool_call_id": tool_call_id,
                         "content": json.dumps(result, ensure_ascii=False)})

        # 参数/schema 错误：不盲目重试，回给模型修正（错误信息已在 tool 消息中）

    # 轮数触顶
    trace.append({"type": "policy_check", "policy": "budget_turns",
                  "detail": f"达到最大轮数 {max_turns}"})
    return {"status": "blocked", "answer": None,
            "trace": trace, "total_cost": round(total_cost, 4), "turns": max_turns}
