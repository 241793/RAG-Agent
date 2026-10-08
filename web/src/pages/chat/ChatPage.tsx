import { useEffect, useRef, useState } from 'react'
import {
  Button, Card, Collapse, Drawer, Dropdown, Empty, Input, List, message, Modal, Select, Slider,
  Space, Switch, Tag, Tooltip, Typography, Upload,
} from 'antd'
import {
  SendOutlined, UserOutlined, RobotOutlined, ClearOutlined, PlusOutlined, DeleteOutlined,
  StopOutlined, ReloadOutlined, CopyOutlined, LikeOutlined, DislikeOutlined, PaperClipOutlined,
  SettingOutlined, EditOutlined, UnorderedListOutlined, ArrowDownOutlined, ToolOutlined, MoreOutlined,
} from '@ant-design/icons'
import { useSearchParams } from 'react-router-dom'
import {
  chatApi, docApi, kbApi, providerApi, streamChat, usageApi,
  type Attachment, type ArtifactRef, type Citation, type Conversation, type KB, type ModelConfig, type StreamHandlers, type UsageTotals,
} from '../../api'
import { errMsg } from '../../api/http'
import { useAuth } from '../../stores/auth'
import MarkdownBody from '../../components/MarkdownBody'
import AttachmentView from '../../components/AttachmentView'
import PendingAttachmentProgress from '../../components/PendingAttachmentProgress'
import ReasoningBlock from '../../components/ReasoningBlock'
import PendingActionCard from '../../components/PendingActionCard'
import MessageOutline from '../../components/MessageOutline'
import MessageTimeline from '../../components/MessageTimeline'

interface Msg {
  id?: number
  role: 'user' | 'assistant'
  content: string
  reasoning?: string
  citations?: Citation[]
  attachments?: Attachment[]
  artifacts?: ArtifactRef[]
  usage?: Record<string, number>
  model?: string
  feedback?: number | null
  streaming?: boolean
  steps?: { call: any; result?: any }[]
  pending?: any
  pendingResolved?: boolean
}

