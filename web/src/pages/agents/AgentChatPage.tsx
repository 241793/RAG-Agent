import { useEffect, useRef, useState } from 'react'
import {
  Button, Card, Collapse, Empty, Input, List, message, Select, Space, Tag, Tooltip, Typography,
} from 'antd'
import {
  SendOutlined, UserOutlined, RobotOutlined, ClearOutlined, ToolOutlined,
  StopOutlined, CopyOutlined, PlusOutlined, DeleteOutlined, LikeOutlined, DislikeOutlined,
  UnorderedListOutlined, ArrowDownOutlined,
} from '@ant-design/icons'
import { errMsg } from '../../api/http'
import PendingActionCard from '../../components/PendingActionCard'
import MessageOutline from '../../components/MessageOutline'
import MessageTimeline from '../../components/MessageTimeline'
import MarkdownBody from '../../components/MarkdownBody'
import ReasoningBlock from '../../components/ReasoningBlock'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeftOutlined } from '@ant-design/icons'
import {
  agentApi, chatApi, streamChat, providerApi, API_BASE,
  type Agent, type AgentMode, type Conversation, type ModelConfig, type ToolCallEvt, type ToolResultEvt, type PendingActionEvt,
} from '../../api'

interface ToolStep {
  call: ToolCallEvt
  result?: ToolResultEvt
}
interface Msg {
  role: 'user' | 'assistant'
  content: string
  reasoning?: string
  steps?: ToolStep[]
  id?: number
  feedback?: number | null
  pending?: PendingActionEvt
  pendingResolved?: boolean
}

