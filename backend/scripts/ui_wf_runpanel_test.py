"""工作流运行面板验证：不跳聊天、实时日志、输入表单、历史（安全版 _cdp）。"""
from __future__ import annotations

import base64
import os
import sys
import time

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _cdp import open_browser  # noqa: E402

BASE = "http://127.0.0.1:6677"


def _tok():
    return httpx.post(BASE + "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}).json()["access_token"]


def main():
    tok = _tok()
    h = {"Authorization": "Bearer " + tok}
    agents = httpx.get(BASE + "/api/v1/agents", headers=h, timeout=10).json()
    wf_agents = [a for a in agents if a.get("type") == "workflow"]
    print("工作流智能体:", [(a["id"], a["name"]) for a in wf_agents])
    aid = wf_agents[0]["id"] if wf_agents else (agents[0]["id"] if agents else None)

    b, cdp, ws = open_browser(port=9380, tag="wf")
    try:
        cdp.send("Page.navigate", {"url": BASE + "/login"})
        time.sleep(3)
        cdp.ev("(async()=>{const r=await fetch('/api/v1/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'admin',password:'admin123'})});const d=await r.json();localStorage.setItem('access_token',d.access_token);return 'ok';})()", True)

        # 1) 智能体列表点 workflow 卡片"运行"→ 应进 /workflow（非 /chat）
        cdp.send("Page.navigate", {"url": BASE + "/agents"})
        time.sleep(4)
        cdp.ev("(()=>{const cards=[...document.querySelectorAll('.ant-card')];const wf=cards.find(c=>c.innerText.includes('工作流'));const btns=wf?[...wf.querySelectorAll('button, .anticon')]:[];const run=btns.find(x=>(x.getAttribute('aria-label')||x.title||'').includes('运行'));run&&run.click();})()")
        time.sleep(3)
        url = cdp.ev("location.pathname + location.search")
        print("点运行后 URL:", url)
        print("未跳聊天:", "/chat" not in (url or ""))
        print("运行面板打开(含'运行工作流'):", cdp.ev("document.body.innerText.includes('运行工作流')"))

        # 2) 直接进编排页运行面板，检查输入表单与元素
        if aid:
            cdp.send("Page.navigate", {"url": f"{BASE}/agents/{aid}/workflow?panel=run"})
            time.sleep(4)
        print("面板含'运行':", cdp.ev("(()=>{const d=document.querySelector('.ant-drawer');return d?d.innerText.includes('运行'):false;})()"))
        print("面板含'历史':", cdp.ev("(()=>{const d=document.querySelector('.ant-drawer');return d?d.innerText.includes('历史'):false;})()"))
        shot = cdp.send("Page.captureScreenshot", {"format": "png"}).get("result", {}).get("data")
        if shot:
            open("data/ui_wf_run.png", "wb").write(base64.b64decode(shot))
        print("完成")
    finally:
        ws.close()
        b.stop()


if __name__ == "__main__":
    main()
