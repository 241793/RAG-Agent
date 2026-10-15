"""更新日志服务：解析 CHANGELOG.md，本地优先、GitHub Release 兜底。

设计要点（勿凭直觉改动）：

1. **本地文件优先**：CHANGELOG.md 已打进桌面版包内、也已 COPY 进 Docker 镜像，
   因此内网 / 离线环境也能读到更新内容。这是相对「只读 GitHub Release」的关键优势。
2. **必须容错**：CHANGELOG 是人工维护的 Markdown，格式可能有出入（缺日期、
   `[Unreleased]`、多余空行）。解析器只做尽力而为，绝不因格式问题抛异常。
3. **兜底不臆造**：本地与 GitHub 都拿不到时返回 `source="none"` 且空列表，
   前端据此隐藏滚动条 —— 而不是编一段假内容。
"""
from __future__ import annotations

import re
import time

from app.core.config import RESOURCE_DIR, settings
from app.core.logging import get_logger

logger = get_logger("changelog")

# 版本块标题：## [1.0.1] - 2026-10-20 / ## [1.0.1] / ## 1.0.1
# 同时容忍 [Unreleased]
_H2_RE = re.compile(r"^##\s+\[?([^\]\s]+)\]?\s*(?:-\s*(.+?))?\s*$")
# 分组标题：### 新增
_H3_RE = re.compile(r"^###\s+(.+?)\s*$")
# 条目：- xxx / * xxx
_ITEM_RE = re.compile(r"^[-*]\s+(.+?)\s*$")

_CACHE_TTL = 300  # 5 分钟：本地文件变动不频繁，也避免频繁读盘
_cache: dict[str, object] = {"ts": 0.0, "data": None}


# 「未发布」段（Keep a Changelog 约定）不是给终端用户看的更新日志：
# 它常含开发待办，展示到滚动条上会泄露内部信息。运行时一律过滤掉。
_SKIP_VERSIONS = {"unreleased", "未发布"}


def parse_changelog(text: str, *, keep_unreleased: bool = False) -> list[dict]:
    """把 Keep-a-Changelog 文本解析为版本块列表（新→旧）。

    返回 `[{version, date, sections:[{title, items:[...]}]}, ...]`
    无法识别的行会被跳过；格式异常不抛错。
    """
    if not text:
        return []

    versions: list[dict] = []
    cur: dict | None = None
    cur_sec: dict | None = None

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue

        m2 = _H2_RE.match(line)
        if m2:
            name, date = m2.group(1).strip(), (m2.group(2) or "").strip()
            # 跳过「未发布」段（内含开发待办，不应展示给终端用户）
            if not keep_unreleased and name.lower() in _SKIP_VERSIONS:
                cur, cur_sec = None, None
                continue
            # 跳过「更新日志」这类文档大标题之外的一级标题干扰
            cur = {"version": name, "date": date or None, "sections": []}
            versions.append(cur)
            cur_sec = None
            continue

        m3 = _H3_RE.match(line)
        if m3 and cur is not None:
            cur_sec = {"title": m3.group(1).strip(), "items": []}
            cur["sections"].append(cur_sec)
            continue

        mi = _ITEM_RE.match(line)
        if mi and cur is not None:
            item = mi.group(1).strip()
            if not item:
                continue
            # 条目出现在任何分组标题之前时，归入「变更」
            if cur_sec is None:
                cur_sec = {"title": "变更", "items": []}
                cur["sections"].append(cur_sec)
            cur_sec["items"].append(item)
            continue

    return versions


def _strip_markdown_link(s: str) -> str:
    """把 Markdown 行内链接/加粗简化掉，让滚动条文案干净。"""
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = s.replace("**", "").replace("`", "")
    return s.strip()


def load_local() -> str | None:
    """读取打进包内 / 仓库内的 CHANGELOG.md。读不到返回 None。"""
    try:
        f = RESOURCE_DIR / "CHANGELOG.md"
        if f.is_file():
            return f.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        logger.warning("changelog_local_read_failed")
    return None


def _from_release(notes: str, version: str, date: str | None, url: str | None) -> list[dict]:
    """把 Release 正文转成一个版本块（复用同一套解析）。"""
    if not notes:
        return []
    lines = notes.splitlines()
    # Release 正文通常没有 ## 标题，补一个再解析；已有标题则不重复加
    if not (lines and _H2_RE.match(lines[0])):
        notes = f"## {version}\n{notes}"
    parsed = parse_changelog(notes)
    if parsed:
        parsed[0]["date"] = date or parsed[0].get("date")
        parsed[0]["url"] = url
    return parsed


async def get_changelog(*, force: bool = False) -> dict:
    """获取更新日志。本地优先，GitHub Release 兜底。永不抛异常。"""
    now = time.time()
    if (
        not force
        and _cache.get("data") is not None
        and (now - float(_cache.get("ts") or 0)) < _CACHE_TTL
    ):
        return {**_cache["data"], "cached": True}  # type: ignore[arg-type]

    versions: list[dict] = []
    source = "none"

    # 1) 本地 CHANGELOG.md
    local = load_local()
    if local:
        versions = parse_changelog(local)
        if versions:
            source = "local"

    # 2) 兜底：GitHub Release 正文
    if not versions:
        try:
            from app.services import update_service

            info = await update_service.check_update()
            if info.get("notes"):
                versions = _from_release(
                    info["notes"],
                    str(info.get("latest") or settings.app_version),
                    info.get("published_at"),
                    info.get("html_url"),
                )
                if versions:
                    source = "release"
        except Exception:  # noqa: BLE001
            logger.warning("changelog_release_fallback_failed")

    for v in versions:
        for sec in v.get("sections", []):
            sec["items"] = [_strip_markdown_link(i) for i in sec.get("items", [])]

    data = {
        "ok": True,
        "source": source,
        "current": settings.app_version,
        "latest": versions[0] if versions else None,
        "history": versions,
    }
    _cache.update({"ts": now, "data": data})
    return {**data, "cached": False}


def clear_cache() -> None:
    _cache.update({"ts": 0.0, "data": None})
