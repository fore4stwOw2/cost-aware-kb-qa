"""
把 data/docs/ 里的所有文档切片、向量化，存成本地索引。
运行：python ingest.py
改了 config.py 的切片参数、或增删了文档后，重新运行一次即可。
"""
import pickle
import re

import numpy as np
from sentence_transformers import SentenceTransformer

import config


def chunk_text(text: str, size: int, overlap: int) -> list[str]:
    """把长文本切成约 size 字的片段，相邻片段重叠 overlap 字，尽量在段落/句子边界断开。"""
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):  # 还有后文才需要找"好的断点"
            for sep in ("\n\n", "\n", "。", "；", ". "):
                cut = text.rfind(sep, start + int(size * 0.6), end)
                if cut > start:
                    end = cut + len(sep)
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def main() -> None:
    docs = sorted(config.DATA_DIR.glob("*.md")) + sorted(config.DATA_DIR.glob("*.txt"))
    if not docs:
        raise SystemExit(f"❌ {config.DATA_DIR} 里没有 .md/.txt 文档，先按 02-语料收集清单.md 放几篇进去。")

    all_chunks: list[dict] = []
    for path in docs:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for piece in chunk_text(text, config.CHUNK_SIZE, config.CHUNK_OVERLAP):
            if len(piece) >= config.MIN_CHUNK_LEN:
                all_chunks.append({"text": piece, "source": path.name})

    print(f"读取 {len(docs)} 篇文档，切出 {len(all_chunks)} 个片段，开始向量化…")
    model = SentenceTransformer(config.EMBED_MODEL)
    embeddings = model.encode(
        [c["text"] for c in all_chunks],
        normalize_embeddings=True,
        show_progress_bar=True,
    )

    config.INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(config.INDEX_PATH, "wb") as f:
        pickle.dump(
            {"chunks": all_chunks, "emb": np.asarray(embeddings), "embed_model": config.EMBED_MODEL},
            f,
        )
    print(f"✅ 完成：{len(docs)} 篇文档 / {len(all_chunks)} 个切片，索引已存到 {config.INDEX_PATH}")


if __name__ == "__main__":
    main()
