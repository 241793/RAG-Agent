import { useEffect, useMemo, useRef, useState } from 'react'
import { Button, Card, Input, Modal, Popconfirm, Segmented, Space, Switch, Tag, Tooltip, Typography, message } from 'antd'
import { ReloadOutlined, DownloadOutlined, DeleteOutlined, VerticalAlignBottomOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { systemApi } from '../../api'
import { errMsg } from '../../api/http'
import PageContainer from '../../components/PageContainer'

interface LogRow {
  raw: string
  time: string
  level: string
  event: string
  fields: string
  exception?: string
  parsed: boolean
}

const LEVELS = ['error', 'warning', 'info', 'debug'] as const
const LEVEL_COLOR: Record<string, string> = {
  error: 'red', critical: 'red', warning: 'orange', warn: 'orange',
  info: 'blue', debug: 'default',
}
// 左侧色条：一眼分辨级别
const LEVEL_BAR: Record<string, string> = {
  error: '#ff4d4f', critical: '#ff4d4f', warning: '#faad14', warn: '#faad14',
  info: '#1677ff', debug: '#8c8c8c',
}
const LEVEL_TEXT: Record<string, string> = {
  error: '#ff7875', critical: '#ff7875', warning: '#ffc069', warn: '#ffc069',
  info: '#79c0ff', debug: '#8b949e',
}

function humanSize(n: number): string {
  if (!n) return '0 B'
  const u = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let v = n
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${u[i]}`
}

/** 解析一行日志（JSON 优先；否则按文本兜底）。 */
function parseLine(line: string): LogRow {
  const s = (line || '').trim()
  if (s.startsWith('{')) {
    try {
      const d = JSON.parse(s)
      const ts = d.timestamp || d.time || d.ts || ''
      let time = ts
      try { time = ts ? dayjs(ts).format('HH:mm:ss.SSS') : '' } catch { /* keep raw */ }
      const level = String(d.level || d.levelname || 'info').toLowerCase()
      const event = String(d.event || d.msg || d.message || '')
      const skip = new Set(['timestamp', 'time', 'ts', 'level', 'levelname', 'event', 'msg', 'message', 'exception'])
      const fields = Object.entries(d)
        .filter(([k]) => !skip.has(k))
        .map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`)
        .join('  ')
      return { raw: line, time, level, event, fields, exception: d.exception, parsed: true }
    } catch { /* fallthrough */ }
  }
  const m = s.match(/^\[?(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[^\]]*)\]?\s*\[?(info|warn(?:ing)?|error|debug|critical)\]?\s*([\s\S]*)$/i)
  if (m) {
    return { raw: line, time: m[1].slice(0, 19).replace('T', ' '), level: m[2].toLowerCase(), event: '', fields: m[3], parsed: true }
  }
  return { raw: line, time: '', level: '', event: '', fields: s, parsed: false }
}

const MAX_BUFFER = 3000 // 缓冲上限（仅黏底时裁剪，避免上翻时内容位移）

