<template>
  <PageContainer title="系统日志" :subtitle="path ? `日志文件：${path}` : '查看后端运行日志（可跟随最新，上翻查看时不会被新日志打断）'">
    <template #extra>
      <el-radio-group :model-value="rawMode ? 'raw' : 'fmt'" size="small" @change="(v: any) => (rawMode = v === 'raw')">
        <el-radio-button value="fmt">格式化</el-radio-button>
        <el-radio-button value="raw">原文</el-radio-button>
      </el-radio-group>
      <el-switch
        v-model="auto"
        inline-prompt
        active-text="跟随最新"
        inactive-text="已暂停"
        @change="onAutoChange"
      />
      <el-button :icon="Refresh" :loading="loading" @click="refresh">刷新</el-button>
      <el-button :icon="Download" @click="download">下载</el-button>
      <el-button :icon="Delete" type="danger" plain @click="clear">清理</el-button>
    </template>

    <!-- 日志文件统计 -->
    <div class="app-card panel stats">
      <div class="stat-inline">
        <span class="k">日志路径</span>
        <span class="mono v path">{{ stats?.path || '—' }}</span>
      </div>
      <div class="stat-inline">
        <span class="k">文件数</span><span class="v">{{ stats?.file_count ?? '—' }} 个</span>
      </div>
      <div class="stat-inline">
        <span class="k">总大小</span><span class="v">{{ fmtSize(stats?.total_bytes) }}</span>
      </div>
      <div class="stat-inline">
        <span class="k">单文件上限</span><span class="v">{{ fmtSize(stats?.max_bytes) }}</span>
      </div>
      <div class="stat-inline">
        <span class="k">保留天数</span><span class="v">{{ stats?.retention_days ?? '—' }} 天</span>
      </div>
    </div>

    <div class="app-card panel log-panel">
      <div class="filters">
        <el-radio-group v-model="level" size="small" @change="onLevelChange">
          <el-radio-button value="all">全部 {{ counts.all || 0 }}</el-radio-button>
          <el-radio-button value="error">error {{ counts.error || 0 }}</el-radio-button>
          <el-radio-button value="warning">warning {{ counts.warning || 0 }}</el-radio-button>
          <el-radio-button value="info">info {{ counts.info || 0 }}</el-radio-button>
          <el-radio-button value="debug">debug {{ counts.debug || 0 }}</el-radio-button>
        </el-radio-group>
        <el-input
          v-model="keyword"
          placeholder="关键字过滤（如 request_id / error）"
          clearable
          style="width: 280px"
          @keyup.enter="reload"
          @clear="reload"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <span class="spacer" />
        <span class="text-muted meta">显示 {{ visible.length }} / 共 {{ rows.length }} 行</span>
      </div>

      <div class="log-wrap">
        <div class="log-head">
          <span class="c-time">时间</span>
          <span class="c-level">级别</span>
          <span class="c-event">事件</span>
          <span class="c-body">内容</span>
        </div>

        <div ref="boxRef" class="log-box" @scroll="onScroll">
          <div v-if="!visible.length" class="log-empty">
            {{ loading ? '加载中…' : keyword ? '无匹配日志（换个关键字试试）' : '暂无日志（或日志文件为空）' }}
          </div>

          <template v-else-if="rawMode">
            <div
              v-for="(r, i) in visible"
              :key="i"
              class="log-row raw"
              :class="{ nowrap: !wrap }"
            >{{ r.raw }}</div>
          </template>

          <template v-else>
            <div
              v-for="(r, i) in visible"
              :key="i"
              class="log-row"
              :style="{ borderLeftColor: levelBar(r.level) }"
              :class="[r.level, { nowrap: !wrap }]"
              title="点击查看完整内容"
              @click="openDetail(r)"
            >
              <span class="c-time dim">{{ r.time || '—' }}</span>
              <span class="c-level">
                <span v-if="r.level" class="lvl-tag" :style="{ color: levelText(r.level), borderColor: levelText(r.level) }">{{ r.level }}</span>
                <span v-else class="dim">—</span>
              </span>
              <span class="c-event" :style="{ color: levelText(r.level) || '#c9d1d9' }">{{ r.event || '—' }}</span>
              <span class="c-body">
                {{ r.fields }}
                <span v-if="r.exception" class="exc"> {{ firstLine(r.exception) }}</span>
              </span>
            </div>
          </template>
        </div>

        <el-button
          v-if="pending > 0"
          class="jump-btn"
          type="primary"
          size="small"
          :icon="Bottom"
          @click="scrollToBottom"
        >{{ pending }} 条新日志 · 回到最新</el-button>
      </div>

      <div class="log-foot">
        <el-switch v-model="wrap" size="small" active-text="自动换行" />
        <span class="text-muted foot-hint">
          {{ auto ? '跟随最新中（每 3 秒）' : '已暂停跟随' }} · 级别色条：红=错误 / 橙=警告 / 蓝=信息
        </span>
      </div>
    </div>

    <el-drawer v-model="drawer" :title="detail ? `日志详情 · ${detail.event || '(无事件名)'}` : '日志详情'" size="640px">
      <template v-if="detail">
        <div class="detail">
          <div class="detail-meta">
            <span class="lvl-tag" :style="{ color: levelText(detail.level), borderColor: levelText(detail.level) }">{{ detail.level || '—' }}</span>
            <b>{{ detail.event || '(无事件名)' }}</b>
            <span class="dim">{{ detail.time || '—' }}</span>
          </div>

          <div v-if="detail.fields" class="detail-sec">
            <div class="detail-label">字段</div>
            <pre class="detail-pre">{{ detail.fields }}</pre>
          </div>

          <div v-if="detail.exception" class="detail-sec">
            <div class="detail-label danger-text">异常堆栈</div>
            <pre class="detail-pre exc-pre">{{ detail.exception }}</pre>
          </div>

          <div class="detail-sec">
            <div class="detail-label">原始行</div>
            <pre class="detail-pre dark">{{ detail.raw }}</pre>
          </div>
        </div>
      </template>
      <template #footer>
        <el-button @click="copyRaw">复制原文</el-button>
        <el-button type="primary" @click="drawer = false">关闭</el-button>
      </template>
    </el-drawer>
  </PageContainer>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Download, Delete, Search, Bottom } from '@element-plus/icons-vue'
