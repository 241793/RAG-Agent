# ---- 阶段 1：构建前端（Vue3 + Vite）----
FROM node:20-slim AS web
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
# build 脚本 = vue-tsc --noEmit && vite build
RUN npm run build

# ---- 阶段 2：后端运行时（FastAPI + SQLite）----
FROM python:3.11-slim AS app

# 目录布局：/app 是**可挂载的工作目录**（宿主机 ./rag-web 映射到这里），
# /opt/seed 是镜像内置的种子副本 —— 首启时若 /app 为空则从种子自举。
# backend/ 与 web/dist/ 必须同级（config.py 用 __file__ 上溯定位 RESOURCE_DIR）。
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/backend \
    RAG_HOST=0.0.0.0 \
    RAG_PORT=6677 \
    PORT=6677 \
    RAG_DEPLOYMENT=docker \
    DATABASE_URL=sqlite+aiosqlite:////app/backend/data/rag.db

# 依赖装进镜像（不随源码覆盖而变；requirements 变更时由更新流程补装）
COPY backend/requirements.txt ./seed/backend/requirements.txt
# INSTALL_PG=true 时额外装 PostgreSQL 驱动（用 docker compose --profile pg 时由 build.args 传入）
# fonts-wqy-zenhei：PDF 渲染中文字体（slim 基础镜像不含任何字体，缺了中文会变乱码）。
#   刻意不用 fonts-noto-cjk —— 它是 CFF/PostScript 轮廓，reportlab 的 TTFont 会直接拒绝
#   （ttfonts.py: 'postscript outlines are not supported'），必须选 TrueType 轮廓的字体。
ARG INSTALL_PG=false
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-wqy-zenhei \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r ./seed/backend/requirements.txt \
    && if [ "$INSTALL_PG" = "true" ]; then pip install --no-cache-dir asyncpg pgvector; fi

# 种子副本：首启自举 / 更新失败回滚都用它
COPY backend/ ./seed/backend/
COPY --from=web /src/web/dist ./seed/web/dist/
COPY CHANGELOG.md ./seed/CHANGELOG.md

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# /app 由 compose 挂载到宿主机 ./rag-web（源码 + 前端 + 数据 + 更新区都在里面）
VOLUME ["/app"]
EXPOSE 6677

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:6677/health',timeout=4)"

# entrypoint 负责：自举 /app → 建 data 与 updates → 启动
# run_server.py 内含幂等 seed_all()：首启自动建库、建 admin/admin123 与内置角色
ENTRYPOINT ["/entrypoint.sh"]