export default function LogPage() {
  const [rows, setRows] = useState<LogRow[]>([])          // 全量（按关键字过滤后）
  const [loading, setLoading] = useState(false)
  const [levelFilter, setLevelFilter] = useState<string>('all') // 客户端级别过滤
  const [keyword, setKeyword] = useState('')
  const [auto, setAuto] = useState(true)                  // 默认跟随最新
  const [path, setPath] = useState('')
  const [rawMode, setRawMode] = useState(false)
  const [wrap, setWrap] = useState(true)
  const [stats, setStats] = useState<any>(null)
  const [detail, setDetail] = useState<LogRow | null>(null)
  const [pending, setPending] = useState(0)               // 上翻期间到达的新日志数

  const boxRef = useRef<HTMLDivElement>(null)
  const rowsRef = useRef<LogRow[]>([])
  const atBottomRef = useRef(true)
  const pendingRef = useRef(0)

  // 客户端按级别过滤 + 各级别计数（来自全量，保证数字准确）
  const visible = useMemo(
    () => (levelFilter === 'all' ? rows : rows.filter((r) => r.level === levelFilter)),
    [rows, levelFilter],
  )
  const counts = useMemo(() => {
    const c: Record<string, number> = { all: rows.length }
    for (const r of rows) if (r.level) c[r.level] = (c[r.level] || 0) + 1
    return c
  }, [rows])

  const scrollToBottom = () => {
    const el = boxRef.current
    if (el) el.scrollTop = el.scrollHeight
    atBottomRef.current = true
    pendingRef.current = 0
    setPending(0)
  }

  const onScroll = () => {
    const el = boxRef.current
    if (!el) return
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 48
    atBottomRef.current = nearBottom
    if (nearBottom && pendingRef.current) { pendingRef.current = 0; setPending(0) }
  }

  /** 拉取日志：增量追加（不整体替换），保证上翻时已有内容不位移。 */
  const load = async (initial = false) => {
    if (initial) setLoading(true)
    try {
      const r = await systemApi.logs({ lines: 500, keyword: keyword || undefined })
      setPath(r.path)
      const fresh = r.lines.map(parseLine)
      const prev = rowsRef.current

      let merged = fresh
      let appended = fresh.length
      if (!initial && prev.length) {
        // 用首尾双锚点定位重叠，避免行内时间戳重复导致误判
        const lastPrev = prev[prev.length - 1]?.raw
        let li = -1
        for (let i = fresh.length - 1; i >= 0; i--) { if (fresh[i].raw === lastPrev) { li = i; break } }
        if (li >= 0) {
          const added = fresh.slice(li + 1)
          appended = added.length
          if (appended === 0) {
            // 无新行：保持引用不变，避免无谓重渲染
            return
          }
          merged = [...prev, ...added]
        } else {
          // 无重叠（文件被清理/轮转）→ 整体替换
          appended = fresh.length
        }
      }

      // 仅在黏底时裁剪缓冲；上翻时保留，绝不因裁剪导致内容上移
      if (atBottomRef.current && merged.length > MAX_BUFFER) {
        merged = merged.slice(merged.length - MAX_BUFFER)
      }
      rowsRef.current = merged
      setRows(merged)

      if (atBottomRef.current) {
        // 等 DOM 提交后再滚到底
        requestAnimationFrame(() => {
          const el = boxRef.current
          if (el) el.scrollTop = el.scrollHeight
        })
      } else if (appended > 0) {
        pendingRef.current += appended
        setPending(pendingRef.current)
      }
    } catch (e) { message.error(errMsg(e)) }
    finally { if (initial) setLoading(false) }
  }

  const loadStats = async () => {
    try { setStats(await systemApi.logStats()) } catch { /* ignore */ }
  }

  useEffect(() => { load(true); loadStats() }, [])
  // 关键字变化 → 重新拉取（服务端过滤）；重置缓冲
  useEffect(() => {
    rowsRef.current = []
    pendingRef.current = 0
    setPending(0)
    load(true)
  }, [keyword])
  // 自动刷新：只追加，不打断上翻
  useEffect(() => {
    if (!auto) return
    const t = setInterval(() => { load(false); loadStats() }, 3000)
    return () => clearInterval(t)
  }, [auto, keyword])

  // 切换级别过滤后，若原本黏底则继续黏底
  useEffect(() => {
    if (atBottomRef.current) {
      requestAnimationFrame(() => { const el = boxRef.current; if (el) el.scrollTop = el.scrollHeight })
    }
  }, [levelFilter, rawMode])

  const download = () => {
    const token = localStorage.getItem('access_token')
    fetch(systemApi.downloadUrl(), { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then((r) => r.blob())
      .then((b) => {
        const url = URL.createObjectURL(b)
        const a = document.createElement('a')
        a.href = url; a.download = 'app.log'; a.click()
        URL.revokeObjectURL(url)
      })
      .catch((e) => message.error(String(e)))
  }

  const clearLogs = async () => {
    try {
      const r = await systemApi.clearLogs()
      message.success(`${r.message}（释放 ${humanSize(r.freed_bytes)}）`)
      rowsRef.current = []
      load(true); loadStats()
    } catch (e) { message.error(errMsg(e)) }
  }

  const levelOptions = [
    { value: 'all', label: `全部 ${counts.all || 0}` },
    ...LEVELS.map((lv) => ({ value: lv, label: `${lv} ${counts[lv] || 0}` })),
  ]

  return (
    <PageContainer
      title="系统日志"
      subtitle={path ? `日志文件：${path}` : '查看后端运行日志（跟随最新，上翻查看时不会被新日志打断）'}
      extra={
        <Space>
          <Switch checkedChildren="原文" unCheckedChildren="格式化" checked={rawMode} onChange={setRawMode} />
          <Tooltip title="每 3 秒拉取新日志并自动跟到最新；当你向上滚动查看历史时会自动暂停跟随">
            <Switch checkedChildren="跟随最新" unCheckedChildren="跟随最新" checked={auto} onChange={setAuto} />
          </Tooltip>
          <Button icon={<ReloadOutlined />} onClick={() => { load(true); loadStats() }} loading={loading}>刷新</Button>
          <Button icon={<DownloadOutlined />} onClick={download}>下载</Button>
          <Popconfirm title="清空所有日志（含备份）？" onConfirm={clearLogs}>
            <Button danger icon={<DeleteOutlined />}>清理</Button>
          </Popconfirm>
        </Space>
      }
    >
      <Card
        title={
          <Space wrap>
            <Segmented size="small" value={levelFilter} onChange={(v) => setLevelFilter(v as string)} options={levelOptions} />
            <Input.Search placeholder="关键字过滤（如 request_id / error）" style={{ width: 280 }} allowClear
              value={keyword} onChange={(e) => setKeyword(e.target.value)} onSearch={() => load(true)} />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              显示 {visible.length} / 共 {rows.length} 行
            </Typography.Text>
            {stats && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                · 文件 {stats.file_count} 个 / {humanSize(stats.total_bytes)}（单文件上限 {humanSize(stats.max_bytes)}，保留 {stats.retention_days} 天）
              </Typography.Text>
            )}
          </Space>
        }
      >
        <div style={{ position: 'relative' }}>
          {/* 粘性表头 */}
          <div style={{
            display: 'flex', gap: 10, padding: '4px 12px', fontSize: 11, letterSpacing: 0.3,
            color: '#8b949e', background: '#161b22', borderBottom: '1px solid #30363d',
            borderRadius: '6px 6px 0 0', fontFamily: 'ui-monospace, Consolas, monospace',
          }}>
            <span style={{ flex: '0 0 92px' }}>时间</span>
            <span style={{ flex: '0 0 62px' }}>级别</span>
            <span style={{ flex: '0 0 auto', minWidth: 110 }}>事件</span>
            <span style={{ flex: 1 }}>内容</span>
          </div>

          <div ref={boxRef} onScroll={onScroll} className="log-view" style={{
            background: '#0d1117', color: '#c9d1d9', padding: '2px 0',
            fontFamily: 'ui-monospace, Consolas, monospace', fontSize: 12.5, lineHeight: 1.7,
            maxHeight: '68vh', overflow: 'auto', borderRadius: '0 0 6px 6px',
          }}>
            {visible.length === 0 ? (
              <div style={{ color: '#6e7681', padding: '10px 12px' }}>
                {loading ? '加载中…' : (keyword ? '无匹配日志（换个关键字试试）' : '暂无日志（或日志文件为空）')}
              </div>
            ) : rawMode ? (
              visible.map((r, i) => (
                <div key={i} className="log-row" style={{
                  whiteSpace: wrap ? 'pre-wrap' : 'pre', wordBreak: wrap ? 'break-all' : 'normal',
                  overflowX: wrap ? 'hidden' : 'auto', padding: '0 12px',
                }}>{r.raw}</div>
              ))
            ) : (
              visible.map((r, i) => (
                <div key={i} className="log-row" onClick={() => setDetail(r)} title="点击查看完整内容"
                  style={{
                    display: 'flex', gap: 10, padding: '1px 12px', alignItems: 'baseline', cursor: 'pointer',
                    borderLeft: `3px solid ${LEVEL_BAR[r.level] || 'transparent'}`,
                    background: r.level === 'error' ? 'rgba(248,81,73,0.06)'
                      : r.level === 'warning' ? 'rgba(210,153,34,0.06)' : 'transparent',
                  }}>
                  <span style={{ color: '#6e7681', flex: '0 0 92px' }}>{r.time || '—'}</span>
                  <span style={{ flex: '0 0 62px' }}>
                    {r.level
                      ? <Tag color={LEVEL_COLOR[r.level] || 'default'} style={{ margin: 0, fontSize: 10, lineHeight: '16px', paddingInline: 4 }}>{r.level}</Tag>
                      : <span style={{ color: '#484f58' }}>—</span>}
                  </span>
                  <span style={{
                    flex: '0 0 auto', minWidth: 110, fontWeight: 600,
                    color: LEVEL_TEXT[r.level] || '#c9d1d9',
                  }}>{r.event || '—'}</span>
                  <span style={{
                    flex: 1, color: '#adbac7',
                    whiteSpace: wrap ? 'pre-wrap' : 'pre', wordBreak: wrap ? 'break-all' : 'normal',
                    overflow: wrap ? 'hidden' : 'auto',
                  }}>
                    {r.fields}
                    {r.exception && <span style={{ color: '#ff7b72' }}> {r.exception.split('\n')[0]}</span>}
                  </span>
                </div>
              ))
            )}
          </div>

          {/* 上翻时：新日志到达提示，点击回到最新 */}
          {pending > 0 && (
            <Button
              type="primary" size="small" icon={<VerticalAlignBottomOutlined />}
              onClick={scrollToBottom}
              style={{
                position: 'absolute', right: 20, bottom: 16, zIndex: 5,
                boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
              }}
            >
              {pending} 条新日志 · 回到最新
            </Button>
          )}
        </div>

        <div style={{ marginTop: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Space>
            <Tooltip title="关闭后每行不换行、可横向滚动，适合看长 JSON">
              <span style={{ fontSize: 12, color: 'var(--color-text-2)' }}>自动换行 <Switch size="small" checked={wrap} onChange={setWrap} /></span>
            </Tooltip>
          </Space>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {auto ? '跟随最新中' : '已暂停跟随'} · 级别色条：红=错误 / 橙=警告 / 蓝=信息
          </Typography.Text>
        </div>
      </Card>

      <Modal title="日志详情" open={!!detail} onCancel={() => setDetail(null)} footer={
        <Space>
          <Button onClick={() => { navigator.clipboard?.writeText(detail?.raw || ''); message.success('已复制原文') }}>复制原文</Button>
          <Button type="primary" onClick={() => setDetail(null)}>关闭</Button>
        </Space>
      } width={860}>
        {detail && (
          <div style={{ fontFamily: 'ui-monospace, Consolas, monospace', fontSize: 13 }}>
            <div style={{ marginBottom: 12 }}>
              <Tag color={LEVEL_COLOR[detail.level] || 'default'}>{detail.level || '—'}</Tag>
              <b>{detail.event || '(无事件名)'}</b>
              <span style={{ color: '#888', marginLeft: 12 }}>{detail.time}</span>
            </div>
            {detail.fields && (
              <div style={{ marginBottom: 12 }}>
                <div style={{ color: '#888', fontSize: 12, marginBottom: 4 }}>字段</div>
                <pre style={{ background: 'var(--color-bg-subtle)', padding: 10, borderRadius: 6, whiteSpace: 'pre-wrap', wordBreak: 'break-all', margin: 0 }}>
                  {detail.fields}
                </pre>
              </div>
            )}
            {detail.exception && (
              <div style={{ marginBottom: 12 }}>
                <div style={{ color: '#c00', fontSize: 12, marginBottom: 4 }}>异常堆栈</div>
                <pre style={{ background: '#fff2f0', padding: 10, borderRadius: 6, whiteSpace: 'pre-wrap', wordBreak: 'break-all', margin: 0, maxHeight: 360, overflow: 'auto' }}>
                  {detail.exception}
                </pre>
              </div>
            )}
            <div>
              <div style={{ color: '#888', fontSize: 12, marginBottom: 4 }}>原始行</div>
              <pre style={{ background: '#0d1117', color: '#c9d1d9', padding: 10, borderRadius: 6, whiteSpace: 'pre-wrap', wordBreak: 'break-all', margin: 0, maxHeight: 260, overflow: 'auto' }}>
                {detail.raw}
              </pre>
            </div>
          </div>
        )}
      </Modal>
    </PageContainer>
  )
}
