"""问答页 A/B 需求浏览器验证：token 展示、模型上提、跨用户切换。"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time

import httpx

CDP = "http://127.0.0.1:9364"
BASE = "http://127.0.0.1:6677"


def main():
    # 不再按进程名全杀（会误杀用户浏览器）；改用独立 user-data-dir，退出时只清自己。
    time.sleep(2)
    edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    subprocess.Popen(
        [edge, "--headless=new", "--disable-gpu", "--no-sandbox",
         "--remote-debugging-port=9364", "--remote-allow-origins=*",
         "--user-data-dir=" + os.path.expandvars(r"%TEMP%\ragedg_chat"), "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(6)
    tid = httpx.put(f"{CDP}/json/new?about:blank").json()["id"]
    ws_url = [x["webSocketDebuggerUrl"] for x in httpx.get(f"{CDP}/json").json() if x["id"] == tid][0]
    import websocket
    ws = websocket.create_connection(ws_url, timeout=60)
    mid = [0]

    def send(m, p=None):
        mid[0] += 1
        ws.send(json.dumps({"id": mid[0], "method": m, "params": p or {}}))
        while True:
            r = json.loads(ws.recv())
            if r.get("id") == mid[0]:
                return r

    def ev(e, ap=False):
        r = send("Runtime.evaluate", {"expression": e, "awaitPromise": ap, "returnByValue": True})
        return r.get("result", {}).get("result", {}).get("value")

    send("Runtime.enable"); send("Page.enable")
    send("Emulation.setDeviceMetricsOverride", {"width": 1600, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
    send("Page.navigate", {"url": BASE + "/login"})
    time.sleep(3)
    ev("(async()=>{const r=await fetch('/api/v1/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'admin',password:'admin123'})});const d=await r.json();localStorage.setItem('access_token',d.access_token);return 'ok';})()", ap=True)
    send("Page.navigate", {"url": BASE + "/chat"})
    time.sleep(5)

    print("模型选择器常驻（顶部）:", ev("document.body.innerText.includes('模型：')"))
    print("检索范围在:", ev("document.body.innerText.includes('检索范围：')"))
    print("用量统计条-本会话累计:", ev("document.body.innerText.includes('本会话累计')"))
    print("用量统计条-今日消耗:", ev("document.body.innerText.includes('今日消耗')"))
    print("用量统计条-命中缓存:", ev("document.body.innerText.includes('命中缓存')"))
    print("跨用户切换器（admin 可见）:", ev("!!document.querySelector('.ant-select-selection-placeholder') && document.body.innerText.includes('查看用户')" ) or ev("(()=>{const s=[...document.querySelectorAll('.ant-select')];return s.some(x=>x.innerText.includes('查看用户'));})()"))
    shot = send("Page.captureScreenshot", {"format": "png"}).get("result", {}).get("data")
    if shot:
        open("data/ui_chat_ab.png", "wb").write(base64.b64decode(shot))
        print("截图 data/ui_chat_ab.png")
    ws.close()
    # 退出时只清理本脚本自己的 headless 实例（按专属 user-data-dir 匹配）
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _cdp import _kill_by_user_data_dir
    _kill_by_user_data_dir(os.path.expandvars(r'%TEMP%\ragedg_chat'))
    print("完成")


if __name__ == "__main__":
    main()
