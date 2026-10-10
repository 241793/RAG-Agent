"""聊天室消息广播层（进程内）。

单进程 uvicorn 下用内存连接表即可；抽成 ChatBroadcaster 便于将来多 worker
时替换为 Redis pub/sub（否则同房间成员在不同进程会收不到彼此消息）。

设计：按 (tenant_id, room_id) 维护连接集合；也维护「用户级」连接用于私聊推送与
未读角标（一个用户可能开多个标签页）。
"""
from __future__ import annotations

import asyncio
import json

from app.core.logging import get_logger

logger = get_logger("chat_ws")


class ChatBroadcaster:
    """进程内广播器：房间 → 连接集合；用户 → 连接集合。"""

    def __init__(self) -> None:
        self._rooms: dict[tuple[int, int], set] = {}
        self._users: dict[int, set] = {}
        self._lock = asyncio.Lock()

    async def join(self, *, tenant_id: int, room_id: int, user_id: int, ws) -> None:
        async with self._lock:
            self._rooms.setdefault((tenant_id, room_id), set()).add(ws)
            self._users.setdefault(user_id, set()).add(ws)

    async def leave(self, *, tenant_id: int, room_id: int, user_id: int, ws) -> None:
        async with self._lock:
            rs = self._rooms.get((tenant_id, room_id))
            if rs:
                rs.discard(ws)
                if not rs:
                    self._rooms.pop((tenant_id, room_id), None)
            us = self._users.get(user_id)
            if us:
                us.discard(ws)
                if not us:
                    self._users.pop(user_id, None)

    async def broadcast_room(self, *, tenant_id: int, room_id: int, payload: dict) -> None:
        """向房间内所有连接推送。"""
        conns = list(self._rooms.get((tenant_id, room_id), set()))
        await self._send_all(conns, payload)

    async def send_to_user(self, *, user_id: int, payload: dict) -> None:
        """向某用户的全部连接推送（私聊/角标）。"""
        conns = list(self._users.get(user_id, set()))
        await self._send_all(conns, payload)

    async def _send_all(self, conns: list, payload: dict) -> None:
        if not conns:
            return
        text = json.dumps(payload, ensure_ascii=False, default=str)
        dead = []
        for ws in conns:
            try:
                await ws.send_text(text)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    for s in self._rooms.values():
                        s.discard(ws)
                    for s in self._users.values():
                        s.discard(ws)

    def online_in_room(self, tenant_id: int, room_id: int) -> int:
        return len(self._rooms.get((tenant_id, room_id), set()))


broadcaster = ChatBroadcaster()
