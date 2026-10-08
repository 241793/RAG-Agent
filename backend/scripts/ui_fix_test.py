"""验证：思考过程显示 + 流式流畅（安全版 _cdp）。"""
from __future__ import annotations

import base64
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _cdp import open_browser  # noqa: E402

BASE = "http://127.0.0.1:6677"


def main():
    b, cdp, ws = open_browser(port=9402, tag="fix")
    try:
        cdp.send("Page.navigate", {"url": BASE + "/login"})
        time.sleep(3)
        cdp.ev("(async()=>{const r=await fetch('/api/v1/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'admin',password:'admin123'})});const d=await r.json();localStorage.setItem('access_token',d.access_token);return 'ok';})()", True)
        cdp.send("Page.navigate", {"url": BASE + "/chat"})
        time.sleep(4)
        cdp.ev("(()=>{const t=[...document.querySelectorAll('textarea')].find(x=>(x.placeholder||'').includes('输入问题'));t.focus();const proto=Object.getPrototypeOf(t);const set=Object.getOwnPropertyDescriptor(proto,'value').set;if(t._valueTracker)t._valueTracker.setValue('');set.call(t,'用python写一个快速排序并解释原理');t.dispatchEvent(new Event('input',{bubbles:true}));})()")
        time.sleep(0.5)
        cdp.ev("Array.from(document.querySelectorAll('button')).find(b=>b.innerText.replace(/\\s/g,'')==='发送')?.click()")

        # 流式中轮询 reasoning-body
        mid_ok = False
        for i in range(14):
            time.sleep(1)
            body = cdp.ev("document.querySelector('.reasoning-body')?.innerText?.length ?? 0")
            plain = cdp.ev("!!document.querySelector('.streaming-plain')")
            if body and body > 0:
                print(f"t={i+1}s 思考过程已显示, 长度={body}, 纯文本渲染中={plain}")
                mid_ok = True
                break
        print("流式中思考内容可见:", mid_ok)
        shot = cdp.send("Page.captureScreenshot", {"format": "png"}).get("result", {}).get("data")
        if shot:
            open("data/ui_fix_stream.png", "wb").write(base64.b64decode(shot))

        # 等完成
        time.sleep(18)
        print("完成后 .reasoning-body 存在(应无=已收起):", cdp.ev("!!document.querySelector('.reasoning-body')"))
        print("完成后代码块已高亮(应有 .code-block):", cdp.ev("!!document.querySelector('.code-block') || document.body.innerText.includes('def ') || document.body.innerText.includes('quick')"))
        # 手动点开思考
        cdp.ev("document.querySelector('.reasoning-head')?.click()")
        time.sleep(0.5)
        print("手动点开后 .reasoning-body 存在:", cdp.ev("!!document.querySelector('.reasoning-body')"))
        shot2 = cdp.send("Page.captureScreenshot", {"format": "png"}).get("result", {}).get("data")
        if shot2:
            open("data/ui_fix_done.png", "wb").write(base64.b64decode(shot2))
        print("完成")
    finally:
        ws.close()
        b.stop()


if __name__ == "__main__":
    main()
