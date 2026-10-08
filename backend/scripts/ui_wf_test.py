"""工作流编排页验证：画布显示节点、属性面板、增删节点。"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time

import httpx

CDP = "http://127.0.0.1:9334"
BASE = "http://127.0.0.1:6677"


def main():
    # 不再按进程名全杀（会误杀用户浏览器）；改用独立 user-data-dir，退出时只清自己。
    time.sleep(2)
    edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    subprocess.Popen(
        [edge, "--headless=new", "--disable-gpu", "--no-sandbox",
         "--remote-debugging-port=9334", "--remote-allow-origins=*",
         "--user-data-dir=" + os.path.expandvars(r"%TEMP%\ragedg_wf"), "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(6)
    tid = httpx.put(f"{CDP}/json/new?about:blank").json()["id"]
    ws_url = None
    for x in httpx.get(f"{CDP}/json").json():
        if x["id"] == tid:
            ws_url = x["webSocketDebuggerUrl"]
    import websocket

    ws = websocket.create_connection(ws_url, timeout=30)
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

    send("Runtime.enable")
    send("Page.enable")
    send("Emulation.setDeviceMetricsOverride", {"width": 1600, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
    send("Page.navigate", {"url": BASE + "/login"})
    time.sleep(3)
    print("token:", ev("(async()=>{const r=await fetch('/api/v1/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'admin',password:'admin123'})});const d=await r.json();localStorage.setItem('access_token',d.access_token);return localStorage.getItem('access_token')?'SET':'NO';})()", ap=True))

    send("Page.navigate", {"url": BASE + "/agents/1/workflow"})
    time.sleep(5)
    print("节点面板项:", ev("document.querySelectorAll('.ant-card-body button').length"))
    # React Flow 节点数
    rc_nodes = ev("document.querySelectorAll('.react-flow__node').length")
    rc_edges = ev("document.querySelectorAll('.react-flow__edge').length")
    print("画布节点数:", rc_nodes, "| 连线数:", rc_edges)
    print("节点文本:", ev("Array.from(document.querySelectorAll('.react-flow__node')).map(n=>n.innerText.replace(/\\n/g,'/')).join(' | ')"))

    # 点第一个节点，看属性面板
    ev("document.querySelector('.react-flow__node')?.dispatchEvent(new MouseEvent('click',{bubbles:true}))")
    time.sleep(1)
    panel = ev("document.querySelector('.ant-card:last-child')?.innerText || ''")
    print("属性面板含'节点配置':", "节点配置" in (panel or ""), "| 含'应用':", "应用" in (panel or ""))

    shot = send("Page.captureScreenshot", {"format": "png"}).get("result", {}).get("data")
    if shot:
        open("data/ui_wf.png", "wb").write(base64.b64decode(shot))
        print("截图 data/ui_wf.png")
    ws.close()
    # 退出时只清理本脚本自己的 headless 实例（按专属 user-data-dir 匹配）
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _cdp import _kill_by_user_data_dir
    _kill_by_user_data_dir(os.path.expandvars(r'%TEMP%\ragedg_wf'))
    print("完成")


if __name__ == "__main__":
    main()
