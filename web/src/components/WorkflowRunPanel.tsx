import { useEffect, useMemo, useState } from 'react'
import {
  Alert, Button, Collapse, Drawer, Empty, Form, Input, InputNumber, message, Space, Switch, Table, Tabs, Tag, Typography,
} from 'antd'
import {
  PlayCircleOutlined, CheckCircleOutlined, CloseCircleOutlined, MinusCircleOutlined,
  LoadingOutlined, HistoryOutlined, CheckOutlined, CloseOutlined,
} from '@ant-design/icons'
import { workflowApi, API_BASE } from '../api'
import { errMsg } from '../api/http'
import { NODE_META } from './WorkflowCanvas'
import MarkdownBody from './MarkdownBody'
import AttachmentView from './AttachmentView'

interface NodeLog {
  node_id: string
  node_type?: string
  status: string
  latency_ms?: number
  input?: any
  output?: any
  error?: string
}

interface Props {
  agentId: number
  graph: any
  open: boolean
  onClose: () => void
  onFinish?: () => void
  onNodeStatus?: (updater: (prev: Record<string, string>) => Record<string, string>) => void
}

function statusIcon(s?: string) {
  if (s === 'running') return <LoadingOutlined style={{ color: '#1677ff' }} />
  if (s === 'success') return <CheckCircleOutlined style={{ color: '#52c41a' }} />
  if (s === 'failed') return <CloseCircleOutlined style={{ color: '#ff4d4f' }} />
  if (s === 'skipped') return <MinusCircleOutlined style={{ color: '#d9d9d9' }} />
  if (s === 'waiting') return <LoadingOutlined style={{ color: '#faad14' }} />
  return <MinusCircleOutlined style={{ color: '#ccc' }} />
}

