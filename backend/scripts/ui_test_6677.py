"""统一入口(6677)前端端到端验证：登录 -> 各页面渲染。"""
from __future__ import annotations

import base64
import json
import sys
import time

import httpx

CDP = "http://127.0.0.1:9334"
BASE = "http://127.0.0.1:6677"


def new_tab(url: str) -> str:
    return httpx.put(f"{CDP}/json/new?{url}").json()["id"]


def ws_url(tab_id: str) -> str:
    for t in httpx.get(f"{CDP}/json").json():
        if t["id"] == tab_id:
            return t["webSocketDebuggerUrl"]
    raise RuntimeError("tab not found")


class C:
    def __init__(self, ws):
        import websocket
        self.ws = websocket.create_connection(ws, timeout=30)
        self.mid = 0

    def send(self, m, p=None):
        self.mid += 1
        self.ws.send(json.dumps({"id": self.mid, "method": m, "params": p or {}}))
        while True:
            r = json.loads(self.ws.recv())
            if r.get("id") == self.mid:
                return r

    def ev(self, expr, ap=False):
        return self.send("Runtime.evaluate", {"expression": expr, "awaitPromise": ap, "returnByValue": True}).get("result", {}).get("result", {}).get("value")


def main():
    tid = new_tab(BASE + "/login")
    time.sleep(3)
    c = C(ws_url(tid))
    c.send("Runtime.enable")
    c.send("Page.enable")
    time.sleep(1)
    print("[1] 登录页 title:", c.ev("document.title"), "| root:", c.ev("!!document.getElementById('root')"))

    # 登录（同源相对路径）
    r = c.ev("""(async()=>{const r=await fetch('/api/v1/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'admin',password:'admin123'})});const d=await r.json();localStorage.setItem('access_token',d.access_token);return d.access_token?'OK':'FAIL';})()""", ap=True)
    print("[2] 同源登录:", r)

    for path, kw in [("/kb", "知识库"), ("/chat", "智能问答"), ("/retrieval", "检索调试"), ("/admin/models", "模型管理")]:
        c.send("Page.navigate", {"url": BASE + path})
        time.sleep(3)
        txt = c.ev("document.body.innerText") or ""
        print(f"[3] {path} -> 渲染含'{kw}':", kw in txt, "| 长度", len(txt))

    # 截图对话页
    c.send("Page.navigate", {"url": BASE + "/chat"})
    time.sleep(3)
    shot = c.send("Page.captureScreenshot", {"format": "png"})
    data = shot.get("result", {}).get("data")
    if data:
        open("data/ui_6677.png", "wb").write(base64.b64decode(data))
        print("[4] 截图 data/ui_6677.png")
    c.ws.close()
    print("完成。")


if __name__ == "__main__":
    main()
