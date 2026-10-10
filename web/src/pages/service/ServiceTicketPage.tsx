import { useEffect, useRef, useState } from 'react'
import {
  Alert, Avatar, Button, Card, Col, Collapse, Drawer, Empty, Form, Input, List, message, Modal, Popconfirm, Row,
  Segmented, Select, Space, Statistic, Switch, Table, Tabs, Tag, Tooltip, Typography, Upload,
} from 'antd'
import {
  SendOutlined, UserOutlined, PaperClipOutlined, WechatOutlined, QqOutlined,
  CloudServerOutlined, MessageOutlined, ClockCircleOutlined, BellOutlined, BellFilled,
  FileTextOutlined, ExclamationCircleOutlined, CustomerServiceOutlined, RobotOutlined, EditOutlined, DownloadOutlined,
} from '@ant-design/icons'
import { serviceTicketApi, chatApi, rbacApi, type ServiceTicketItem, type QuickReplyItem } from '../../api'
import { errMsg } from '../../api/http'
import PageContainer from '../../components/PageContainer'
import EmptyState from '../../components/EmptyState'
import AttachmentView from '../../components/AttachmentView'
import Can from '../../components/Can'
import { useAuth } from '../../stores/auth'

const STATUS: Record<string, { label: string; color: string }> = {
  open: { label: '待处理', color: 'red' },
  pending: { label: '处理中', color: 'orange' },
  resolved: { label: '已解决', color: 'green' },
  closed: { label: '已关闭', color: 'default' },
}
const PRIORITY: Record<string, { label: string; color: string }> = {
  low: { label: '低', color: 'default' },
  normal: { label: '普通', color: 'blue' },
  high: { label: '高', color: 'orange' },
  urgent: { label: '紧急', color: 'red' },
}
const CHANNEL_META: Record<string, { label: string; icon: any; color: string }> = {
  qqbot: { label: 'QQ', icon: <QqOutlined />, color: 'blue' },
  wxclaw: { label: '微信', icon: <WechatOutlined />, color: 'green' },
  wework: { label: '企业微信', icon: <WechatOutlined />, color: 'cyan' },
  feishu: { label: '飞书', icon: <CloudServerOutlined />, color: 'purple' },
}

function fmtTime(ms?: number | null) {
  return ms ? new Date(ms).toLocaleString('zh-CN') : '-'
}

function slaInfo(t: ServiceTicketItem) {
  if (!t.sla_due_at) return null
  // SLA 状态色：沿用 antd 语义色板（error/success/warning/次要），与 Tag 内置色一致
  if (t.sla_breached) return { text: '已超时', color: 'error' }
  if (['closed', 'resolved'].includes(t.status)) return null
  if (t.first_response_at) return { text: '已响应', color: 'success' }
  const left = t.sla_due_at - Date.now()
  if (left <= 0) return { text: '已超时', color: 'error' }
  const mins = Math.round(left / 60000)
  const txt = mins >= 60 ? `${Math.round(mins / 60)}h` : `${mins}min`
  return { text: `剩余 ${txt}`, color: mins <= 30 ? 'warning' : 'default' }
}

function ChannelTag({ kind }: { kind?: string | null }) {
  if (!kind) return <Tag>问答页</Tag>
  const m = CHANNEL_META[kind] || { label: kind, icon: <MessageOutlined />, color: 'default' }
  return <Tag color={m.color} icon={m.icon}>{m.label}</Tag>
}

function StatusDot({ status }: { status: string }) {
  const s = STATUS[status] || STATUS.open
  return <Tag color={s.color}>{s.label}</Tag>
}

