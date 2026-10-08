"""HITL 前端验证：管理员对话触发写工具 → 弹确认卡片 → 点确认 → 技能创建。"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time

import httpx

CDP_PORT = 9351
BASE = "http://127.0.0.1:6677"


def main():
    # 不再按进程名全杀（会误杀用户浏览器）；改用独立 user-data-dir，退出时只清自己。
    time.sleep(2)
    edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    subprocess.Popen(
        [edge, "--headless=new", "--disable-gpu", "--no-sandbox",
         f"--remote-debugging-port={CDP_PORT}", "--remote-allow-origins=*",
         "--user-data-dir=" + os.path.expandvars(r"%TEMP%\ragedg_hitl"), "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(6)
    cdp = f"http://127.0.0.1:{CDP_PORT}"
    tid = httpx.put(f"{cdp}/json/new?about:blank").json()["id"]
    ws_url = [x["webSocketDebuggerUrl"] for x in httpx.get(f"{cdp}/json").json() if x["id"] == tid][0]
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

    send("Page.navigate", {"url": BASE + "/agents/4/chat"})
    time.sleep(4)
    # 输入并发送
    ev("(()=>{const tas=document.querySelectorAll('textarea');const t=tas[tas.length-1];const proto=Object.getPrototypeOf(t);const set=Object.getOwnPropertyDescriptor(proto,'value').set;if(t._valueTracker)t._valueTracker.setValue('');set.call(t,'用 create_skill 工具创建名为 UI_HITL 的技能，正文写 # 界面验证');t.dispatchEvent(new Event('input',{bubbles:true}));return 'set';})()")
    time.sleep(0.5)
    ev("Array.from(document.querySelectorAll('button')).find(b=>b.innerText.replace(/\\s/g,'')==='发送')?.click()")
    # 等 LLM 触发 pending_action
    time.sleep(20)
    print("待确认卡片出现:", ev("!!document.querySelector('.ant-card-head-title') && document.body.innerText.includes('待确认操作')"))
    print("确认执行按钮:", ev("Array.from(document.querySelectorAll('button')).some(b=>b.innerText.includes('确认执行'))"))
    shot = send("Page.captureScreenshot", {"format": "png"}).get("result", {}).get("data")
    if shot:
        open("data/ui_hitl_card.png", "wb").write(base64.b64decode(shot))
        print("截图 data/ui_hitl_card.png")
    # 点确认
    ev("Array.from(document.querySelectorAll('button')).find(b=>b.innerText.includes('确认执行'))?.click()")
    time.sleep(12)
    print("卡片已处理:", ev("document.body.innerText.includes('已处理')") )
    shot2 = send("Page.captureScreenshot", {"format": "png"}).get("result", {}).get("data")
    if shot2:
        open("data/ui_hitl_done.png", "wb").write(base64.b64decode(shot2))
    # 后端核对
    tok = open("data/.token").read().strip()
    r = httpx.get(BASE + "/api/v1/skills", headers={"Authorization": "Bearer " + tok}, timeout=10)
    names = [s["name"] for s in r.json()]
    print("技能列表含 UI_HITL:", any("UI_HITL" in n for n in names))
    ws.close()
    # 退出时只清理本脚本自己的 headless 实例（按专属 user-data-dir 匹配）
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _cdp import _kill_by_user_data_dir

    _kill_by_user_data_dir(os.path.expandvars(r"%TEMP%\ragedg_hitl"))
    print("完成")


if __name__ == "__main__":
    main()
