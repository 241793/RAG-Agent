"""权限分层浏览器验证：员工被路由守卫拦截、菜单无管理入口。"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time

import httpx

CDP = "http://127.0.0.1:9350"
BASE = "http://127.0.0.1:6677"


def _session(title, user, pwd, checks):
    # 不再按进程名全杀（会误杀用户浏览器）；改用独立 user-data-dir，退出时只清自己。
    time.sleep(2)
    edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    port = 9350
    subprocess.Popen(
        [edge, "--headless=new", "--disable-gpu", "--no-sandbox",
         f"--remote-debugging-port={port}", "--remote-allow-origins=*",
         "--user-data-dir=" + os.path.expandvars(r"%TEMP%\ragedg_rbac"), "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(6)
    cdp = f"http://127.0.0.1:{port}"
    tid = httpx.put(f"{cdp}/json/new?about:blank").json()["id"]
    ws_url = [x["webSocketDebuggerUrl"] for x in httpx.get(f"{cdp}/json").json() if x["id"] == tid][0]
    import websocket
    ws = websocket.create_connection(ws_url, timeout=40)
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
    tok = ev(f"(async()=>{{const r=await fetch('/api/v1/auth/login',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{username:'{user}',password:'{pwd}'}})}});const d=await r.json();localStorage.setItem('access_token',d.access_token);return d.access_token?'SET':'NO';}})()", ap=True)
    print(f"[{title}] login:", tok)
    out = checks(send, ev, ws)
    ws.close()
    # 退出时只清理本脚本自己的 headless 实例（按专属 user-data-dir 匹配）
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _cdp import _kill_by_user_data_dir
    _kill_by_user_data_dir(os.path.expandvars(r'%TEMP%\ragedg_rbac'))
    return out


def employee_checks(send, ev, ws):
    res = {}
    # 1) 直达 admin/users 应 403
    send("Page.navigate", {"url": BASE + "/admin/users"}); time.sleep(4)
    res["admin_users_403"] = ev("document.body.innerText.includes('403')")
    # 2) 侧栏不应有"用户/角色/模型管理"
    menu = ev("(()=>{const m=document.querySelector('.ant-menu');return m?m.innerText:'';})()") or ""
    res["no_user_menu"] = "用户" not in menu
    res["no_model_menu"] = "模型管理" not in menu
    res["no_role_menu"] = "角色" not in menu
    # 3) 员工可访问 /chat
    send("Page.navigate", {"url": BASE + "/chat"}); time.sleep(3)
    res["chat_ok"] = ev("!document.body.innerText.includes('403')")
    return res


def admin_checks(send, ev, ws):
    res = {}
    send("Page.navigate", {"url": BASE + "/admin/users"}); time.sleep(4)
    res["admin_users_ok"] = not ev("document.body.innerText.includes('403')")
    menu = ev("(()=>{const m=document.querySelector('.ant-menu');return m?m.innerText:'';})()") or ""
    res["has_model_menu"] = "模型管理" in menu
    return res


if __name__ == "__main__":
    emp = _session("员工", "emp1", "emp123", employee_checks)
    print("员工结果:", json.dumps(emp, ensure_ascii=False))
    adm = _session("管理员", "admin", "admin123", admin_checks)
    print("管理员结果:", json.dumps(adm, ensure_ascii=False))
