"""验证：打开历史会话后点赞状态是否能恢复高亮。"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time

import httpx

CDP = "http://127.0.0.1:9337"
BASE = "http://127.0.0.1:6677"


def main():
    # 不再按进程名全杀（会误杀用户浏览器）；改用独立 user-data-dir，退出时只清自己。
    time.sleep(2)
    edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    subprocess.Popen(
        [edge, "--headless=new", "--disable-gpu", "--no-sandbox",
         "--remote-debugging-port=9337", "--remote-allow-origins=*",
         "--user-data-dir=" + os.path.expandvars(r"%TEMP%\ragedg_fb2"), "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(6)
    tid = httpx.put(f"{CDP}/json/new?about:blank").json()["id"]
    ws_url = [x["webSocketDebuggerUrl"] for x in httpx.get(f"{CDP}/json").json() if x["id"] == tid]
    import websocket
    ws = websocket.create_connection(ws_url[0], timeout=40)
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
    ev("(async()=>{const r=await fetch('/api/v1/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'admin',password:'admin123'})});const d=await r.json();localStorage.setItem('access_token',d.access_token);return 'ok';})()", ap=True)

    send("Page.navigate", {"url": BASE + "/agents/3/chat"})
    time.sleep(4)
    # 点击历史会话"你好"（conv4）
    print("点会话:", ev("(()=>{const it=Array.from(document.querySelectorAll('.ant-list-item')).find(x=>x.innerText.includes('你好'));if(!it)return 'not found';it.click();return 'clicked';})()"))
    time.sleep(3)
    print("助手回答存在:", ev("!!document.querySelector('.md-body')"))
    print("点赞图标数:", ev("document.querySelectorAll('.anticon-like').length"))
    print("点赞图标颜色:", ev("(()=>{const i=document.querySelector('.anticon-like');return i?getComputedStyle(i).color:'none';})()"))
    shot = send("Page.captureScreenshot", {"format": "png"}).get("result", {}).get("data")
    if shot:
        open("data/ui_agent_fb_restore.png", "wb").write(base64.b64decode(shot))
        print("截图 data/ui_agent_fb_restore.png")
    # 点踩一下，验证能改
    ev("document.querySelector('.anticon-like')?.closest('button')?.click()")
    time.sleep(2)
    print("点掉赞后颜色:", ev("(()=>{const i=document.querySelector('.anticon-like');return i?getComputedStyle(i).color:'none';})()"))
    tok = open("data/.token").read().strip()
    msgs = httpx.get(BASE + "/api/v1/chat/conversations/4/messages", headers={"Authorization": "Bearer " + tok}, timeout=10).json()
    a = [m for m in msgs if m["role"] == "assistant"]
    print("后端 msg6 feedback:", a[-1].get("feedback") if a else "(none)")
    ws.close()
    # 退出时只清理本脚本自己的 headless 实例（按专属 user-data-dir 匹配）
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _cdp import _kill_by_user_data_dir
    _kill_by_user_data_dir(os.path.expandvars(r'%TEMP%\ragedg_fb2'))
    print("完成")


if __name__ == "__main__":
    main()
