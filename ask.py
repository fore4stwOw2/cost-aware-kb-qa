"""
命令行问答：和 app.py 走同一条 qa_core 管线（非流式）。
用途：自动测试、批量验收、W3 评测脚本的地基。
用法：.venv/bin/python ask.py "问题1" "问题2" ...
"""
import os
import sys

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
import qa_core  # noqa: E402


def main() -> None:
    questions = sys.argv[1:]
    if not questions:
        print('用法: .venv/bin/python ask.py "问题1" "问题2" ...')
        return

    client = OpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL") or None,
    )
    index = qa_core.load_index()
    embedder = qa_core.load_embedder()

    total_cost = 0.0
    for q in questions:
        r = qa_core.answer_question(client, embedder, index, q)
        total_cost += r["cost"]
        print("=" * 72)
        print("Q:", q)
        print("检索:", "、".join(f"{x['source']}({x['score']:.2f})" for x in r["refs"]))
        if r["refused"]:
            print("→ [拒答]", r["reply"])
        else:
            print("A:", r["reply"])
            u = r["usage"]
            est = "（估算）" if u["estimated"] else ""
            print(f"[tokens] 入 {u['p']} / 出 {u['c']}{est}   [成本] ${r['cost']:.4f}")
    print("=" * 72)
    print(f"本轮 {len(questions)} 题合计成本: ${total_cost:.4f}")


if __name__ == "__main__":
    main()
