"""
核心问答管线：app.py（网页界面）和 ask.py / 未来的评测脚本共用这一份逻辑。
保证"界面上看到的回答"和"自动评测跑出来的回答"走的是同一条链路——
这是 W3 评测结果能代表产品真实表现的前提。
"""
import os
import pickle

import numpy as np

import config

QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："  # BGE 模型官方建议的查询前缀


# ---------- 加载 ----------
def load_embedder():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(config.EMBED_MODEL)


def load_index():
    with open(config.INDEX_PATH, "rb") as f:
        return pickle.load(f)


# ---------- 检索 ----------
def retrieve(index, embedder, query: str, top_k: int | None = None) -> list[dict]:
    """返回 TOP_K 个最相关切片，按相似度从高到低。"""
    q = embedder.encode([QUERY_PREFIX + query], normalize_embeddings=True)[0]
    scores = index["emb"] @ q
    k = top_k or config.TOP_K
    top_idx = np.argsort(scores)[::-1][:k]
    return [
        {
            "score": float(scores[i]),
            "source": index["chunks"][i]["source"],
            "text": index["chunks"][i]["text"],
        }
        for i in top_idx
    ]


# ---------- 提示词与消息 ----------
def build_messages(history: list[dict], refs: list[dict]) -> list[dict]:
    """history: [{'role','content'}, ...]（含当前这条用户提问）；refs: 检索结果。"""
    context = "\n\n".join(
        f"[{i}] （来源：{r['source']}）\n{r['text']}" for i, r in enumerate(refs, 1)
    )
    system_prompt = (
        "你是企业知识库问答助手。只依据下面的参考资料回答问题，并在引用了资料的地方标注 [编号]。"
        "如果资料不足以回答，就明确说'知识库中没有找到相关内容'，不要编造。\n\n"
        f"参考资料：\n{context}"
    )
    recent = history[-6:]  # 只带最近几轮，控制输入成本
    return [{"role": "system", "content": system_prompt}] + recent


# ---------- 成本 ----------
def estimate_tokens(text: str) -> int:
    """没有 usage 时的粗估：中文约 1.5-2 字 = 1 token，取 1.8 折中。"""
    return int(len(text) / 1.8)


def calc_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    price = config.PRICE_TABLE.get(model, config.FALLBACK_PRICE)
    return input_tokens / 1e6 * price["input"] + output_tokens / 1e6 * price["output"]


# ---------- 一条龙（非流式，供命令行/评测脚本用） ----------
def answer_question(client, embedder, index, question: str, threshold: float | None = None) -> dict:
    """检索 → 拒答判断 → 调用 → 成本。返回完整结果字典。"""
    threshold = config.SIM_THRESHOLD if threshold is None else threshold
    refs = retrieve(index, embedder, question)

    if refs[0]["score"] < threshold:
        return {
            "reply": "知识库中没有找到相关内容。建议查阅官方文档，或转人工支持。",
            "refs": refs, "usage": None, "cost": 0.0, "refused": True,
        }

    messages = build_messages([{"role": "user", "content": question}], refs)
    model = os.getenv("CHAT_MODEL", "")
    resp = client.chat.completions.create(
        model=model, messages=messages, temperature=0,
    )
    usage = {"p": resp.usage.prompt_tokens, "c": resp.usage.completion_tokens, "estimated": False}
    reply = resp.choices[0].message.content or ""
    return {
        "reply": reply,
        "refs": refs,
        "usage": usage,
        "cost": calc_cost(model, usage["p"], usage["c"]),
        "refused": False,
    }