import dayjs from 'dayjs'
import PageContainer from '@/components/PageContainer.vue'
import { systemApi } from '@/api'
import { errMsg } from '@/api/http'

interface LogRow {
  raw: string
  time: string
  level: string
  event: string
  fields: string
  exception?: string
  parsed: boolean
}

interface LogStats {
  path: string
  total_bytes: number
  file_count: number
  max_bytes: number
  backup_count: number
  retention_days: number
}

const MAX_BUFFER = 3000

const LEVEL_BAR: Record<string, string> = {
  error: '#ff4d4f', critical: '#ff4d4f', warning: '#faad14', warn: '#faad14',
  info: '#1677ff', debug: '#8c8c8c',
}
const LEVEL_TEXT: Record<string, string> = {
  error: '#ff7875', critical: '#ff7875', warning: '#ffc069', warn: '#ffc069',
  info: '#79c0ff', debug: '#8b949e',
}

function levelBar(lv: string) { return LEVEL_BAR[lv] || 'transparent' }
function levelText(lv: string) { return LEVEL_TEXT[lv] || '' }
function firstLine(s: string) { return (s || '').split('\n')[0] }

function humanSize(n?: number): string {
  if (!n || n <= 0) return '0 B'
  const u = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let v = n
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)} ${u[i]}`
}
const fmtSize = humanSize

function normLevel(raw: unknown): string {
  const s = String(raw || 'info').toLowerCase()
  if (s === 'critical' || s === 'fatal' || s === 'err') return 'error'
  if (s === 'warn') return 'warning'
  return s
}

/** 解析一行日志（JSON 优先；否则按文本兜底）。 */
function parseLine(line: string): LogRow {
  const s = (line || '').trim()
  if (s.startsWith('{')) {
    try {
      const d = JSON.parse(s)
      const ts = d.timestamp || d.time || d.ts || ''
      let time = String(ts)
      if (ts) { try { time = dayjs(ts).format('HH:mm:ss.SSS') } catch { /* keep raw */ } }
      const level = normLevel(d.level || d.levelname)
      const event = String(d.event || d.msg || d.message || '')
      const skip = new Set(['timestamp', 'time', 'ts', 'level', 'levelname', 'event', 'msg', 'message', 'exception'])
      const fields = Object.entries(d)
        .filter(([k]) => !skip.has(k))
        .map(([k, v]) => `${k}=${v && typeof v === 'object' ? JSON.stringify(v) : v}`)
        .join('  ')
      return { raw: line, time, level, event, fields, exception: d.exception, parsed: true }
    } catch { /* fallthrough */ }
  }
  const m = s.match(/^\[?(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[^\]]*)\]?\s*\[?(info|warn(?:ing)?|error|debug|critical)\]?\s*([\s\S]*)$/i)
  if (m) {
    return { raw: line, time: m[1].slice(0, 19).replace('T', ' '), level: normLevel(m[2]), event: '', fields: m[3], parsed: true }
  }
  return { raw: line, time: '', level: '', event: '', fields: s, parsed: false }
}

const rows = ref<LogRow[]>([])
const loading = ref(false)
const level = ref('all')
const keyword = ref('')
const auto = ref(true)
const path = ref('')
const rawMode = ref(false)
const wrap = ref(true)
const stats = ref<LogStats | null>(null)
const detail = ref<LogRow | null>(null)
const drawer = ref(false)
const pending = ref(0)

const boxRef = ref<HTMLDivElement | null>(null)
let atBottom = true
let timer: number | undefined

const visible = computed(() => (level.value === 'all' ? rows.value : rows.value.filter((r) => r.level === level.value)))
const counts = computed(() => {
  const c: Record<string, number> = { all: rows.value.length }
  for (const r of rows.value) if (r.level) c[r.level] = (c[r.level] || 0) + 1
  return c
})

function scrollToBottom() {
  const el = boxRef.value
  if (el) el.scrollTop = el.scrollHeight
  atBottom = true
  pending.value = 0
}
function stickBottom() {
  nextTick(() => {
    const el = boxRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}
function onScroll() {
  const el = boxRef.value
  if (!el) return
  const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 48
  atBottom = nearBottom
  if (nearBottom && pending.value) pending.value = 0
}
function onLevelChange() { if (atBottom) stickBottom() }
function onAutoChange() { if (auto.value) { load(false); scrollToBottom() } }

/** 拉取日志：增量追加（不整体替换），保证上翻时已有内容不位移。 */
async function load(initial = false) {
  if (initial) loading.value = true
  try {
    const r = await systemApi.logs({ lines: 500, keyword: keyword.value || undefined })
    path.value = r.path
    const fresh = (r.lines || []).map(parseLine)
    const prev = rows.value

    let merged = fresh
    let appended = fresh.length
    if (!initial && prev.length) {
      // 用尾锚点定位重叠，避免行内时间戳重复导致误判
      const lastPrev = prev[prev.length - 1]?.raw
      let li = -1
      for (let i = fresh.length - 1; i >= 0; i--) { if (fresh[i].raw === lastPrev) { li = i; break } }
      if (li >= 0) {
        const added = fresh.slice(li + 1)
        appended = added.length
        if (appended === 0) return // 无新行：保持引用不变，避免无谓重渲染
        merged = [...prev, ...added]
      }
    }

    // 仅在黏底时裁剪缓冲；上翻时保留，绝不因裁剪导致内容上移
    if (atBottom && merged.length > MAX_BUFFER) merged = merged.slice(merged.length - MAX_BUFFER)
    rows.value = merged

    if (atBottom) stickBottom()
    else if (appended > 0) pending.value += appended
  } catch (e) {
    if (initial) rows.value = []
    ElMessage.error(errMsg(e))
  } finally {
    if (initial) loading.value = false
  }
}

async function loadStats() {
  stats.value = await systemApi.logStats().catch(() => stats.value)
}

function refresh() { load(true); loadStats() }
function reload() { rows.value = []; pending.value = 0; atBottom = true; load(true) }

function startTimer() {
  stopTimer()
  if (auto.value) timer = window.setInterval(() => { load(false); loadStats() }, 3000)
}
function stopTimer() { if (timer) { clearInterval(timer); timer = undefined } }

function openDetail(r: LogRow) { detail.value = r; drawer.value = true }
function copyRaw() {
  const t = detail.value?.raw || ''
  navigator.clipboard?.writeText(t).then(() => ElMessage.success('已复制原文')).catch(() => ElMessage.warning('复制失败'))
}

function download() {
  const token = localStorage.getItem('access_token')
  fetch(systemApi.downloadUrl(), { headers: token ? { Authorization: `Bearer ${token}` } : {} })
    .then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      return r.blob()
    })
    .then((b) => {
      const url = URL.createObjectURL(b)
      const a = document.createElement('a')
      a.href = url
      a.download = 'app.log'
      a.click()
      URL.revokeObjectURL(url)
    })
    .catch((e) => ElMessage.error(String(errMsg(e))))
}

async function clear() {
  try {
    await ElMessageBox.confirm('将删除全部历史日志（含备份），此操作不可恢复。', '确认清空日志？', {
      type: 'warning',
      confirmButtonText: '清空',
      cancelButtonText: '取消',
    })
  } catch { return }
  try {
    const r = await systemApi.clearLogs()
    ElMessage.success(`${r.message || '已清空'}（删除 ${r.removed ?? 0} 个，释放 ${humanSize(r.freed_bytes)}）`)
    rows.value = []
    pending.value = 0
    load(true)
    loadStats()
  } catch (e) { ElMessage.error(errMsg(e)) }
}

onMounted(() => {
  load(true)
  loadStats()
  startTimer()
})
onBeforeUnmount(stopTimer)

// 跟随开关变化时重启轮询
watch(auto, () => startTimer())
</script>

<style scoped>
.panel { padding: 18px 20px; }
.stats { display: flex; flex-wrap: wrap; gap: 10px 32px; margin-bottom: 16px; }
.stat-inline { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.stat-inline .k { color: var(--text-muted); }
.stat-inline .v { color: var(--text-title); font-weight: 500; }
.stat-inline .path { max-width: 460px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.filters { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 14px; }
.spacer { flex: 1; }
.meta { font-size: 12px; }

.log-wrap { position: relative; }
.log-head {
  display: flex; gap: 10px; padding: 5px 12px; font-size: 11px; letter-spacing: 0.3px;
  color: #8b949e; background: #161b22; border-bottom: 1px solid #30363d;
  border-radius: 8px 8px 0 0;
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
}
.log-box {
  background: #0d1117; color: #c9d1d9; padding: 2px 0;
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
  font-size: 12.5px; line-height: 1.7;
  max-height: 62vh; min-height: 220px; overflow: auto;
  border-radius: 0 0 8px 8px;
}
.log-empty { color: #6e7681; padding: 12px; }
.log-row {
  display: flex; gap: 10px; padding: 1px 12px; align-items: baseline;
  border-left: 3px solid transparent;
}
.log-row.raw { white-space: pre-wrap; word-break: break-all; cursor: text; }
.log-row:not(.raw) { cursor: pointer; }
.log-row.nowrap { white-space: pre; word-break: normal; overflow-x: auto; }
.log-row.error { background: rgba(248, 81, 73, 0.06); }
.log-row.warning { background: rgba(210, 153, 34, 0.06); }
.c-time { flex: 0 0 96px; }
.c-level { flex: 0 0 68px; }
.c-event { flex: 0 0 auto; min-width: 110px; font-weight: 600; }
.c-body { flex: 1; color: #adbac7; white-space: inherit; word-break: inherit; overflow: inherit; }
.dim { color: #6e7681; }
.lvl-tag {
  display: inline-block; border: 1px solid currentColor; border-radius: 4px;
  font-size: 10px; line-height: 15px; padding: 0 4px; color: #8b949e;
}
.exc { color: #ff7b72; }

.jump-btn { position: absolute; right: 20px; bottom: 16px; z-index: 5; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4); }

.log-foot { display: flex; justify-content: space-between; align-items: center; margin-top: 10px; }
.foot-hint { font-size: 12px; }

.detail { font-family: 'SFMono-Regular', Consolas, monospace; font-size: 13px; }
.detail-meta { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
.detail-sec { margin-bottom: 14px; }
.detail-label { font-size: 12px; color: var(--text-muted); margin-bottom: 4px; }
.detail-pre {
  background: var(--bg-muted); border: 1px solid var(--border-subtle); border-radius: 8px;
  padding: 12px; white-space: pre-wrap; word-break: break-all; margin: 0;
  max-height: 360px; overflow: auto; font-size: 12px; line-height: 1.6;
}
.detail-pre.dark { background: #0d1117; color: #c9d1d9; border-color: #30363d; }
.exc-pre { background: #fff2f0; }
.danger-text { color: var(--color-danger, #dc2626); }
</style>
