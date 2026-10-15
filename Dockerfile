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

# 目录布局刻意与源码一致（backend/ + web/dist/ 并列），
# 因为 config.py 用 __file__ 上溯定位 RESOURCE_DIR（web/dist 所在）。
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/backend \
    RAG_HOST=0.0.0.0 \
    RAG_PORT=6677 \
    PORT=6677 \
    DATABASE_URL=sqlite+aiosqlite:////app/backend/data/rag.db

COPY backend/requirements.txt ./backend/requirements.txt
# INSTALL_PG=true 时额外装 PostgreSQL 驱动（用 docker compose --profile pg 时由 build.args 传入）
# fonts-wqy-zenhei：PDF 渲染中文字体（slim 基础镜像不含任何字体，缺了中文会变乱码）。
#   刻意不用 fonts-noto-cjk —— 它是 CFF/PostScript 轮廓，reportlab 的 TTFont 会直接拒绝
#   （ttfonts.py: 'postscript outlines are not supported'），必须选 TrueType 轮廓的字体。
ARG INSTALL_PG=false
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-wqy-zenhei \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r ./backend/requirements.txt \
    && if [ "$INSTALL_PG" = "true" ]; then pip install --no-cache-dir asyncpg pgvector; fi

COPY backend/ ./backend/
COPY --from=web /src/web/dist ./web/dist
# 更新日志：容器内也能读到，无需访问 GitHub（changelog_service 读 RESOURCE_DIR=/app）
COPY CHANGELOG.md ./CHANGELOG.md

# SQLite 库 + 上传文件 + 技能包 + 日志统一落在 /app/backend/data 下
VOLUME ["/app/backend/data"]
EXPOSE 6677

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:6677/health',timeout=4)"

# run_server.py 内含幂等 seed_all()：首启自动建库、建 admin/admin123 与内置角色
CMD ["python", "/app/backend/run_server.py"]
