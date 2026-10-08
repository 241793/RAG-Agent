"""Agent 完善 UI 验证：工具Tab/版本Tab/模型选择器/技能参数（安全版 _cdp）。"""
from __future__ import annotations

import os
import sys
import time

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _cdp import open_browser  # noqa: E402

BASE = "http://127.0.0.1:6677"


def main():
    tok = httpx.post(BASE + "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}).json()["access_token"]
    agents = httpx.get(BASE + "/api/v1/agents", headers={"Authorization": "Bearer " + tok}).json()
    aid = agents[0]["id"] if agents else 1

    b, cdp, ws = open_browser(port=9385, tag="ag")
    try:
        cdp.send("Page.navigate", {"url": BASE + "/login"})
        time.sleep(3)
        cdp.ev("(async()=>{const r=await fetch('/api/v1/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'admin',password:'admin123'})});const d=await r.json();localStorage.setItem('access_token',d.access_token);return 'ok';})()", True)

        cdp.send("Page.navigate", {"url": f"{BASE}/agents/{aid}/edit"})
        time.sleep(4)
        tabs = cdp.ev("Array.from(document.querySelectorAll('.ant-tabs-tab')).map(t=>t.innerText)")
        print("Tabs:", tabs)
        # 工具 Tab
        cdp.ev("(()=>{const t=[...document.querySelectorAll('.ant-tabs-tab')].find(x=>x.innerText.includes('可用工具'));t&&t.click();})()")
        time.sleep(1)
        print("工具Tab含生成文件:", cdp.ev("document.body.innerText.includes('生成文件')"))
        # 版本 Tab
        cdp.ev("(()=>{const t=[...document.querySelectorAll('.ant-tabs-tab')].find(x=>x.innerText.includes('版本'));t&&t.click();})()")
        time.sleep(1)
        print("版本Tab含生成快照:", cdp.ev("document.body.innerText.includes('生成快照')"))
        # 基础配置含可见性
        cdp.ev("(()=>{const t=[...document.querySelectorAll('.ant-tabs-tab')].find(x=>x.innerText.includes('基础配置'));t&&t.click();})()")
        time.sleep(1)
        print("基础配置含可见性:", cdp.ev("document.body.innerText.includes('可见性')"))

        # 智能体对话页含模型选择器
        cdp.send("Page.navigate", {"url": f"{BASE}/agents/{aid}/chat"})
        time.sleep(3)
        print("对话页含模型选择:", cdp.ev("document.body.innerText.includes('模型：')"))

        # 工具管理页
        cdp.send("Page.navigate", {"url": BASE + "/admin/tools"})
        time.sleep(3)
        print("工具管理页存在:", cdp.ev("document.body.innerText.includes('工具管理')"))
        print("完成")
    finally:
        ws.close()
        b.stop()


if __name__ == "__main__":
    main()
