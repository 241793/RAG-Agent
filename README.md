# 企业级 RAG 知识库智能体平台

可对接企业内部系统、也供员工直接使用，具备多权限体系的企业级 RAG 平台。

**当前为第一轮交付**：地基 + 核心闭环（上传文档 → 解析切分 → 向量化 → 检索 → 流式问答 → 引用溯源），已端到端跑通。

**已交付的第二轮：智能体（Agent）平台** —— 完整的 Agent 能力：
- **工具循环 Agent（ReAct）**：LLM 自主调用工具（知识库检索 / HTTP / 自定义），多轮直到得出答案
- **技能（Skill）**：能力包（提示词+工具+知识库）与工具（HTTP 可调用）两种形态
- **行为模式（AgentMode）**：同一智能体多套行为，切换换提示词/工具/参数
- **工作流编排（DAG）**：7 类节点（start/llm/knowledge_retrieval/condition/http/end）+ 变量引用 + 条件分支 + 可视化画布
- **多权限**：文档级 ACL（含部门向下继承）+ RBAC 角色/权限矩阵

---

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | FastAPI + SQLAlchemy 2.0 async + Uvicorn |
| 数据库 | **默认 SQLite**（零依赖），可切换 **PostgreSQL(+pgvector)** / **MySQL** |
| 向量检索 | pgvector（PG）/ numpy 应用层（SQLite/MySQL），自动切换 |
| 任务队列 | 进程内 asyncio 队列（零依赖），可换 Celery |
| 前端 | React 19 + TypeScript + Vite + antd + @xyflow/react（画布） |
| 模型 | 统一 Provider 抽象层：OpenAI 兼容 / Anthropi Claud / Ollama / 本地 bge / 离线 |

## 智能体平台用法

1. **模型管理**：配置 Provider 与 chat 模型（支持工具调用的模型才能用 ReAct）
2. **智能体** → 新建：填系统提示词、选知识库、开启「知识库检索工具」
3. **运行**：进「智能体」卡片点运行，提问后会看到**工具调用过程**（可折叠卡片），最终给带引用的答案
4. **技能**：新建「能力包」（提示词模板）或「工具」（HTTP），在智能体编辑页勾选启用
5. **行为模式**：智能体编辑页 → 行为模式 Tab，添加多套（如写作/审核模式），运行时切换
6. **工作流**：workflow 类型智能体 → 点「编排」→ 可视化画布拖拽连线 / JSON 定义 → 运行看节点执行状态

> 离线验证：`python scripts/agent_selftest.py`（无需模型 key，验证 ReAct 循环）

## 目录结构

```
backend/
  app/
    core/          # 配置/数据库/安全/日志/错误
    models/        # SQLAlchemy ORM（19 张表，含预留权限表）
    schemas/       # Pydantic DTO
    api/v1/        # auth/kb/document/retrieval/chat/provider
    services/      # permission(权限唯一入口)/retrieval/chat
    providers/     # 模型抽象层：base/registry/drivers/*
    retrieval/     # vector_store/bm25/fusion
    ingest/        # storage/parsers/chunkers(含父子分块)
    tasks/         # 进程内队列 + 入库流水线
  scripts/         # seed.py(初始化) / selftest.py(自测)
  data/            # SQLite 库 + 上传文件（gitignore）
web/               # 前端
```

---

## 快速开始

> **统一入口**：后端监听 **6677** 端口，并同时托管前端构建产物。浏览器只需访问 `http://127.0.0.1:6677` 一个地址。

### 一键启动（推荐）

```bash
start.bat
```

自动完成：初始化数据库 → 构建前端 → 启动服务。然后打开 http://127.0.0.1:6677 ，登录 **admin / admin123**。

### 手动启动

```bash
# 1. 后端准备
cd backend
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
cp .env.example .env
./.venv/Scripts/python.exe scripts/seed.py

# 2. 构建前端（产物进 web/dist，由后端托管）
cd ../web
npm install
npm run build

# 3. 启动统一服务
cd ../backend
./.venv/Scripts/python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 6677
```

