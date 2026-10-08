"""全局配置：从 .env 读取，支持数据库/向量/存储/任务多后端切换。

路径策略（打包友好）：
- 源码运行：BASE_DIR = 项目根目录；数据在 backend/data/
- 冻结运行（PyInstaller）：BASE_DIR = 可执行文件所在目录（绿色版：数据跟随 exe），
  只读资源（前端 dist）在 sys._MEIPASS。
"""
from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _base_dir() -> Path:
    """可写根目录：
    - 冻结态：优先环境变量 RAG_DATA_DIR；否则用 %APPDATA%/RAG知识库，
      避免写入只读的安装目录（Program Files）。
    - 源码态：backend 目录。
    """
    if _is_frozen():
        env_dir = os.environ.get("RAG_DATA_DIR")
        if env_dir:
            return Path(env_dir)
        appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
        return Path(appdata) / "RAG知识库"
    return Path(__file__).resolve().parent.parent.parent  # backend/


def _project_root() -> Path:
    """项目根目录（含 web/ 前端）。源码态 = backend 的上级。"""
    if _is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent.parent  # 项目根


def _resource_dir() -> Path:
    """只读资源目录：冻结时是 _MEIPASS，否则是项目根（web/dist 所在）。"""
    if _is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return _project_root()


BASE_DIR = _base_dir()          # 可写：数据库、上传文件、.env
RESOURCE_DIR = _resource_dir()  # 只读：前端 dist 等

# 数据统一放 BASE_DIR/data（冻结态默认为 %APPDATA%/RAG知识库/data）
DATA_DIR = BASE_DIR / "data"
# 确保数据目录存在（SQLite 需目录已存在，冻结态尤其关键）
DATA_DIR.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # 应用
    app_name: str = "RAG Knowledge Base"
    app_env: str = "prod" if _is_frozen() else "dev"
    debug: bool = not _is_frozen()
    api_prefix: str = "/api/v1"
    port: int = 6677

    # 数据库
    database_url: str = f"sqlite+aiosqlite:///{(DATA_DIR / 'rag.db').as_posix()}"

    # 向量
    vector_backend: str = "auto"  # auto | pgvector | numpy
    embedding_dim: int = 1024
    vector_max_scan: int = 0  # NumpyStore 单次扫描上限（0=不限，防超大库 OOM）

    # 检索
    retrieval_top_k: int = 5
    retrieval_candidate_k: int = 20
    retrieval_vec_min: float = 0.0    # 向量召回前置门（0=不过滤）
    retrieval_bm25_min: float = 0.0   # BM25 召回前置门（0=不过滤）
    rerank_enabled: bool = False      # 是否启用重排
    rerank_pool: int = 30             # 进重排的候选数
    rerank_allow_fake: bool = False   # 允许 local_hash 假重排（仅自测）
    embedding_fallback_local: bool = True  # 上游 embedding 失败时回退到本地 local_hash（保证入库）
    provider_health_interval_min: int = 30  # Provider 健康检查周期（分钟，0=关闭）
    inject_capabilities_default: bool = True  # 向 AI 注入「平台能力 + 账号权限」摘要
    github_token: str = ""  # 搜索技能用（GitHub API Token）；配置后 search 限流 10→30 次/分钟

    # 外部知识库连接器
    connector_allow_private: bool = False  # 允许外部源指向内网/环回（企业内网部署时开启）
    connector_default_timeout: int = 15    # 连接器出站超时（秒）
    connector_max_top_k: int = 20          # 外部源单次召回的候选上限

    # MCP（Model Context Protocol）
    mcp_allow_stdio: bool = False           # 是否允许本地 stdio 型 MCP server（会执行命令）
    mcp_stdio_allowed_cmds: str = "python,python3,node,npx,uvx"  # stdio 命令白名单（首 token）
    mcp_default_timeout: int = 30           # MCP 调用超时（秒）
    mcp_stdio_idle_seconds: int = 600       # stdio 长驻进程空闲回收（秒）

    # 客服
    service_notify_on_reply: bool = True    # 客户在工单里有新回复时通知客服（全局默认；工单级可覆盖）
    # 邮件入库（IMAP）
    email_poll_interval_seconds: int = 300  # 邮件源轮询周期（秒，0=关闭）

    # 安全
    secret_key: str = "change-me-to-a-long-random-string-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440
    refresh_token_expire_minutes: int = 10080
    file_token_expire_minutes: int = 30  # 文件访问签名 URL 有效期

    # 存储
    storage_backend: str = "local"
    storage_local_dir: str = str(DATA_DIR / "files")
    # 技能包解压目录
    skill_pack_dir: str = str(DATA_DIR / "skills")
    # 运行日志落盘（轮转）；空字符串=只输出到 stdout
    log_file: str = str(DATA_DIR / "logs" / "app.log")
    log_max_bytes: int = 10 * 1024 * 1024
    log_backup_count: int = 5
    log_retention_days: int = 7            # 备份日志保留天数
    log_cleanup_interval_hours: int = 6    # 自动清理周期（小时，0=关闭）

    # 任务
    task_backend: str = "memory"  # memory | celery
    redis_url: str = "redis://localhost:6379/1"
    # 定时任务
    scheduler_max_concurrency: int = 4       # 同时在跑的定时任务数上限
    scheduler_max_retries_cap: int = 10      # 单任务重试次数硬上限（防放大）
    scheduler_history_keep: int = 200        # 每任务保留的历史条数

    # 内容安全（本地检测器）
    security_guard_enabled: bool = True
    security_guard_block_threshold: int = 70  # 达到则拦截
    security_guard_flag_threshold: int = 30  # 达到则标记
    security_guard_wrap_context: bool = True  # 是否给检索内容加边界标记
    security_guard_sensitive_words: str = ""  # 逗号分隔的敏感词

    # 默认 Provider
    default_llm_base_url: str = ""
    default_llm_api_key: str = ""
    default_llm_model: str = "gpt-4o-mini"
    default_embedding_base_url: str = ""
    default_embedding_api_key: str = ""
    default_embedding_model: str = "text-embedding-3-small"

    # CORS
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_postgres(self) -> bool:
        return "postgres" in self.database_url

    @property
    def is_mysql(self) -> bool:
        return "mysql" in self.database_url

    @property
    def resolved_vector_backend(self) -> str:
        """解析向量后端：auto 时依据 DB 类型决定。"""
        if self.vector_backend != "auto":
            return self.vector_backend
        return "pgvector" if self.is_postgres else "numpy"

    @property
    def storage_dir(self) -> Path:
        p = Path(self.storage_local_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def skill_pack_path(self) -> Path:
        p = Path(self.skill_pack_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
