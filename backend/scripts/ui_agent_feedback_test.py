"""智能体对话页点赞验证：发消息→点赞→刷新会话→反馈仍在。"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time

import httpx

CDP = "http://127.0.0.1:9336"
BASE = "http://127.0.0.1:6677"


def main():
    # 不再按进程名全杀（会误杀用户浏览器）；改用独立 user-data-dir，退出时只清自己。
    time.sleep(2)
    edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    subprocess.Popen(
        [edge, "--headless=new", "--disable-gpu", "--no-sandbox",
         "--remote-debugging-port=9336", "--remote-allow-origins=*",
         "--user-data-dir=" + os.path.expandvars(r"%TEMP%\ragedg_fb"), "about:blank"],
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

    # 打开智能体 3 的对话页（工作流型，能快速返回）
    send("Page.navigate", {"url": BASE + "/agents/3/chat"})
    time.sleep(4)
    print("页面标题区:", ev("document.body.innerText.includes('智能体')"))
    # 输入并发送
    ev("(()=>{const tas=document.querySelectorAll('textarea');const t=tas[tas.length-1];const proto=Object.getPrototypeOf(t);const setter=Object.getOwnPropertyDescriptor(proto,'value').set;if(t._valueTracker)t._valueTracker.setValue('');setter.call(t,'say hi');t.dispatchEvent(new Event('input',{bubbles:true}));return 'set';})()")
    time.sleep(0.5)
    ev("Array.from(document.querySelectorAll('button')).find(b=>b.innerText.replace(/\\s/g,'')==='发送')?.click()")
    time.sleep(14)
    print("助手回答存在:", ev("!!document.querySelector('.md-body')"))
    likes = ev("document.querySelectorAll('button[title], button').length")
    # 点赞：找 LikeOutlined 对应的按钮（anticon-like）
    print("点赞按钮数:", ev("document.querySelectorAll('.anticon-like').length"))
    ev("document.querySelector('.anticon-like')?.closest('button')?.click()")
    time.sleep(2)
    print("点赞后颜色(应为绿色):", ev("(()=>{const i=document.querySelector('.anticon-like');return i?getComputedStyle(i.parentElement).color:'none';})()"))
    shot = send("Page.captureScreenshot", {"format": "png"}).get("result", {}).get("data")
    if shot:
        open("data/ui_agent_fb.png", "wb").write(base64.b64decode(shot))
    # 后端核对最新助手消息 feedback
    tok = open("data/.token").read().strip()
    convs = httpx.get(BASE + "/api/v1/chat/conversations", headers={"Authorization": "Bearer " + tok}, timeout=10).json()
    cid = convs[0]["id"]
    msgs = httpx.get(BASE + f"/api/v1/chat/conversations/{cid}/messages", headers={"Authorization": "Bearer " + tok}, timeout=10).json()
    asst = [m for m in msgs if m["role"] == "assistant"]
    print("后端最新助手消息 feedback:", asst[-1].get("feedback") if asst else "(none)")
    ws.close()
    # 退出时只清理本脚本自己的 headless 实例（按专属 user-data-dir 匹配）
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _cdp import _kill_by_user_data_dir
    _kill_by_user_data_dir(os.path.expandvars(r'%TEMP%\ragedg_fb'))
    print("完成")


if __name__ == "__main__":
    main()