访问 http://127.0.0.1:6677 （前端），http://127.0.0.1:6677/docs （API 文档）。

### 前端开发模式（可选）

改前端时用热更新，Vite 跑在 5173 并把 `/api` 代理到 6677：

```bash
cd web && npm run dev
```

此时访问 http://127.0.0.1:5173 。改完后 `npm run build` 让后端托管最新产物。

---

## 配置模型（关键）

首次打开后，进入「**模型管理**」添加 Provider 与模型配置。支持以下类型：

| 类型 | 说明 | base_url 示例 |
|---|---|---|
| `openai` | OpenAI 兼容（含中转站、vLLM） | `https://api.xxx.com/v1` |
| `anthropi` | Anthropi Claud | `https://api.anthropi.com` |
| `ollama` | 本地 Ollama | `http://localhost:11434/v1` |
| `local_bge` | 本地 bge（需 `pip install FlagEmbedding`） | 模型路径 |
| `local_hash` | 离线自测（无需网络） | `local` |

每个 Provider 下可配置多种用途：**chat / embedding / rerank**。
embedding 维度需与知识库一致（bge-m3=1024，text-embedding-3-small=1536）。

> 也可在 `.env` 中预置默认 Provider，`seed.py` 会自动写入。

---

## 切换数据库（数据可迁移）

编辑 `backend/.env` 的 `DATABASE_URL`：

```ini
# SQLite（默认）
DATABASE_URL=sqlite+aiosqlite:///./data/rag.db
# PostgreSQL
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/rag
# MySQL
DATABASE_URL=mysql+asyncmy://root:root@localhost:3306/rag
```

切换后安装对应驱动并重建表：

```bash
pip install asyncpg pgvector    # PostgreSQL
pip install asyncmy             # MySQL
```

向量后端 `VECTOR_BACKEND=auto` 会自动选择：PostgreSQL 用 pgvector 原生检索，其余用 numpy 应用层余弦。

迁移已有 SQLite 数据到 PG/MySQL：用 `alembic` 建表后，通过 `scripts/` 下的导出导入脚本搬运（后续提供）。

---

## 权限体系（本轮范围）

- **租户隔离**：所有数据带 `tenant_id`。
- **权限过滤唯一入口**：`backend/app/services/permission.py` —— 所有检索的权限条件都由此生成，避免越权召回（企业 RAG 最高危点）。
- **知识库可见性**：`public`（全租户）/ `internal`（按成员）/ `private`（仅显式成员）。
- **principal 统一编码**：`PUBLIC=0`、`USER=1e12+id`、`DEPT=2e12+id`、`ROLE=3e12+id`、`GROUP=4e12+id`。本轮用到 USER/PUBLIC，部门/角色/组的完整 RBAC 已预留表结构与编码，下一轮启用。

**已预留但下轮启用**：完整 RBAC 角色权限矩阵、文档级 ACL、部门树授权、审计日志、SSO、API Key、应用编排工作流、Docker Compose。

---

## 验证

离线自测（无需任何模型 key，验证完整闭环）：

```bash
# 先启动后端，然后
./.venv/Scripts/python.exe scripts/selftest.py
```

预期：建离线 Provider → 建知识库 → 上传文档 → 入库 ready → 检索返回带分数结果 → 流式对话 → 引用溯源。

---

## 常见问题

**Q: 中文关键词检索效果一般？**
默认用应用层按字分词。PostgreSQL 可启用 `zhparser` 扩展增强中文 BM25；未启用时向量单路检索仍可用。

**Q: 换 embedding 模型后检索异常？**
向量空间不兼容，需重建该知识库的向量（切换模型后重新上传文档）。

**Q: 对话无输出？**
检查「模型管理」是否配置了 chat 模型，或先用 `local_hash` 离线驱动验证链路。
