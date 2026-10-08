"""MCP stdio 长驻进程管理。

本地 stdio 型 MCP server 通过子进程通信；启动常含初始化开销，每次调用拉起会很慢，
因此按 server_id 复用长驻进程（JSON-RPC 逐行），空闲超时回收。

安全：仅当 settings.mcp_allow_stdio 为真、且命令首 token 在 mcp_stdio_allowed_cmds
白名单内才允许启动（防任意命令执行）。
"""
from __future__ import annotations

import asyncio
import json
import shlex
import time

from app.core.errors import ValidationError
from app.core.logging import get_logger

logger = get_logger("mcp_stdio")


def check_stdio_allowed(command: str) -> None:
    """校验 stdio 命令是否被允许（开关 + 白名单）。不通过抛 ValidationError。"""
    from app.core.config import settings

    if not settings.mcp_allow_stdio:
        raise ValidationError(
            "本地 stdio 型 MCP server 默认禁用。如确需使用，请设置环境变量 MCP_ALLOW_STDIO=true 后重启。"
        )
    if not command or not command.strip():
        raise ValidationError("stdio 型 MCP server 缺少 command")
    try:
        tokens = shlex.split(command)
    except ValueError as e:
        raise ValidationError(f"command 解析失败：{e}") from e
    if not tokens:
        raise ValidationError("stdio 型 MCP server 缺少 command")
    first = tokens[0].lower()
    allowed = {c.strip().lower() for c in settings.mcp_stdio_allowed_cmds.split(",") if c.strip()}
    base = first.replace("\\", "/").rsplit("/", 1)[-1]
    base = base[:-4] if base.endswith(".exe") else base
    if base not in allowed:
        raise ValidationError(
            f"stdio 命令不在白名单内：{tokens[0]}（允许：{', '.join(sorted(allowed))}）"
        )


class _StdioChannel:
    """单个 stdio MCP server 的长驻通道（逐行 JSON-RPC）。"""

    def __init__(self, command: str, args: list[str], env: dict | None) -> None:
        self.command = command
        self.args = list(args or [])
        self.env = dict(env or {})
        self.proc: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self.last_used = time.time()
        self._initialized = False

    async def _ensure_proc(self) -> None:
        if self.proc and self.proc.returncode is None:
            return
        import os
        import shlex

        # 兼容 "python -m foo" 形式的整串命令
        tokens = shlex.split(self.command) + self.args
        env = {**os.environ, **{str(k): str(v) for k, v in self.env.items()}}
        self.proc = await asyncio.create_subprocess_exec(
            *tokens,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self._initialized = False
        logger.info("mcp_stdio_started", pid=self.proc.pid, cmd=tokens[0])

    async def _send(self, body: dict) -> None:
        assert self.proc and self.proc.stdin
        line = (json.dumps(body, ensure_ascii=False) + "\n").encode("utf-8")
        self.proc.stdin.write(line)
        await self.proc.stdin.drain()

    async def _read_until(self, id_: int, deadline: float) -> dict:
        assert self.proc and self.proc.stdout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise ValidationError("stdio MCP 响应超时")
            try:
                raw = await asyncio.wait_for(self.proc.stdout.readline(), timeout=remaining)
            except asyncio.TimeoutError:
                raise ValidationError("stdio MCP 响应超时")
            if not raw:
                raise ValidationError("stdio MCP 进程已退出")
            try:
                obj = json.loads(raw.decode("utf-8", errors="ignore").strip() or "{}")
            except json.JSONDecodeError:
                continue  # 跳过非 JSON 行（日志等）
            if obj.get("id") == id_:
                return obj

    async def request(self, body: dict, timeout: int) -> dict:
        async with self._lock:
            await self._ensure_proc()
            self.last_used = time.time()
            deadline = time.time() + timeout
            await self._send(body)
            return await self._read_until(int(body.get("id")), deadline)

    async def close(self) -> None:
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.terminate()
                await asyncio.wait_for(self.proc.wait(), timeout=3)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    self.proc.kill()
                except Exception:  # noqa: BLE001
                    pass
        self.proc = None


class _McpManager:
    def __init__(self) -> None:
        self._channels: dict[int, _StdioChannel] = {}
        self._reaper: asyncio.Task | None = None

    async def get_stdio(self, server) -> _StdioChannel:
        check_stdio_allowed(server.command or "")
        key = server.id
        ch = self._channels.get(key)
        if ch is None:
            ch = _StdioChannel(server.command, server.args or [], server.env or {})
            self._channels[key] = ch
            self._ensure_reaper()
        return ch

    def _ensure_reaper(self) -> None:
        if self._reaper is None or self._reaper.done():
            try:
                self._reaper = asyncio.get_running_loop().create_task(self._reap())
            except RuntimeError:
                self._reaper = None

    async def _reap(self) -> None:
        from app.core.config import settings

        while True:
            await asyncio.sleep(60)
            now = time.time()
            idle = settings.mcp_stdio_idle_seconds
            for key, ch in list(self._channels.items()):
                if now - ch.last_used > idle:
                    await ch.close()
                    self._channels.pop(key, None)
                    logger.info("mcp_stdio_reaped", server_id=key)

    async def stop(self, server_id: int) -> None:
        ch = self._channels.pop(server_id, None)
        if ch:
            await ch.close()

    async def stop_all(self) -> None:
        for ch in list(self._channels.values()):
            await ch.close()
        self._channels.clear()
        if self._reaper and not self._reaper.done():
            self._reaper.cancel()


mcp_manager = _McpManager()
