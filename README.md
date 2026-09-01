# Cost-Aware KB-QA · 成本感知的知识库问答

AI PM 作品集项目（进行中）：知识库问答 → 难度分类 → 便宜/贵模型分级路由 → 每条回答展示成本 → 库外拒答、上游故障自动降级，并用评测集证明"省了多少成本、质量损失多少"。

**当前进度：W1 · 单模型版**（知识库问答 + 引用 + 成本显示 + 拒答逻辑，路由是 W2 的事）

## 本地运行

```bash
# 1. 创建虚拟环境并安装依赖（只需一次）
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. 配置：复制 .env.example 为 .env，填入 API key / base_url / 模型名

# 3. 文档入库（增删了 data/docs/ 里的文档后重新跑）
.venv/bin/python ingest.py

# 4. 启动
.venv/bin/streamlit run app.py
```

## 目录说明

| 文件/目录 | 是什么 |
|-----------|--------|
| `app.py` | 问答应用（Streamlit） |
| `ingest.py` | 文档切片 + 向量化 + 建本地索引 |
| `config.py` | 所有参数：切片、检索、拒答阈值、模型单价表 |
| `data/docs/` | 知识库语料（出处见 `data/SOURCES.md`） |
| `docs/problem-log.md` | 问题日志：模型每次犯错的记录 |
| `01~03-*.md` | 项目计划文档：需求一页纸 / 语料清单 / Agent 任务卡 |

## 已知边界（诚实声明）

- 语料目前是 3 篇种子文档（来自 AIPM-Wiki，出处见 SOURCES），尚未替换为各家官方文档全集
- config.py 里的模型单价是**占位价，未核验**——核验官方定价页是进行中的作业
- 拒答阈值故意调低（0.30）：W1 阶段先观察模型的瞎编行为，W2 用证据调优
- 没有做：模型路由（W2）、评测集（W3）、部署（W5）

## 合规红线

- API key 只放 `.env`（已被 gitignore），不进代码、不进文档
- 语料只用公开材料，任何公司内部数据（协议价、客户量、内部文档）不进本项目
