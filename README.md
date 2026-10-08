# 企业级 RAG 知识库智能体平台(源码非正式版)

可对接企业内部系统、也供员工直接使用，具备多权限体系、智能体与自动化能力的企业级 RAG 平台。

后端 FastAPI + SQLAlchemy 2.0 async，前端 React 19 + TypeScript + Vite + antd，**默认 SQLite 零依赖起步**，可平滑切换 PostgreSQL(+pgvector)/MySQL。
<div>
<img width="1900" height="864" alt="b3f131b9-495f-474d-ba72-85c43c11da73" src="https://github.com/user-attachments/assets/42638f2f-c107-42c1-a08f-3d5a75590350" />
<img width="1910" height="873" alt="ed0b949d-e1a7-43ce-a42f-89a3473dc705" src="https://github.com/user-attachments/assets/4622b380-b610-4254-9e2f-001e0ab4ed59" />
</div>
---

## 功能全景

### 一、知识库与问答

- **三类知识库**（同级，建库时选类型）：
  - **向量知识库**：上传 PDF/Office/图片等文档，自动解析 → 分块 → 向量化 → 检索
  - **图文知识库**：直接录入「一段文字 + 配套图片/附件」，问题命中后**自动把配套文件发给提问者**（无需向量模型，走关键词检索）
  - **外部知识库**：对接 Dify / RAGFlow / FastGPT / 通用 HTTP / MCP / SQL 库 / 飞书表格 / Google Sheets，检索时实时联邦调用并融合排序
- **入库流水线**：多格式解析、父子分块/定长/递归分块、可配向量模型；失败可重灌、支持分块级编辑（改/删/拆分）
- **混合检索**：向量召回 + BM25 关键词 + RRF 融合（三路权重可调）+ 可选重排；**MMR 去冗余**提升结果多样性；**多轮追问改写**把「它/这个」等指代句结合历史压成独立 query；带**检索调试台**观察命中与分数
- **流式问答 + 引用溯源**：答案标注引用编号，可点开原文；区分「知识库资料」与「模型自身知识」防幻觉
- **内容巡检与未命中归因**：知识库健康检查（空/失败/无分块/未标签/陈旧文档）+ 高频未命中 query 聚合，便于补内容
- **问答质量评估**：建评测集（问题 + 标准答案 + 期望文档）→ 批量跑 RAG → **AI 裁判打分**（忠实度/相关性）+ 命中率 → 导出 CSV

### 二、智能体（Agent）平台

- **ReAct 工具循环**：LLM 自主多轮调用工具直到得出答案，运行过程可视化（可折叠的调用卡片）
- **90+ 管理/运维工具** + 13 个内置工具（知识检索 / HTTP / 文件读写 / 表格分析 / 办公文档生成 …）
  - 问答页按需装配工具（`find_tools` 工具路由），省 token、更快
- **技能（Skill）**：能力包（提示词+工具+知识库）与 HTTP 工具两种形态；支持**技能集合**——把多技能仓库整体导入，AI 按需加载子技能（progressive disclosure）
- **技能市场**：`find_skill` 从 GitHub 实时搜索并一键安装技能包
- **行为模式（AgentMode）**：同一智能体多套行为，运行时切换
- **工作流编排（DAG）**：15 类节点（start / llm / 检索 / 条件 / **多路分支 switch** / HTTP / 文件 / 变量 / 代码 / 循环 / **人工审批** / 协作智能体 / 消息推送 / **并行网关 parallel** / 汇聚 join / end）+ 变量引用 + 可视化画布（@xyflow/react）+ 发布/版本回滚

### 三、外部渠道与客服

- **IM 渠道接入**：QQ 机器人、微信（iLink 协议，扫码登录）、企业微信、飞书——收发消息、群聊、图片/文件
- **客服工单**：渠道转人工自动建单；分类/标签/优先级/SLA 超时告警/满意度评价；客服工作台查看双方消息（含附件）、直接回复回发渠道、发附件、客户备注
- **话术库**：预存快捷回复，客服一键引用；工单批量操作（关单/改派/改优先级/打标签）
- **渠道身份绑定**：把外部渠道身份绑定到内部账号，绑定后**继承该账号真实权限**（管理员=全权，外部客户=只读）
- **客服网关 API**：API Key 认证的对外接口，外部系统可建单/查单/追加/评价
- **多语言客服**：`/lang` 切换回答语言，或按渠道默认语言

### 四、办公与自动化

- **智能录单**：定义模板 → AI 从通话记录/聊天/邮件抽结构化台账 → 导出 Excel/CSV
- **办公文档生成**：会议纪要 / 周报日报 / 待办清单 / 公文通知（docx/pdf/xlsx/md）；表格导出支持**柱状/折线/饼图**图表
- **待办日程**：待办/日程/提醒，支持到期推送、重复规则（cron）、提前提醒
- **审批中心**：集中处理工作流中的人工审批节点，支持批准/拒绝并填写意见
- **对话导出/分享**、文档批量合并导出
- **邮件入库**：配置 IMAP，邮件正文与附件自动入库知识库
- **定时任务**：cron / 间隔 / 一次性 / **事件触发**；失败重试、任务级通知；支持**依赖链**（A 成功后自动触发 B）；**执行产物随通知附带**（如生成的报表作为邮件附件）
- **事件订阅 Webhook**：外部系统订阅平台事件（工单/文档/工作流…），带 HMAC 签名回调
- **通知渠道**：站内 / Webhook / 企业微信 / 钉钉 / 邮件 / 外部渠道（把已接入的 QQ/微信/企微/飞书兼作推送出口）

