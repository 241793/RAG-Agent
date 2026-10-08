"""FastAPI 应用装配（统一入口：API + 前端静态文件同端口）。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config import RESOURCE_DIR, settings
from app.core.db import init_models
from app.core.errors import AppError, app_error_handler, unhandled_error_handler
from app.core.logging import get_logger, setup_logging
from app.middleware.request_id import RequestContextMiddleware
from app.tasks.queue import start_workers, stop_workers

setup_logging()
logger = get_logger("main")

# 前端构建产物目录（web/dist）：
# - 源码运行：项目根/web/dist
# - 冻结运行：_MEIPASS/web/dist（PyInstaller --add-data 打入）
WEB_DIST = RESOURCE_DIR / "web" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_models()
    # 叠加 Web 端「系统设置」的覆盖值（热生效项立即生效；启动期项影响本进程）
    try:
        from app.core.db import AsyncSessionLocal
        from app.services.settings_service import apply_overrides

        async with AsyncSessionLocal() as _db:
            await apply_overrides(_db)
    except Exception:  # noqa: BLE001
        logger.exception("settings_overrides_failed")
    if settings.task_backend == "memory":
        await start_workers(2)
    # 后台产物过期清理循环
    import asyncio

    from app.tasks.artifact_tasks import periodic_cleanup
    from app.tasks.scheduler_tasks import scheduler_loop

    cleanup_task = asyncio.create_task(periodic_cleanup())
    scheduler_task = asyncio.create_task(scheduler_loop())

    # Provider 健康检查（周期可配，0=关闭）
    from app.tasks.health_tasks import periodic_health_check

    health_task = asyncio.create_task(
        periodic_health_check(settings.provider_health_interval_min * 60)
    )

    # 日志自动清理（按保留天数）
    from app.tasks.log_tasks import periodic_log_cleanup

    log_task = asyncio.create_task(
        periodic_log_cleanup(settings.log_cleanup_interval_hours * 3600)
    )

    # 邮件入库源轮询
    from app.tasks.email_tasks import periodic_email_poll

    email_task = asyncio.create_task(
        periodic_email_poll(settings.email_poll_interval_seconds)
    )

    # 客服工单 SLA 超时扫描
    from app.tasks.sla_tasks import periodic_sla_check

    sla_task = asyncio.create_task(periodic_sla_check(300))

    # 外部 IM 渠道宿主（长连接）
    from app.channels.manager import channel_manager

    try:
        await channel_manager.start_all()
    except Exception:  # noqa: BLE001
        logger.exception("channels_start_failed")

    logger.info(
        "app_started",
        db=settings.database_url.split("://")[0],
        vector=settings.resolved_vector_backend,
        tasks=settings.task_backend,
    )
    yield
    cleanup_task.cancel()
    scheduler_task.cancel()
    health_task.cancel()
    log_task.cancel()
    email_task.cancel()
    sla_task.cancel()
    try:
        await channel_manager.stop_all()
    except Exception:  # noqa: BLE001
        pass
    # MCP stdio 长驻进程清理
    from app.services.mcp_manager import mcp_manager

    try:
        await mcp_manager.stop_all()
    except Exception:  # noqa: BLE001
        pass
    if settings.task_backend == "memory":
        await stop_workers()
    logger.info("app_stopped")


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)

app.include_router(api_router, prefix=settings.api_prefix)

# OpenAI 兼容端点（根路径 /v1，供内部系统用现成 SDK 接入）
from app.api.v1.openai_compat import router as openai_router  # noqa: E402

app.include_router(openai_router)


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "db": settings.database_url.split("://")[0],
        "vector_backend": settings.resolved_vector_backend,
        "task_backend": settings.task_backend,
    }


# ---- 前端静态托管（统一入口：浏览器只访问本端口）----
if WEB_DIST.exists():
    # 静态资源（js/css/img）
    assets_dir = WEB_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(str(WEB_DIST / "index.html"))

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        """SPA 前端路由回退：非 API 路径一律返回 index.html。"""
        # API / 文档路径不走前端回退（注册顺序已保证 API 优先，此处再兜底）
        if full_path.startswith(("api/", "v1/")) or full_path in ("docs", "openapi.json", "health"):
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Not Found")
        candidate = WEB_DIST / full_path
        if candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(WEB_DIST / "index.html"))
else:
    logger.warning("web_dist_missing", path=str(WEB_DIST), hint="前端未构建，仅提供 API。运行 cd web && npm run build")
