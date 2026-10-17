#!/bin/sh
# 容器入口：自举 /app（挂载到宿主机 ./rag-web）后启动服务。
#
# 为什么需要自举：compose 把宿主机空目录挂到 /app 时，会遮住镜像里的内容。
# 因此镜像把原始代码放在 /opt/seed，这里检测 /app 是否完整，缺了就复制过去。
set -e

SEED=/opt/seed
WORK=/app

log() { echo "[entrypoint] $*"; }

mkdir -p "$WORK"

# ---- 1) 自举 backend：以 app/main.py 是否存在作为完整性判据 ----
if [ ! -f "$WORK/backend/app/main.py" ]; then
  log "初始化 backend（首次启动或目录不完整）"
  mkdir -p "$WORK/backend"
  # 用 . 结尾复制目录内容，避免多套一层
  cp -a "$SEED/backend/." "$WORK/backend/"
else
  log "backend 已存在，跳过初始化"
fi

# ---- 2) 自举前端产物：以 index.html 为判据 ----
if [ ! -f "$WORK/web/dist/index.html" ]; then
  log "初始化 web/dist（首次启动或前端缺失）"
  mkdir -p "$WORK/web"
  cp -a "$SEED/web/dist" "$WORK/web/dist"
else
  log "web/dist 已存在，跳过初始化"
fi

# ---- 3) 更新日志（供 changelog_service 读 RESOURCE_DIR）----
if [ ! -f "$WORK/CHANGELOG.md" ]; then
  cp -a "$SEED/CHANGELOG.md" "$WORK/CHANGELOG.md" 2>/dev/null || true
fi

# ---- 4) 运行时目录 ----
mkdir -p "$WORK/backend/data" "$WORK/updates"

# 数据目录权限（挂载卷可能由 root 创建）
if [ -d "$WORK/backend/data" ] && [ ! -w "$WORK/backend/data" ]; then
  log "警告：$WORK/backend/data 不可写，请检查宿主机目录权限"
fi

# ---- 5) 清理上次更新遗留的中间状态（避免半更新状态卡死）----
if [ -f "$WORK/updates/apply.requested" ]; then
  log "发现未完成的更新请求，交由服务内的看门狗处理"
fi

log "启动服务（工作目录 $WORK）"
exec python "$WORK/backend/run_server.py"
