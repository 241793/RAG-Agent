"""智能体端到端自测（离线，验证 ReAct 工具循环）。

流程：登录 → 配 local_agent 模型 → 建知识库+文档 → 建 Agent → SSE 运行 → 断言工具调用序列。
"""
from __future__ import annotations

import asyncio
import json
import sys

import httpx

BASE = "http://127.0.0.1:6677/api/v1"
SAMPLE = "权限感知检索要求向量检索只召回当前用户有权访问的内容，通过把权限元数据写入分块并在检索时过滤实现。"


async def main() -> None:
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{BASE}/auth/login", json={"username": "admin", "password": "admin123"})
        tok = r.json()["access_token"]
        H = {"Authorization": f"Bearer {tok}"}
        print("[1] 登录 OK")

        # 配 local_agent provider（供 Agent 用）
        r = await c.post(f"{BASE}/providers", headers=H, json={
            "name": "离线Agent", "kind": "local_agent", "base_url": "local", "api_key": ""})
        r.raise_for_status()
        pid = r.json()["id"]
        await c.post(f"{BASE}/providers/configs", headers=H, json={
            "provider_id": pid, "purpose": "chat", "model_name": "local-agent",
            "is_default": False, "priority": 2})
        cfgs = (await c.get(f"{BASE}/providers/configs/all", headers=H)).json()
        chat_cfg = [x for x in cfgs if x["purpose"] == "chat" and x["provider_id"] == pid][0]
        print(f"[2] Agent 模型配置 id={chat_cfg['id']}")

        # 建知识库 + 文档（用已有 embedding 配置）
        r = await c.post(f"{BASE}/kbs", headers=H, json={"name": "agent_kb", "visibility": "public"})
        kb = r.json()["id"]
        files = {"file": ("a.txt", SAMPLE.encode("utf-8"), "text/plain")}
        r = await c.post(f"{BASE}/documents/upload", headers=H, params={"kb_id": kb}, files=files)
        doc = r.json()["id"]
        for _ in range(30):
            d = (await c.get(f"{BASE}/documents/{doc}", headers=H)).json()
            if d["status"] in ("ready", "failed"):
                break
            await asyncio.sleep(0.5)
        print(f"[3] 知识库 {kb} 文档 {d['status']}")

        # 建 Agent
        r = await c.post(f"{BASE}/agents", headers=H, json={
            "name": "知识助手", "type": "agent", "system_prompt": "你是企业知识助手。",
            "model_config_id": chat_cfg["id"], "kb_ids": [kb],
            "tool_config": {"builtin": {"knowledge_retrieval": {"enabled": True}}, "max_turns": 4},
        })
        r.raise_for_status()
        aid = r.json()["id"]
        print(f"[4] 创建 Agent id={aid}")

        # SSE 运行
        print("[5] 运行 Agent（观察工具调用序列）：")
        events = []
        async with c.stream("POST", f"{BASE}/agents/{aid}/run", headers=H,
                            json={"message": "什么是权限感知检索？"}) as resp:
            evt = ""
            async for line in resp.aiter_lines():
                if line.startswith("event:"):
                    evt = line[6:].strip()
                elif line.startswith("data:"):
                    data = json.loads(line[5:].strip())
                    events.append(evt)
                    if evt == "tool_call":
                        print(f"    → tool_call: {data['name']}({data['arguments'][:40]})")
                    elif evt == "tool_result":
                        print(f"    ← tool_result: {data['content'][:60]}...")
                    elif evt == "delta":
                        print(data.get("text", ""), end="")
                    elif evt == "citations":
                        print(f"\n    [引用 {len(data['citations'])} 条]")
                    elif evt == "done":
                        print(f"    [完成]")

        print(f"\n事件序列: {events}")
        assert "tool_call" in events, "未触发工具调用"
        assert "tool_result" in events, "未返回工具结果"
        assert "done" in events, "未正常结束"
        print("\n✅ Agent ReAct 循环端到端通过")


if __name__ == "__main__":
    asyncio.run(main())
