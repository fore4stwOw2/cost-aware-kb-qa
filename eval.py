"""
W3 评测脚本：三臂对比（flash / pro / route）
读 data/eval_set.csv → 各臂跑全部用例 → LLM-as-Judge 评分 → 输出 docs/eval-report-w3.md

用法：
  .venv/bin/python eval.py            # 跑全部三臂（约 90 次主调用 + 评分）
  .venv/bin/python eval.py --mode flash   # 只跑某一臂（快速调试）
"""
import argparse
import csv
import json
import os
import re
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
import config  # noqa: E402
import qa_core  # noqa: E402

EVAL_PATH = Path(config.ROOT) / "data" / "eval_set.csv"
REPORT_PATH = Path(config.ROOT) / "docs" / "eval-report-w3.md"
CACHE_PATH = Path(config.ROOT) / "data" / "eval_cache.json"   # 原始回答缓存（judge 升级后只重判不重跑）
JUDGE_MODEL = config.PREMIUM_MODEL  # 裁判用贵档，评分更可靠


def load_eval() -> list[dict]:
    rows = []
    with open(EVAL_PATH, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


# ---------- 结果缓存（支持 judge 升级后只重判不重跑主调用） ----------
def save_cache(arms: list[dict]) -> None:
    import json as _json
    # 合并进已有缓存（支持并行跑三臂：每个进程保存自己那臂，不互相覆盖）
    existing = load_cache() if CACHE_PATH.exists() else []
    merged = {a["mode"]: a for a in existing}
    for a in arms:
        merged[a["mode"]] = a
    data = {
        "meta": {
            "date": date.today().isoformat(),
            "flash": config.CHEAP_MODEL, "pro": config.PREMIUM_MODEL,
            "judge": JUDGE_MODEL, "price_verified": config.PRICE_VERIFIED_DATE,
        },
        "arms": [
            {
                "mode": a["mode"],
                "rows": [{"id": x["id"], "question": x["question"], "behavior": x["behavior"],
                          "refused": x["refused"], "reply": x["reply"], "cost": x["cost"],
                          "refs": x.get("refs", []),
                          "route_label": x["route_label"], "gold": x["gold"],
                          "judge": x["judge"]} for x in a["rows"]],
            }
            for a in merged.values()
        ],
    }
    CACHE_PATH.write_text(_json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_cache() -> list[dict]:
    import json as _json
    data = _json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return data["arms"]


# ---------- LLM-as-Judge（v4：对照引用片段 + 对照答案要点判完整性） ----------
# v3 教训：只判"是否 grounded / 是否编造"，导致"有依据但只答了一半"的回答也拿满分，
# 三臂质量分全部 5.0，丧失区分度。v4 增加 completeness 维度，对照答案要点判答全没有。
JUDGE_MODEL = config.CLASSIFY_MODEL  # 裁判用便宜档控制成本
_JUDGE_PROMPT = """你是评测裁判（事实核对员）。请对照「引用片段」和「答案要点」核对「AI回答」，判断四件事，只输出 JSON：
{"answerable": true/false, "fabricated": true/false, "grounded": true/false, "complete": true/false, "note": "一句话"}

判定规则：
1. answerable：AI回答是否正面回答了用户问题。答非所问/回避问题 = false。
2. fabricated：AI回答是否编造了「引用片段」里没有的数字、价格、事实。
   - AI 诚实说"引用片段中没有相关内容/资料不足" = 不算编造（fabricated=false）。
   - 引用片段里有的信息，即使 AI 额外展开，也不算编造。
3. grounded：AI回答是否基于引用片段作答（内容与引用一致，或诚实地承认资料不足）。凭空发挥、无依据断言 = false。
4. complete：AI回答是否覆盖了「答案要点」里的关键信息。
   - 只答出一部分要点（如只给了输入价没给输出价、只给了结论没给数字） = false。
   - 明确说"资料不足无法给出完整答案"时：若该信息确实不在引用片段中，视为 complete=true（诚实>硬凑）。
只输出 JSON。"""


def _parse_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _score_from_verdict(v: dict) -> int:
    """把裁判四判断折算成 0-5 质量分（人工口径）。"""
    if v["fabricated"]:
        return 0          # 编造 = 最严重
    if not v["answerable"]:
        return 1          # 答非所问
    if not v["complete"]:
        return 3          # 有依据但没答全
    if v["grounded"]:
        return 5          # 有依据、答全、正面回答
    return 3              # 有回答但依据存疑


def judge_answer(client, question: str, answer_key: str, reply: str, refs: list[dict]) -> dict:
    """refs: 该问题检索到的引用片段列表（来自 qa_core.retrieve）。"""
    context = "\n\n".join(
        f"[{i}] （来源：{r['source']}）\n{r['text'][:600]}" for i, r in enumerate(refs, 1)
    )
    user_msg = f"用户问题：{question}\n答案要点：{answer_key}\n引用片段：\n{context}\n\nAI回答：{reply}"
    # 解析失败时重试一次（推理型模型偶尔思考 token 吃掉输出预算导致截断）
    for attempt in range(2):
        try:
            resp = client.chat.completions.create(
                model=JUDGE_MODEL,
                messages=[
                    {"role": "system", "content": _JUDGE_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0,
                max_tokens=600,
            )
            parsed = _parse_json(resp.choices[0].message.content or "")
            if parsed is None:
                continue  # 重试
            verdict = {
                "answerable": bool(parsed.get("answerable", True)),
                "fabricated": bool(parsed.get("fabricated", False)),
                "grounded": bool(parsed.get("grounded", True)),
                "complete": bool(parsed.get("complete", True)),
                "note": parsed.get("note", ""),
            }
            # faithful 兼容旧字段名：编造才算是"瞎编"
            return {"score": _score_from_verdict(verdict), "faithful": not verdict["fabricated"],
                    "note": verdict["note"], "verdict": verdict}
        except Exception as e:
            last_err = e
    return {"score": 3, "faithful": True, "note": f"裁判调用失败：{last_err if 'last_err' in dir() else '两次均解析失败'}"}


# ---------- 单臂评测 ----------
def run_arm(client, embedder, index, rows, mode: str) -> dict:
    results = []
    total_cost = 0.0
    route_correct = 0
    route_total = 0
    refuse_correct = 0
    refuse_total = 0
    faithful_fail = 0

    for row in rows:
        q = row["question"]
        r = qa_core.answer_question(client, embedder, index, q, mode=mode)
        total_cost += r["cost"]
        info = r["route_info"]
        print(f"  [{mode}] {row['id']} 完成, 成本=${r['cost']:.4f}", flush=True)
        print(f"[{mode}] {row['id']} 完成 成本=${r['cost']:.4f}", flush=True)

        # 拒答正确性（只看期望 refute 的用例）
        if row["behavior"] == "refuse":
            refuse_total += 1
            if r["refused"]:
                refuse_correct += 1

        # 路由准确率（route 臂：分类标签 vs 金标准）
        if mode == "route" and not r["refused"] and info.get("difficulty") and info.get("answerable"):
            route_total += 1
            if info["difficulty"] == row["difficulty"] and info["answerable"] == row["answerable"]:
                route_correct += 1

        # 质量评分：只评"应回答"用例
        judge = None
        if row["behavior"] == "respond":
            if r["refused"]:
                judge = {"score": 0, "faithful": False, "note": "该答但被拒答"}
            else:
                judge = judge_answer(client, q, row["answer_key"], r["reply"], r["refs"])
            if not judge["faithful"]:
                faithful_fail += 1

        results.append({
            "id": row["id"], "question": q, "behavior": row["behavior"],
            "refused": r["refused"], "reply": r["reply"],   # 存完整回复（重判需要全文）
            "refs": [{"source": x["source"], "text": x["text"][:600]} for x in r["refs"]],  # 供 v3 重判
            "judge": judge, "cost": r["cost"],
            "route_label": f"{info.get('difficulty','-')}/{info.get('answerable','-')}" if mode == "route" else "-",
            "gold": f"{row['difficulty']}/{row['answerable']}",
        })

    respond_rows = [x for x in results if x["judge"] is not None]
    avg_quality = sum(x["judge"]["score"] for x in respond_rows) / len(respond_rows) if respond_rows else 0.0
    return {
        "mode": mode,
        "rows": results,
        "total_cost": total_cost,
        "avg_quality": round(avg_quality, 2),
        "route_acc": round(route_correct / route_total, 3) if route_total else None,
        "refuse_acc": round(refuse_correct / refuse_total, 3) if refuse_total else None,
        "faithful_fail": faithful_fail,
        "count": len(results),
    }


# ---------- 报告 ----------
def render_report(arms: list[dict], cost_baseline: float) -> str:
    lines = []
    lines.append(f"# W3 三臂对比评测报告")
    lines.append(f"\n> 生成日期：{date.today().isoformat()} ｜ 评测集：`data/eval_set.csv` 30 条（21 典型 + 6 边界 + 3 对抗）")
    lines.append(f"> 模型：flash=`{config.CHEAP_MODEL}` pro=`{config.PREMIUM_MODEL}` 裁判=`{JUDGE_MODEL}`")
    lines.append(f"> 价格核验日期：{config.PRICE_VERIFIED_DATE} ｜ 温度=0")
    lines.append("\n## 总览")
    lines.append("| 臂 | 总成本 | 平均质量分(0-5) | 路由准确率 | 拒答正确率 | 瞎编数 |")
    lines.append("|----|--------|----------------|-----------|-----------|--------|")
    for a in arms:
        lines.append(
            f"| {a['mode']} | ${a['total_cost']:.4f} | {a['avg_quality']:.2f} | "
            f"{a['route_acc'] if a['route_acc'] is not None else '-'} | "
            f"{a['refuse_acc'] if a['refuse_acc'] is not None else '-'} | {a['faithful_fail']} |"
        )
    route_arm = next((a for a in arms if a["mode"] == "route"), None)
    pro_arm = next((a for a in arms if a["mode"] == "pro"), None)
    if route_arm and pro_arm and pro_arm["total_cost"] > 0:
        save_pct = (1 - route_arm["total_cost"] / pro_arm["total_cost"]) * 100
        quality_drop = pro_arm["avg_quality"] - route_arm["avg_quality"]
        lines.append(
            f"\n**核心结论：路由 vs 全 pro → 省 {save_pct:.1f}% 成本，质量差 {quality_drop:.2f} 分"
            f"（路由准确率 {route_arm['route_acc']}）**"
        )
    lines.append("\n## 明细（route 臂）")
    lines.append("| id | 问题 | 金标准 | 路由判定 | 拒答 | 质量分 | faithful |")
    lines.append("|----|------|--------|---------|------|--------|----------|")
    for x in route_arm["rows"]:
        j = x["judge"]
        lines.append(
            f"| {x['id']} | {x['question'][:28]} | {x['gold']} | {x['route_label']} | "
            f"{'✅' if x['refused'] else '❌'} | {j['score'] if j else '-'} | {j['faithful'] if j else '-'} |"
        )
    return "\n".join(lines)


# ---------- 聚合指标（从行结果算出，供渲染和缓存重放共用） ----------
def compute_arm(mode: str, rows: list[dict]) -> dict:
    total_cost = sum(x["cost"] for x in rows)
    respond_rows = [x for x in rows if x["judge"] is not None]
    avg_quality = sum(x["judge"]["score"] for x in respond_rows) / len(respond_rows) if respond_rows else 0.0
    route_correct = sum(1 for x in rows if x["route_label"] != "-" and x["route_label"] == x["gold"])
    route_total = sum(1 for x in rows if x["route_label"] != "-")
    refuse_correct = sum(1 for x in rows if x["behavior"] == "refuse" and x["refused"])
    refuse_total = sum(1 for x in rows if x["behavior"] == "refuse")
    faithful_fail = sum(1 for x in rows if x["judge"] is not None and not x["judge"]["faithful"])
    return {
        "mode": mode, "rows": rows, "total_cost": total_cost,
        "avg_quality": round(avg_quality, 2),
        "route_acc": round(route_correct / route_total, 3) if route_total else None,
        "refuse_acc": round(refuse_correct / refuse_total, 3) if refuse_total else None,
        "faithful_fail": faithful_fail, "count": len(rows),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="W3 三臂对比评测")
    parser.add_argument("--mode", choices=["flash", "pro", "route"], default=None,
                        help="只跑某一臂（默认跑全部三臂）")
    parser.add_argument("--rejudge", action="store_true",
                        help="加载缓存，只重跑 judge 评分（不重跑主模型调用），再重写报告")
    args = parser.parse_args()

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), base_url=os.getenv("OPENAI_BASE_URL") or None)
    rows = load_eval()

    if args.rejudge:
        if not CACHE_PATH.exists():
            raise SystemExit("❌ 没有缓存，先正常跑一遍 eval.py")
        arms = load_cache()
        # 用当前（可能是 v2）judge 重判所有应回答用例
        embedder = qa_core.load_embedder()
        index = qa_core.load_index()
        by_id = {r["id"]: r for r in rows}
        for arm in arms:
            print(f"--- 重判 {arm['mode']} 臂 ---", flush=True)
            for x in arm["rows"]:
                if x["behavior"] != "respond":
                    x["judge"] = None
                    continue
                src = by_id[x["id"]]
                x["judge"] = judge_answer(client, src["question"], src["answer_key"],
                                          x["reply"], x.get("refs", []))
                print(f"  [{arm['mode']}] {x['id']} 重判完成", flush=True)
        arms = [compute_arm(a["mode"], a["rows"]) for a in arms]
        save_cache(arms)
    else:
        embedder = qa_core.load_embedder()
        index = qa_core.load_index()
        print(f"评测集：{len(rows)} 条", flush=True)
        modes = [args.mode] if args.mode else ["flash", "pro", "route"]
        arms = []
        for mode in modes:
            print(f"--- 跑 {mode} 臂 ---", flush=True)
            arm = run_arm(client, embedder, index, rows, mode)
            # run_arm 已含聚合字段；这里用 compute_arm 统一口径并去重数据
            arms.append(compute_arm(mode, arm["rows"]))
            save_cache(arms)
        save_cache(arms)

    report = render_report(arms, cost_baseline=arms[0]["total_cost"] if arms else 0)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(report, flush=True)
    print(f"\n报告已写入 {REPORT_PATH}", flush=True)


if __name__ == "__main__":
    main()