export default function WorkflowRunPanel({ agentId, graph, open, onClose, onFinish, onNodeStatus }: Props) {
  const [tab, setTab] = useState('run')
  const [form] = Form.useForm()
  const [running, setRunning] = useState(false)
  const [logs, setLogs] = useState<Record<string, NodeLog>>({})
  const [order, setOrder] = useState<string[]>([])
  const [result, setResult] = useState<any>(null)
  const [pending, setPending] = useState<{ run_id: number; node_id: string; title?: string; content?: string } | null>(null)
  const [history, setHistory] = useState<any[]>([])
  const [histLoading, setHistLoading] = useState(false)

  // 从 start 节点提取输入定义
  const inputDefs = useMemo(() => {
    const start = (graph?.nodes || []).find((n: any) => n.type === 'start')
    return (start?.data?.inputs || []) as { name: string; type?: string; required?: boolean; default?: any }[]
  }, [graph])

  const loadHistory = async () => {
    setHistLoading(true)
    try { setHistory((await workflowApi.listRuns(agentId, 30)).runs) }
    catch (e) { message.error(errMsg(e)) } finally { setHistLoading(false) }
  }
  useEffect(() => { if (open && tab === 'history') loadHistory() }, [open, tab])

  const upsert = (nid: string, patch: Partial<NodeLog>) => {
    setLogs((l) => ({ ...l, [nid]: { ...(l[nid] || { node_id: nid, status: 'running' }), ...patch } }))
    setOrder((o) => (o.includes(nid) ? o : [...o, nid]))
    if (patch.status) onNodeStatus?.((prev) => ({ ...prev, [nid]: patch.status as string }))
  }

  const consume = async (url: string, body: any) => {
    const token = localStorage.getItem('access_token')
    const resp = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify(body),
    })
    if (!resp.body) throw new Error('无响应流')
    const reader = resp.body.getReader()
    const dec = new TextDecoder()
    let buf = '', event = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += dec.decode(value, { stream: true })
      const lines = buf.split('\n'); buf = lines.pop() || ''
      for (const line of lines) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) {
          const raw = line.slice(5).trim(); if (!raw) continue
          let d: any; try { d = JSON.parse(raw) } catch { continue }
          if (event === 'node_started') upsert(d.node_id, { node_type: d.node_type, status: 'running' })
          else if (event === 'node_finished') upsert(d.node_id, { node_type: d.node_type, status: d.status, latency_ms: d.latency_ms, input: d.input, output: d.output, error: d.error })
          else if (event === 'approval_required') { setPending({ run_id: d.run_id, node_id: d.node_id, title: d.title, content: d.content }); setRunning(false) }
          else if (event === 'run_finished') {
            setResult(d)
            setRunning(false)
            if (d.status === 'waiting') return
            onFinish?.()
          }
        }
      }
    }
  }

  const run = async () => {
    try {
      await workflowApi.save(agentId, graph)  // 保存最新图
      const vals = await form.validateFields()
      // 按类型转换
      const inputs: Record<string, any> = {}
      for (const def of inputDefs) {
        let v = vals[def.name]
        if (def.type === 'json' && typeof v === 'string') { try { v = JSON.parse(v) } catch { /* keep */ } }
        inputs[def.name] = v
      }
      setLogs({}); setOrder([]); setResult(null); setPending(null); setRunning(true)
      await consume(`${API_BASE}/agents/${agentId}/workflow/run`, { inputs })
    } catch (e: any) {
      if (e?.errorFields) return  // 表单校验失败
      message.error(errMsg(e)); setRunning(false)
    }
  }

  const approve = async (decision: 'approve' | 'reject') => {
    if (!pending) return
    setRunning(true)
    try {
      await consume(workflowApi.approveUrl(pending.run_id), { decision })
      setPending(null)
    } catch (e) { message.error(errMsg(e)); setRunning(false) }
  }

  const renderLogs = (logsMap: Record<string, NodeLog>, ids: string[]) => {
    if (ids.length === 0) return <Empty description="尚无运行" image={Empty.PRESENTED_IMAGE_SIMPLE} />
    return (
      <Collapse
        size="small"
        items={ids.map((nid) => {
          const l = logsMap[nid] || { node_id: nid, status: 'pending' }
          const meta = NODE_META[l.node_type || ''] || { label: l.node_type || '节点', icon: '', color: '#999' }
          return {
            key: nid,
            label: (
              <Space>
                {statusIcon(l.status)}
                <span style={{ fontWeight: 500 }}>{nid}</span>
                <Tag color={meta.color} style={{ margin: 0 }}>{meta.icon} {meta.label}</Tag>
                {l.latency_ms != null && <Typography.Text type="secondary" style={{ fontSize: 12 }}>{l.latency_ms}ms</Typography.Text>}
                {l.error && <Tag color="red">失败</Tag>}
              </Space>
            ),
            children: (
              <div style={{ fontSize: 12 }}>
                {l.input !== undefined && (
                  <div style={{ marginBottom: 6 }}>
                    <b>输入：</b>
                    <pre style={{ margin: 0, maxHeight: 160, overflow: 'auto', whiteSpace: 'pre-wrap' }}>{JSON.stringify(l.input, null, 2)}</pre>
                  </div>
                )}
                {l.output !== undefined && (
                  <div>
                    <b>输出：</b>
                    <pre style={{ margin: 0, maxHeight: 220, overflow: 'auto', whiteSpace: 'pre-wrap' }}>{JSON.stringify(l.output, null, 2)}</pre>
                  </div>
                )}
                {l.error && <Typography.Text type="danger">{l.error}</Typography.Text>}
              </div>
            ),
          }
        })}
      />
    )
  }

  const openHistoryRun = async (runId: number) => {
    try {
      const r = await workflowApi.getRun(runId)
      const map: Record<string, NodeLog> = {}
      const ids: string[] = []
      for (const n of r.nodes) {
        map[n.node_id] = { node_id: n.node_id, node_type: n.node_type, status: n.status, input: n.input, output: n.output, error: n.error_msg }
        ids.push(n.node_id)
      }
      setLogs(map); setOrder(ids); setResult({ status: r.run.status, output: r.run.output, error: r.run.error_msg })
      setTab('run')
    } catch (e) { message.error(errMsg(e)) }
  }

  const renderOutput = () => {
    if (!result) return null
    const out = result.output
    const text = typeof out === 'object' && out ? (out.output ?? JSON.stringify(out)) : String(out ?? result.error ?? '')
    const files: any[] = []
    if (out && typeof out === 'object' && (out.file_key || out.artifact_id)) files.push(out)
    return (
      <div style={{ marginTop: 12 }}>
        <Alert type={result.status === 'success' ? 'success' : result.status === 'waiting' ? 'warning' : 'error'}
          message={result.status === 'success' ? '执行成功' : result.status === 'waiting' ? '等待审批' : (result.status === 'canceled' ? '已取消' : '执行失败')} />
        {text && <div style={{ marginTop: 8 }}><MarkdownBody content={String(text)} /></div>}
        {files.map((f) => <AttachmentView key={f.artifact_id || f.file_key} artifact att={f} />)}
      </div>
    )
  }

  return (
    <Drawer title="运行工作流" width={600} open={open} onClose={onClose} destroyOnClose>
      <Tabs activeKey={tab} onChange={setTab} items={[
        {
          key: 'run',
          label: '运行',
          children: (
            <div>
              {inputDefs.length > 0 ? (
                <Form form={form} layout="vertical" size="small">
                  {inputDefs.map((d) => (
                    <Form.Item key={d.name} name={d.name} label={d.name}
                      initialValue={d.default}
                      rules={d.required ? [{ required: true, message: `请输入 ${d.name}` }] : []}>
                      {d.type === 'number' ? <InputNumber style={{ width: '100%' }} />
                        : d.type === 'boolean' ? <Switch />
                        : d.type === 'json' ? <Input.TextArea rows={3} style={{ fontFamily: 'monospace' }} />
                        : <Input />}
                    </Form.Item>
                  ))}
                </Form>
              ) : (
                <Alert type="info" showIcon message="该工作流未声明输入（start 节点无 inputs），可直接运行。" style={{ marginBottom: 12 }} />
              )}
              <Space style={{ marginBottom: 12 }}>
                <Button type="primary" icon={<PlayCircleOutlined />} loading={running} onClick={run} disabled={!!pending}>运行</Button>
              </Space>

              {pending && (
                <Alert type="warning" showIcon style={{ marginBottom: 12 }}
                  message={pending.title || '需要人工审批'}
                  description={<div style={{ whiteSpace: 'pre-wrap', maxHeight: 160, overflow: 'auto' }}>{pending.content}</div>}
                  action={
                    <Space direction="vertical">
                      <Button size="small" type="primary" icon={<CheckOutlined />} onClick={() => approve('approve')}>通过</Button>
                      <Button size="small" danger icon={<CloseOutlined />} onClick={() => approve('reject')}>拒绝</Button>
                    </Space>
                  } />
              )}

              {renderLogs(logs, order)}
              {renderOutput()}
            </div>
          ),
        },
        {
          key: 'history',
          label: <Space><HistoryOutlined />历史</Space>,
          children: (
            <Table
              rowKey="id" size="small" loading={histLoading} dataSource={history} pagination={false}
              locale={{ emptyText: <Empty description="暂无运行记录" /> }}
              columns={[
                { title: '时间', dataIndex: 'created_at', width: 160, render: (v: number) => v ? new Date(v).toLocaleString('zh-CN') : '-' },
                { title: '状态', dataIndex: 'status', width: 90, render: (v: string) => <Tag color={v === 'success' ? 'green' : v === 'waiting' ? 'orange' : 'red'}>{v}</Tag> },
                { title: '耗时', dataIndex: 'latency_ms', width: 80, render: (v: number) => v ? `${v}ms` : '-' },
                { title: '操作', width: 80, render: (_: any, r: any) => <Button size="small" type="link" onClick={() => openHistoryRun(r.id)}>查看</Button> },
              ]}
            />
          ),
        },
      ]} />
    </Drawer>
  )
}
