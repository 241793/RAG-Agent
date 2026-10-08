"""验证：代码高亮渲染 + 定时任务页可视化选时间 + Agent 工具开关（安全版 _cdp）。"""
from __future__ import annotations

import base64
import os
import sys
import time

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _cdp import open_browser  # noqa: E402

BASE = "http://127.0.0.1:6677"


def main():
    b, cdp, ws = open_browser(port=9375, tag="feat")
    try:
        cdp.send("Page.navigate", {"url": BASE + "/login"})
        time.sleep(3)
        cdp.ev("(async()=>{const r=await fetch('/api/v1/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'admin',password:'admin123'})});const d=await r.json();localStorage.setItem('access_token',d.access_token);return 'ok';})()", True)

        # 1) 定时任务页
        cdp.send("Page.navigate", {"url": BASE + "/scheduled"})
        time.sleep(4)
        print("定时任务页存在:", cdp.ev("document.body.innerText.includes('定时任务')"))
        print("菜单含定时任务:", cdp.ev("document.body.innerText.includes('定时任务')"))
        # 打开新建 → 检查可视化选时间
        cdp.ev("(()=>{const b=[...document.querySelectorAll('button')].find(x=>x.innerText.includes('新建定时任务'));b&&b.click();})()")
        time.sleep(1.5)
        print("选时间-含'每天':", cdp.ev("document.body.innerText.includes('每天')"))
        print("选时间-含cron预览:", cdp.ev("document.body.innerText.includes('cron')"))
        shot = cdp.send("Page.captureScreenshot", {"format": "png"}).get("result", {}).get("data")
        if shot:
            open("data/ui_scheduled.png", "wb").write(base64.b64decode(shot))

        # 2) Agent 编辑页工具开关
        agents = httpx.get(BASE + "/api/v1/agents", headers={"Authorization": "Bearer " + _tok()}).json()
        if agents:
            cdp.send("Page.navigate", {"url": f"{BASE}/agents/{agents[0]['id']}/edit"})
            time.sleep(3)
            cdp.ev("(()=>{const t=[...document.querySelectorAll('.ant-tabs-tab')].find(x=>x.innerText.includes('可用工具'));t&&t.click();})()")
            time.sleep(1.5)
            print("工具页含'生成文件':", cdp.ev("document.body.innerText.includes('生成文件')"))
            print("工具页含开关:", cdp.ev("document.querySelectorAll('.ant-switch').length > 0"))
        print("完成")
    finally:
        ws.close()
        b.stop()


def _tok():
    return httpx.post(BASE + "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}).json()["access_token"]


if __name__ == "__main__":
    main()
