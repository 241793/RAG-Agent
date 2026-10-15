const { app, BrowserWindow, dialog } = require('electron')
const { spawn } = require('child_process')
const path = require('path')
const http = require('http')
const fs = require('fs')

// 设置应用名（影响 userData 目录：%APPDATA%/RAG知识库）
app.setName('RAG知识库')

// 固定后端端口（可改）
const PORT = process.env.RAG_PORT || process.env.PORT || '6677'
const HOST = '127.0.0.1'
const BASE_URL = `http://${HOST}:${PORT}`

let backendProc = null
let mainWindow = null

// 解析打包后后端可执行文件路径
function resolveBackend() {
  // 开发态：直接用 backend/dist/rag-backend/rag-backend.exe
  const devExe = path.join(__dirname, '..', 'backend', 'dist', 'rag-backend', 'rag-backend.exe')
  // 打包态：resources/backend/rag-backend.exe
  const prodExe = path.join(process.resourcesPath || '', 'backend', 'rag-backend.exe')

  if (app.isPackaged && fs.existsSync(prodExe)) return prodExe
  if (fs.existsSync(devExe)) return devExe
  if (fs.existsSync(prodExe)) return prodExe
  return null
}

// 探测后端是否就绪
function pingHealth(timeoutMs = 1500) {
  return new Promise((resolve) => {
    const req = http.get(`${BASE_URL}/health`, { timeout: timeoutMs }, (res) => {
      res.resume()
      resolve(res.statusCode === 200)
    })
    req.on('error', () => resolve(false))
    req.on('timeout', () => { req.destroy(); resolve(false) })
  })
}

// 等待后端就绪（最多 ~60s）
async function waitBackend(maxMs = 60000) {
  const start = Date.now()
  while (Date.now() - start < maxMs) {
    if (await pingHealth()) return true
    await new Promise((r) => setTimeout(r, 800))
  }
  return false
}

function startBackend(exePath) {
  // 数据目录：用户数据目录（Windows: %APPDATA%/RAG知识库），可写且持久
  const userDataDir = app.getPath('userData')
  fs.mkdirSync(userDataDir, { recursive: true })

  const env = {
    ...process.env,
    RAG_HOST: HOST,
    RAG_PORT: PORT,
    // 后端据此把数据库/上传文件写到用户目录（而非只读的安装目录）
    RAG_DATA_DIR: userDataDir,
  }

  backendProc = spawn(exePath, [], {
    env,
    cwd: path.dirname(exePath),
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  })

  backendProc.stdout.on('data', (d) => console.log('[backend]', d.toString().trim()))
  backendProc.stderr.on('data', (d) => console.error('[backend]', d.toString().trim()))
  backendProc.on('exit', (code) => {
    console.log('[backend] exited with code', code)
    backendProc = null
  })
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 1000,
    minHeight: 680,
    title: 'RAG 知识库',
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  // 先加载本地加载页，后端就绪后跳转
  mainWindow.loadFile(path.join(__dirname, 'loading.html'))
  mainWindow.on('closed', () => { mainWindow = null })
}

async function boot() {
  createWindow()
  startUpdateWatcher()

  const exe = resolveBackend()
  if (!exe) {
    dialog.showErrorBox('启动失败', '未找到后端程序。请先运行 backend 打包脚本生成 dist/rag-backend。')
    return
  }

  // 若已有后端在跑（比如用户手动开的），跳过启动
  if (!(await pingHealth())) {
    startBackend(exe)
  }

  const ok = await waitBackend()
  if (ok && mainWindow) {
    mainWindow.loadURL(BASE_URL)
  } else if (mainWindow) {
    dialog.showErrorBox('启动超时', '后端服务未能在预期时间内就绪，请检查端口占用或查看日志。')
  }
}

app.whenReady().then(boot)

// ==================== 更新：轮询信号 → 退出 → 换盘 → 重启 ====================
// 分工说明：后端负责下载/校验/解压到暂存区并写信号文件；换盘必须由外部脚本执行，
// 因为 Windows 不允许覆盖正在运行的 exe（本进程与后端 exe 都会被锁）。
// 本进程只负责：发现信号 → 拉起脚本 → 退出（释放文件锁）。
const UPDATE_POLL_MS = 3000
let updateApplied = false

function updatesDir() {
  return path.join(app.getPath('userData'), 'updates')
}

function startUpdateWatcher() {
  setInterval(() => {
    if (updateApplied || !app.isPackaged) return
    const signal = path.join(updatesDir(), 'apply.requested')
    if (!fs.existsSync(signal)) return

    updateApplied = true
    try {
      applyUpdate(signal)
    } catch (e) {
      console.error('[update] apply failed:', e)
      updateApplied = false
    }
  }, UPDATE_POLL_MS)
}

function applyUpdate(signal) {
  const dir = updatesDir()
  const pendingPath = path.join(dir, 'pending.json')
  if (!fs.existsSync(pendingPath)) {
    console.error('[update] pending.json missing, abort')
    return
  }
  const pending = JSON.parse(fs.readFileSync(pendingPath, 'utf8'))
  const script = pending.script || path.join(dir, 'apply_update.bat')
  if (!fs.existsSync(script)) {
    console.error('[update] apply script missing:', script)
    return
  }

  // 安装目录与 exe 名只有本进程能可靠给出（后端不知道自己的安装位置）
  const exePath = app.getPath('exe')
  const installDir = path.dirname(exePath)
  const exeName = path.basename(exePath)
  const logPath = path.join(dir, 'update_apply.log')

  console.log('[update] applying', pending.version, '->', installDir)
  const child = spawn(
    'cmd.exe',
    ['/c', script, pending.staging, installDir, exeName, logPath],
    { detached: true, stdio: 'ignore', windowsHide: true }
  )
  child.unref()

  // 清理信号，避免重启后又触发一次
  try { fs.unlinkSync(signal) } catch (e) { /* ignore */ }

  // 先杀后端（释放 rag-backend.exe 的文件锁），再退出自身
  if (backendProc) {
    try { backendProc.kill() } catch (e) { /* ignore */ }
  }
  app.quit()
}

app.on('window-all-closed', () => {
  if (backendProc) {
    try { backendProc.kill() } catch (e) { /* ignore */ }
  }
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', () => {
  if (backendProc) {
    try { backendProc.kill() } catch (e) { /* ignore */ }
  }
})
