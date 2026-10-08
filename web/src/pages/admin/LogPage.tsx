import { useEffect, useState } from 'react'
import { Button, Card, Input, Modal, Popconfirm, Select, Space, Switch, Tag, Tooltip, Typography, message } from 'antd'
import { ReloadOutlined, DownloadOutlined, DeleteOutlined } from '@ant-design/icons'
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

const LEVEL_COLOR: Record<string, string> = {
  error: 'red', critical: 'red', warning: 'orange', warn: 'orange',
  info: 'blue', debug: 'default',
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
      try { time = ts ? dayjs(ts).format('YYYY-MM-DD HH:mm:ss') : '' } catch { /* keep raw */ }
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

export default function LogPage() {
  const [rows, setRows] = useState<LogRow[]>([])
  const [loading, setLoading] = useState(false)
  const [level, setLevel] = useState<string | undefined>()
  const [keyword, setKeyword] = useState('')
  const [auto, setAuto] = useState(false)
  const [path, setPath] = useState('')
  const [rawMode, setRawMode] = useState(false)
  const [stats, setStats] = useState<any>(null)
  const [detail, setDetail] = useState<LogRow | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const r = await systemApi.logs({ lines: 500, level, keyword: keyword || undefined })
      setRows(r.lines.map(parseLine))
      setPath(r.path)
    } catch (e) { message.error(errMsg(e)) }
    finally { setLoading(false) }
  }

  const loadStats = async () => {
    try { setStats(await systemApi.logStats()) } catch { /* ignore */ }
  }

  useEffect(() => { load(); loadStats() }, [])
  useEffect(() => {
    if (!auto) return
    const t = setInterval(() => { load(); loadStats() }, 5000)
    return () => clearInterval(t)
  }, [auto, level, keyword])

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
      load(); loadStats()
    } catch (e) { message.error(errMsg(e)) }
  }

  return (
    <PageContainer
      title="系统日志"
      subtitle={path ? `日志文件：${path}` : '查看后端运行日志（最近 500 行）'}
      extra={
        <Space>
          <Switch checkedChildren="原文" unCheckedChildren="格式化" checked={rawMode} onChange={setRawMode} />
          <Switch checkedChildren="自动刷新" unCheckedChildren="自动刷新" checked={auto} onChange={setAuto} />
          <Button icon={<ReloadOutlined />} onClick={() => { load(); loadStats() }} loading={loading}>刷新</Button>
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
            <Select placeholder="级别" allowClear style={{ width: 120 }} value={level} onChange={setLevel}
              options={[{ value: 'info', label: 'info' }, { value: 'warning', label: 'warning' }, { value: 'error', label: 'error' }]} />
            <Input.Search placeholder="关键字过滤" style={{ width: 260 }} allowClear
              value={keyword} onChange={(e) => setKeyword(e.target.value)} onSearch={load} />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>共 {rows.length} 行</Typography.Text>
            {stats && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                · 文件 {stats.file_count} 个 / {humanSize(stats.total_bytes)}（单文件上限 {humanSize(stats.max_bytes)}，保留 {stats.retention_days} 天，每 {stats.cleanup_interval_hours}h 自动清理）
              </Typography.Text>
            )}
          </Space>
        }
      >
        <div style={{
          background: '#1e1e1e', color: '#d4d4d4', borderRadius: 6, padding: '6px 0',
          fontFamily: 'ui-monospace, Consolas, monospace', fontSize: 12.5, lineHeight: 1.7,
          maxHeight: '66vh', overflow: 'auto',
        }}>
          {rows.length === 0 ? (
            <div style={{ color: '#888', padding: '8px 12px' }}>{loading ? '加载中…' : '暂无日志（或日志文件为空）'}</div>
          ) : rawMode ? (
            rows.map((r, i) => (
              <div key={i} style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all', padding: '0 12px' }}>{r.raw}</div>
            ))
          ) : (
            rows.map((r, i) => (
              <div key={i} onClick={() => setDetail(r)} title="点击查看完整内容"
                style={{
                  display: 'flex', gap: 10, padding: '1px 12px', alignItems: 'baseline', cursor: 'pointer',
                  borderBottom: '1px solid rgba(255,255,255,0.04)',
                }}>
                <span style={{ color: '#7d8590', flex: '0 0 152px' }}>{r.time || '—'}</span>
                <span style={{ flex: '0 0 64px' }}>
                  {r.level
                    ? <Tag color={LEVEL_COLOR[r.level] || 'default'} style={{ margin: 0, fontSize: 11, lineHeight: '16px' }}>{r.level}</Tag>
                    : <span style={{ color: '#5a5a5a' }}>—</span>}
                </span>
                <span style={{
                  flex: '0 0 auto', minWidth: 90, fontWeight: 600,
                  color: r.level === 'error' ? '#ff7875' : r.level === 'warning' ? '#ffc069' : '#79c0ff',
                }}>{r.event || '—'}</span>
                <span style={{ flex: 1, wordBreak: 'break-all', color: '#c9d1d9' }}>
                  {r.fields}
                  {r.exception && <span style={{ color: '#ff7875' }}> {r.exception.split('\n')[0]}</span>}
                </span>
              </div>
            ))
          )}
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
                <pre style={{ background: '#f6f8fa', padding: 10, borderRadius: 6, whiteSpace: 'pre-wrap', wordBreak: 'break-all', margin: 0 }}>
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
              <Tooltip title="已复制？">
                <pre style={{ background: '#1e1e1e', color: '#d4d4d4', padding: 10, borderRadius: 6, whiteSpace: 'pre-wrap', wordBreak: 'break-all', margin: 0, maxHeight: 260, overflow: 'auto' }}>
                  {detail.raw}
                </pre>
              </Tooltip>
            </div>
          </div>
        )}
      </Modal>
    </PageContainer>
  )
}
