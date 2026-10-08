# 桌面版打包说明

把 RAG 知识库平台打包成 Windows 桌面应用（绿色免安装版）。

## 结构

```
desktop/                  # Electron 外壳
├─ main.js                # 主进程：拉起后端 → 等就绪 → 开窗
├─ loading.html           # 启动过渡页
├─ icon.ico / icon.png    # 应用图标
└─ package.json           # electron-builder 配置

backend/
├─ run_server.py          # 后端入口（PyInstaller 用）
├─ build_backend.spec     # PyInstaller 配置（目录版）
└─ dist/rag-backend/      # 打包产物（exe + 依赖 + 前端 dist）

desktop/release/win-unpacked/   # 最终桌面应用（RAG知识库.exe）
```

## 打包步骤

### 1. 构建前端

```bash
cd web && npm run build
```

### 2. 打包后端（PyInstaller 目录版）

```bash
cd backend
./.venv/Scripts/python.exe -m pip install pyinstaller   # 首次
./.venv/Scripts/python.exe -m PyInstaller build_backend.spec --noconfirm --distpath dist --workpath build/pyi
```

产物：`backend/dist/rag-backend/`（约 121 MB）

### 3. 打包桌面应用（electron-builder）

```bash
cd desktop
npm install    # 首次
npm run dist   # 输出到 desktop/release/win-unpacked/
```

> **国内网络**：Electron 二进制需走镜像，且 electron-builder 会复用
> `node_modules/electron/dist` 的本地运行时（package.json 里 `electronDist` 已配置）。
> 若报下载失败，设置：
> ```bash
> export ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/"
> export npm_config_registry="https://registry.npmmirror.com"
> ```

## 数据目录

运行时数据（数据库、上传文件）写在**用户可写目录**，不在安装目录：

```
%APPDATA%\RAG知识库\data\rag.db       # 数据库
%APPDATA%\RAG知识库\data\files\       # 上传的文档
```

- 首次运行自动初始化（建库、内置 admin/admin123、9 个角色）
- 后端通过环境变量 `RAG_DATA_DIR` 接收数据目录（由 Electron 注入）

## 运行

双击 `desktop/release/win-unpacked/RAG知识库.exe`：
1. Electron 加载启动页
2. 拉起内置后端（端口 6677）
3. 后端就绪后自动打开主界面
4. 关闭窗口即退出，后端一并停止

默认端口 6677，可用环境变量 `RAG_PORT` 覆盖。

## 关键技术点

| 问题 | 解法 |
|---|---|
| 打包后路径指向临时解压目录 | `config.py` 用 `sys.frozen` 感知，数据写 `%APPDATA%` |
| PyInstaller 收集不到 app 包 | `run_server.py` 显式 `from app.main import app` |
| 前端 dist 找不到 | spec 用 `datas` 把 `web/dist` 打进包，运行时经 `_MEIPASS` 访问 |
| 后端未初始化 | 启动时 `asyncio.run(seed_all())` 幂等播种 |
| Electron 下载慢/失败 | `electronDist` 指向本地 `node_modules/electron/dist` |
| C 盘空间不足 | 把 `TEMP`、`electron_config_cache` 指向其它盘 |
