# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（目录版 onedir）。

用法（在 backend/ 目录下）：
    ./.venv/Scripts/python.exe -m PyInstaller build_backend.spec --noconfirm

产物：dist/rag-backend/  （内含 rag-backend.exe + 依赖 + web/dist 前端）
绿色版：主程序启动后，数据写在 exe 同级的 data/ 目录。
"""
import os
from pathlib import Path

# 项目根与前端 dist
PROJECT_ROOT = Path(SPECPATH).parent          # backend/ 的上级 = 项目根
WEB_DIST = PROJECT_ROOT / "web" / "dist"
BACKEND_DIR = Path(SPECPATH)                   # backend/

# 数据文件：前端 dist 打进包内（冻结时经 sys._MEIPASS 访问）
datas = []
if WEB_DIST.exists():
    datas.append((str(WEB_DIST), "web/dist"))
else:
    print(f"[WARN] 前端未构建，跳过：{WEB_DIST}  （先 cd web && npm run build）")

# 需要显式声明的隐藏导入（动态 import / C 扩展，PyInstaller 静态分析易漏）
hiddenimports = [
    "app",                           # 显式导入包，确保被收集
    "app.main",
    "app.bootstrap",
    "app.models",                    # 动态 import 注册所有表
    "aiosqlite",
    "greenlet",
    "sqlalchemy.dialects.sqlite.aiosqlite",
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "pymupdf",
    "docx",
    "openpyxl",
    "pptx",
    "bs4",
    "lxml",
    "lxml.etree",
    "markdown",
]

block_cipher = None

a = Analysis(
    ["run_server.py"],
    pathex=[str(BACKEND_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PyQt5", "PySide2", "IPython", "pytest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="rag-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon=str(PROJECT_ROOT / "desktop" / "icon.ico") if (PROJECT_ROOT / "desktop" / "icon.ico").exists() else None,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="rag-backend",
)