export default function AgentChatPage() {
  const { id } = useParams()
  const agentId = Number(id)
  const nav = useNavigate()
  const [agent, setAgent] = useState<Agent | null>(null)
  const [modes, setModes] = useState<AgentMode[]>([])
  const [modeId, setModeId] = useState<number | undefined>()
  const [models, setModels] = useState<ModelConfig[]>([])
  const [modelId, setModelId] = useState<number | undefined>()
  const [input, setInput] = useState('')
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [streaming, setStreaming] = useState(false)
  const [convId, setConvId] = useState<number | undefined>()
  const [convs, setConvs] = useState<Conversation[]>([])
  const listRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const atBottomRef = useRef(true)
  const [showJump, setShowJump] = useState(false)
  const [outlineOpen, setOutlineOpen] = useState(false)
  const [highlightIdx, setHighlightIdx] = useState<number | null>(null)

  const loadConvs = async () => {
    try {
      const all = await chatApi.conversations()
      // 只保留属于本智能体的会话
      setConvs(all.filter((c) => (c as any).settings?.agent_id === agentId))
    } catch (e) { message.error(errMsg(e)) }
  }

  useEffect(() => {
    (async () => {
      try {
        setAgent(await agentApi.get(agentId))
        setModes(await agentApi.modes(agentId))
        const cs = await providerApi.configs()
        setModels(cs.filter((c) => c.purpose === 'chat'))
        await loadConvs()
      } catch (e) { message.error(errMsg(e)) }
    })()
  }, [agentId])

  // 仅在用户贴底时自动跟随；向上翻历史不被打断
  useEffect(() => {
    if (atBottomRef.current) {
      listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' })
    } else if (streaming) {
      setShowJump(true)
    }
  }, [msgs, streaming])

  const onScroll = () => {
    const el = listRef.current
    if (!el) return
    const bottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80
    atBottomRef.current = bottom
    setShowJump(!bottom)
  }

  const jumpToLatest = () => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' })
    atBottomRef.current = true
    setShowJump(false)
  }

  const jumpToMessage = (idx: number) => {
    const el = document.getElementById(`msg-${idx}`)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
      setHighlightIdx(idx)
      setTimeout(() => setHighlightIdx((h) => (h === idx ? null : h)), 1800)
    }
  }

  const openConversation = async (cid: number) => {
    try {
      setConvId(cid)
      const ms = await chatApi.messages(cid)
      setMsgs(ms.filter((m) => m.role === 'user' || m.role === 'assistant')
        .map((m) => ({
          role: m.role as 'user' | 'assistant',
          content: m.content,
          reasoning: (m as any).reasoning,
          steps: (m as any).tool_calls,
          id: m.id,
          feedback: (m as any).feedback ?? null,
        })))
    } catch (e) { message.error(errMsg(e)) }
  }

  const newConv = () => {
    setConvId(undefined)
    const greeting = (agent?.config as any)?.greeting
    setMsgs(greeting ? [{ role: 'assistant', content: greeting }] : [])
  }

  const delConv = async (cid: number) => {
    try { await chatApi.remove(cid); loadConvs(); if (convId === cid) newConv() }
    catch (e) { message.error(errMsg(e)) }
  }

  const doFeedback = async (idx: number, val: number) => {
    const m = msgs[idx]
    if (!m.id) { message.info('请等回答完成后再评价'); return }
    const next = m.feedback === val ? 0 : val
    try {
      await chatApi.feedback(m.id, next)
      setMsgs((arr) => { const c = [...arr]; c[idx] = { ...c[idx], feedback: next }; return c })
    } catch (e) { message.error(errMsg(e)) }
  }

  const confirmAction = async (idx: number, actionId: number, decision: 'approve' | 'reject') => {
    setMsgs((arr) => { const c = [...arr]; c[idx] = { ...c[idx], pendingResolved: true }; return c })
    setStreaming(true)
    const ctrl = new AbortController()
    abortRef.current = ctrl
    const upd = (fn: (m: Msg) => Msg) => {
      setMsgs((arr) => { const c = [...arr]; c[c.length - 1] = fn(c[c.length - 1]); return c })
    }
    try {
      const token = localStorage.getItem('access_token')
      const resp = await fetch(agentApi.confirmToolUrl(agentId), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({ action_id: actionId, decision }),
        signal: ctrl.signal,
      })
      if (!resp.body) throw new Error('无响应流')
      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = '', event = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        for (const line of lines) {
          if (line.startsWith('event:')) event = line.slice(6).trim()
          else if (line.startsWith('data:')) {
            const raw = line.slice(5).trim()
            if (!raw) continue
            let data: any
            try { data = JSON.parse(raw) } catch { continue }
            if (event === 'delta') upd((m) => ({ ...m, content: m.content + (data.text || '') }))
            else if (event === 'done') upd((m) => ({ ...m, id: data.message_id }))
            else if (event === 'error') message.error(data.message)
          }
        }
      }
    } catch (e: any) {
      if (e?.name !== 'AbortError') message.error(errMsg(e))
    } finally {
      setStreaming(false); abortRef.current = null; loadConvs()
    }
  }

  const send = async () => {
    const text = input.trim()
    if (!text) return
    setInput('')
    setMsgs((m) => [...m, { role: 'user', content: text }, { role: 'assistant', content: '', steps: [] }])
    setStreaming(true)
    const ctrl = new AbortController()
    abortRef.current = ctrl

    const upd = (fn: (m: Msg) => Msg) => {
      setMsgs((arr) => {
        const copy = [...arr]
        copy[copy.length - 1] = fn(copy[copy.length - 1])
        return copy
      })
    }

    try {
      await streamChat(
        { conversation_id: convId, kb_ids: agent?.kb_ids || [], message: text,
          mode_id: modeId, model_config_id: modelId } as any,
        {
          onMeta: (d: any) => { if (d.conversation_id) setConvId(d.conversation_id) },
          onDelta: (t) => upd((m) => ({ ...m, content: m.content + t })),
          onReasoning: (t) => upd((m) => ({ ...m, reasoning: (m.reasoning || '') + t })),
          onToolCall: (evt) => upd((m) => ({ ...m, steps: [...(m.steps || []), { call: evt }] })),
          onToolResult: (evt) => upd((m) => {
            const steps = [...(m.steps || [])]
            const idx = steps.findIndex((s) => s.call.id === evt.id && !s.result)
            if (idx >= 0) steps[idx] = { ...steps[idx], result: evt }
            else steps.push({ call: { id: evt.id, name: evt.name, arguments: '' }, result: evt })
            return { ...m, steps }
          }),
          onDone: (mid) => upd((m) => ({ ...m, id: mid })),
          onPendingAction: (evt) => upd((m) => ({ ...m, pending: evt })),
          onError: (msg) => message.error(msg),
        },
        ctrl.signal,
        `${API_BASE}/agents/${agentId}/run`,
      )
    } catch (e: any) {
      if (e?.name !== 'AbortError') message.error(errMsg(e))
    } finally {
      setStreaming(false); abortRef.current = null; loadConvs()
    }
  }

  const stop = () => { abortRef.current?.abort(); setStreaming(false) }

  return (
    <div style={{ display: 'flex', gap: 12, height: 'calc(100vh - 112px)' }}>
      {/* 历史会话侧栏 */}
      <div style={{ width: 200, flex: '0 0 auto', display: 'flex', flexDirection: 'column' }}>
        <Button icon={<PlusOutlined />} block onClick={newConv} style={{ marginBottom: 8 }}>新对话</Button>
        <div style={{ flex: 1, overflowY: 'auto', border: '1px solid #f0f0f0', borderRadius: 6 }}>
          <List size="small" dataSource={convs} locale={{ emptyText: '暂无历史' }}
            renderItem={(c: any) => (
              <List.Item style={{ cursor: 'pointer', background: c.id === convId ? '#e6f4ff' : undefined, padding: '6px 10px' }}
                onClick={() => openConversation(c.id)}
                actions={[<DeleteOutlined key="d" onClick={(e) => { e.stopPropagation(); delConv(c.id) }} />]}>
                <Typography.Text ellipsis style={{ fontSize: 13 }}>{c.title || '未命名'}</Typography.Text>
              </List.Item>
            )}
          />
        </div>
      </div>

      {/* 主对话区 */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
      <Space style={{ marginBottom: 12 }} wrap>
        <Button icon={<ArrowLeftOutlined />} onClick={() => nav('/agents')}>返回</Button>
        <Typography.Text strong>{agent?.name || '智能体'}</Typography.Text>
        {modes.length > 0 && (
          <>
            <span>模式：</span>
            <Select
              allowClear
              style={{ minWidth: 160 }}
              placeholder="默认模式"
              value={modeId}
              onChange={setModeId}
              options={modes.map((m) => ({ value: m.id, label: m.name }))}
            />
          </>
        )}
        {models.length > 0 && (
          <>
            <span>模型：</span>
            <Select allowClear style={{ minWidth: 180 }} placeholder="默认模型" value={modelId}
              onChange={setModelId}
              options={models.map((m) => ({ value: m.id, label: m.display_name || m.model_name }))} />
          </>
        )}
        {msgs.length >= 4 && <Button icon={<UnorderedListOutlined />} onClick={() => setOutlineOpen(true)}>目录</Button>}
        <Button icon={<ClearOutlined />} onClick={newConv}>新对话</Button>
      </Space>

      <div style={{ position: 'relative', flex: 1, minHeight: 0, display: 'flex' }}>
        <div ref={listRef} onScroll={onScroll} style={{ flex: 1, minWidth: 0, height: '100%', overflowY: 'auto', paddingRight: 8 }}>
        {msgs.length === 0 ? (
          <Empty style={{ marginTop: 80 }} description="向智能体提问，它会自动调用工具获取答案" />
        ) : (
          msgs.map((m, i) => (
            <div key={i} id={`msg-${i}`} style={{
              display: 'flex', gap: 10, marginBottom: 18,
              flexDirection: m.role === 'user' ? 'row-reverse' : 'row',
              borderRadius: 8, transition: 'background 0.3s',
              background: highlightIdx === i ? '#fffbe6' : undefined,
              padding: highlightIdx === i ? '6px 8px' : undefined,
            }}>
              <div style={{ flex: '0 0 auto', paddingTop: 4 }}>
                {m.role === 'user' ? <UserOutlined /> : <RobotOutlined style={{ color: '#1677ff' }} />}
              </div>
              <Card size="small" style={{ maxWidth: '82%', background: m.role === 'user' ? '#e6f4ff' : '#fff' }}>
                {m.steps && m.steps.length > 0 && (
                  <Collapse
                    size="small"
                    style={{ marginBottom: 8 }}
                    items={m.steps.map((s, si) => ({
                      key: si,
                      label: <Space><ToolOutlined /><span>调用工具：{s.call.name}</span>{s.result?.is_error ? <Tag color="red">失败</Tag> : <Tag color="green">完成</Tag>}</Space>,
                      children: (
                        <div style={{ fontSize: 12 }}>
                          <div><b>参数：</b><pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{s.call.arguments}</pre></div>
                          {s.result && <div style={{ marginTop: 6 }}><b>结果：</b><pre style={{ margin: 0, whiteSpace: 'pre-wrap', maxHeight: 200, overflow: 'auto' }}>{s.result.content}</pre></div>}
                        </div>
                      ),
                    }))}
                  />
                )}
                {m.role === 'assistant' && <ReasoningBlock reasoning={m.reasoning} streaming={streaming && i === msgs.length - 1} />}
                {m.role === 'assistant'
                  ? (streaming && i === msgs.length - 1
                      ? <div className="md-body streaming-plain">{m.content || '…'}</div>
                      : <MarkdownBody content={m.content} />)
                  : <div className="md-body">{m.content}</div>}
                {m.pending && (
                  <div style={{ marginTop: 10 }}>
                    <PendingActionCard
                      action={m.pending}
                      resolved={m.pendingResolved}
                      onConfirm={(aid, decision) => confirmAction(i, aid, decision)}
                    />
                  </div>
                )}
                {m.role === 'assistant' && m.content && !streaming && (
                  <div style={{ marginTop: 6 }}>
                    <Space size={2}>
                      <Tooltip title="复制"><Button type="text" size="small" icon={<CopyOutlined />}
                        onClick={() => { navigator.clipboard?.writeText(m.content); message.success('已复制') }} /></Tooltip>
                      <Tooltip title="有帮助"><Button type="text" size="small" icon={<LikeOutlined />}
                        style={{ color: m.feedback === 1 ? '#52c41a' : undefined }} onClick={() => doFeedback(i, 1)} /></Tooltip>
                      <Tooltip title="没帮助"><Button type="text" size="small" icon={<DislikeOutlined />}
                        style={{ color: m.feedback === -1 ? '#f5222d' : undefined }} onClick={() => doFeedback(i, -1)} /></Tooltip>
                    </Space>
                  </div>
                )}
              </Card>
            </div>
          ))
        )}
        {showJump && (
          <div style={{ position: 'sticky', bottom: 8, textAlign: 'center', pointerEvents: 'none' }}>
            <Button size="small" type="primary" icon={<ArrowDownOutlined />}
              style={{ pointerEvents: 'auto', boxShadow: '0 2px 8px rgba(0,0,0,0.15)' }}
              onClick={jumpToLatest}>回到最新</Button>
          </div>
        )}
        </div>
        <MessageTimeline
          items={msgs.map((m, i) => ({ index: i, role: m.role, text: m.content }))}
          scrollRoot={listRef}
          onJump={jumpToMessage}
        />
      </div>

      <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
        <Input.TextArea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="输入问题，Enter 发送，Shift+Enter 换行"
          autoSize={{ minRows: 1, maxRows: 4 }}
          onPressEnter={(e) => { if (!e.shiftKey) { e.preventDefault(); send() } }}
        />
        {streaming
          ? <Button danger icon={<StopOutlined />} onClick={stop}>停止</Button>
          : <Button type="primary" icon={<SendOutlined />} onClick={send}>发送</Button>}
      </div>
      </div>

      <MessageOutline
        open={outlineOpen}
        onClose={() => setOutlineOpen(false)}
        onJump={jumpToMessage}
        items={msgs.map((m, i) => ({ index: i, role: m.role, text: m.content }))}
      />
    </div>
  )
}
