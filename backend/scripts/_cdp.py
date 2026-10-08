"""安全的 headless 浏览器启动/清理：只操作本实例启动的进程。

设计目标：绝不误杀用户正在使用的浏览器窗口。
  - 每个实例独立 --user-data-dir（随机唯一目录），作为"只杀自己"的匹配锚点。
  - stop() 优先 terminate 自己 Popen 的句柄；兜底按命令行精确匹配本实例目录。
  - 端口可动态分配，避免多脚本冲突。

用法：
    from _cdp import HeadlessBrowser
    with HeadlessBrowser(port=9364, tag="chat") as b:
        cdpsocket = b.ws_connect()   # 或自行用 httpx/websocket 连 b.port
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import time
import uuid

import httpx

_EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def _find_edge() -> str:
    for p in _EDGE_CANDIDATES:
        if os.path.isfile(p):
            return p
    raise RuntimeError("未找到 msedge.exe")


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _kill_by_user_data_dir(udd: str) -> None:
    """Windows：按命令行精确匹配本实例的 user-data-dir，只杀本实例的 msedge 进程树。"""
    if os.name != "nt":
        return
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
        f"Where-Object {{ $_.CommandLine -like '*{udd}*' }} | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=15)
    except Exception:  # noqa: BLE001
        pass


class HeadlessBrowser:
    def __init__(self, *, port: int | None = None, tag: str = "ui") -> None:
        self.port = port or free_port()
        self.user_data_dir = os.path.join(
            tempfile.gettempdir(), f"ragedg_{tag}_{uuid.uuid4().hex[:8]}"
        )
        self.proc: subprocess.Popen | None = None

    @property
    def cdp(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> "HeadlessBrowser":
        edge = _find_edge()
        self.proc = subprocess.Popen(
            [
                edge, "--headless=new", "--disable-gpu", "--no-sandbox",
                f"--remote-debugging-port={self.port}", "--remote-allow-origins=*",
                "--user-data-dir=" + self.user_data_dir, "about:blank",
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        # 轮询等待 CDP 就绪
        for _ in range(60):
            try:
                httpx.get(f"{self.cdp}/json/version", timeout=0.5)
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.2)
        return self

    def stop(self) -> None:
        # 1) 只 terminate 自己启动的进程
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                try:
                    self.proc.kill()
                except Exception:  # noqa: BLE001
                    pass
        # 2) 兜底：按本实例的 user-data-dir 精确匹配（只命中自己派生的子进程）
        _kill_by_user_data_dir(self.user_data_dir)

    def new_tab(self, url: str = "about:blank") -> str:
        return httpx.put(f"{self.cdp}/json/new?{url}").json()["id"]

    def ws_url(self, tab_id: str) -> str:
        for x in httpx.get(f"{self.cdp}/json").json():
            if x["id"] == tab_id:
                return x["webSocketDebuggerUrl"]
        raise RuntimeError("tab not found")

    def __enter__(self) -> "HeadlessBrowser":
        return self.start()

    def __exit__(self, *a) -> None:
        self.stop()


class CDP:
    """极简 CDP 客户端：send/ev 骨架，供 ui_*.py 复用。"""

    def __init__(self, ws) -> None:
        self.ws = ws
        self._mid = 0

    def send(self, method: str, params: dict | None = None) -> dict:
        self._mid += 1
        self.ws.send(json.dumps({"id": self._mid, "method": method, "params": params or {}}))
        while True:
            r = json.loads(self.ws.recv())
            if r.get("id") == self._mid:
                return r

    def ev(self, expr: str, await_promise: bool = False):
        r = self.send("Runtime.evaluate", {"expression": expr, "awaitPromise": await_promise, "returnByValue": True})
        return r.get("result", {}).get("result", {}).get("value")


def open_browser(port: int | None = None, tag: str = "ui", width: int = 1600, height: int = 1000):
    """启动浏览器 + 新标签 + 建 CDP 连接，返回 (browser, cdp, ws)。调用方负责 browser.stop()。"""
    import websocket

    b = HeadlessBrowser(port=port, tag=tag).start()
    tab = b.new_tab("about:blank")
    ws = websocket.create_connection(b.ws_url(tab), timeout=60)
    cdp = CDP(ws)
    cdp.send("Runtime.enable")
    cdp.send("Page.enable")
    cdp.send("Emulation.setDeviceMetricsOverride",
             {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False})
    return b, cdp, ws