### 五、平台能力

- **MCP 客户端**：接入 http / sse / stdio 三类 MCP 服务器，工具自动注册为 AI 工具
- **模型管理**：统一 Provider 抽象（OpenAI 兼容 / Anthropi Claud / Ollama / 本地 bge / 离线 local_hash），每个 Provider 可配 chat / embedding / rerank，含连通性测试
- **RBAC + 文档级 ACL**：用户 / 角色 / 部门 / 用户组四级授权；知识库可见性（公开/内部/私有）+ 文档级例外授权 + 部门向下继承
- **审计与日志**：写操作审计、系统运行日志、内容安全检测
- **用量统计**：按模型/用户/天聚合 token 消耗；**工具调用统计**（次数/成功率/耗时）
- **API 密钥**：OpenAI 兼容接口，供外部系统调用平台
- **单点登录**：企业微信 / 钉钉 / 飞书
- **系统设置**：Web 端热改配置（含启动期项 + 重启按钮）
- **桌面版**：Electron 打包（`desktop/`）

---

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | FastAPI + SQLAlchemy 2.0 async + Uvicorn |
| 数据库 | **默认 SQLite**（零依赖），可切换 **PostgreSQL(+pgvector)** / **MySQL** |
| 向量检索 | pgvector（PG）/ numpy 应用层（SQLite/MySQL），自动切换 |
| 任务队列 | 进程内 asyncio 队列（零依赖），可换 Celery |
| 前端 | React 19 + TypeScript + Vite + antd + @xyflow/react（工作流画布） |
| 模型 | 统一 Provider 抽象层：OpenAI 兼容 / Anthropi Claud / Ollama / 本地 bge / 离线 |
| 桌面 | Electron 33 + electron-builder |

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

```bash
cd web && npm run dev
```

Vite 跑在 5173 并把 `/api` 代理到 6677。改完后 `npm run build` 让后端托管最新产物。

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

---

## 权限体系

- **租户隔离**：所有数据带 `tenant_id`。
- **权限过滤唯一入口**：`backend/app/services/permission.py` —— 所有检索的权限条件都由此生成，避免越权召回（企业 RAG 最高危点）。
- **知识库可见性**：`public`（全租户）/ `internal`（按成员）/ `private`（仅显式成员）。
- **文档级 ACL**：知识库之上的例外授权（allow/deny），支持部门向下继承。
- **principal 统一编码**：`PUBLIC=0`、`USER=1e12+id`、`DEPT=2e12+id`、`ROLE=3e12+id`、`GROUP=4e12+id`。用户 / 角色 / 部门 / 用户组四级授权均已启用。
- **渠道身份绑定**：外部渠道身份可绑定到内部账号，绑定后继承真实权限。

---

## 目录结构

```
backend/
  app/
    core/          # 配置/数据库/安全/日志/错误
    models/        # SQLAlchemy ORM（55 张表）
    schemas/       # Pydantic DTO
    api/v1/        # 35 个路由模块（kb/document/chat/agents/channels/service/…）
    services/      # permission(权限唯一入口)/retrieval/chat/eval/service_ticket/…
    agents/        # 智能体运行时：react 循环 / tools / workflow 引擎
    providers/     # 模型抽象层：base/registry/drivers/*
    retrieval/     # vector_store/bm25/fusion
    ingest/        # storage/parsers/chunkers(含父子分块)
    channels/      # IM 渠道驱动（qqbot/wxclaw/wework/feishu）
    connectors/    # 外部知识库连接器
    notifiers/     # 通知出口
    tasks/         # 进程内队列 + 入库/调度/评测/SLA 等后台任务
  scripts/         # seed.py(初始化) / 自测脚本
  data/            # SQLite 库 + 上传文件（gitignore）
web/               # 前端（39 个页面）
desktop/           # Electron 桌面版
```

---

## 常见问题

**Q: 中文关键词检索效果一般？**
默认用应用层按字分词。PostgreSQL 可启用 `zhparser` 扩展增强中文 BM25；未启用时向量单路检索仍可用。

**Q: 换 embedding 模型后检索异常？**
向量空间不兼容，需重建该知识库的向量（切换模型后重新上传文档）。

**Q: 对话无输出？**
检查「模型管理」是否配置了 chat 模型，或先用 `local_hash` 离线驱动验证链路。

**Q: 图文知识库报「向量模型」错误？**
图文知识库**不需要**向量模型，走关键词检索；若提示向量相关错误，确认库类型为「图文知识库」而非「向量知识库」。

---

## License

[MIT](LICENSE)
