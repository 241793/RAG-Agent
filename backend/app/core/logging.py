"""结构化日志（structlog）。输出到 stdout，并可选落盘（轮转文件）。"""
from __future__ import annotations

import logging
import sys

import structlog

from app.core.config import settings


def setup_logging() -> None:
    # structlog 经 stdlib logging 落地，这样文件 handler 才能接住日志
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if settings.debug else logging.INFO
        ),
        cache_logger_on_first_use=True,
    )

    # 渲染器：debug 用彩色控制台，否则 JSON（与旧行为一致）
    renderer = (
        structlog.dev.ConsoleRenderer()
        if settings.debug
        else structlog.processors.JSONRenderer()
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[structlog.processors.TimeStamper(fmt="iso")],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )
    # 文件用 JSON 渲染（无 ANSI 颜色码，便于阅读与下载）
    file_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[structlog.processors.TimeStamper(fmt="iso")],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.DEBUG if settings.debug else logging.INFO)

    # 压制第三方噪音（SQLAlchemy SQL / aiosqlite 游标操作 / httpx 请求），避免淹没业务日志
    for noisy in (
        "sqlalchemy.engine", "sqlalchemy.pool", "sqlalchemy.dialects",
        "aiosqlite", "httpx", "httpcore", "asyncio",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    root.addHandler(stream)

    # 落盘：轮转文件 handler（供「系统日志」页查看）
    if settings.log_file:
        try:
            from logging.handlers import RotatingFileHandler
            from pathlib import Path

            Path(settings.log_file).parent.mkdir(parents=True, exist_ok=True)
            fh = RotatingFileHandler(
                settings.log_file, maxBytes=settings.log_max_bytes,
                backupCount=settings.log_backup_count, encoding="utf-8",
            )
            fh.setFormatter(file_formatter)
            root.addHandler(fh)
        except Exception:  # noqa: BLE001
            pass  # 落盘失败不影响 stdout


def get_logger(name: str = "app"):
    return structlog.get_logger(name)
