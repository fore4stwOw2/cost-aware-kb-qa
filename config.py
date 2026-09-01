"""
项目配置：所有可调参数都集中在这里。
改完任何参数后，切片/检索类参数需要重新运行 `python ingest.py`。
"""
import os
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

# ---------- 双档路由（W2） ----------
# 便宜档 / 贵档 / 分类器。允许用环境变量覆盖（供自动化测试模拟故障、Verifier 验收用）。
CHEAP_MODEL = os.getenv("CHEAP_MODEL", "deepseek-v4-flash")
PREMIUM_MODEL = os.getenv("PREMIUM_MODEL", "deepseek-v4-pro")
CLASSIFY_MODEL = os.getenv("CLASSIFY_MODEL", "deepseek-v4-flash")  # 分类器用便宜档，单次约 $0.0001

# 路由模式：route（默认，按分类路由）/ flash（固定便宜档）/ pro（固定贵档）
ROUTE_MODE = os.getenv("ROUTE_MODE", "route")

# ---------- 单价表（每百万 token，美元） ----------
# 核验来源：https://api-docs.deepseek.com/quick_start/pricing （2026-09-01 访问）
# 取"高峰时段 + 缓存未命中"的较贵价估算（保守口径）；淡季为半价、缓存命中更便宜。
# key 必须和 .env 里的 CHAT_MODEL 完全一致才能匹配上。
PRICE_TABLE = {
    "deepseek-v4-flash": {
        "input": 0.44, "output": 1.32,
        "note": "高峰价；淡季减半；缓存命中输入 $0.014",
    },
    "deepseek-v4-pro": {
        "input": 1.32, "output": 3.96,
        "note": "高峰价；淡季减半；W2 的'贵档'候选",
    },
}
# 如果 .env 里的 CHAT_MODEL 在上表找不到，就用这个兜底价（界面会标"单价未配置"）
FALLBACK_PRICE = {"input": 1.0, "output": 2.0, "note": "单价表里没有这个模型名，占位价"}
PRICE_VERIFIED_DATE = "2026-09-01"   # 上次核验官方定价页的日期；价格变动时更新这里