export default function ChatPage() {
  const { hasPermission } = useAuth()
  const [searchParams] = useSearchParams()
  const [kbs, setKbs] = useState<KB[]>([])
  const [selectedKbs, setSelectedKbs] = useState<number[]>([])
  const [retrievalMode, setRetrievalMode] = useState<'auto' | 'custom' | 'off'>('auto') // 检索范围三态
  const [aiTools, setAiTools] = useState(true)      // 允许 AI 调用平台工具
  const [autoWrite, setAutoWrite] = useState(false) // 写操作免确认（全自动）
  const [input, setInput] = useState('')
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [streaming, setStreaming] = useState(false)
  const [convId, setConvId] = useState<number | undefined>()
  const [convs, setConvs] = useState<Conversation[]>([])
  const [models, setModels] = useState<ModelConfig[]>([])
  const [modelId, setModelId] = useState<number | undefined>()
  const [temperature, setTemperature] = useState(0.2)
  const [showParams, setShowParams] = useState(false)
  const [pendingAtts, setPendingAtts] = useState<Attachment[]>([])
  const [docKb, setDocKb] = useState<number | undefined>()
  const [docPreview, setDocPreview] = useState<{ title: string; content: string } | null>(null)
  // 用量统计
  const [todayUsage, setTodayUsage] = useState<UsageTotals | null>(null)
  const [convUsage, setConvUsage] = useState<UsageTotals | null>(null)
  const [convSummary, setConvSummary] = useState<string | null>(null)
  // 跨用户查看
  const canReadAll = hasPermission('chat:read_all')
  const [viewUsers, setViewUsers] = useState<{ user_id: number; name: string; conversation_count: number; channel_label?: string | null; external_id?: string | null }[]>([])
  const [viewUser, setViewUser] = useState<number | undefined>()
  const listRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const convIdRef = useRef<number | undefined>(undefined)
  const atBottomRef = useRef(true)          // 用户是否贴近底部
  const [showJump, setShowJump] = useState(false)   // 显示"回到最新"
  const [outlineOpen, setOutlineOpen] = useState(false)
  const [highlightIdx, setHighlightIdx] = useState<number | null>(null)

  const loadConvs = async () => {
    try {
      if (viewUser) setConvs(await chatApi.adminConversations(viewUser) as Conversation[])
      else setConvs(await chatApi.conversations())
    } catch (e) { message.error(errMsg(e)) }
  }

  const refreshUsage = async () => {
    try { setTodayUsage(await usageApi.meToday()) } catch { /* ignore */ }
    if (convId) { try { setConvUsage(await chatApi.usage(convId)) } catch { /* ignore */ } }
    else setConvUsage(null)
  }

  useEffect(() => {
    kbApi.list().then(setKbs).catch(() => {})
    providerApi.configs().then((cs) => {
      const chatModels = cs.filter((c) => c.purpose === 'chat')
      setModels(chatModels)
      const def = chatModels.find((m) => m.is_default) || chatModels[0]
      if (def) setModelId(def.id)
    }).catch(() => {})
    loadConvs()
    refreshUsage()
    if (canReadAll) chatApi.adminChatUsers().then(setViewUsers).catch(() => {})
  }, [])

  // 从 URL ?conv= 打开指定会话（文件管理页跳转过来）
  useEffect(() => {
    const cid = searchParams.get('conv')
    if (cid) openConversation(Number(cid))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => { convIdRef.current = convId; refreshUsage() }, [convId])
  useEffect(() => { loadConvs() }, [viewUser])

  // 仅在用户贴底时自动跟随（向上翻历史不被打断）
  useEffect(() => {
    if (atBottomRef.current) {
      listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' })
    } else if (streaming) {
      setShowJump(true)   // 有新内容但用户在看历史 → 提示"回到最新"
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

  const openConversation = async (id: number) => {
    try {
      setConvId(id)
      const ms = await chatApi.messages(id)
      setMsgs(ms.filter((m) => m.role === 'user' || m.role === 'assistant').map((m) => ({
        id: m.id, role: m.role as 'user' | 'assistant', content: m.content,
        reasoning: (m as any).reasoning,
        citations: m.citations, attachments: m.attachments, artifacts: m.artifacts, feedback: m.feedback,
        usage: m.usage, model: m.model,
      })))
      // 回填模型选择器
      const c = convs.find((x) => x.id === id)
      if (c?.model_config_id) setModelId(c.model_config_id)
      setConvSummary(c?.summary || null)
    } catch (e) { message.error(errMsg(e)) }
  }

  const newConversation = () => { setMsgs([]); setConvId(undefined); setPendingAtts([]); setConvUsage(null); setDocKb(undefined) }

  // 切换模型：立即持久化到当前会话
  const changeModel = async (id: number) => {
    setModelId(id)
    if (convId) { try { await chatApi.setModel(convId, id); loadConvs() } catch { /* ignore */ } }
  }

  const delConversation = async (id: number) => {
    try { await chatApi.remove(id); loadConvs(); if (convId === id) newConversation() }
    catch (e) { message.error(errMsg(e)) }
  }

  const renameConversation = async (c: Conversation) => {
    const t = window.prompt('重命名会话', c.title)
    if (!t) return
    try { await chatApi.rename(c.id, t); loadConvs() } catch (e) { message.error(errMsg(e)) }
  }

  const exportConversation = (c: any, fmt: 'md' | 'pdf' | 'docx') => {
    const token = localStorage.getItem('access_token') || ''
    // 带 token 下载（原生 <a> 不带 Authorization 头，用 query 传）
    fetch(chatApi.exportUrl(c.id, fmt), { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => { if (!r.ok) throw new Error('导出失败'); return r.blob() })
      .then((blob) => {
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url; a.download = `${c.title || '对话记录'}.${fmt}`
        a.click(); URL.revokeObjectURL(url)
      })
      .catch((e) => message.error(errMsg(e)))
  }

  const shareConversation = async (c: any) => {
    try {
      const r = await chatApi.share(c.id)
      const full = `${window.location.origin}${r.url}`
      Modal.info({
        title: '分享链接（免登录，短期有效）',
        content: (
          <div>
            <Typography.Paragraph copyable={{ text: full }} style={{ wordBreak: 'break-all', fontSize: 12 }}>
              {full}
            </Typography.Paragraph>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              有效期 {Math.round(r.expires_in / 60)} 分钟，过期后需重新生成。
            </Typography.Text>
          </div>
        ),
      })
    } catch (e) { message.error(errMsg(e)) }
  }

  const doUpload = async (file: File) => {
    try {
      const kind = file.type.startsWith('image/') ? 'image'
        : file.type.startsWith('video/') || file.type.startsWith('audio/') ? 'video' : 'document'
      // 未选知识库 → 不入库（去掉原先静默入第一个库的回退）
      const att = await chatApi.uploadAttachment(file, { kind, kbId: kind === 'document' ? docKb : undefined })
      setPendingAtts((a) => [...a, att])
      if (kind === 'document') {
        message.success(att.doc_id ? '文档已上传，正在入库' : '文档已上传（未选知识库，未入库）')
      } else {
        message.success('已添加')
      }
    } catch (e) { message.error(errMsg(e)) }
    return false
  }

  const runStream = async (payload: any, handlers: StreamHandlers, url?: string) => {
    const ctrl = new AbortController()
    abortRef.current = ctrl
    setStreaming(true)
    try {
      await streamChat(payload, handlers, ctrl.signal, url)
    } catch (e: any) {
      if (e?.name !== 'AbortError') message.error(errMsg(e))
    } finally {
      setStreaming(false); abortRef.current = null
      void refreshUsage()
      const cid = convIdRef.current
      if (cid) void refreshLastAssistant(cid)
    }
  }

  // 确认 AI 写操作（HITL）：执行后续跑，续跑事件渲染到同一条助手消息
  const confirmAction = async (idx: number, actionId: number, decision: 'approve' | 'reject') => {
    setMsgs((arr) => {
      const c = [...arr]
      c[idx] = { ...c[idx], pendingResolved: true, streaming: decision === 'approve' }
      return c
    })
    try {
      const token = localStorage.getItem('access_token')
      const resp = await fetch('/api/v1/chat/tool-confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({ action_id: actionId, decision }),
      })
      if (!resp.body) throw new Error('无响应流')
      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buf = '', ev = ''
      // 把事件应用到第 idx 条消息
      const patch = (fn: (m: any) => any) => setMsgs((m) => {
        const c = [...m]; c[idx] = fn(c[idx]); return c
      })
      const onToolResult = (data: any) => patch((msg) => {
        const steps = [...(msg.steps || [])]
        // 优先按 id 匹配；否则回填最后一条还没有结果的 step（HITL 挂起那条）
        let i = steps.findIndex((s) => s.call.id === data.id && !s.result)
        if (i < 0) {
          for (let k = steps.length - 1; k >= 0; k--) { if (!steps[k].result) { i = k; break } }
        }
        if (i >= 0) steps[i] = { ...steps[i], result: data }
        else steps.push({ call: { id: data.id, name: data.name, arguments: '' }, result: data })
        return { ...msg, steps }
      })
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n'); buf = lines.pop() || ''
        for (const line of lines) {
          if (line.startsWith('event:')) ev = line.slice(6).trim()
          else if (line.startsWith('data:')) {
            const raw = line.slice(5).trim(); if (!raw) continue
            let data: any; try { data = JSON.parse(raw) } catch { continue }
            if (ev === 'tool_result') onToolResult(data)
            else if (ev === 'delta') patch((msg) => ({ ...msg, content: (msg.content || '') + (data.text || '') }))
            else if (ev === 'reasoning') patch((msg) => ({ ...msg, reasoning: (msg.reasoning || '') + (data.text || '') }))
            else if (ev === 'citations') patch((msg) => ({ ...msg, citations: data.citations || [] }))
            else if (ev === 'pending_action') patch((msg) => ({ ...msg, pending: data, pendingResolved: false, streaming: false }))
            else if (ev === 'done') patch((msg) => ({ ...msg, id: data.message_id, streaming: false, pending: undefined }))
            else if (ev === 'error') message.error(data.message)
          }
        }
      }
      patch((msg) => ({ ...msg, streaming: false }))
      if (decision === 'approve') message.success('已执行')
      const cid = convIdRef.current
      if (cid) void refreshLastAssistant(cid)
    } catch (e) {
      patch((msg) => ({ ...msg, streaming: false }))
      message.error(errMsg(e))
    }
  }

  const send = async () => {
    const text = input.trim()
    if (!text && pendingAtts.length === 0) return
    setInput('')
    const atts = pendingAtts
    setPendingAtts([])
    setMsgs((m) => [...m, { role: 'user', content: text, attachments: atts },
      { role: 'assistant', content: '', streaming: true }])
    await runStream(
      {
        conversation_id: convId,
        kb_ids: retrievalMode === 'custom' ? selectedKbs : [],
        use_retrieval: retrievalMode !== 'off',
        message: text || '（见附件）',
        model_config_id: modelId,
        temperature,
        attachments: atts,
        use_tools: aiTools,
        allow_auto_write: autoWrite,
      },
      {
        onMeta: (d) => { if (!convId) { setConvId(d.conversation_id) } },
        onDelta: (t) => setMsgs((m) => {
          const c = [...m]; const last = c.length - 1
          c[last] = { ...c[last], content: c[last].content + t }; return c
        }),
        onReasoning: (t) => setMsgs((m) => {
          const c = [...m]; const last = c.length - 1
          c[last] = { ...c[last], reasoning: (c[last].reasoning || '') + t }; return c
        }),
        onToolCall: (evt: any) => setMsgs((m) => {
          const c = [...m]; const last = c.length - 1
          c[last] = { ...c[last], steps: [...(c[last].steps || []), { call: evt }] }; return c
        }),
        onToolResult: (evt: any) => setMsgs((m) => {
          const c = [...m]; const last = c.length - 1
          const steps = [...(c[last].steps || [])]
          const i = steps.findIndex((s) => s.call.id === evt.id && !s.result)
          if (i >= 0) steps[i] = { ...steps[i], result: evt }
          else steps.push({ call: { id: evt.id, name: evt.name, arguments: '' }, result: evt })
          c[last] = { ...c[last], steps }; return c
        }),
        onPendingAction: (evt: any) => setMsgs((m) => {
          const c = [...m]; const last = c.length - 1
          c[last] = { ...c[last], pending: evt, streaming: false }; return c
        }),
        onCitations: (cit) => setMsgs((m) => {
          const c = [...m]; const last = c.length - 1
          c[last] = { ...c[last], citations: cit }; return c
        }),
        onCitationCheck: (evt) => { if (evt.has_fake_cite) message.warning(evt.warning) },
        onUsage: (u) => setMsgs((m) => {
          const c = [...m]; const last = c.length - 1
          c[last] = { ...c[last], usage: u }; return c
        }),
        onDone: (mid) => setMsgs((m) => {
          const c = [...m]; const last = c.length - 1
          c[last] = { ...c[last], id: mid, streaming: false }; return c
        }),
        onError: (msg) => message.error(msg),
      },
    )
    loadConvs()
  }

  const stop = () => { abortRef.current?.abort(); setStreaming(false) }

  const regenerate = async () => {
    if (!convId) return
    // 本地删掉最后一条 assistant，再请求重生成
    setMsgs((m) => {
      const c = [...m]
      if (c.length && c[c.length - 1].role === 'assistant') c.pop()
      c.push({ role: 'assistant', content: '', streaming: true })
      return c
    })
    await runStream(
      {}, // 后端从会话取最后一条 user
      {
        onDelta: (t) => setMsgs((m) => {
          const c = [...m]; const last = c.length - 1
          c[last] = { ...c[last], content: c[last].content + t }; return c
        }),
        onReasoning: (t) => setMsgs((m) => {
          const c = [...m]; const last = c.length - 1
          c[last] = { ...c[last], reasoning: (c[last].reasoning || '') + t }; return c
        }),
        onCitations: (cit) => setMsgs((m) => {
          const c = [...m]; const last = c.length - 1
          c[last] = { ...c[last], citations: cit }; return c
        }),
        onCitationCheck: (evt) => { if (evt.has_fake_cite) message.warning(evt.warning) },
        onUsage: (u) => setMsgs((m) => {
          const c = [...m]; const last = c.length - 1
          c[last] = { ...c[last], usage: u }; return c
        }),
        onDone: (mid) => setMsgs((m) => {
          const c = [...m]; const last = c.length - 1
          c[last] = { ...c[last], id: mid, streaming: false }; return c
        }),
        onError: (msg) => message.error(msg),
      },
      chatApi.regenerateUrl(convId),
    )
  }

  const copy = (text: string) => { navigator.clipboard?.writeText(text); message.success('已复制') }

  // 流结束后从后端刷新最后一条助手消息（补全 artifacts）
  const refreshLastAssistant = async (cid: number) => {
    try {
      const ms = await chatApi.messages(cid)
      const last = [...ms].reverse().find((x) => x.role === 'assistant')
      if (!last) return
      setMsgs((arr) => {
        const c = [...arr]
        for (let k = c.length - 1; k >= 0; k--) {
          if (c[k].role === 'assistant') {
            c[k] = { ...c[k], artifacts: last.artifacts, usage: last.usage || c[k].usage, model: last.model || c[k].model }
            break
          }
        }
        return c
      })
    } catch { /* ignore */ }
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

  const openCitation = async (c: Citation) => {
    try {
      const r = await docApi.content(c.doc_id)
      setDocPreview({ title: r.title, content: r.content })
    } catch (e) { message.error(errMsg(e)) }
  }

  const downloadAttachment = async (docId: number, idx: number) => {
    try {
      const token = localStorage.getItem('access_token')
      const resp = await fetch(docApi.entryAttachmentUrl(docId, idx),
        { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      if (!resp.ok) throw new Error('下载失败')
      const blob = await resp.blob()
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `attachment_${idx}`
      a.click()
      URL.revokeObjectURL(a.href)
    } catch (e) { message.error(errMsg(e)) }
  }

  return (
    <div style={{ display: 'flex', gap: 12, height: 'calc(100vh - 112px)' }}>
      {/* 历史会话侧栏 */}
      <div style={{ width: 220, flex: '0 0 auto', display: 'flex', flexDirection: 'column' }}>
        {canReadAll && (
          <Select
            size="small" style={{ width: '100%', marginBottom: 8 }} placeholder="查看用户" allowClear
            value={viewUser} onChange={setViewUser}
            options={viewUsers.map((u: any) => {
              const label = u.channel_label
                ? `[${u.channel_label}] ${u.external_id || u.name}（${u.conversation_count}）`
                : `${u.name}（${u.conversation_count}）`
              return { value: u.user_id, label }
            })}
          />
        )}
        {!viewUser && (
          <Button type="primary" icon={<PlusOutlined />} block onClick={newConversation} style={{ marginBottom: 8 }}>新对话</Button>
        )}
        {viewUser && <Tag color="orange" style={{ marginBottom: 8 }}>只读：查看他人会话</Tag>}
        <div style={{ flex: 1, overflowY: 'auto', border: '1px solid #f0f0f0', borderRadius: 6 }}>
          <List
            size="small" dataSource={convs} locale={{ emptyText: '暂无历史' }}
            renderItem={(c: any) => (
              <List.Item
                style={{ cursor: 'pointer', background: c.id === convId ? '#e6f4ff' : undefined, padding: '6px 10px' }}
                onClick={() => openConversation(c.id)}
                actions={viewUser ? [] : [
                  <Dropdown key="more" trigger={['click']} menu={{
                    items: [
                      { key: 'md', label: '导出 Markdown' },
                      { key: 'pdf', label: '导出 PDF' },
                      { key: 'docx', label: '导出 Word' },
                      { type: 'divider' },
                      { key: 'share', label: '生成分享链接' },
                    ],
                    onClick: ({ key, domEvent }) => {
                      domEvent.stopPropagation()
                      if (key === 'share') shareConversation(c)
                      else exportConversation(c, key as 'md' | 'pdf' | 'docx')
                    },
                  }}>
                    <MoreOutlined onClick={(e) => e.stopPropagation()} />
                  </Dropdown>,
                  <EditOutlined key="r" onClick={(e) => { e.stopPropagation(); renameConversation(c) }} />,
                  <DeleteOutlined key="d" onClick={(e) => { e.stopPropagation(); delConversation(c.id) }} />,
                ]}
              >
                <Typography.Text ellipsis style={{ fontSize: 13 }}>
                  {c.title || '未命名'}{viewUser && c.owner_name ? ` · ${c.owner_name}` : ''}
                </Typography.Text>
              </List.Item>
            )}
          />
        </div>
      </div>

      {/* 主对话区 */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <Space style={{ marginBottom: 8 }} wrap>
          <span>模型：</span>
          <Select style={{ width: 200 }} value={modelId} onChange={changeModel}
            options={models.map((m) => ({ value: m.id, label: m.display_name || m.model_name }))} />
          <span>检索范围：</span>
          <Select value={retrievalMode} style={{ width: 200 }} onChange={(v) => setRetrievalMode(v)}
            options={[
              { value: 'auto', label: '自动（全部有权库）' },
              { value: 'custom', label: '指定知识库' },
              { value: 'off', label: '不检索（纯聊天）' },
            ]} />
          {retrievalMode === 'custom' && (
            <Select mode="multiple" style={{ minWidth: 240 }} placeholder="选择知识库"
              value={selectedKbs} onChange={setSelectedKbs}
              options={kbs.map((k) => ({ value: k.id, label: k.name }))} />
          )}
          <Tooltip title="允许 AI 调用平台工具（查用量/建库/传文档等，按你的权限）">
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <Switch size="small" checked={aiTools} onChange={setAiTools} />AI 操作
            </span>
          </Tooltip>
          {aiTools && (
            <Tooltip title="开启后写操作（建库/删除等）免确认直接执行；关闭则需逐条确认">
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                <Switch size="small" checked={autoWrite} onChange={setAutoWrite} />免确认
              </span>
            </Tooltip>
          )}
          <Tooltip title="参数设置"><Button icon={<SettingOutlined />} onClick={() => setShowParams((s) => !s)} /></Tooltip>
          {msgs.length >= 4 && <Tooltip title="对话目录"><Button icon={<UnorderedListOutlined />} onClick={() => setOutlineOpen(true)}>目录</Button></Tooltip>}
          {!viewUser && <Button icon={<ClearOutlined />} onClick={newConversation}>清空</Button>}
        </Space>

        {showParams && (
          <Card size="small" style={{ marginBottom: 8 }}>
            <Space>
              <span>温度：{temperature}</span>
              <Slider style={{ width: 160 }} min={0} max={1} step={0.1} value={temperature} onChange={setTemperature} />
            </Space>
          </Card>
        )}

        <div style={{ position: 'relative', flex: 1, minHeight: 0, display: 'flex' }}>
          <div ref={listRef} onScroll={onScroll} style={{ flex: 1, minWidth: 0, height: '100%', overflowY: 'auto', paddingRight: 8 }}>
            {msgs.length === 0 ? (
            <Empty style={{ marginTop: 80 }} description="直接提问即可：会自动检索知识库辅助回答，也可切换到「不检索（纯聊天）」" />
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
                <Card size="small" style={{ maxWidth: '80%', background: m.role === 'user' ? '#e6f4ff' : '#fff' }}>
                  {m.role === 'assistant' && <ReasoningBlock reasoning={m.reasoning} streaming={m.streaming} />}
                  {m.role === 'assistant' && (m.steps || []).length > 0 && (
                    <Collapse
                      size="small" style={{ marginBottom: 8 }}
                      items={(m.steps || []).map((s: any, si: number) => ({
                        key: si,
                        label: <Space><ToolOutlined /><span>调用 {s.call.name}</span>{s.result ? (s.result.is_error ? <Tag color="red">失败</Tag> : <Tag color="green">完成</Tag>) : <Tag>执行中</Tag>}</Space>,
                        children: (
                          <div style={{ fontSize: 12 }}>
                            <div><b>参数：</b><pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{s.call.arguments}</pre></div>
                            {s.result && <div style={{ marginTop: 6 }}><b>结果：</b><pre style={{ margin: 0, whiteSpace: 'pre-wrap', maxHeight: 200, overflow: 'auto' }}>{s.result.content}</pre></div>}
                          </div>
                        ),
                      }))}
                    />
                  )}
                  {m.role === 'assistant'
                    ? (m.streaming
                        ? <div className="md-body streaming-plain">{m.content || '…'}</div>
                        : <MarkdownBody content={m.content} />)
                    : <div className="md-body">{m.content}</div>}
                  {(m.attachments || []).map((a) => (
                    <AttachmentView key={a.file_key} att={a} />
                  ))}
                  {(m.artifacts || []).length > 0 && (
                    <div style={{ marginTop: 8, paddingTop: 6, borderTop: '1px solid #f0f0f0' }}>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>生成的文件：</Typography.Text>
                      <div style={{ marginTop: 4 }}>
                        {m.artifacts!.map((a) => (
                          <AttachmentView key={a.artifact_id} artifact
                            att={{ artifact_id: a.artifact_id, name: a.name, mime: a.mime, size: a.size }} />
                        ))}
                      </div>
                    </div>
                  )}
                  {m.pending && (
                    <div style={{ marginTop: 10 }}>
                      <PendingActionCard
                        action={m.pending as any}
                        resolved={m.pendingResolved}
                        onConfirm={(aid, decision) => confirmAction(i, aid, decision)}
                      />
                    </div>
                  )}
                  {m.citations && m.citations.length > 0 && (
                    <div style={{ marginTop: 10, borderTop: '1px solid #f0f0f0', paddingTop: 8 }}>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>引用来源（点击查看）：</Typography.Text>
                      <div style={{ marginTop: 4 }}>
                        {m.citations.map((c, ci) => (
                          <Tag key={ci} color={c.source_uri ? 'purple' : 'blue'} style={{ marginBottom: 4, cursor: 'pointer' }}
                            onClick={() => { if (c.source_uri) window.open(c.source_uri, '_blank'); else openCitation(c) }}>
                            [{ci + 1}] {c.doc_title || '文档'}{c.page ? ` · 第${c.page}页` : ''}{c.source_uri ? ' ↗' : ''}
                          </Tag>
                        ))}
                      </div>
                      {m.citations.some((c) => c.attachments?.length) && (
                        <div style={{ marginTop: 6 }}>
                          <Typography.Text type="secondary" style={{ fontSize: 12 }}>相关附件：</Typography.Text>
                          <div style={{ marginTop: 4 }}>
                            {m.citations.filter((c) => c.attachments?.length).map((c, ci) =>
                              c.attachments!.map((a, ai) => (
                                <Tag key={`${ci}-${ai}`} icon={<PaperClipOutlined />} color="geekblue" style={{ marginBottom: 4, cursor: 'pointer' }}
                                  onClick={() => downloadAttachment(c.doc_id, ai)}>
                                  {a.name}
                                </Tag>
                              )))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                  {m.role === 'assistant' && !m.streaming && m.content && (
                    <div style={{ marginTop: 8, borderTop: '1px solid #f0f0f0', paddingTop: 6 }}>
                      <Space size={4} wrap>
                        <Tooltip title="复制"><Button type="text" size="small" icon={<CopyOutlined />} onClick={() => copy(m.content)} /></Tooltip>
                        <Tooltip title="重新生成"><Button type="text" size="small" icon={<ReloadOutlined />} onClick={regenerate} /></Tooltip>
                        <Tooltip title="有帮助"><Button type="text" size="small" icon={<LikeOutlined />}
                          style={{ color: m.feedback === 1 ? '#52c41a' : undefined }} onClick={() => doFeedback(i, 1)} /></Tooltip>
                        <Tooltip title="没帮助"><Button type="text" size="small" icon={<DislikeOutlined />}
                          style={{ color: m.feedback === -1 ? '#f5222d' : undefined }} onClick={() => doFeedback(i, -1)} /></Tooltip>
                        {m.usage && (
                          <Tooltip title={m.model ? `模型：${m.model}` : ''}>
                            <Typography.Text type="secondary" style={{ fontSize: 12, marginLeft: 4 }}>
                              ↑{m.usage.prompt_tokens ?? 0} ↓{m.usage.completion_tokens ?? 0} · {m.usage.total_tokens ?? 0} tokens
                              {(m.usage.cached_tokens ?? 0) > 0 ? ` · 缓存 ${m.usage.cached_tokens}` : ''}
                              {m.model ? ` · ${m.model}` : ''}
                            </Typography.Text>
                          </Tooltip>
                        )}
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

        {/* 用量统计条 */}
        <div style={{
          display: 'flex', gap: 18, alignItems: 'center', padding: '5px 10px', marginTop: 8,
          borderTop: '1px solid #f0f0f0', fontSize: 12, color: '#8c8c8c', background: '#fafafa', borderRadius: 6,
        }}>
          <span>本会话累计：<b style={{ color: '#595959' }}>{convUsage ? `${convUsage.total_tokens} tokens` : '-'}</b>
            {convUsage ? ` / ${convUsage.calls} 次` : ''}</span>
          <span>今日消耗：<b style={{ color: '#595959' }}>{todayUsage ? `${todayUsage.total_tokens} tokens` : '-'}</b>
            {todayUsage ? ` / ${todayUsage.calls} 次` : ''}</span>
          <span>命中缓存：<b style={{ color: '#595959' }}>{todayUsage?.cached_tokens ?? 0}</b></span>
          {convSummary && (
            <Tooltip title={convSummary}>
              <Tag color="blue" style={{ margin: 0, cursor: 'help' }}>已压缩历史</Tag>
            </Tooltip>
          )}
          {todayUsage && <span style={{ marginLeft: 'auto' }}>↑{todayUsage.prompt_tokens} ↓{todayUsage.completion_tokens}</span>}
        </div>

        {/* 附件预览 */}
        {pendingAtts.length > 0 && (
          <Space wrap style={{ marginTop: 8 }}>
            {pendingAtts.map((a, i) => (
              <Tag key={a.file_key} closable onClose={() => setPendingAtts((x) => x.filter((_, j) => j !== i))}
                icon={a.type === 'image' ? undefined : <PaperClipOutlined />}>
                {a.name}
                {a.doc_id ? <PendingAttachmentProgress docId={a.doc_id} /> : null}
              </Tag>
            ))}
          </Space>
        )}

        {viewUser ? (
          <div style={{ marginTop: 12, color: '#8c8c8c', fontSize: 13 }}>只读模式：正在查看他人会话</div>
        ) : (
          <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
            <Upload beforeUpload={doUpload} showUploadList={false} multiple
              accept=".pdf,.docx,.doc,.xlsx,.xls,.pptx,.csv,.txt,.md,image/*,video/*">
              <Tooltip title="上传图片/文档/视频"><Button icon={<PaperClipOutlined />} /></Tooltip>
            </Upload>
            {kbs.length > 0 && (
              <Select size="small" style={{ width: 150 }} placeholder="文档入库到（可空）" allowClear
                value={docKb} onChange={(v) => setDocKb(v)}
                options={kbs.map((k) => ({ value: k.id, label: k.name }))} />
            )}
            <Input.TextArea
              value={input} onChange={(e) => setInput(e.target.value)}
              placeholder="输入问题，Enter 发送，Shift+Enter 换行"
              autoSize={{ minRows: 1, maxRows: 4 }}
              onPressEnter={(e) => { if (!e.shiftKey) { e.preventDefault(); send() } }}
            />
            {streaming
              ? <Button danger icon={<StopOutlined />} onClick={stop}>停止</Button>
              : <Button type="primary" icon={<SendOutlined />} onClick={send}>发送</Button>}
          </div>
        )}
      </div>

      {/* 引用原文预览 */}
      <Drawer title={docPreview?.title || '文档预览'} width={640} open={!!docPreview} onClose={() => setDocPreview(null)}>
        <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>
          {docPreview?.content || '(无内容)'}
        </Typography.Paragraph>
      </Drawer>

      <MessageOutline
        open={outlineOpen}
        onClose={() => setOutlineOpen(false)}
        onJump={jumpToMessage}
        items={msgs.map((m, i) => ({ index: i, role: m.role, text: m.content }))}
      />
    </div>
  )
}
