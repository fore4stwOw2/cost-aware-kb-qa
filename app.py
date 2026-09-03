"""
成本感知知识库问答 · W2 版（双档路由）
检索 → 分类器（难度+可答性）→ 路由到便宜/贵档 → 带引用回答 + 成本 + 路由理由；
库外拒答（$0）、上游故障自动降级。问答逻辑在 qa_core.py（与 ask.py 共用）。
运行：streamlit run app.py
"""
import os

import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

import config
import qa_core

load_dotenv()

st.set_page_config(page_title="成本感知知识库问答", page_icon="💡")
st.title("💡 成本感知知识库问答")
st.caption("W2：双档路由。分类器判断难度与可答性 → 简单走便宜档 / 复杂走贵档 / 库外拒答 / 故障降级。")

# ---------- 侧边栏 ----------
with st.sidebar:
    st.header("设置")
    mode = st.radio("模式", ["route", "flash", "pro", "agent"],
                    format_func=lambda m: {"route": "🛤️ 智能路由（默认）", "flash": "⚡ 固定便宜档",
                                           "pro": "💎 固定贵档", "agent": "🤖 Agent 任务"}[m],
                    index=0)
    st.caption(f"便宜档：`{config.CHEAP_MODEL}`（约 $0.44/$1.32）")
    st.caption(f"贵档：`{config.PREMIUM_MODEL}`（约 $1.32/$3.96）")
    st.caption(f"分类器：`{config.CLASSIFY_MODEL}`（单次约 $0.0001）")
    st.caption(f"Agent 规划：`{config.AGENT_MODEL}`（上限 {config.AGENT_MAX_TURNS} 轮 / ${config.AGENT_MAX_COST}）")
    st.caption(f"价格核验日期：{config.PRICE_VERIFIED_DATE}")

    sim_threshold = st.slider(
        "兜底拒答阈值（检索相似度低于它就拒答）", 0.0, 0.9, float(config.SIM_THRESHOLD), 0.05
    )
    st.caption("仅 route 模式生效：分类器判断可答性，此阈值是第二道免费兜底。")
    show_scores = st.checkbox("显示检索得分（调试）", value=False)
    st.divider()
    st.metric("本次会话累计成本", f"${st.session_state.get('total_cost', 0.0):.4f}")


# ---------- 资源加载 ----------
@st.cache_resource
def _embedder():
    return qa_core.load_embedder()


@st.cache_data
def _index():
    return qa_core.load_index()


if not any(config.DATA_DIR.glob("*.md")) and not any(config.DATA_DIR.glob("*.txt")):
    st.error(f"❌ {config.DATA_DIR} 里没有文档。先按 02-语料收集清单.md 放入语料，再运行 `python ingest.py`。")
    st.stop()

if not config.INDEX_PATH.exists():
    st.error("❌ 还没有索引。先在终端运行：`python ingest.py`")
    st.stop()

index = _index()
embedder = _embedder()

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    st.warning(
        "✋ 还差最后一步：编辑项目根目录的 `.env`，填入 OPENAI_API_KEY / OPENAI_BASE_URL，"
        "然后刷新本页。（key 只填在 .env 文件里，不要发到聊天窗口）"
    )
    st.stop()

client = OpenAI(api_key=api_key, base_url=os.getenv("OPENAI_BASE_URL") or None,
                timeout=config.API_TIMEOUT)


def render_route_line(meta: dict) -> None:
    """在回答上方渲染一行路由信息。"""
    info = meta.get("route_info") or {}
    if not info:
        return
    if info.get("classify_error"):
        st.caption(f"⚠️ 分类器异常：{info['classify_error']}")
    if meta.get("refused"):
        st.caption(f"🚫 拒答（{info.get('answerable', '-')}）：{meta.get('refuse_reason', '')}")
        return
    parts = [f"🧭 {info.get('mode')}"]
    if info.get("difficulty"):
        parts.append(f"难度={info['difficulty']}")
    if info.get("answerable"):
        parts.append(f"可答性={info['answerable']}")
    parts.append(f"选档={info.get('chosen_model', '?')}")
    if info.get("degraded"):
        parts.append("⚠️降级运行")
    if info.get("reason"):
        parts.append(f"理由：{info['reason']}")
    st.caption(" · ".join(parts))


def render_meta(meta: dict) -> None:
    """在回答下方渲染：引用来源 + token 用量与成本。"""
    refs = meta.get("refs") or []
    with st.expander("📚 引用来源", expanded=False):
        for i, r in enumerate(refs, 1):
            st.markdown(f"**[{i}] {r['source']}**（相似度 {r['score']:.2f}）")
            st.markdown(f"> {r['text'][:80]}…")

    usage, cost = meta.get("usage"), meta.get("cost", 0.0)
    if usage is None:
        st.caption(f"🚫 本次未调用主模型，成本 ${cost:.4f}")
        return
    est = "（估算）" if usage.get("estimated") else ""
    extra = f"（含路由 {usage.get('route_p', 0)}入/{usage.get('route_c', 0)}出）" if usage.get("route_p") else ""
    st.caption(f"💰 输入 {usage['p']} tokens / 输出 {usage['c']} tokens{est}{extra} / 本次成本 ≈ ${cost:.4f}")


