"""
命令行问答：和 app.py 走同一条 qa_core 管线。
用法：
  .venv/bin/python ask.py "问题1" "问题2" ...          # 默认按 config.ROUTE_MODE
  .venv/bin/python ask.py --mode flash "问题"           # 固定便宜档
  .venv/bin/python ask.py --mode pro   "问题"           # 固定贵档
  .venv/bin/python ask.py --mode route "问题"           # 路由模式（W2 核心）
  .venv/bin/python ask.py --threshold 0.5 "问题"        # 覆盖拒答阈值（Verifier 用）
"""
import argparse
import json
import os
import socket
import sys

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
import config  # noqa: E402
import qa_core  # noqa: E402

# OS 级 socket 超时：对 SDK 未覆盖的裸 socket 调用兜底（W5 演示稳定化）
# 注意：httpx 客户端自带 socket 管理，不读此默认值；真正兜底靠
#   ① OpenAI client timeout + 每次 create 的 timeout=config.API_TIMEOUT
#   ② 演示脚本 scripts/demo_path.sh 的 killpg 进程组强杀（60s/路径，已验证）
socket.setdefaulttimeout(config.API_TIMEOUT)


def _fmt_route_info(r: dict) -> str:
    info = r["route_info"]
    parts = [f"模式={info['mode']}"]
    if r.get("status") == "error":
        parts.append("❌ 故障（所有模型调用失败）")
    elif r["refused"]:
        parts.append(f"拒答({info.get('answerable', '-')})")
        if r.get("refuse_reason"):
            parts.append(f"原因={r['refuse_reason']}")
    else:
        parts.append(f"难度={info.get('difficulty', '-')} 可答性={info.get('answerable', '-')}")
        parts.append(f"选档={info.get('chosen_model', '-')} 实际={info.get('used_model', '-')}")
        if info.get("reason"):
            parts.append(f"理由={info['reason']}")
        if info.get("degraded"):
            parts.append("⚠️降级运行")
    if info.get("classify_error"):
        parts.append(f"分类器异常={info['classify_error']}")
    return " | ".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description="成本感知知识库问答 · 命令行")
    parser.add_argument("questions", nargs="*", help="要问的问题，可多个")
    parser.add_argument("--mode", choices=["flash", "pro", "route"], default=None,
                        help="路由模式：flash/pro/route（默认读 config.ROUTE_MODE）")
    parser.add_argument("--threshold", type=float, default=None,
                        help="覆盖拒答阈值（默认为 config.SIM_THRESHOLD）")
    parser.add_argument("--agent", default=None,
                        help="Agent 任务：传入任务描述（如'帮我测算用 deepseek-v4-flash 做客服问答的月成本，DAU 1万'）")
    parser.add_argument("--auto-confirm", action="store_true",
                        help="Agent 高风险动作自动确认（供自动化测试/Verifier 用）")
    args = parser.parse_args()

    client = OpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL") or None,
        timeout=config.API_TIMEOUT,
    )

    if args.agent:
        import agent_core

        def _confirm(card):
            if args.auto_confirm:
                print(f"  ✅ 自动确认高风险动作: {card['action']}")
                return True
            ans = input(f"  ⚠️ 确认执行 {card['action']}？（对象: {card['object'][:60]}）[y/N] ")
            return ans.strip().lower() in ("y", "yes")

        print("=" * 72)
        print("🤖 Agent 任务:", args.agent)
        r = agent_core.run_agent(client, args.agent, confirm_callback=_confirm)
        print(f"状态: {r['status']} | 轮数: {r['turns']} | 成本: ${r['total_cost']:.4f}")
        if r.get("card"):
            print("  📋 确认卡:", json.dumps(r["card"], ensure_ascii=False)[:200])
        for ev in r["trace"]:
            if ev["type"] == "tool_call":
                print(f"  🔧 t{ev['turn']} {ev['tool']} ok={ev['ok']} {ev['result_summary'][:80]}")
            elif ev["type"] == "policy_check":
                print(f"  🛡️ 策略: {ev['policy']} {ev.get('detail', '')[:80]}")
            elif ev["type"] == "model_turn" and "error" in ev:
                print(f"  ❌ 模型调用失败 t{ev['turn']}: {ev['error'][:150]}")
        if r["answer"]:
            print("A:", r["answer"])
        return

    index = qa_core.load_index()
    embedder = qa_core.load_embedder()

    mode = args.mode or os.getenv("ROUTE_MODE", "route")
    total_cost = 0.0
    for q in args.questions:
        r = qa_core.answer_question(client, embedder, index, q, mode=mode, threshold=args.threshold)
        total_cost += r["cost"]
        print("=" * 72)
        print("Q:", q)
        print("🧭", _fmt_route_info(r))
        if r["refused"]:
            print("→ [拒答]", r["reply"])
            if r["usage"]:
                u = r["usage"]
                print(f"[路由开销] 入 {u.get('p',0)} / 出 {u.get('c',0)}   [成本] ${r['cost']:.4f}")
        elif r.get("status") == "error":
            print("→ [❌ 故障]", r["reply"])
            if r["usage"]:
                u = r["usage"]
                print(f"[已发生路由开销] 入 {u.get('p',0)} / 出 {u.get('c',0)}   [成本] ${r['cost']:.4f}")
        else:
            print("A:", r["reply"])
            u = r["usage"]
            est = "（估算）" if u.get("estimated") else ""
            extra = f"（含路由 {u.get('route_p',0)}入/{u.get('route_c',0)}出）" if u.get("route_p") else ""
            print(f"[tokens] 入 {u['p']} / 出 {u['c']}{est}{extra}   [成本] ${r['cost']:.4f}")
    print("=" * 72)
    print(f"本轮 {len(args.questions)} 题合计成本: ${total_cost:.4f}")


if __name__ == "__main__":
    main()
