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
import os
import sys

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
import qa_core  # noqa: E402


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
    parser.add_argument("questions", nargs="+", help="要问的问题，可多个")
    parser.add_argument("--mode", choices=["flash", "pro", "route"], default=None,
                        help="路由模式：flash/pro/route（默认读 config.ROUTE_MODE）")
    parser.add_argument("--threshold", type=float, default=None,
                        help="覆盖拒答阈值（默认为 config.SIM_THRESHOLD）")
    args = parser.parse_args()

    client = OpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL") or None,
    )
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