def render_trace(trace: list[dict]) -> None:
    """Agent 轨迹渲染（B2）：工具调用序列 + 策略事件。"""
    with st.expander("🛰️ Agent 轨迹", expanded=True):
        for ev in trace:
            t = ev["type"]
            if t == "tool_call":
                st.markdown(f"🔧 **t{ev['turn']} {ev['tool']}**"
                            f"（ok={ev['ok']}）`{ev['args_summary'][:80]}`")
                st.caption(ev["result_summary"][:200])
            elif t == "policy_check":
                icon = {"waiting_approval": "⚠️", "approved": "✅", "cancelled": "🚫",
                        "budget_turns": "⛔", "budget_cost": "⛔", "blacklist": "🛡️"}.get(
                    ev.get("policy"), "🛡️")
                st.caption(f"{icon} 策略[{ev.get('policy')}] {ev.get('detail', '')[:120]}")
            elif t == "model_turn" and "error" in ev:
                st.caption(f"❌ 模型调用失败 t{ev['turn']}: {ev['error'][:120]}")
            elif t == "final_result":
                st.markdown(f"🏁 最终回答（t{ev.get('turn', '-')}）")


# ---------- Agent 确认闸门（两阶段：先跑到闸门→用户确认→带决定重跑） ----------
agent_pending = st.session_state.get("agent_pending")
if agent_pending is not None:
    card = agent_pending["card"]
    st.warning("⚠️ 高风险动作需要人工确认")
    st.json(card)
    c1, c2 = st.columns(2)
    if c1.button("✅ 确认执行（dry-run）", key="agent_confirm_yes"):
        st.session_state["agent_decision"] = True
        st.rerun()
    if c2.button("🚫 拒绝并取消", key="agent_confirm_no"):
        st.session_state["agent_decision"] = False
        st.rerun()

    decision = st.session_state.get("agent_decision")
    if decision is not None:
        import agent_core
        st.session_state.pop("agent_pending", None)
        st.session_state.pop("agent_decision", None)
        with st.chat_message("assistant"):
            r = agent_core.run_agent(client, agent_pending["task"],
                                     confirm_callback=lambda _card: decision)
            if r["status"] == "cancelled":
                st.markdown("🚫 已取消：未执行任何副作用。")
            elif r["status"] == "succeeded":
                render_trace(r["trace"])
                st.markdown(r["answer"] or "（无回答）")
            else:
                st.markdown(f"状态：`{r['status']}`")
            st.caption(f"Agent 成本 ${r['total_cost']:.4f} / {r['turns']} 轮")
        st.session_state.messages.append({"role": "assistant", "content": "（Agent 任务结束）"})

# ---------- 历史消息 ----------
if "messages" not in st.session_state:
    st.session_state.messages = []

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if m.get("meta"):
            render_route_line(m["meta"])
            render_meta(m["meta"])

