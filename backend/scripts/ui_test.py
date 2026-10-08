"""通过 CDP 驱动 Edge/Chrome 做前端端到端验证。"""
from __future__ import annotations

import base64
import json
import time

import httpx

CDP = "http://127.0.0.1:9334"
FRONT = "http://127.0.0.1:5173"


def new_tab(url: str) -> str:
    r = httpx.put(f"{CDP}/json/new?{url}")
    return r.json()["id"]


def ws_url(tab_id: str) -> str:
    tabs = httpx.get(f"{CDP}/json").json()
    for t in tabs:
        if t["id"] == tab_id:
            return t["webSocketDebuggerUrl"]
    raise RuntimeError("tab not found")


class CDPClient:
    def __init__(self, ws: str) -> None:
        import websocket  # type: ignore

        self.ws = websocket.create_connection(ws, timeout=30)
        self.mid = 0

    def send(self, method: str, params: dict | None = None) -> dict:
        self.mid += 1
        self.ws.send(json.dumps({"id": self.mid, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.mid:
                return msg

    def eval(self, expr: str, await_promise: bool = False):
        r = self.send(
            "Runtime.evaluate",
            {"expression": expr, "awaitPromise": await_promise, "returnByValue": True},
        )
        return r.get("result", {}).get("result", {}).get("value")

    def close(self):
        self.ws.close()


def main() -> None:
    tid = new_tab(FRONT + "/login")
    time.sleep(3)
    c = CDPClient(ws_url(tid))
    c.send("Runtime.enable")
    c.send("Page.enable")
    time.sleep(1)

    # 1. 页面标题/根节点
    title = c.eval("document.title")
    has_root = c.eval("!!document.getElementById('root')")
    body_len = c.eval("document.body.innerText.length")
    print(f"[1] title={title!r} root={has_root} bodyTextLen={body_len}")

    # 2. 执行登录（调用前端同款接口，写入 localStorage）
    login_js = """
    (async () => {
      const r = await fetch('http://127.0.0.1:5173/api/v1/auth/login', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({username:'admin',password:'admin123'})
      });
      const d = await r.json();
      localStorage.setItem('access_token', d.access_token);
      localStorage.setItem('refresh_token', d.refresh_token);
      return d.access_token ? 'OK' : 'FAIL';
    })()
    """
    print("[2] 登录:", c.eval(login_js, await_promise=True))

    # 3. 导航到知识库页
    c.send("Page.navigate", {"url": FRONT + "/kb"})
    time.sleep(4)
    kb_text = c.eval("document.body.innerText")
    print("[3] 知识库页含'知识库':", "知识库" in (kb_text or ""))
    print("    页面片段:", repr((kb_text or "")[:150]))

    # 4. 导航到对话页
    c.send("Page.navigate", {"url": FRONT + "/chat"})
    time.sleep(3)
    chat_text = c.eval("document.body.innerText")
    print("[4] 对话页加载:", "智能问答" in (chat_text or "") or "选择" in (chat_text or ""), repr((chat_text or "")[:120]))

    # 5. 模型管理页
    c.send("Page.navigate", {"url": FRONT + "/admin/models"})
    time.sleep(3)
    m_text = c.eval("document.body.innerText")
    print("[5] 模型管理页:", "Provider" in (m_text or ""), repr((m_text or "")[:120]))

    # 6. 截图
    shot = c.send("Page.captureScreenshot", {"format": "png"})
    data = shot.get("result", {}).get("data")
    if data:
        with open("data/ui_models.png", "wb") as f:
            f.write(base64.b64decode(data))
        print("[6] 截图已保存 data/ui_models.png")

    c.close()
    print("前端验证完成。")


if __name__ == "__main__":
    main()
