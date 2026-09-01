"""
项目配置：所有可调参数都集中在这里。
改完任何参数后，切片/检索类参数需要重新运行 `python ingest.py`。
"""
from pathlib import Path

# ---------- 路径 ----------
ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data" / "docs"          # 知识库语料放这里
INDEX_PATH = ROOT / "data" / "index.pkl"   # 生成的本地向量索引

# ---------- 切片参数 ----------
CHUNK_SIZE = 500      # 每个切片约多少字
CHUNK_OVERLAP = 50    # 相邻切片重叠多少字（防止答案正好被切断）
MIN_CHUNK_LEN = 20    # 短于这个字数的切片直接丢弃

# ---------- 检索参数 ----------
TOP_K = 3             # 每次检索取最相关的几个切片

# 拒答阈值：检索最高相似度低于它时，不调用大模型，直接拒答。
# ★ W1 故意调得很低（基本不拒答）：先观察模型在库外问题上怎么瞎编，
#   把这些 case 记进 docs/problem-log.md，W2 再用证据回来调这个值。
SIM_THRESHOLD = 0.30

# ---------- 模型 ----------
# 本地向量模型（免费、离线、对中文友好），首次运行会自动下载约 100MB
EMBED_MODEL = "BAAI/bge-small-zh-v1.5"

# ---------- 单价表（每百万 token，美元） ----------
# ★★ 这是你的作业：打开各家官方定价页核验后填入真实数字，并把下面的日期改成核验当天 ★★
# key 必须和 .env 里的 CHAT_MODEL 完全一致才能匹配上。
PRICE_TABLE = {
    "deepseek-chat": {
        "input": 0.27, "output": 1.10,
        "note": "占位示例价，未经核验！去 api-docs.deepseek.com 核验后修改",
    },
    "贵档占位-以后换成真实模型名": {
        "input": 3.0, "output": 15.0,
        "note": "W2 接第二档模型时替换",
    },
}
# 如果 .env 里的 CHAT_MODEL 在上表找不到，就用这个兜底价（界面会标"单价未配置"）
FALLBACK_PRICE = {"input": 1.0, "output": 2.0, "note": "单价表里没有这个模型名，占位价"}
PRICE_VERIFIED_DATE = "未核验"   # 核验后改成 "2026-09-XX" 这样的日期