# ---------- 新输入 ----------
if prompt := st.chat_input("问点什么，比如：Claude Sonnet 4 多少钱？"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        # ---- Agent 模式（B2）：任务循环 + 确认闸门 ----
        if mode == "agent":
            import agent_core
            st.session_state.pop("agent_pending", None)
            st.session_state.pop("agent_decision", None)

            def _confirm(card):
                st.session_state["agent_pending"] = {"card": card, "task": prompt}
                return False  # 先停到闸门，等用户按钮后带决定重跑

            r = agent_core.run_agent(client, prompt, confirm_callback=_confirm)
            if r["status"] == "needs_confirmation":
                st.info("⏳ 任务已暂停在高风险动作前，请在上方确认卡选择。")
            elif r["status"] == "succeeded":
                render_trace(r["trace"])
                st.markdown(r["answer"] or "（无回答）")
                st.caption(f"🤖 Agent 成本 ${r['total_cost']:.4f} / {r['turns']} 轮")
                st.session_state.total_cost = st.session_state.get("total_cost", 0.0) + r["total_cost"]
            elif r["status"] == "blocked":
                render_trace(r["trace"])
                st.warning("⛔ 预算/轮数触顶，任务已停止（未静默继续）。")
                st.caption(f"🤖 Agent 成本 ${r['total_cost']:.4f} / {r['turns']} 轮")
            else:
                render_trace(r["trace"])
                st.markdown(f"状态：`{r['status']}`")
            st.session_state.messages.append({"role": "assistant", "content": f"（Agent: {r['status']}）"})
            st.rerun() if r["status"] == "needs_confirmation" else None
            st.stop()

        # 路由决策（分类器在这里调用）
        decision = qa_core.route_decision(client, embedder, index, prompt,
                                          threshold=sim_threshold, mode=mode)
        refs = decision["refs"]
        if show_scores:
            st.caption("检索得分：" + "、".join(f"{r['score']:.2f}" for r in refs))

        if decision["refuse"]:
            # 拒答分支（分类器/阈值判定库外，主模型未调用）
            reply = qa_core.REFUSAL_MSG
            st.markdown(reply)
            if decision["classifier_cost"] > 0:
                st.session_state.total_cost = st.session_state.get("total_cost", 0.0) + decision["classifier_cost"]
            meta = {
                "refs": refs,
                "usage": decision["classifier_usage"],
                "cost": decision["classifier_cost"],
                "refused": True,
                "refuse_reason": decision["refuse_reason"],
                "route_info": {
                    "mode": mode,
                    "difficulty": decision["difficulty"],
                    "answerable": decision["answerable"],
                    "reason": decision["reason"],
                    "chosen_model": None,
                    "classify_error": decision["classify_error"],
                },
            }
        else:
            # 正常回答分支（流式 + 降级兜底）
            model = decision["chosen_model"]
            alt = config.PREMIUM_MODEL if model == config.CHEAP_MODEL else config.CHEAP_MODEL
            history = [
                {"role": m["role"], "content": m["content"]}
                for m in st.session_state.messages
                if m["role"] in ("user", "assistant")
            ]
            api_messages = qa_core.build_messages(history, refs)

            # 流式状态用可变容器捕获（模块级代码不能用 nonlocal）
            stream_state = {"used_model": model, "degraded": False, "failed": False,
                            "usage": {"p": 0, "c": 0, "estimated": False}}

            def stream_reply():
                last_err = None
                for attempt in (model, model, alt):  # 主档重试一次，仍失败换另一档
                    try:
                        resp = client.chat.completions.create(
                            model=attempt, messages=api_messages, temperature=0,
                            stream=True, stream_options={"include_usage": True},
                            timeout=config.API_TIMEOUT,
                        )
                        stream_state["used_model"] = attempt
                        stream_state["degraded"] = (attempt == alt)
                        for chunk in resp:
                            if getattr(chunk, "usage", None):
                                stream_state["usage"]["p"] = chunk.usage.prompt_tokens
                                stream_state["usage"]["c"] = chunk.usage.completion_tokens
                            if chunk.choices and chunk.choices[0].delta.content:
                                yield chunk.choices[0].delta.content
                        return  # 成功即返回
                    except Exception as e:
                        last_err = e
                stream_state["failed"] = True
                yield f"⚠️ 主模型与降级模型均调用失败：`{last_err}`\n\n（请把这条报错原样发给你的 AI 助手）"

            reply = st.write_stream(stream_reply())
            usage_data = stream_state["usage"]
            used_model = stream_state["used_model"]
            degraded = stream_state["degraded"]
            is_error = stream_state["failed"]

            if usage_data["p"] or usage_data["c"]:
                input_t, output_t = usage_data["p"], usage_data["c"]
            else:
                input_t = qa_core.estimate_tokens(api_messages[0]["content"]) + sum(
                    qa_core.estimate_tokens(m["content"]) for m in api_messages[1:]
                )
                output_t = qa_core.estimate_tokens(reply)
                usage_data = {"p": input_t, "c": output_t, "estimated": True}
            merged_usage = qa_core._merge_usage(usage_data, decision["classifier_usage"])
            cost = qa_core.calc_cost(used_model, input_t, output_t) + decision["classifier_cost"]

            if used_model not in config.PRICE_TABLE:
                st.caption(f"⚠️ 单价表里没有 `{used_model}`，按占位价估算（见 config.py）")
            meta = {
                "refs": refs,
                "usage": merged_usage,
                "cost": cost,
                "refused": False,
                "status": "error" if is_error else None,
                "route_info": {
                    "mode": mode,
                    "difficulty": decision["difficulty"],
                    "answerable": decision["answerable"],
                    "reason": decision["reason"],
                    "chosen_model": model,
                    "used_model": used_model,
                    "degraded": degraded,
                    "classify_error": decision["classify_error"],
                },
            }
            # 故障时主模型成本未发生，但分类器成本已花掉，如实计入
            if is_error:
                st.session_state.total_cost = st.session_state.get("total_cost", 0.0) + decision["classifier_cost"]
            else:
                st.session_state.total_cost = st.session_state.get("total_cost", 0.0) + cost

        render_route_line(meta)
        render_meta(meta)

    st.session_state.messages.append({"role": "assistant", "content": reply, "meta": meta})
