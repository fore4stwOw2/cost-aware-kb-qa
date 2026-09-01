"""
成本感知知识库问答 · W1 版（单模型）
功能：本地知识库检索 → 带引用回答 → 显示 token 用量与估算成本 → 低相似度拒答。
运行：streamlit run app.py
"""
import os
import pickle

import numpy as np
import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI
from sentence_transformers import SentenceTransformer

import config

load_dotenv()

st.set_page_config(page_title="成本感知知识库问答", page_icon="💡")
st.title("💡 成本感知知识库问答")
st.caption("W1：单模型版。检索知识库 → 带引用回答 → 显示本次成本；相似度低于阈值时拒答。")

# ---------- 侧边栏 ----------
with st.sidebar:
    st.header("设置")
    chat_model = os.getenv("CHAT_MODEL", "")
    st.caption(f"聊天模型：`{chat_model or '未配置'}`")
    st.caption(f"价格核验日期：⚠️ {config.PRICE_VERIFIED_DATE}")
    sim_threshold = st.slider(
        "拒答阈值（检索相似度低于它就拒答）", 0.0, 0.9, float(config.SIM_THRESHOLD), 0.05
    )
    st.caption("W1 故意调低：先观察模型在库外问题上怎么瞎编并记入问题日志，W2 再用证据调这里。")
    show_scores = st.checkbox("显示检索得分（调试）", value=True)
    st.divider()
    st.metric("本次会话累计成本", f"${st.session_state.get('total_cost', 0.0):.4f}")


# ---------- 资源加载 ----------
@st.cache_resource
def load_embedder():
    return SentenceTransformer(config.EMBED_MODEL)


@st.cache_data
def load_index():
    with open(config.INDEX_PATH, "rb") as f:
        return pickle.load(f)


if not any(config.DATA_DIR.glob("*.md")) and not any(config.DATA_DIR.glob("*.txt")):
    st.error(f"❌ {config.DATA_DIR} 里没有文档。先按 02-语料收集清单.md 放入语料，再运行 `python ingest.py`。")
    st.stop()

if not config.INDEX_PATH.exists():
    st.error("❌ 还没有索引。先在终端运行：`python ingest.py`")
    st.stop()

index = load_index()
embedder = load_embedder()

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    st.warning(
        "✋ 还差最后一步：编辑项目根目录的 `.env`，填入 OPENAI_API_KEY / OPENAI_BASE_URL / CHAT_MODEL，"
        "然后刷新本页。（key 只填在 .env 文件里，不要发到聊天窗口）"
    )
    st.stop()

client = OpenAI(api_key=api_key, base_url=os.getenv("OPENAI_BASE_URL") or None)

# BGE 系列模型官方建议：查询侧加指令前缀，检索更准
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："


def retrieve(query: str) -> list[dict]:
    """返回 TOP_K 个最相关切片，按相似度从高到低。"""
    q = embedder.encode([QUERY_PREFIX + query], normalize_embeddings=True)[0]
    scores = index["emb"] @ q
    top_idx = np.argsort(scores)[::-1][: config.TOP_K]
    return [
        {
            "score": float(scores[i]),
            "source": index["chunks"][i]["source"],
            "text": index["chunks"][i]["text"],
        }
        for i in top_idx
    ]


def render_meta(meta: dict) -> None:
    """在回答下方渲染：引用来源 + token 用量与成本。"""
    refs = meta.get("refs") or []
    with st.expander("📚 引用来源", expanded=False):
        for i, r in enumerate(refs, 1):
            st.markdown(f"**[{i}] {r['source']}**（相似度 {r['score']:.2f}）")
            st.markdown(f"> {r['text'][:80]}…")

    usage, cost = meta.get("usage"), meta.get("cost", 0.0)
    if usage is None:
        st.caption("🚫 本次未调用大模型，成本 $0")
        return
    est = "（估算）" if usage.get("estimated") else ""
    st.caption(f"💰 输入 {usage['p']} tokens / 输出 {usage['c']} tokens{est} / 本次成本 ≈ ${cost:.4f}")


def estimate_tokens(text: str) -> int:
    """没有 usage 时的粗估：中文约 1.5-2 字 = 1 token，取 1.8 折中。"""
    return int(len(text) / 1.8)


# ---------- 历史消息 ----------
if "messages" not in st.session_state:
    st.session_state.messages = []

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if m.get("meta"):
            render_meta(m["meta"])

# ---------- 新输入 ----------
if prompt := st.chat_input("问点什么，比如：上下文窗口超过 27 万 token 后怎么计费？"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        refs = retrieve(prompt)
        if show_scores:
            st.caption("检索得分：" + "、".join(f"{r['score']:.2f}" for r in refs))

        # ---- 拒答分支：不花一分钱 ----
        if refs[0]["score"] < sim_threshold:
            reply = "知识库中没有找到相关内容。建议查阅官方文档，或转人工支持。"
            st.markdown(reply)
            meta = {"refs": refs, "usage": None, "cost": 0.0}
        else:
            # ---- 正常回答分支 ----
            context = "\n\n".join(
                f"[{i}] （来源：{r['source']}）\n{r['text']}" for i, r in enumerate(refs, 1)
            )
            system_prompt = (
                "你是企业知识库问答助手。只依据下面的参考资料回答问题，并在引用了资料的地方标注 [编号]。"
                "如果资料不足以回答，就明确说'知识库中没有找到相关内容'，不要编造。\n\n"
                f"参考资料：\n{context}"
            )
            history = [
                {"role": m["role"], "content": m["content"]}
                for m in st.session_state.messages
                if m["role"] in ("user", "assistant")
            ][-6:]  # 只带最近几轮，控制输入成本

            usage_data: dict = {"p": 0, "c": 0, "estimated": False}

            def stream_reply():
                try:
                    resp = client.chat.completions.create(
                        model=chat_model,
                        messages=[{"role": "system", "content": system_prompt}] + history,
                        temperature=0,
                        stream=True,
                        stream_options={"include_usage": True},
                    )
                    for chunk in resp:
                        if getattr(chunk, "usage", None):
                            usage_data["p"] = chunk.usage.prompt_tokens
                            usage_data["c"] = chunk.usage.completion_tokens
                        if chunk.choices and chunk.choices[0].delta.content:
                            yield chunk.choices[0].delta.content
                except Exception as e:  # 报错原样展示，方便贴回给 AI 助手排查
                    yield f"⚠️ 调用失败：`{e}`\n\n（请把这条报错原样发给你的 AI 助手）"

            reply = st.write_stream(stream_reply())

            price = config.PRICE_TABLE.get(chat_model, config.FALLBACK_PRICE)
            if usage_data["p"] or usage_data["c"]:
                input_t, output_t = usage_data["p"], usage_data["c"]
            else:  # 服务商没返回 usage，退回估算
                input_t = estimate_tokens(system_prompt) + sum(
                    estimate_tokens(m["content"]) for m in history
                )
                output_t = estimate_tokens(reply)
                usage_data = {"p": input_t, "c": output_t, "estimated": True}
            cost = input_t / 1e6 * price["input"] + output_t / 1e6 * price["output"]

            if chat_model not in config.PRICE_TABLE:
                st.caption(f"⚠️ 单价表里没有 `{chat_model}`，按占位价估算（见 config.py）")
            meta = {"refs": refs, "usage": usage_data, "cost": cost}
            st.session_state.total_cost = st.session_state.get("total_cost", 0.0) + cost

        render_meta(meta)

    st.session_state.messages.append({"role": "assistant", "content": reply, "meta": meta})