export default function ServiceTicketPage() {
  const hasPermission = useAuth((s) => s.hasPermission)
  const canManage = hasPermission('service:manage')
  const [items, setItems] = useState<ServiceTicketItem[]>([])
  const [loading, setLoading] = useState(false)
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [current, setCurrent] = useState<ServiceTicketItem | null>(null)
  const [detailTab, setDetailTab] = useState<string>('dialog')
  const [reply, setReply] = useState('')
  const [sending, setSending] = useState(false)
  const [note, setNote] = useState('')
  const [ctx, setCtx] = useState<any>(null)
  const [channelConvs, setChannelConvs] = useState<any[]>([])
  const [convOpen, setConvOpen] = useState<any>(null)
  const [convNotes, setConvNotes] = useState<{ content: string; ts: number }[]>([])
  const [convNote, setConvNote] = useState('')
  const [convMsgs, setConvMsgs] = useState<any[]>([])
  const [convReply, setConvReply] = useState('')
  const [convSending, setConvSending] = useState(false)
  const [convWatch, setConvWatch] = useState(true)
  const [editingNoteId, setEditingNoteId] = useState<number | null>(null)  // 正在编辑备注的客户(ChannelUser.id)
  const [noteDraft, setNoteDraft] = useState('')
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [bulkBusy, setBulkBusy] = useState(false)
  const [quickReplies, setQuickReplies] = useState<QuickReplyItem[]>([])
  const [staff, setStaff] = useState<{ id: number; username: string; display_name?: string }[]>([])
  const [qrOpen, setQrOpen] = useState(false)
  const [qrTitle, setQrTitle] = useState('')
  const [qrContent, setQrContent] = useState('')
  const [qrEdit, setQrEdit] = useState<QuickReplyItem | null>(null)
  const [qrEditForm] = Form.useForm()
  const convRef = useRef<HTMLDivElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (qrEdit) qrEditForm.setFieldsValue({ title: qrEdit.title, content: qrEdit.content })
  }, [qrEdit])

  const saveQrEdit = async () => {
    if (!qrEdit) return
    const v = await qrEditForm.validateFields().catch(() => null)
    if (!v) return
    try {
      await serviceTicketApi.updateQuickReply(qrEdit.id, { title: v.title, content: v.content })
      setQuickReplies(await serviceTicketApi.quickReplies()); message.success('已保存'); setQrEdit(null)
    } catch (e) { message.error(errMsg(e)) }
  }

  const load = async () => {
    setLoading(true)
    try {
      const [tickets, convs] = await Promise.all([
        serviceTicketApi.list(statusFilter ? { status: statusFilter } : {}),
        serviceTicketApi.channelConversations().catch(() => []),
      ])
      setItems(tickets); setChannelConvs(convs)
    } catch (e) { message.error(errMsg(e)) } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [statusFilter])
  useEffect(() => { serviceTicketApi.quickReplies().then(setQuickReplies).catch(() => {}) }, [])
  useEffect(() => { rbacApi.users(1, 200).then((r) => setStaff(r.items)).catch(() => {}) }, [])

  const doBulk = async (action: string, value?: number | string | null) => {
    if (!selectedIds.length) return
    setBulkBusy(true)
    try {
      const r = await serviceTicketApi.bulk(selectedIds, action, value)
      message.success(`已处理 ${r.updated} 条工单`)
      setSelectedIds([]); load()
    } catch (e) { message.error(errMsg(e)) } finally { setBulkBusy(false) }
  }
  const doAssign = async (assigneeId: number | null) => {
    if (!current) return
    try {
      setCurrent(await serviceTicketApi.assign(current.id, assigneeId))
      message.success(assigneeId ? '已转派' : '已取消指派'); load()
    } catch (e) { message.error(errMsg(e)) }
  }
  const doResolve = async () => {
    if (!current) return
    try { setCurrent(await serviceTicketApi.resolve(current.id)); message.success('已标记为解决'); load() }
    catch (e) { message.error(errMsg(e)) }
  }

  const openTicket = async (t: ServiceTicketItem) => {
    try {
      setCurrent(await serviceTicketApi.get(t.id)); setReply(''); setNote(''); setCtx(null); setDetailTab('dialog')
      serviceTicketApi.context(t.id).then(setCtx).catch(() => {})
    }
    catch (e) { message.error(errMsg(e)) }
  }

  const send = async () => {
    if (!current || !reply.trim()) return
    setSending(true)
    try {
      const t = await serviceTicketApi.reply(current.id, reply.trim())
      setCurrent(t); setReply(''); load()
      message.success('已回复并回发到渠道')
    } catch (e) { message.error(errMsg(e)) } finally { setSending(false) }
  }

  const addNote = async () => {
    if (!current || !note.trim()) return
    try {
      const t = await serviceTicketApi.addNote(current.id, note.trim())
      setCurrent(t); setNote(''); message.success('已添加内部备注（客户不可见）')
    } catch (e) { message.error(errMsg(e)) }
  }

  const setStatus = async (status: string) => {
    if (!current) return
    try { setCurrent(await serviceTicketApi.update(current.id, { status })); load() }
    catch (e) { message.error(errMsg(e)) }
  }

  const toggleWatch = async (watch: boolean) => {
    if (!current) return
    try {
      const t = await serviceTicketApi.update(current.id, { watch })
      setCurrent(t); setItems((arr) => arr.map((x) => x.id === t.id ? { ...x, watch } : x))
      message.success(watch ? '已开启：该工单有新回复时通知你' : '已关闭提醒')
    } catch (e) { message.error(errMsg(e)) }
  }

  const openConversation = async (c: any) => {
    setConvOpen(c); setConvMsgs([]); setConvReply(''); setConvNotes([]); setConvNote('')
    serviceTicketApi.conversationMeta(c.id).then((m) => {
      setConvWatch(m.watch !== false)
      setConvNotes(m.notes || [])
    }).catch(() => {})
    try {
      const msgs = await serviceTicketApi.conversationMessages(c.id)
      const keys = msgs.flatMap((m) => (m.attachments || []).map((a: any) => a.file_key)).filter(Boolean)
      if (keys.length) {
        try {
          const { urls } = await chatApi.signAttachmentsBatch(keys)
          msgs.forEach((m) => (m.attachments || []).forEach((a: any) => { if (urls[a.file_key]) a.url = urls[a.file_key] }))
        } catch { /* 忽略签名失败 */ }
      }
      setConvMsgs(msgs)
      setTimeout(() => convRef.current?.scrollTo({ top: convRef.current.scrollHeight }), 50)
    } catch (e) { message.error(errMsg(e)) }
  }

  const sendConvReply = async () => {
    if (!convOpen || !convReply.trim()) return
    setConvSending(true)
    try {
      const r = await serviceTicketApi.replyInConversation(convOpen.id, convReply.trim())
      setConvReply('')
      await openConversation(convOpen)
      message.success(r.sent_to_channel ? '已回复并回发到客户渠道' : '已回复（渠道未连接，未回发）')
    } catch (e) { message.error(errMsg(e)) } finally { setConvSending(false) }
  }

  const sendConvAttachment = async (file: File) => {
    if (!convOpen) return false
    try {
      const r = await serviceTicketApi.sendConversationAttachment(convOpen.id, file)
      await openConversation(convOpen)
      message.success(r.sent_to_channel ? '附件已发送并回发客户' : '附件已发送（渠道暂不支持媒体，客户可在会话中查看）')
    } catch (e) { message.error(errMsg(e)) }
    return false
  }

  const toggleConvWatch = async (watch: boolean) => {
    if (!convOpen) return
    try {
      await serviceTicketApi.setConversationWatch(convOpen.id, watch)
      setConvWatch(watch)
      message.success(watch ? '已开启：该会话有新消息时通知你' : '已关闭提醒')
    } catch (e) { message.error(errMsg(e)) }
  }

  const addConvNote = async () => {
    if (!convOpen || !convNote.trim()) return
    try {
      const r = await serviceTicketApi.addConversationNote(convOpen.id, convNote.trim())
      setConvNotes(r.notes || [])
      setConvNote('')
      message.success('已添加会话备注（仅客服可见）')
    } catch (e) { message.error(errMsg(e)) }
  }

  const saveCustomerNote = async (channelUserId: number) => {
    try {
      const r = await serviceTicketApi.setCustomerNote(channelUserId, noteDraft.trim())
      setChannelConvs((arr) => arr.map((c) => c.channel_user_id === channelUserId ? { ...c, note: r.note } : c))
      setEditingNoteId(null); setNoteDraft('')
      message.success('备注已保存')
    } catch (e) { message.error(errMsg(e)) }
  }

  const stats = {
    open: items.filter((t) => t.status === 'open').length,
    pending: items.filter((t) => t.status === 'pending').length,
    breached: items.filter((t) => t.sla_breached).length,
  }

  const bubble = (m: any, i: number) => {
    const isUser = m.role === 'user'          // 客户 → 左
    const isMine = !isUser                     // 客服 / AI → 右
    const isAgent = m.role === 'agent'
    const who = isUser ? '客户' : isAgent ? '客服' : 'AI'
    const avatar = (
      <Avatar size={32} style={{ flexShrink: 0, marginLeft: isMine ? 8 : 0, marginRight: isMine ? 0 : 8,
        background: isUser ? '#8c8c8c' : isAgent ? '#1677ff' : '#13c2c2' }}
        icon={isUser ? <UserOutlined /> : isAgent ? <CustomerServiceOutlined /> : <RobotOutlined />} />
    )
    return (
      <div key={i} style={{ marginBottom: 16, display: 'flex', justifyContent: isMine ? 'flex-end' : 'flex-start', alignItems: 'flex-start' }}>
        {!isMine && avatar}
        <div style={{ maxWidth: '74%' }}>
          <div style={{ fontSize: 11, color: '#9aa4b2', marginBottom: 3, textAlign: isMine ? 'right' : 'left' }}>
            {who} · {fmtTime(m.ts || m.created_at)}
          </div>
          <div style={{
            background: isUser ? '#fff' : isAgent ? '#e6f4ff' : '#e6fffb',
            border: `1px solid ${isUser ? '#eef0f3' : isAgent ? '#bae0ff' : '#b5f5ec'}`,
            borderRadius: 12, padding: '9px 13px', boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
          }}>
            {m.content && <div style={{ whiteSpace: 'pre-wrap', fontSize: 13, lineHeight: 1.6 }}>{m.content}</div>}
            {(m.attachments || []).map((a: any, k: number) => <AttachmentView key={a.file_key || k} att={a} />)}
          </div>
        </div>
        {isMine && avatar}
      </div>
    )
  }

  const statCard = (title: string, value: number, color: string, icon: any) => (
    <Card size="small" bordered={false} style={{ boxShadow: '0 1px 4px rgba(0,0,0,0.06)', borderRadius: 10 }}>
      <Statistic title={title} value={value} valueStyle={{ color }} prefix={icon} />
    </Card>
  )

  return (
    <PageContainer
      title="客服工单"
      subtitle="渠道客户请求「转人工」自动建单；客服回复直接发回客户渠道（QQ/微信/企微/飞书）"
      extra={
        <Space>
          <Select allowClear placeholder="按状态筛选" style={{ width: 140 }} value={statusFilter}
            onChange={setStatusFilter}
            options={Object.entries(STATUS).map(([v, m]) => ({ value: v, label: m.label }))} />
          <Can perm="service:manage"><Button onClick={() => setQrOpen(true)}>话术库</Button></Can>
          <Button icon={<DownloadOutlined />} onClick={() => {
            const token = localStorage.getItem('access_token') || ''
            fetch(serviceTicketApi.exportUrl(statusFilter || undefined), { headers: { Authorization: `Bearer ${token}` } })
              .then((r) => { if (!r.ok) throw new Error('导出失败'); return r.blob() })
              .then((b) => {
                const a = document.createElement('a')
                a.href = URL.createObjectURL(b); a.download = `工单导出_${Date.now()}.csv`
                a.click(); URL.revokeObjectURL(a.href)
              }).catch((e) => message.error(errMsg(e)))
          }}>导出 CSV</Button>
          <Button onClick={load}>刷新</Button>
        </Space>
      }
    >
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6}>{statCard('待处理', stats.open, '#ff4d4f', <ExclamationCircleOutlined />)}</Col>
        <Col xs={12} sm={6}>{statCard('处理中', stats.pending, '#fa8c16', <ClockCircleOutlined />)}</Col>
        <Col xs={12} sm={6}>{statCard('已超时', stats.breached, '#cf1322', <BellFilled />)}</Col>
        <Col xs={12} sm={6}>{statCard('全部', items.length, '#1677ff', <FileTextOutlined />)}</Col>
      </Row>

      <Card bordered={false} styles={{ body: { paddingTop: 8 } }}>
        {selectedIds.length > 0 && (
          <Alert type="info" style={{ marginBottom: 12 }} showIcon
            message={
              <Space wrap>
                <span>已选 {selectedIds.length} 条：</span>
                <Button size="small" loading={bulkBusy} onClick={() => doBulk('resolve')}>批量解决</Button>
                <Button size="small" danger loading={bulkBusy} onClick={() => doBulk('close')}>批量关闭</Button>
                <Select size="small" placeholder="批量改优先级" style={{ width: 130 }} value={undefined}
                  onChange={(v) => doBulk('priority', v)}
                  options={Object.entries(PRIORITY).map(([v, m]) => ({ value: v, label: m.label }))} />
                <Button size="small" onClick={() => setSelectedIds([])}>取消选择</Button>
              </Space>
            } />
        )}
        <Tabs items={[
          {
            key: 'tickets', label: `工单（${items.length}）`,
            children: (
              <Table
                rowKey="id" dataSource={items} loading={loading} pagination={{ pageSize: 15, hideOnSinglePage: true }}
                scroll={{ x: 'max-content' }}
                rowSelection={{
                  selectedRowKeys: selectedIds,
                  onChange: (keys) => setSelectedIds(keys as number[]),
                }}
                onRow={(r) => ({ onClick: () => openTicket(r), style: { cursor: 'pointer' } })}
                locale={{ emptyText: <EmptyState description="暂无工单" /> }}
                columns={[
                  { title: '工单', dataIndex: 'id', width: 72,
                    render: (v) => <Typography.Text strong style={{ color: '#1677ff' }}>#{v}</Typography.Text> },
                  { title: '标题', dataIndex: 'subject', ellipsis: true,
                    render: (v, r) => (
                      <Space size={4}>
                        {r.watch === false ? <BellOutlined style={{ color: '#bfbfbf' }} /> : <BellFilled style={{ color: '#1677ff' }} />}
                        <span>{v}</span>
                      </Space>
                    ) },
                  { title: '状态', dataIndex: 'status', width: 96, render: (v) => <StatusDot status={v} /> },
                  { title: '优先级', dataIndex: 'priority', width: 84,
                    render: (v: string) => <Tag color={PRIORITY[v]?.color}>{PRIORITY[v]?.label || v}</Tag> },
                  { title: '渠道', width: 100, render: (_: any, r) => <ChannelTag kind={r.channel_kind} /> },
                  { title: '用户', dataIndex: 'external_user', width: 130, ellipsis: true, render: (v) => v || '-' },
                  { title: 'SLA', width: 96,
                    render: (_: any, r) => {
                      const s = slaInfo(r)
                      return s ? <Tag color={s.color} style={{ fontSize: 12 }}>{s.text}</Tag>
                        : <span style={{ color: 'var(--color-text-3)' }}>-</span>
                    } },
                  { title: '最后消息', dataIndex: 'last_message_at', width: 156,
                    render: (v) => <span style={{ fontSize: 12, color: '#8c8c8c' }}>{fmtTime(v)}</span> },
                ]}
              />
            ),
          },
          {
            key: 'convs', label: `渠道会话（${channelConvs.length}）`,
            children: (
              <Table
                rowKey="id" dataSource={channelConvs} pagination={{ pageSize: 15, hideOnSinglePage: true }} size="small"
                onRow={(r) => ({ onClick: () => openConversation(r), style: { cursor: 'pointer' } })}
                locale={{ emptyText: <EmptyState description="暂无渠道会话" /> }}
                columns={[
                  { title: '会话', dataIndex: 'id', width: 80, render: (v) => `#${v}` },
                  { title: '标题', dataIndex: 'title', ellipsis: true },
                  { title: '渠道', dataIndex: 'channel', width: 110, render: (v: string) => <ChannelTag kind={v} /> },
                  { title: '外部用户', dataIndex: 'external_id', ellipsis: true, render: (v) => v || '-' },
                  {
                    title: '备注', width: 240,
                    render: (_: any, r) => {
                      if (editingNoteId === r.channel_user_id) {
                        return (
                          <Space.Compact style={{ width: '100%' }} onClick={(e) => e.stopPropagation()}>
                            <Input size="small" autoFocus value={noteDraft} onChange={(e) => setNoteDraft(e.target.value)}
                              placeholder="备注该客户" onPressEnter={() => saveCustomerNote(r.channel_user_id)} />
                            <Button size="small" type="primary" onClick={() => saveCustomerNote(r.channel_user_id)}>存</Button>
                            <Button size="small" onClick={() => { setEditingNoteId(null); setNoteDraft('') }}>取消</Button>
                          </Space.Compact>
                        )
                      }
                      return (
                        <Space size={4}>
                          {r.note
                            ? <Tooltip title={r.note}><Typography.Text style={{ fontSize: 12 }} ellipsis>{r.note}</Typography.Text></Tooltip>
                            : <Typography.Text type="secondary" style={{ fontSize: 12 }}>-</Typography.Text>}
                          <Can perm="service:manage">
                            <Button size="small" type="link" icon={<EditOutlined />}
                              onClick={(e) => { e.stopPropagation(); setEditingNoteId(r.channel_user_id); setNoteDraft(r.note || '') }} />
                          </Can>
                        </Space>
                      )
                    },
                  },
                  { title: '最后消息', dataIndex: 'last_message', ellipsis: true, render: (v) => v || '-' },
                  { title: '消息数', dataIndex: 'message_count', width: 80 },
                  { title: '操作', width: 90,
                    render: (_: any, r) => <Button size="small" onClick={(e) => { e.stopPropagation(); openConversation(r) }}>查看</Button> },
                ]}
              />
            ),
          },
        ]} />
      </Card>

      {/* 工单详情 */}
      <Drawer width={820} open={!!current} onClose={() => setCurrent(null)}
        title={null} styles={{ header: { display: 'none' }, body: { padding: 0 } }}>
        {current && (
          <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
            <div style={{ padding: '16px 20px', background: 'linear-gradient(135deg,#f0f5ff,#fafafa)', borderBottom: '1px solid #f0f0f0' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <Space align="center" style={{ marginBottom: 6 }} wrap>
                    <Typography.Title level={4} style={{ margin: 0 }}>#{current.id} {current.subject}</Typography.Title>
                    <StatusDot status={current.status} />
                    <Tag color={PRIORITY[current.priority]?.color}>{PRIORITY[current.priority]?.label || current.priority}</Tag>
                  </Space>
                  <Space size={12} wrap style={{ fontSize: 12, color: '#666' }}>
                    <ChannelTag kind={current.channel_kind} />
                    <span><UserOutlined /> {current.external_user || '-'}</span>
                    {current.customer_lang && <Tag>{current.customer_lang}</Tag>}
                    {(() => { const s = slaInfo(current); return s ? <span style={{ color: s.color }}><ClockCircleOutlined /> {s.text}</span> : null })()}
                  </Space>
                </div>
                <Can perm="service:manage">
                  <Space direction="vertical" size={6} style={{ alignItems: 'flex-end' }}>
                    <Select size="small" style={{ width: 130 }} value={current.status}
                      onChange={setStatus} options={Object.entries(STATUS).map(([v, m]) => ({ value: v, label: m.label }))} />
                    <Space size={6}>
                      <Button size="small" onClick={doResolve} disabled={current.status === 'resolved' || current.status === 'closed'}>标记解决</Button>
                      <Select size="small" style={{ width: 110 }} placeholder="转派给…" value={undefined}
                        onChange={(v) => doAssign(v)} allowClear
                        options={staff.map((u) => ({ value: u.id, label: u.display_name || u.username }))} />
                    </Space>
                    <Tooltip title={current.watch === false ? '已关闭：有新回复不通知' : '开启中：有新回复会通知你'}>
                      <Space size={6} style={{ fontSize: 12, color: '#595959' }}>
                        {current.watch === false ? <BellOutlined style={{ color: '#bfbfbf' }} /> : <BellFilled style={{ color: '#1677ff' }} />}
                        <span>有新回复通知我</span>
                        <Switch size="small" checked={current.watch !== false} onChange={toggleWatch} />
                      </Space>
                    </Tooltip>
                  </Space>
                </Can>
              </div>
            </div>

            {ctx && (ctx.ticket_total > 1 || ctx.recent_messages?.length) && (
              <div style={{ padding: '0 20px' }}>
                <Collapse size="small" ghost items={[{
                  key: 'ctx',
                  label: <span style={{ fontSize: 12 }}><UserOutlined /> 客户上下文（历史工单 {ctx.ticket_total}，进行中 {ctx.ticket_open}）</span>,
                  children: (
                    <div style={{ fontSize: 12 }}>
                      {ctx.history?.slice(0, 6).map((h: any) => (
                        <div key={h.id} style={{ color: '#666' }}>#{h.id} [{STATUS[h.status]?.label || h.status}] {h.subject}</div>
                      ))}
                    </div>
                  ),
                }]} />
              </div>
            )}

            <div style={{ padding: '8px 20px 0' }}>
              <Segmented value={detailTab} onChange={(v) => setDetailTab(v as string)} block
                options={[
                  { label: '对话', value: 'dialog' },
                  { label: `内部备注${(current.internal_notes || []).length ? `（${current.internal_notes!.length}）` : ''}`, value: 'notes' },
                ]} />
            </div>

            {detailTab === 'dialog' ? (
              <div ref={listRef} style={{ flex: 1, overflowY: 'auto', padding: 20, minHeight: 0 }}>
                {(current.messages || []).length === 0
                  ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无消息" />
                  : (current.messages || []).map((m, i) => bubble(m, i))}
              </div>
            ) : (
              <div style={{ flex: 1, overflowY: 'auto', padding: 20, minHeight: 0 }}>
                <Alert type="warning" showIcon style={{ marginBottom: 12 }} message="内部备注仅客服可见，不会发送给客户。" />
                {(current.internal_notes || []).length === 0 && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无备注" />}
                {(current.internal_notes || []).map((n, i) => (
                  <div key={i} style={{ borderLeft: '3px solid #faad14', background: '#fffbe6', borderRadius: 6, padding: '8px 12px', marginBottom: 10 }}>
                    <div style={{ fontSize: 11, color: '#d48806' }}>客服备注 · {fmtTime(n.ts)}</div>
                    <div style={{ whiteSpace: 'pre-wrap', fontSize: 13 }}>{n.content}</div>
                  </div>
                ))}
                {canManage && (
                  <Space.Compact style={{ width: '100%', marginTop: 8 }}>
                    <Input.TextArea rows={2} value={note} onChange={(e) => setNote(e.target.value)}
                      placeholder="添加内部备注（仅客服可见，不会发给客户）" />
                    <Button type="primary" onClick={addNote}>添加备注</Button>
                  </Space.Compact>
                )}
              </div>
            )}

            {canManage && current.status !== 'closed' && detailTab === 'dialog' && (
              <div style={{ padding: 16, borderTop: '1px solid #f0f0f0', background: '#fafafa' }}>
                {quickReplies.length > 0 && (
                  <Select
                    size="small" placeholder="插入快捷回复（话术）" style={{ width: 260, marginBottom: 8 }}
                    value={undefined} showSearch optionFilterProp="label"
                    onChange={(v) => {
                      const qr = quickReplies.find((q) => q.id === v)
                      if (qr) setReply((cur) => (cur ? cur + '\n' : '') + qr.content)
                    }}
                    options={quickReplies.map((q) => ({ value: q.id, label: `${q.title}：${q.content.slice(0, 24)}` }))} />
                )}
                <Space.Compact style={{ width: '100%' }}>
                  <Input.TextArea rows={2} value={reply} onChange={(e) => setReply(e.target.value)}
                    placeholder="输入回复内容，回车或点发送，会回发给客户（Shift+Enter 换行）"
                    onPressEnter={(e) => { if (!e.shiftKey) { e.preventDefault(); send() } }} />
                  <Button type="primary" icon={<SendOutlined />} loading={sending} onClick={send}>发送</Button>
                </Space.Compact>
              </div>
            )}
            {current.status === 'closed' && (
              <div style={{ padding: 16, borderTop: '1px solid #f0f0f0' }}>
                <Alert type="success" showIcon message={`工单已关闭${current.resolution ? '：' + current.resolution : ''}`} />
              </div>
            )}
          </div>
        )}
      </Drawer>

      {/* 渠道会话工作台 */}
      <Drawer width={900} open={!!convOpen} onClose={() => setConvOpen(null)}
        title={convOpen ? <Space><ChannelTag kind={convOpen.channel} />会话 #{convOpen.id}｜{convOpen.title || ''}</Space> : ''}
        styles={{ body: { display: 'flex', flexDirection: 'column', padding: 16, height: '100%' } }}>
        {convOpen && (
          <>
            {/* 头部：外部用户 + 提醒开关 */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10, flexWrap: 'wrap', gap: 8 }}>
              <span style={{ fontSize: 12, color: '#666' }}>外部用户：{convOpen.external_id || '-'}</span>
              <Can perm="service:manage">
                <Tooltip title={convWatch ? '开启中：该会话有新消息会通知你' : '已关闭：有新消息不通知'}>
                  <Space size={6} style={{ fontSize: 12, color: '#595959' }}>
                    {convWatch ? <BellFilled style={{ color: '#1677ff' }} /> : <BellOutlined style={{ color: '#bfbfbf' }} />}
                    <span>有新消息通知我</span>
                    <Switch size="small" checked={convWatch} onChange={toggleConvWatch} />
                  </Space>
                </Tooltip>
              </Can>
            </div>

            <div ref={convRef} style={{ flex: 1, minHeight: 0, overflowY: 'auto', background: '#f7f8fa', borderRadius: 8, padding: 12 }}>
              {convMsgs.length === 0
                ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无消息" />
                : convMsgs.map((m, i) => bubble(m, i))}
            </div>

            <Can perm="service:manage">
              <div style={{ width: '100%', marginTop: 12 }}>
                {quickReplies.length > 0 && (
                  <Select size="small" placeholder="插入快捷回复（话术）" style={{ width: 260, marginBottom: 8 }}
                    value={undefined} showSearch optionFilterProp="label"
                    onChange={(v) => {
                      const qr = quickReplies.find((q) => q.id === v)
                      if (qr) setConvReply((cur) => (cur ? cur + '\n' : '') + qr.content)
                    }}
                    options={quickReplies.map((q) => ({ value: q.id, label: `${q.title}：${q.content.slice(0, 24)}` }))} />
                )}
                <Input.TextArea rows={3} value={convReply} onChange={(e) => setConvReply(e.target.value)}
                  style={{ resize: 'vertical', marginBottom: 8 }}
                  placeholder="输入回复内容，回车发送，会直接回发给客户（Shift+Enter 换行）"
                  onPressEnter={(e) => { if (!e.shiftKey) { e.preventDefault(); sendConvReply() } }} />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Upload beforeUpload={sendConvAttachment} showUploadList={false} multiple>
                    <Button icon={<PaperClipOutlined />}>发送附件</Button>
                  </Upload>
                  <Button type="primary" icon={<SendOutlined />} loading={convSending} onClick={sendConvReply}>发送</Button>
                </div>
              </div>
            </Can>
            <Can perm="service:manage">
              <Collapse size="small" ghost style={{ marginTop: 8 }} items={[{
                key: 'cnotes',
                label: <span style={{ fontSize: 12 }}><EditOutlined /> 会话备注{convNotes.length ? `（${convNotes.length}）` : ''}（仅客服可见）</span>,
                children: (
                  <div>
                    {convNotes.length === 0 && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无会话备注" />}
                    {convNotes.map((n, i) => (
                      <div key={i} style={{ borderLeft: '3px solid #faad14', background: '#fffbe6', borderRadius: 6, padding: '6px 10px', marginBottom: 8 }}>
                        <div style={{ fontSize: 11, color: '#d48806' }}>{fmtTime(n.ts)}</div>
                        <div style={{ whiteSpace: 'pre-wrap', fontSize: 13 }}>{n.content}</div>
                      </div>
                    ))}
                    <Space.Compact style={{ width: '100%', marginTop: 4 }}>
                      <Input value={convNote} onChange={(e) => setConvNote(e.target.value)}
                        placeholder="给该会话加内部备注（不会发给客户）" onPressEnter={addConvNote} />
                      <Button type="primary" onClick={addConvNote}>添加</Button>
                    </Space.Compact>
                  </div>
                ),
              }]} />
            </Can>
          </>
        )}
      </Drawer>

      {/* 话术库管理 */}
      <Modal title="快捷回复话术库" open={qrOpen} onCancel={() => setQrOpen(false)} footer={null} width={640}>
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          预存常用话术，客服回复时可在「插入快捷回复」下拉里一键引用。
        </Typography.Paragraph>
        <Space.Compact style={{ width: '100%', marginBottom: 12 }}>
          <Input placeholder="话术标题" value={qrTitle} onChange={(e) => setQrTitle(e.target.value)} style={{ width: 180 }} />
          <Input placeholder="话术内容" value={qrContent} onChange={(e) => setQrContent(e.target.value)} />
          <Button type="primary" onClick={async () => {
            if (!qrTitle.trim() || !qrContent.trim()) { message.warning('标题与内容都要填'); return }
            try {
              await serviceTicketApi.createQuickReply({ title: qrTitle, content: qrContent })
              setQrTitle(''); setQrContent('')
              setQuickReplies(await serviceTicketApi.quickReplies()); message.success('已添加')
            } catch (e) { message.error(errMsg(e)) }
          }}>添加</Button>
        </Space.Compact>
        <List size="small" dataSource={quickReplies}
          locale={{ emptyText: '暂无话术' }}
          renderItem={(q) => (
            <List.Item actions={[
              <a key="e" onClick={() => setQrEdit(q)}>编辑</a>,
              <Popconfirm key="d" title="删除该话术？" onConfirm={async () => {
                try { await serviceTicketApi.removeQuickReply(q.id); setQuickReplies(await serviceTicketApi.quickReplies()) }
                catch (e) { message.error(errMsg(e)) }
              }}><a>删除</a></Popconfirm>,
            ]}>
              <List.Item.Meta title={q.title}
                description={<Typography.Text type="secondary" style={{ fontSize: 12 }}>{q.content}</Typography.Text>} />
            </List.Item>
          )} />
      </Modal>

      {/* 编辑话术 */}
      <Modal title="编辑话术" open={!!qrEdit} onOk={saveQrEdit} onCancel={() => setQrEdit(null)} destroyOnClose>
        <Form form={qrEditForm} layout="vertical">
          <Form.Item name="title" label="标题" rules={[{ required: true, message: '请输入标题' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="content" label="内容" rules={[{ required: true, message: '请输入内容' }]}>
            <Input.TextArea rows={4} />
          </Form.Item>
        </Form>
      </Modal>
    </PageContainer>
  )
}
