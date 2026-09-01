"""
W3 评测脚本：三臂对比（flash / pro / route）
读 data/eval_set.csv → 各臂跑全部用例 → LLM-as-Judge 评分 → 输出 docs/eval-report-w3.md

用法：
  .venv/bin/python eval.py            # 跑全部三臂（约 90 次主调用 + 评分）
  .venv/bin/python eval.py --mode flash   # 只跑某一臂（快速调试）
  .venv/bin/python eval.py --rejudge      # 加载缓存，只重判 judge（不重跑主调用）

指标口径（单一事实来源 = compute_arm，由行结果统一计算）：
  - 路由准确率：仅统计 route 模式下「未拒答」（真正被分类）的用例，分类标签==金标准 的比例。
    库外题被阈值/分类器直接拒答 = 正确拒答（计入拒答正确率），不计入路由准确率。
  - 平均质量分：有 judge 判分的用例（respond 已答 + refuse 却硬答的）平均分。
  - 拒答正确率：behavior=refuse 的用例中真正被拒答的比例。
  - 瞎编数：judge 判 fabricated=true 的用例数（编造才是瞎编；"该答却拒答"单列不计入）。
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

# 裁判模型：便宜档（flash）。与 spec 决策记录一致（v4 校准后确认 flash 布尔判定足够且成本可控）。
JUDGE_MODEL = config.CLASSIFY_MODEL

# category → 评测集分桶（21 典型 / 6 边界 / 3 对抗），load_eval 校验用
_TYPICAL_CATS = {"定价", "成本", "术语"}
_BOUNDARY_CATS = {"选型", "长上下文", "长上下文加价"}
_ADVERSARIAL_CATS = {"库外", "越权"}


def load_eval() -> list[dict]:
    rows = []
    required = {"id", "question", "difficulty", "answerable", "behavior", "answer_key", "category"}
    with open(EVAL_PATH, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if not required.issubset(r.keys()):
                raise SystemExit(f"❌ 评测集缺少字段，应有 {sorted(required)}")
            if r["behavior"] not in {"respond", "refuse"}:
                raise SystemExit(f"❌ {r['id']} behavior 非法: {r['behavior']}")
            if r["answerable"] not in {"in_kb", "out_of_kb"}:
                raise SystemExit(f"❌ {r['id']} answerable 非法: {r['answerable']}")
            rows.append(r)
    # 校验 21/6/3 配比
    n_typical = sum(1 for r in rows if r["category"] in _TYPICAL_CATS)
    n_boundary = sum(1 for r in rows if r["category"] in _BOUNDARY_CATS)
    n_adversarial = sum(1 for r in rows if r["category"] in _ADVERSARIAL_CATS)
    print(f"评测集配比：典型 {n_typical} + 边界 {n_boundary} + 对抗 {n_adversarial}（共 {len(rows)} 条）", flush=True)
    return rows


# ---------- 结果缓存（支持 judge 升级后只重判不重跑主调用） ----------
def save_cache(arms: list[dict]) -> None:
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
    CACHE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_cache() -> list[dict]:
    data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return data["arms"]


# ---------- LLM-as-Judge（v4：对照引用片段 + 答案要点，四维判定） ----------
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
    """健壮解析：先整体 loads；失败则找最外层平衡的 {} 再解析（容忍多余前后缀）。"""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    # 去掉可能的 markdown 围栏
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    # 找最外层平衡括号
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except Exception:
                    return None
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
    """refs: 该问题检索到的引用片段列表（来自 qa_core.retrieve）。
    返回 {"score", "faithful", "note", "verdict", "error"}；error=True 表示裁判本身失败（计入披露）。"""
    context = "\n\n".join(
        f"[{i}] （来源：{r['source']}）\n{r['text'][:600]}" for i, r in enumerate(refs, 1)
    )
    user_msg = f"用户问题：{question}\n答案要点：{answer_key}\n引用片段：\n{context}\n\nAI回答：{reply}"
    last_err = None
    for _attempt in range(2):
        try:
            resp = client.chat.completions.create(
                model=JUDGE_MODEL,
                messages=[
                    {"role": "system", "content": _JUDGE_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0,
                max_tokens=800,
                extra_body={"reasoning_effort": "low"},
            )
            parsed = _parse_json(resp.choices[0].message.content or "")
            if parsed is None:
                last_err = "两次均解析失败"
                continue  # 重试
            verdict = {
                "answerable": bool(parsed.get("answerable", True)),
                "fabricated": bool(parsed.get("fabricated", False)),
                "grounded": bool(parsed.get("grounded", True)),
                "complete": bool(parsed.get("complete", True)),
                "note": parsed.get("note", ""),
            }
            return {"score": _score_from_verdict(verdict), "faithful": not verdict["fabricated"],
                    "note": verdict["note"], "verdict": verdict, "error": False}
        except Exception as e:
            last_err = str(e)
    return {"score": 3, "faithful": True, "note": f"裁判调用失败：{last_err}", "verdict": None,
            "error": True}


# ---------- 单臂评测 ----------
def run_arm(client, embedder, index, rows, mode: str) -> list[dict]:
    """跑完一个臂，返回每行结果（不在此聚合，聚合统一走 compute_arm）。"""
    results = []
    for row in rows:
        q = row["question"]
        r = qa_core.answer_question(client, embedder, index, q, mode=mode)
        info = r["route_info"]
        refused = r["refused"]
        # 路由标签：route 模式下只有真正被分类（未拒答）才计入路由准确率分母
        route_label = "-"
        if mode == "route" and not refused and info.get("difficulty") and info.get("answerable"):
            route_label = f"{info['difficulty']}/{info['answerable']}"

        # 判定结果：
        #  respond + 已答        → 正常 judge
        #  respond + 被拒答       → "该答却拒答"（质量 0，但不算瞎编，单列计数）
        #  refuse + 被拒答       → 正确拒答（无质量分）
        #  refuse + 却硬答       → 拒答失误 + 对该回答做瞎编审计（补库外盲区）
        if row["behavior"] == "respond":
            if refused:
                judge = {"score": 0, "faithful": True, "note": "该答但被拒答",
                         "verdict": None, "error": False, "should_answer_refused": True}
            else:
                judge = judge_answer(client, q, row["answer_key"], r["reply"], r["refs"])
        else:  # refuse
            if refused:
                judge = None
            else:
                j = judge_answer(client, q, row["answer_key"], r["reply"], r["refs"])
                # 库外题却硬答：质量分最多 1（答了本不该答的），编造则 0
                judge = {"score": 0 if not j["faithful"] else 1, "faithful": j["faithful"],
                         "note": f"库外题未拒答而硬答；{j['note']}", "verdict": j["verdict"],
                         "error": j["error"], "refuse_miss": True}

        results.append({
            "id": row["id"], "question": q, "behavior": row["behavior"],
            "refused": refused, "reply": r["reply"], "refs": [
                {"source": x["source"], "text": x["text"][:600]} for x in r["refs"]],
            "judge": judge, "cost": r["cost"],
            "route_label": route_label,
            "gold": f"{row['difficulty']}/{row['answerable']}",
        })
        print(f"[{mode}] {row['id']} 完成 成本=${r['cost']:.4f}", flush=True)
    return results


# ---------- 聚合指标（单一事实来源：所有口径在这里统一计算） ----------
def compute_arm(mode: str, rows: list[dict]) -> dict:
    total_cost = sum(x["cost"] for x in rows)

    judged = [x for x in rows if x["judge"] is not None and not x["judge"].get("error")]
    avg_quality = sum(x["judge"]["score"] for x in judged) / len(judged) if judged else 0.0

    route_correct = sum(1 for x in rows if x["route_label"] != "-" and x["route_label"] == x["gold"])
    route_total = sum(1 for x in rows if x["route_label"] != "-")
    refuse_correct = sum(1 for x in rows if x["behavior"] == "refuse" and x["refused"])
    refuse_total = sum(1 for x in rows if x["behavior"] == "refuse")
    # 瞎编 = 裁判判 fabricated 且裁判本身成功；"该答却拒答"单列
    faithful_fail = sum(1 for x in rows if x["judge"] is not None
                        and not x["judge"].get("error") and not x["judge"]["faithful"])
    should_answer_refused = sum(1 for x in rows if x["judge"] is not None
                                and x["judge"].get("should_answer_refused"))
    refuse_miss = sum(1 for x in rows if x["judge"] is not None and x["judge"].get("refuse_miss"))
    judge_failed = sum(1 for x in rows if x["judge"] is not None and x["judge"].get("error"))

    return {
        "mode": mode, "rows": rows, "total_cost": total_cost,
        "avg_quality": round(avg_quality, 2),
        "route_acc": round(route_correct / route_total, 3) if route_total else None,
        "refuse_acc": round(refuse_correct / refuse_total, 3) if refuse_total else None,
        "faithful_fail": faithful_fail,
        "should_answer_refused": should_answer_refused,
        "refuse_miss": refuse_miss,
        "judge_failed": judge_failed,
        "count": len(rows),
    }


# ---------- 报告 ----------
def render_report(arms: list[dict]) -> str:
    # 配比按评测集实际动态计算（避免硬编码与数据漂移）
    rows = load_eval()
    n_typical = sum(1 for r in rows if r["category"] in _TYPICAL_CATS)
    n_boundary = sum(1 for r in rows if r["category"] in _BOUNDARY_CATS)
    n_adversarial = sum(1 for r in rows if r["category"] in _ADVERSARIAL_CATS)

    def in_kb_quality(arm: dict) -> float | None:
        """只统计 in_kb 用例的质量分（库外题被拒答或硬答都不参与，保证跨臂可比）。"""
        scores = [x["judge"]["score"] for x in arm["rows"]
                  if x["judge"] is not None and not x["judge"].get("error") and x["gold"].endswith("in_kb")]
        return round(sum(scores) / len(scores), 2) if scores else None

    lines = []
    lines.append("# W3 三臂对比评测报告")
    lines.append(
        f"\n> 生成日期：{date.today().isoformat()} ｜ 评测集：`data/eval_set.csv` {len(rows)} 条"
        f"（典型 {n_typical} + 边界 {n_boundary} + 对抗 {n_adversarial}）"
    )
    lines.append(f"> 模型：flash=`{config.CHEAP_MODEL}` pro=`{config.PREMIUM_MODEL}` 裁判=`{JUDGE_MODEL}`")
    lines.append(f"> 价格核验日期：{config.PRICE_VERIFIED_DATE} ｜ 温度=0")
    lines.append("\n## 总览")
    lines.append("| 臂 | 总成本 | 平均质量分(0-5) | 路由准确率 | 拒答正确率 | 瞎编数 | 该答却拒答 | 库外硬答 | 裁判失败 |")
    lines.append("|----|--------|----------------|-----------|-----------|--------|------------|---------|---------|")
    for a in arms:
        lines.append(
            f"| {a['mode']} | ${a['total_cost']:.4f} | {a['avg_quality']:.2f} | "
            f"{a['route_acc'] if a['route_acc'] is not None else '-'} | "
            f"{a['refuse_acc'] if a['refuse_acc'] is not None else '-'} | {a['faithful_fail']} | "
            f"{a['should_answer_refused']} | {a['refuse_miss']} | {a['judge_failed']} |"
        )

    route_arm = next((a for a in arms if a["mode"] == "route"), None)
    pro_arm = next((a for a in arms if a["mode"] == "pro"), None)
    if route_arm and pro_arm and pro_arm["total_cost"] > 0:
        save_pct = (1 - route_arm["total_cost"] / pro_arm["total_cost"]) * 100
        # 质量对比用 in_kb 共同子集（公平口径）：库外题 pro 硬答会拉低分，不属于路由能力差异
        rq, pq = in_kb_quality(route_arm), in_kb_quality(pro_arm)
        if rq is not None and pq is not None:
            quality_drop = pq - rq
            lines.append(
                f"\n**核心结论：路由 vs 全 pro → 省 {save_pct:.1f}% 成本；"
                f"in_kb 子集质量差 {quality_drop:+.2f} 分（route {rq} vs pro {pq}）"
                f"，路由准确率 {route_arm['route_acc']}，拒答正确率 {route_arm['refuse_acc']}**"
            )
            lines.append(
                f"\n（质量分按 in_kb 共同子集对比：库外题 pro/flash 固定档会硬答并被扣分，"
                f"不属于路由本身的能力差异，故不计入对比；两臂总览的平均质量分含库外硬答扣分。）"
            )
        else:
            lines.append(f"\n**核心结论：路由 vs 全 pro → 省 {save_pct:.1f}% 成本（路由准确率 {route_arm['route_acc']}）**")
    lines.append(f"\n（注：\"库外硬答\"= 库外题本应拒答却回答，flash/pro 固定档不做拒答故会硬答，已计入瞎编审计；"
                 f"\"裁判失败\"= judge 自身调用失败的题数，未参与质量分与瞎编统计。）")

    if route_arm:
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
        embedder = qa_core.load_embedder()
        index = qa_core.load_index()
        by_id = {r["id"]: r for r in rows}
        for arm in arms:
            print(f"--- 重判 {arm['mode']} 臂 ---", flush=True)
            for x in arm["rows"]:
                # 保持初始路径语义：respond 被拒答 / refuse 被正确拒答 不重判；其余重判
                if (x["behavior"] == "respond" and x["refused"]) or \
                   (x["behavior"] == "refuse" and x["refused"]):
                    continue
                src = by_id[x["id"]]
                j = judge_answer(client, src["question"], src["answer_key"],
                                 x["reply"], x.get("refs", []))
                if x["behavior"] == "refuse" and not x["refused"]:
                    j = {"score": 0 if not j["faithful"] else 1, "faithful": j["faithful"],
                         "note": f"库外题未拒答而硬答；{j['note']}", "verdict": j["verdict"],
                         "error": j["error"], "refuse_miss": True}
                x["judge"] = j
                print(f"  [{arm['mode']}] {x['id']} 重判完成", flush=True)
        arms = [compute_arm(a["mode"], a["rows"]) for a in arms]
        save_cache(arms)
    else:
        embedder = qa_core.load_embedder()
        index = qa_core.load_index()
        modes = [args.mode] if args.mode else ["flash", "pro", "route"]
        arms = []
        for mode in modes:
            print(f"--- 跑 {mode} 臂 ---", flush=True)
            rows_out = run_arm(client, embedder, index, rows, mode)
            arms.append(compute_arm(mode, rows_out))
            save_cache(arms)

    report = render_report(arms)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(report, flush=True)
    print(f"\n报告已写入 {REPORT_PATH}", flush=True)


if __name__ == "__main__":
    main()
