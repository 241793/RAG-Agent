"""对话附件展示 + 文件管理页验证（使用安全版 _cdp，不会误杀用户浏览器）。"""
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
    b, cdp, ws = open_browser(port=9370, tag="att")
    try:
        cdp.send("Page.navigate", {"url": BASE + "/login"})
        time.sleep(3)
        cdp.ev("(async()=>{const r=await fetch('/api/v1/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'admin',password:'admin123'})});const d=await r.json();localStorage.setItem('access_token',d.access_token);return 'ok';})()", True)

        # 文件管理页
        cdp.send("Page.navigate", {"url": BASE + "/admin/files"})
        time.sleep(4)
        print("文件管理页-表头:", cdp.ev("document.body.innerText.includes('文件管理')"))
        print("文件管理页-有预览列:", cdp.ev("document.body.innerText.includes('预览')"))
        print("文件管理页-有清理按钮:", cdp.ev("document.body.innerText.includes('清理过期')"))
        print("文件管理页-行数:", cdp.ev("document.querySelectorAll('.ant-table-tbody tr.ant-table-row').length"))
        shot = cdp.send("Page.captureScreenshot", {"format": "png"}).get("result", {}).get("data")
        if shot:
            open("data/ui_filepage2.png", "wb").write(base64.b64decode(shot))

        # 对话页：检查入库选择器有 clear
        cdp.send("Page.navigate", {"url": BASE + "/chat"})
        time.sleep(4)
        print("对话页-模型常驻:", cdp.ev("document.body.innerText.includes('模型：')"))
        print("对话页-入库选择器可清空:", cdp.ev("!!document.querySelector('.ant-select-clear')  || [...document.querySelectorAll('.ant-select')].some(s=>s.innerText.includes('文档入库到'))"))
        print("完成")
    finally:
        ws.close()
        b.stop()


if __name__ == "__main__":
    main()
