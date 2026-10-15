"""更新检查服务：查询 GitHub Release，判断是否有新版本。

设计要点（勿凭直觉改动）：

1. **复用 `skill_search_service._gh_get`** —— 它已带 SSRF 校验（`_check_url`，放行
   github.com 等公网）与限流识别，无需另造一套出站逻辑。
2. **不引入 `packaging` 依赖**：仓库 `requirements.txt` 里没有，且更新检查是
   安全路径，不该为它新增依赖。自写语义化版本比较即可满足 `1.0.10 > 1.0.9`。
3. **未认证 GitHub API 仅 60 次/小时/IP**，故加内存缓存 + ETag 透传（304 不扣配额）。
4. **优雅降级是硬要求**：离线/限流/超时一律返回 `ok=False`，绝不抛 500、
   绝不臆造版本号（臆造会让用户看到不存在的「新版本」）。
5. 部署形态决定「更新」的含义：只有桌面版能自更新；Docker/源码只回报可执行命令。
"""
from __future__ import annotations

import re
import time

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("update")

GITHUB_API = "https://api.github.com"

# 缓存 TTL（秒）：避免每次打开页面都打 GitHub（未认证仅 60 次/小时）
_CACHE_TTL = 15 * 60
_cache: dict[str, object] = {"ts": 0.0, "data": None}

# 预发布标记：默认不计为「有更新」，避免把 rc/beta 推给普通用户
_PRERELEASE_RE = re.compile(r"-")


def _parse_version(v: str) -> tuple[int, ...] | None:
    """把 'v1.2.3' / '1.2.3-rc1' 解析为可比较的元组。无法解析返回 None。"""
    s = (v or "").strip().lstrip("vV")
    # 只取主版本部分（忽略 -rc1 / +build 等后缀）
    core = re.split(r"[-+]", s, maxsplit=1)[0]
    if not core:
        return None
    parts = core.split(".")
    out: list[int] = []
    for p in parts:
        if not p.isdigit():
            return None
        out.append(int(p))
    return tuple(out) if out else None


def is_newer(latest: str, current: str) -> bool:
    """latest 是否比 current 新。任一侧不可解析时返回 False（保守，不误报更新）。"""
    a = _parse_version(latest)
    b = _parse_version(current)
    if a is None or b is None:
        return False
    # 补齐长度后逐段比较（1.0 → 1.0.0）
    n = max(len(a), len(b))
    a = a + (0,) * (n - len(a))
    b = b + (0,) * (n - len(b))
    return a > b


def is_prerelease(tag: str) -> bool:
    """tag 是否为预发布（含 -rc/-beta/-alpha 等）。"""
    return bool(_PRERELEASE_RE.search((tag or "").strip().lstrip("vV")))


def detect_deployment() -> str:
    """判定部署形态：desktop（可自更新）/ docker / source。"""
    import os
    import sys
    from pathlib import Path

    # Docker：存在 /.dockerenv 或 /proc/1/cgroup 含 docker/kubepods
    try:
        if Path("/.dockerenv").exists():
            return "docker"
        if Path("/proc/1/cgroup").exists():
            txt = Path("/proc/1/cgroup").read_text(errors="ignore")
            if "docker" in txt or "kubepods" in txt:
                return "docker"
    except Exception:  # noqa: BLE001
        pass
    if os.environ.get("RAG_DEPLOYMENT", "").strip() in ("desktop", "docker", "source"):
        return os.environ["RAG_DEPLOYMENT"].strip()
    # 冻结态（PyInstaller）视为桌面版；桌面版由 Electron 注入 RAG_DATA_DIR
    if getattr(sys, "frozen", False):
        return "desktop"
    return "source"


def _hint_for(deployment: str, version: str, image: str) -> str:
    """不同部署形态对应的人工更新命令（桌面版走应用内更新，无需命令）。"""
    if deployment == "docker":
        return f"docker pull {image}:{version} && docker compose up -d"
    if deployment == "source":
        return "git pull && cd web && npm ci && npm run build，然后重启后端"
    return "在「关于/更新」中点击「立即更新」，下载完成后会自动重启应用"


def _pick_asset(assets: list[dict]) -> dict | None:
    """挑选桌面版更新包：优先 win-x64.zip。"""
    for a in assets:
        name = (a.get("name") or "").lower()
        if name.endswith(".zip") and "win-x64" in name:
            return a
    return None


async def check_update(*, force: bool = False) -> dict:
    """检查是否有新版本。永不抛异常，失败时返回 {"ok": False, "error": ...}。"""
    from app.services.skill_search_service import _gh_get, _rate_limited

    current = settings.app_version
    deployment = detect_deployment()
    repo = (getattr(settings, "update_repo", "") or "241793/RAG-Agent").strip()
    image = f"ghcr.io/{repo.lower()}"

    base = {
        "ok": True,
        "current": current,
        "deployment": deployment,
        "repo": repo,
        "releases_url": f"https://github.com/{repo}/releases",
    }

    # 缓存命中（非强制刷新）
    now = time.time()
    cached = _cache.get("data")
    cached_repo = _cache.get("repo")
    if (
        not force
        and cached is not None
        and cached_repo == repo
        and (now - float(_cache.get("ts") or 0)) < _CACHE_TTL
    ):
        return {**cached, "cached": True}  # type: ignore[arg-type]

    if not getattr(settings, "update_check_enabled", True):
        return {**base, "update_available": False, "latest": current,
                "disabled": True, "error": "更新检查已在系统设置中关闭"}

    token = getattr(settings, "github_token", "") or None
    try:
        status, data, headers = await _gh_get(
            f"/repos/{repo}/releases/latest", token=token, timeout=15
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("update_check_failed", err=str(e)[:200])
        return {**base, "ok": False, "update_available": False, "latest": None,
                "error": f"无法连接更新服务：{str(e)[:120]}"}

    if _rate_limited(status, headers):
        return {**base, "ok": False, "update_available": False, "latest": None,
                "error": "GitHub API 已限流，请稍后再试或在系统设置中配置 GitHub Token"}

    if status == 404:
        return {**base, "ok": False, "update_available": False, "latest": None,
                "error": f"未找到仓库 {repo} 的 Release（仓库需为公开；私有仓库请配置 GitHub Token）"}

    if status != 200 or not isinstance(data, dict):
        return {**base, "ok": False, "update_available": False, "latest": None,
                "error": f"更新服务返回异常（HTTP {status}）"}

    tag = (data.get("tag_name") or "").strip()
    latest_ver = tag.lstrip("vV")
    notes = (data.get("body") or "").strip()
    assets = data.get("assets") or []
    asset = _pick_asset(assets)
    prerelease = bool(data.get("prerelease")) or is_prerelease(tag)

    result = {
        **base,
        "latest": latest_ver,
        "tag": tag,
        "update_available": is_newer(latest_ver, current),
        "prerelease": prerelease,
        "published_at": data.get("published_at"),
        "notes": notes[:8000],
        "html_url": data.get("html_url"),
        "can_self_update": deployment == "desktop" and asset is not None,
        "asset": (
            {
                "name": asset.get("name"),
                "size": asset.get("size"),
                "digest": asset.get("digest"),
                "url": asset.get("browser_download_url"),
            }
            if asset
            else None
        ),
        "hint": _hint_for(deployment, latest_ver, image),
    }

    _cache.update({"ts": now, "data": result, "repo": repo})
    return {**result, "cached": False}


def clear_cache() -> None:
    """清空缓存（测试与手动刷新用）。"""
    _cache.update({"ts": 0.0, "data": None, "repo": None})
