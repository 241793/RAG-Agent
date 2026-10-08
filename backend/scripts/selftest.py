"""端到端自测脚本（离线驱动，无需网络）。

流程：建离线 Provider/模型配置 → 建知识库 → 上传文档 → 等待入库 → 检索 → 对话。
用法：python scripts/selftest.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

BASE = "http://127.0.0.1:6677/api/v1"

SAMPLE_TEXT = """向量数据库是用于存储和检索高维向量的系统。常见的有 pgvector、Qdrant、Milvus。
pgvector 是 PostgreSQL 的扩展，适合中小规模、与业务数据共库的场景。
Qdrant 是独立的向量数据库，过滤与混合检索体验好，适合中大规模。

RAG（检索增强生成）通过先检索相关知识，再让大模型基于检索结果回答，
可以有效减少大模型幻觉，并让回答有据可查。

权限感知检索是企业级 RAG 的关键。它要求向量检索只召回当前用户有权访问的内容，
通常通过把权限元数据（如知识库 ID、部门、角色）写入每个分块的元数据，
并在检索 SQL 中附加过滤条件来实现。
企业落地 RAG 最常见的风险是越权召回，即用户检索到了无权限的文档内容。
"""


async def main() -> None:
    async with httpx.AsyncClient(timeout=60) as c:
        # 1. 登录
        r = await c.post(f"{BASE}/auth/login", json={"username": "admin", "password": "admin123"})
        r.raise_for_status()
        tok = r.json()["access_token"]
        H = {"Authorization": f"Bearer {tok}"}
        print("[1] 登录成功")

        # 2. 建离线 Provider
        r = await c.post(
            f"{BASE}/providers",
            headers=H,
            json={"name": "离线自测", "kind": "local_hash", "base_url": "local", "api_key": ""},
        )
        r.raise_for_status()
        pid = r.json()["id"]
        print(f"[2] Provider id={pid}")

        # 3. 建 chat + embedding 模型配置
        for purpose, model in (("chat", "local-hash"), ("embedding", "local-hash")):
            r = await c.post(
                f"{BASE}/providers/configs",
                headers=H,
                json={
                    "provider_id": pid,
                    "purpose": purpose,
                    "model_name": model,
                    "embedding_dim": 1024 if purpose == "embedding" else None,
                    "is_default": True,
                    "priority": 1,
                },
            )
            r.raise_for_status()
        print("[3] 模型配置完成 (chat + embedding)")

        # 4. 建知识库
        r = await c.post(
            f"{BASE}/kbs", headers=H,
            json={"name": "selftest_kb", "visibility": "public"},
        )
        r.raise_for_status()
        kb_id = r.json()["id"]
        print(f"[4] 知识库 id={kb_id}")

        # 5. 上传文档
        files = {"file": ("sample.txt", SAMPLE_TEXT.encode("utf-8"), "text/plain")}
        r = await c.post(f"{BASE}/documents/upload", headers=H, params={"kb_id": kb_id}, files=files)
        r.raise_for_status()
        doc_id = r.json()["id"]
        print(f"[5] 文档上传 id={doc_id}")

        # 6. 等待处理
        for _ in range(30):
            r = await c.get(f"{BASE}/documents/{doc_id}", headers=H)
            d = r.json()
            if d["status"] in ("ready", "failed"):
                print(f"[6] 处理完成 status={d['status']} chunks={d['chunk_count']} err={d.get('error_msg')}")
                break
            await asyncio.sleep(0.5)
        else:
            print("[6] 超时未完成"); return

        # 7. 检索
        r = await c.post(
            f"{BASE}/retrieval/query", headers=H,
            json={"query": "什么是权限感知检索", "kb_ids": [kb_id], "top_k": 3},
        )
        r.raise_for_status()
        chunks = r.json()["chunks"]
        print(f"[7] 检索返回 {len(chunks)} 条:")
        for ch in chunks[:3]:
            print(f"    score={ch['score']} page={ch['page']} :: {ch['content'][:50]}...")

        # 8. 对话（SSE）
        print("[8] 对话流式:")
        async with c.stream(
            "POST", f"{BASE}/chat/completions", headers=H,
            json={"kb_ids": [kb_id], "message": "什么是权限感知检索？", "top_k": 3},
        ) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("event:"):
                    evt = line[6:].strip()
                elif line.startswith("data:"):
                    data = json.loads(line[5:].strip())
                    if evt == "delta":
                        print(data.get("text", ""), end="")
                    elif evt == "citations":
                        print(f"\n    引用: {len(data['citations'])} 条")
                    elif evt == "done":
                        print("    [完成]")
        print("\n自测完成。")


if __name__ == "__main__":
    asyncio.run(main())
