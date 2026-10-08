"""P4 页面浏览器验证：登录 -> 各新页面渲染。"""
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
         "--user-data-dir=" + os.path.expandvars(r"%TEMP%\ragedg_p4v"), "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(6)
    tid = httpx.put(f"{CDP}/json/new?{BASE}/login").json()["id"]
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
    send("Emulation.setDeviceMetricsOverride", {"width": 1400, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
    time.sleep(1)
    ev("""(async()=>{const r=await fetch('/api/v1/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'admin',password:'admin123'})});const d=await r.json();localStorage.setItem('access_token',d.access_token);return 'OK';})()""", ap=True)
    pages = [
        ("/admin/audit", "审计日志"),
        ("/admin/api-keys", "API 密钥"),
        ("/admin/sso", "单点登录"),
        ("/admin/usage", "用量统计"),
        ("/chat", "智能问答"),
        ("/skills", "技能"),
    ]
    for path, kw in pages:
        send("Page.navigate", {"url": BASE + path})
        time.sleep(2.5)
        txt = ev("document.body.innerText") or ""
        menu = ev("document.querySelectorAll('.ant-menu-item').length")
        print(f"{path}: 含[{kw}]={kw in txt} 菜单项={menu}")
    # 截图技能页
    send("Page.navigate", {"url": BASE + "/skills"})
    time.sleep(2.5)
    shot = send("Page.captureScreenshot", {"format": "png"}).get("result", {}).get("data")
    if shot:
        open("data/ui_skills.png", "wb").write(base64.b64decode(shot))
        print("截图 data/ui_skills.png")
    ws.close()
    # 退出时只清理本脚本自己的 headless 实例（按专属 user-data-dir 匹配）
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _cdp import _kill_by_user_data_dir
    _kill_by_user_data_dir(os.path.expandvars(r'%TEMP%\ragedg_p4v'))
    print("完成")


if __name__ == "__main__":
    main()
