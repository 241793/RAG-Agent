"""技能页浏览器验证：查看包 → 点文件 → 读内容 → 编辑保存 → 校验持久化。"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time

import httpx

CDP = "http://127.0.0.1:9335"
BASE = "http://127.0.0.1:6677"


def main():
    # 不再按进程名全杀（会误杀用户浏览器）；改用独立 user-data-dir，退出时只清自己。
    time.sleep(2)
    edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    subprocess.Popen(
        [edge, "--headless=new", "--disable-gpu", "--no-sandbox",
         "--remote-debugging-port=9335", "--remote-allow-origins=*",
         "--user-data-dir=" + os.path.expandvars(r"%TEMP%\ragedg_sk2"), "about:blank"],
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

    send("Page.navigate", {"url": BASE + "/skills"})
    time.sleep(4)
    print("技能行数:", ev("document.querySelectorAll('.ant-table-tbody tr.ant-table-row').length"))
    # 点"查看包"
    ev("Array.from(document.querySelectorAll('.ant-table-tbody button')).find(b=>b.innerText.includes('查看包'))?.click()")
    time.sleep(2)
    files = ev("Array.from(document.querySelectorAll('.ant-drawer-body div[style*=monospace]')).map(d=>d.innerText)")
    print("包内文件:", files)
    print("含 SKILL.md:", any('SKILL.md' in (f or '') for f in (files or [])))
    # 点 SKILL.md
    ev("Array.from(document.querySelectorAll('.ant-drawer-body div[style*=monospace]')).find(d=>d.innerText.includes('SKILL.md'))?.click()")
    time.sleep(2)
    # 此时应有第二个 Drawer 展示文件内容
    txt = ev("(()=>{const tas=document.querySelectorAll('.ant-drawer textarea');return tas.length?tas[tas.length-1].value:'(none)';})()")
    print("打开文本域数:", ev("document.querySelectorAll('.ant-drawer textarea').length"))
    print("SKILL.md 内容前80字:", (txt or '')[:80].replace('\n', '\\n'))
    # 追加一行并保存（React 兼容注入：调整 valueTracker 后派发 input 事件）
    inject = """(()=>{
      const tas=document.querySelectorAll('.ant-drawer textarea');
      const t=tas[tas.length-1];
      const prev=t.value;
      const proto=Object.getPrototypeOf(t);
      const setter=Object.getOwnPropertyDescriptor(proto,'value').set;
      if(t._valueTracker) t._valueTracker.setValue(prev);
      setter.call(t, prev + "\\n\\n<!-- edited via UI -->\\n");
      t.dispatchEvent(new Event('input',{bubbles:true}));
      return 'injected';
    })()"""
    print("注入:", ev(inject))
    time.sleep(1)
    has_save = ev("Array.from(document.querySelectorAll('.ant-drawer button')).some(b=>b.innerText.replace(/\\s/g,'').includes('保存'))")
    save_enabled = ev("Array.from(document.querySelectorAll('.ant-drawer button')).some(b=>b.innerText.replace(/\\s/g,'').includes('保存')&&!b.disabled)")
    print("存在保存按钮:", has_save, "| 可点击:", save_enabled)
    ev("Array.from(document.querySelectorAll('.ant-drawer button')).find(b=>b.innerText.replace(/\\s/g,'').includes('保存'))?.click()")
    time.sleep(2)
    print("保存提示:", ev("document.querySelector('.ant-message')?.innerText || '(none)'"))
    ev("Array.from(document.querySelectorAll('.ant-drawer button')).find(b=>b.innerText.includes('保存'))?.click()")
    time.sleep(2)
    print("保存提示:", ev("document.querySelector('.ant-message')?.innerText || '(none)'"))

    shot = send("Page.captureScreenshot", {"format": "png"}).get("result", {}).get("data")
    if shot:
        open("data/ui_skill_files.png", "wb").write(base64.b64decode(shot))
        print("截图 data/ui_skill_files.png")
    # 后端核对
    tok = open("data/.token").read().strip()
    r = httpx.get(BASE + "/api/v1/skills/1/package/file", headers={"Authorization": "Bearer " + tok},
                  params={"path": "SKILL.md"}, timeout=10)
    print("后端读回含编辑标记:", "edited via UI" in (r.json().get("content") or ""))
    ws.close()
    # 退出时只清理本脚本自己的 headless 实例（按专属 user-data-dir 匹配）
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _cdp import _kill_by_user_data_dir
    _kill_by_user_data_dir(os.path.expandvars(r'%TEMP%\ragedg_sk2'))
    print("完成")


if __name__ == "__main__":
    main()
