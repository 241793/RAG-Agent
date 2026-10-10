import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert, Avatar, Button, Card, Descriptions, Divider, Drawer, Dropdown, Empty, Form, Image, Input, InputNumber, List, message, Modal, Popconfirm, Popover, Select, Space, Spin, Switch, Tabs, Tag, Tooltip, Typography, Upload,
} from 'antd'
import {
  SendOutlined, PlusOutlined, TeamOutlined, RobotOutlined, UserOutlined, PaperClipOutlined,
  PushpinOutlined, MoreOutlined, ReloadOutlined, EditOutlined,
  SearchOutlined, ProfileOutlined, FolderOutlined, AudioMutedOutlined, MailOutlined, PhoneOutlined, ApartmentOutlined, InboxOutlined,
} from '@ant-design/icons'
import { useFileDrop } from '../../hooks/useFileDrop'
import { chatRoomApi, rbacApi, agentApi, chatApi, authApi, scheduledApi, type ChatRoomBrief, type ChatMsgItem } from '../../api'
import { errMsg } from '../../api/http'
import AttachmentView from '../../components/AttachmentView'
import MarkdownBody from '../../components/MarkdownBody'

const ROLE_LABEL: Record<string, string> = { owner: '群主', admin: '管理员', member: '成员' }

/** 部门标签（聊天室各界面统一展示）。 */
function DeptTag({ name, style }: { name?: string | null; style?: React.CSSProperties }) {
  if (!name) return null
  return (
    <Tag color="cyan" style={{ margin: 0, fontSize: 11, lineHeight: '16px', padding: '0 5px', ...style }}>
      {name}
    </Tag>
  )
}

function fmtTime(ms: number) {
  const d = new Date(ms)
  const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  const hm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  return sameDay ? hm : `${d.getMonth() + 1}-${d.getDate()} ${hm}`
}

export default function ChatRoomPage() {
  // 不套 PageContainer 标题/副标题，让聊天框占满整屏高度（标题信息移到聊天内部展示）
  return <ChatRoomCore height="calc(100vh - 105px)" />
}

/** 聊天核心 UI（页面与悬浮窗共用）。height 控制容器高度。 */
export function ChatRoomCore({ height = 'calc(100vh - 190px)', compact = false }: { height?: string; compact?: boolean }) {
  const [rooms, setRooms] = useState<ChatRoomBrief[]>([])
  const [activeId, setActiveId] = useState<number | null>(null)
  const [detail, setDetail] = useState<any>(null)
  const [msgs, setMsgs] = useState<ChatMsgItem[]>([])
  const [input, setInput] = useState('')
  const [pendingAtts, setPendingAtts] = useState<any[]>([])
  const [sending, setSending] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [hasMore, setHasMore] = useState(false)
  const [me, setMe] = useState<any>(null)
  const [users, setUsers] = useState<{ id: number; label: string }[]>([])
  const [agents, setAgents] = useState<any[]>([])
  const [newOpen, setNewOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [memberOpen, setMemberOpen] = useState(false)
  const [botOpen, setBotOpen] = useState(false)
  const [filesOpen, setFilesOpen] = useState(false)
  const [annOpen, setAnnOpen] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const [groupBotOpen, setGroupBotOpen] = useState(false)
  const [profileUid, setProfileUid] = useState<number | null>(null)
  const [mentionIds, setMentionIds] = useState<number[]>([])
  const [replyTo, setReplyTo] = useState<ChatMsgItem | null>(null)
  const [autoScroll, setAutoScroll] = useState(true)
  const [pendingCount, setPendingCount] = useState(0)
  const [atOpen, setAtOpen] = useState(false)   // @ 选择器
  const [atQuery, setAtQuery] = useState('')
  const [remarks, setRemarks] = useState<Record<string, string>>({})  // 私聊备注 {peerId: remark}

  const listRef = useRef<HTMLDivElement>(null)
  const taRef = useRef<any>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const activeIdRef = useRef<number | null>(null)
  const atBottomRef = useRef(true)
  const reconnectRef = useRef<any>(null)

  activeIdRef.current = activeId

  // 拉当前用户 / 可选成员 / 智能体 / 私聊备注
  useEffect(() => {
    fetchMe()
    rbacApi.users(1, 500).then((r) => setUsers(r.items.map((u) => ({ id: u.id, label: u.display_name || u.username })))).catch(() => {})
    agentApi.list().then((a) => setAgents(a.filter((x) => x.type === 'agent'))).catch(() => {})
    loadRemarks()
  }, [])

  const loadRemarks = async () => {
    try { const r = await chatRoomApi.remarks(); setRemarks(r.remarks || {}) } catch { /* ignore */ }
  }

  const fetchMe = async () => {
    try { const r = await import('../../api').then((m) => m.authApi.me()); setMe(r) } catch { /* ignore */ }
  }

  // 展示名：优先用我给对方设的备注，其次真实姓名（仅私聊对端 / 消息发送者本人）
  const dispName = (userId: number | null | undefined, realName: string) => {
    if (!userId) return realName
    return remarks[String(userId)] || realName
  }

  // 设置/清除某人的私聊备注
  const editRemark = (userId: number, realName: string, current?: string) => {
    let v = current || ''
    Modal.confirm({
      title: `设置备注 · ${realName}`,
      icon: null,
      content: (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
          <Input defaultValue={v} maxLength={32} placeholder="输入备注名（留空则清除）" onChange={(e) => { v = e.target.value }} />
          <span style={{ fontSize: 12, color: 'var(--color-text-3)' }}>仅你可见，不会修改对方的真实用户名。</span>
        </div>
      ),
      onOk: async () => {
        try {
          const r = await chatRoomApi.setRemark(userId, v.trim())
          setRemarks((m) => { const n = { ...m }; if (r.remark) n[String(userId)] = r.remark; else delete n[String(userId)]; return n })
          message.success(r.message || '已保存')
        } catch (e) { message.error(errMsg(e)) }
      },
    })
  }

  const loadRooms = async () => {
    try {
      const rs = await chatRoomApi.list()
      setRooms(rs)
      if (rs.length && activeId == null) openRoom(rs[0].id)
    } catch (e) { message.error(errMsg(e)) }
  }
  useEffect(() => { loadRooms() }, [])

  const openRoom = async (id: number) => {
    setActiveId(id)
    setMsgs([]); setReplyTo(null); setPendingAtts([])
    setAutoScroll(true); atBottomRef.current = true; setPendingCount(0)
    try {
      const [d, h] = await Promise.all([chatRoomApi.detail(id), chatRoomApi.messages(id, undefined, 30)])
      setDetail(d)
      setMsgs(h.items); setHasMore(h.has_more)
      chatRoomApi.read(id).catch(() => {})
      setRooms((rs) => rs.map((r) => r.id === id ? { ...r, unread: 0 } : r))
      requestAnimationFrame(() => scrollBottom())
      // 让后端把这个房间加入 WS 订阅（新建群后需要）
      wsRef.current?.readyState === WebSocket.OPEN && wsRef.current.send(JSON.stringify({ type: 'subscribe', room_id: id }))
    } catch (e) { message.error(errMsg(e)) }
  }

  const scrollBottom = (smooth = false) => {
    const el = listRef.current; if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
    atBottomRef.current = true; setPendingCount(0)
  }

  const onScroll = () => {
    const el = listRef.current; if (!el) return
    atBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60
    // 顶部 → 加载更多
    if (el.scrollTop < 40 && hasMore && !loadingMore) loadMore()
  }

  const loadMore = async () => {
    if (!activeId || !msgs.length) return
    setLoadingMore(true)
    const el = listRef.current
    const prevH = el?.scrollHeight || 0
    try {
      const r = await chatRoomApi.messages(activeId, msgs[0].id, 30)
      setMsgs((m) => [...r.items, ...m]); setHasMore(r.has_more)
      requestAnimationFrame(() => { if (el) el.scrollTop = el.scrollHeight - prevH })
    } catch (e) { message.error(errMsg(e)) } finally { setLoadingMore(false) }
  }

  // WebSocket 实时
  useEffect(() => {
    let closed = false
    const connect = () => {
      try {
        const ws = new WebSocket(chatRoomApi.wsUrl())
        wsRef.current = ws
        ws.onmessage = (ev) => {
          let d: any
          try { d = JSON.parse(ev.data) } catch { return }
          handleWs(d)
        }
        ws.onclose = () => { if (!closed) reconnectRef.current = setTimeout(connect, 3000) }
        ws.onerror = () => ws.close()
      } catch { /* ignore */ }
    }
    connect()
    return () => { closed = true; if (reconnectRef.current) clearTimeout(reconnectRef.current); wsRef.current?.close() }
  }, [])

  const handleWs = (d: any) => {
    if (d.type === 'message') {
      const m: ChatMsgItem = d.message
      // 更新房间列表预览
      setRooms((rs) => rs.map((r) => r.id === d.room_id
        ? { ...r, last_message_at: m.created_at, last_preview: m.content?.slice(0, 60) || (m.attachments ? '[附件]' : ''), unread: (r.id === activeIdRef.current ? 0 : (r.unread || 0) + 1) }
        : r))
      if (d.room_id === activeIdRef.current) {
        setMsgs((cur) => cur.some((x) => x.id === m.id) ? cur : [...cur, m])
        if (atBottomRef.current) requestAnimationFrame(() => scrollBottom())
        else setPendingCount((n) => n + 1)
        chatRoomApi.read(m.room_id).catch(() => {})
      }
    } else if (d.type === 'revoke' && d.room_id === activeIdRef.current) {
      setMsgs((cur) => cur.map((m) => m.id === d.message_id ? { ...m, revoked: true, content: '', attachments: null } : m))
    } else if (d.type === 'pin' && d.room_id === activeIdRef.current) {
      setMsgs((cur) => cur.map((m) => m.id === d.message_id ? { ...m, pinned: d.pinned } : m))
    } else if (d.type === 'announcement' && d.room_id === activeIdRef.current) {
      // 公告变化：刷新整个房间详情（含多条公告列表）
      openRoom(activeIdRef.current!)
    } else if (d.type === 'cleared' && d.room_id === activeIdRef.current) {
      setMsgs([])
    } else if (d.type === 'room_updated' && d.room_id === activeIdRef.current) {
      setDetail((cur: any) => cur ? { ...cur, name: d.name ?? cur.name, announcement: d.announcement ?? cur.announcement } : cur)
      setRooms((rs) => rs.map((r) => r.id === d.room_id ? { ...r, name: d.name ?? r.name } : r))
    } else if (d.type === 'mute_all' && d.room_id === activeIdRef.current) {
      setDetail((cur: any) => cur ? { ...cur, mute_all: !!d.enabled } : cur)
    }
  }

  const doUpload = async (file: File) => {
    try {
      const att = await chatApi.uploadAttachment(file)
      setPendingAtts((a) => [...a, att])
    } catch (e) { message.error(errMsg(e)) }
    return false
  }

  /** 批量上传（拖入/多选）：逐个上传，失败的不影响其它 */
  const uploadFiles = async (files: File[]) => {
    let ok = 0
    for (const f of files) {
      try {
        const att = await chatApi.uploadAttachment(f)
        setPendingAtts((a) => [...a, att])
        ok += 1
      } catch (e) { message.error(`${f.name}：${errMsg(e)}`) }
    }
    if (ok) message.success(`已添加 ${ok} 个附件`)
  }

  const drop = useFileDrop(uploadFiles)

  const send = async () => {
    if (!activeId) return
    const content = input.trim()
    if (!content && !pendingAtts.length) return
    setSending(true)
    try {
      await chatRoomApi.send(activeId, {
        content, attachments: pendingAtts.length ? pendingAtts : undefined,
        mentions: mentionIds.length ? mentionIds : undefined,
        reply_to_id: replyTo?.id ?? null,
      })
      setInput(''); setPendingAtts([]); setMentionIds([]); setReplyTo(null)
      // 乐观：WS 会推回来；若 WS 未连接则手动拉一次
      if (wsRef.current?.readyState !== WebSocket.OPEN) {
        const r = await chatRoomApi.messages(activeId, undefined, 30)
        setMsgs(r.items); scrollBottom()
      }
    } catch (e) { message.error(errMsg(e)) } finally { setSending(false) }
  }

  const revoke = async (m: ChatMsgItem) => {
    if (!activeId) return
    try { await chatRoomApi.revoke(activeId, m.id) } catch (e) { message.error(errMsg(e)) }
  }
  const pin = async (m: ChatMsgItem, pinned: boolean) => {
    if (!activeId) return
    try { await chatRoomApi.pin(activeId, m.id, pinned); setMsgs((cur) => cur.map((x) => x.id === m.id ? { ...x, pinned } : x)) }
    catch (e) { message.error(errMsg(e)) }
  }

  // 权限
  const myRole = detail?.my_role || ''
  const canAdmin = myRole === 'owner' || myRole === 'admin' || me?.is_admin
  const canPin = canAdmin

  const createRoom = async () => {
    if (!newName.trim()) { message.warning('请输入群名称'); return }
    try {
      const r = await chatRoomApi.create({ name: newName.trim() })
      setNewOpen(false); setNewName(''); await loadRooms(); openRoom(r.id)
    } catch (e) { message.error(errMsg(e)) }
  }

  const startDirect = async (userId: number) => {
    try {
      const r = await chatRoomApi.direct(userId)
      await loadRooms(); openRoom(r.id)
    } catch (e) { message.error(errMsg(e)) }
  }

  // 全员禁言：支持手动 / 定时（到点自动解除）
  const openMuteAll = () => {
    if (!detail) return
    const cur = (detail as any).mute_all ?? false
    let minutes = 0
    Modal.confirm({
      title: cur ? '关闭全员禁言？' : '开启全员禁言',
      icon: null,
      content: cur ? <span>关闭后所有成员可正常发言。</span> : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
          <span style={{ fontSize: 12, color: 'var(--color-text-2)' }}>自动解除时间（分钟，0=手动解除）</span>
          <InputNumber min={0} defaultValue={0} style={{ width: 160 }} onChange={(v) => { minutes = Number(v) || 0 }} />
        </div>
      ),
      onOk: async () => {
        try {
          const r: any = await chatRoomApi.muteAll(detail.id, !cur, cur ? 0 : minutes)
          message.success(r.message || '已操作')
          await openRoom(detail.id)
        } catch (e) { message.error(errMsg(e)) }
      },
    })
  }

  // 插入 @某人到输入框：若光标前刚打了一半的 "@xxx"，先吃掉它再插入（QQ 式）
  const handleMention = (uid: number, name: string) => {
    setMentionIds((ids) => (ids.includes(uid) ? ids : [...ids, uid]))
    setInput((t) => {
      const m = t.match(/@[^\s@]*$/)
      const base = m ? t.slice(0, m.index) : t
      const sep = base && !base.endsWith(' ') ? ' ' : ''
      return `${base}${sep}@${name} `
    })
    setAtOpen(false); setAtQuery('')
    setTimeout(() => taRef.current?.focus(), 0)
  }

  // 可 @ 对象：成员（已含机器人，is_agent 标记）。QQ 也允许 @ 自己。
  const mentionable = useMemo(() => {
    const seen = new Set<string>()
    const out: { uid: number; name: string; agent: boolean; role: string; department?: string | null; username?: string | null }[] = []
    for (const m of (detail?.members || [])) {
      const key = m.is_agent ? `a${m.agent_id}` : `u${m.user_id}`
      if (seen.has(key)) continue
      seen.add(key)
      out.push({
        uid: m.is_agent ? m.agent_id : m.user_id, name: m.name, agent: !!m.is_agent, role: m.role,
        department: m.department, username: m.username,
      })
    }
    // 兜底：detail.bots 中未进入 members 的机器
    for (const b of (detail?.bots || [])) {
      const key = `a${b.agent_id}`
      if (seen.has(key)) continue
      seen.add(key)
      out.push({ uid: b.agent_id, name: b.name, agent: true, role: '' })
    }
    return out
  }, [detail])
  const atFiltered = useMemo(() => {
    const q = atQuery.trim().toLowerCase()
    return mentionable.filter((x) => !q || x.name.toLowerCase().includes(q)
      || (x.username || '').toLowerCase().includes(q) || (x.department || '').toLowerCase().includes(q))
  }, [mentionable, atQuery])

  // 输入框内容变化：检测光标前是否有 "@xxx" → 打开/过滤 @ 选择器
  const onInputChange = (val: string) => {
    setInput(val)
    const m = val.match(/@([^\s@]*)$/)
    if (m) { setAtOpen(true); setAtQuery(m[1]) } else setAtOpen(false)
  }

  return (
    <>
      <div
        {...drop.dropProps}
        style={{ display: 'flex', gap: 12, height, minHeight: compact ? 320 : 480, position: 'relative' }}
      >
        {/* 拖入文件遮罩 */}
        {drop.dragging && (
          <div style={{
            position: 'absolute', inset: 0, zIndex: 50, borderRadius: 8, pointerEvents: 'none',
            border: '2px dashed var(--color-primary, #2563eb)',
            background: 'rgba(37,99,235,0.08)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            flexDirection: 'column', gap: 6, color: 'var(--color-primary, #2563eb)', fontSize: 14,
          }}>
            <InboxOutlined style={{ fontSize: 40 }} />
            <span>松开即可添加到附件</span>
          </div>
        )}
        {/* 左：房间列表 */}
        <Card size="small" style={{ width: 260, flex: '0 0 auto', display: 'flex', flexDirection: 'column' }}
          styles={{ body: { padding: 8, display: 'flex', flexDirection: 'column', height: '100%' } }}
          title={<Space><TeamOutlined />会话</Space>}
          extra={me?.is_admin ? <Tooltip title="新建群聊"><Button size="small" type="text" icon={<PlusOutlined />} onClick={() => setNewOpen(true)} /></Tooltip> : null}>
          <div style={{ flex: 1, overflowY: 'auto' }}>
            <List
              size="small" dataSource={rooms}
              locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="加载中…" /> }}
              renderItem={(r) => (
                <Dropdown key={r.id} trigger={['contextMenu']} menu={{
                  items: [
                    { key: 'open', label: '打开' },
                    ...(r.kind === 'direct' && r.peer ? [{ key: 'remark', label: r.peer.remark ? '修改备注' : '设置备注' }] : []),
                    { key: 'read', label: '标为已读', disabled: !r.unread },
                  ],
                  onClick: ({ key, domEvent }) => {
                    domEvent.stopPropagation()
                    if (key === 'open') openRoom(r.id)
                    else if (key === 'remark' && r.peer) editRemark(r.peer.user_id, r.peer.name, r.peer.remark || '')
                    else if (key === 'read') { chatRoomApi.read(r.id).then(() => setRooms((rs) => rs.map((x) => x.id === r.id ? { ...x, unread: 0 } : x))) }
                  },
                }}>
                <List.Item
                  style={{ cursor: 'pointer', padding: '6px 8px', borderRadius: 6, background: r.id === activeId ? 'var(--color-primary-soft)' : undefined }}
                  onClick={() => openRoom(r.id)}
                >
                  <div style={{ width: '100%', minWidth: 0 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 6 }}>
                      <Typography.Text ellipsis strong={!!r.unread} style={{ fontSize: 13 }}>
                        {r.kind === 'direct' ? <><UserOutlined /> </> : r.is_default ? '📢 ' : ''}
                        {r.kind === 'direct' && r.peer ? (r.peer.remark || r.peer.name) : r.name}
                      </Typography.Text>
                      {!!r.unread && <Tag color="red" style={{ margin: 0 }}>{r.unread}</Tag>}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4, minWidth: 0 }}>
                      {r.kind === 'direct' && r.peer && (r.peer.department || r.peer.username) && (
                        <>
                          <DeptTag name={r.peer.department} />
                          {r.peer.username && <span style={{ fontSize: 11, color: 'var(--color-text-3)' }}>@{r.peer.username}</span>}
                        </>
                      )}
                      <Typography.Text type="secondary" ellipsis style={{ fontSize: 12, flex: 1, minWidth: 0 }}>{r.last_preview || '暂无消息'}</Typography.Text>
                    </div>
                  </div>
                </List.Item>
                </Dropdown>
              )}
            />
          </div>
        </Card>

        {/* 中：消息区 */}
        <Card size="small" style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}
          styles={{ body: { padding: 0, display: 'flex', flexDirection: 'column', height: '100%' } }}
          title={
            <Space>
              {detail?.kind === 'direct' ? <UserOutlined /> : (detail?.is_default ? '📢' : <TeamOutlined />)}
              {detail?.kind === 'direct'
                ? (() => { const peer = detail?.members?.find((m: any) => m.user_id !== me?.id); return peer ? dispName(peer.user_id, peer.name) : '私聊' })()
                : (detail?.name || '选择会话')}
              {detail && detail.kind !== 'direct' && <Tag color={ROLE_LABEL[myRole] === '群主' ? 'gold' : myRole === 'admin' ? 'blue' : 'default'}>{me?.is_admin && !myRole ? '管理员' : (ROLE_LABEL[myRole] || '成员')}</Tag>}
              {detail?.kind === 'direct' && <Tag>私聊</Tag>}
              {detail?.kind === 'direct' && (() => {
                const peer = detail?.members?.find((m: any) => m.user_id !== me?.id)
                if (!peer) return null
                return <>
                  <DeptTag name={peer.department} />
                  {peer.username && <Typography.Text type="secondary" style={{ fontSize: 12 }}>@{peer.username}</Typography.Text>}
                </>
              })()}
            </Space>
          }
          extra={
            <Space>
              <Tooltip title="自动滚动到最新"><span style={{ fontSize: 12, color: 'var(--color-text-3)' }}>自动跟随 <Switch size="small" checked={autoScroll} onChange={setAutoScroll} /></span></Tooltip>
              {detail && <Tooltip title="搜索聊天记录"><Button size="small" icon={<SearchOutlined />} onClick={() => setSearchOpen(true)} /></Tooltip>}
              {detail?.kind === 'direct' && (
                <Tooltip title="查看对方资料"><Button size="small" icon={<ProfileOutlined />}
                  onClick={() => { const peer = detail.members?.find((m: any) => m.user_id !== me?.id); if (peer) setProfileUid(peer.user_id) }} /></Tooltip>
              )}
              {me?.id && (
                <Tooltip title="我的资料"><Button size="small" icon={<UserOutlined />} onClick={() => setProfileUid(me.id)} /></Tooltip>
              )}
              <Button size="small" icon={<ReloadOutlined />} onClick={() => activeId && openRoom(activeId)} />
            </Space>
          }>
          {!detail ? <Empty style={{ marginTop: 80 }} description="从左侧选择一个会话" /> : (
            <>
              {/* 群公告（多条，QQ 式：显示最新一条 + 条数，点击查看全部） */}
              {detail.announcements?.length > 0 && (
                <div onClick={() => setAnnOpen(true)}
                  style={{ margin: '0 12px 8px', padding: '6px 10px', background: 'var(--color-warn-soft)', borderRadius: 6, fontSize: 13, cursor: 'pointer' }}>
                  <PushpinOutlined style={{ color: 'var(--color-warn)', marginRight: 6 }} />
                  {detail.announcements[0].pinned && <Tag color="orange" style={{ marginRight: 4 }}>置顶</Tag>}
                  {detail.announcements[0].content}
                  {detail.announcements.length > 1 && <Typography.Text type="secondary" style={{ fontSize: 12, marginLeft: 6 }}>（共 {detail.announcements.length} 条，点击查看）</Typography.Text>}
                  {detail.announcements.length === 1 && <Typography.Text type="secondary" style={{ fontSize: 12, marginLeft: 6 }}>（点击查看全部）</Typography.Text>}
                </div>
              )}
              {/* 全员禁言提示 */}
              {(detail as any).mute_all && (
                <div style={{ margin: '0 12px 8px', padding: '4px 10px', background: 'var(--color-error-soft, #fff1f0)', color: 'var(--color-error, #cf1322)', borderRadius: 6, fontSize: 12 }}>
                  <AudioMutedOutlined /> 全员禁言中{canAdmin ? '（管理员可发言）' : '，暂时无法发言'}
                </div>
              )}
              {/* 置顶消息 */}
              {detail.pinned?.length > 0 && (
                <div style={{ margin: '0 12px 8px', padding: '4px 10px', borderLeft: '3px solid var(--color-warn)', background: 'var(--color-bg-subtle)', fontSize: 12, borderRadius: 4 }}>
                  {detail.pinned.slice(0, 2).map((p: ChatMsgItem) => (
                    <div key={p.id}><PushpinOutlined /> <b>{p.sender_name}</b>：{p.content?.slice(0, 60)}</div>
                  ))}
                </div>
              )}

              <div ref={listRef} onScroll={onScroll} style={{ flex: 1, overflowY: 'auto', padding: '8px 12px', minHeight: 0, position: 'relative' }}>
                {loadingMore && <div style={{ textAlign: 'center', fontSize: 12, color: 'var(--color-text-3)' }}>加载中…</div>}
                {!hasMore && msgs.length > 0 && <div style={{ textAlign: 'center', fontSize: 12, color: 'var(--color-text-3)', marginBottom: 8 }}>— 没有更多了 —</div>}
                {msgs.map((m) => <Bubble key={m.id} m={m} me={me} canAdmin={canAdmin} canPin={canPin}
                  displayName={dispName(m.sender_id, m.sender_name)}
                  onRevoke={() => revoke(m)} onPin={() => pin(m, !m.pinned)} onReply={() => setReplyTo(m)}
                  onMention={handleMention}
                  onProfile={() => setProfileUid(m.sender_id)}
                  onPrivate={() => { if (m.sender_type === 'user' && m.sender_id && m.sender_id !== me?.id) startDirect(m.sender_id) }} />)}
              </div>

              {pendingCount > 0 && (
                <Button type="primary" size="small" style={{ position: 'absolute', right: 24, bottom: 150, zIndex: 10 }}
                  onClick={() => scrollBottom(true)}>↓ {pendingCount} 条新消息</Button>
              )}

              {/* 输入区 */}
              <div style={{ borderTop: '1px solid var(--color-border)', padding: 10 }}>
                {replyTo && (
                  <div style={{ fontSize: 12, color: 'var(--color-text-2)', marginBottom: 6 }}>
                    回复 <b>{replyTo.sender_name}</b>：{replyTo.content?.slice(0, 40)}
                    <Button size="small" type="link" onClick={() => setReplyTo(null)}>取消</Button>
                  </div>
                )}
                {pendingAtts.length > 0 && (
                  <Space wrap style={{ marginBottom: 6 }}>
                    {pendingAtts.map((a, i) => (
                      <Tag key={i} closable onClose={() => setPendingAtts((arr) => arr.filter((_, j) => j !== i))}>
                        {a.type === 'image' ? '🖼' : a.type === 'video' ? '🎬' : '📎'} {a.name}
                      </Tag>
                    ))}
                  </Space>
                )}
                <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
                  {/* @ 选择器（像 QQ）：可搜索群内所有人+机器人 */}
                  <Popover
                    open={atOpen} onOpenChange={(o) => { setAtOpen(o); if (o) setAtQuery('') }}
                    trigger="click"
                    placement="topLeft"
                    content={
                      <div style={{ width: 240 }}>
                        <Input size="small" autoFocus placeholder="搜索成员 / 机器人"
                          value={atQuery} onChange={(e) => setAtQuery(e.target.value)} style={{ marginBottom: 6 }} allowClear />
                        <div style={{ maxHeight: 240, overflowY: 'auto' }}>
                          <List size="small" dataSource={atFiltered}
                            locale={{ emptyText: <div style={{ color: 'var(--color-text-3)', fontSize: 12, padding: 8 }}>无匹配成员</div> }}
                            renderItem={(x: any) => (
                              <List.Item style={{ cursor: 'pointer', padding: '4px 6px' }} onClick={() => handleMention(x.uid, dispName(x.uid, x.name))}>
                                <Space size={6}>
                                  <Avatar size={20} icon={x.agent ? <RobotOutlined /> : <UserOutlined />}
                                    style={{ background: x.agent ? '#7c3aed' : '#8c8c8c' }} />
                                  <span style={{ fontSize: 13 }}>{dispName(x.uid, x.name)}</span>
                                  {!x.agent && <DeptTag name={x.department} style={{ fontSize: 10 }} />}
                                  {!x.agent && x.username && <span style={{ fontSize: 11, color: 'var(--color-text-3)' }}>@{x.username}</span>}
                                  {x.agent && <Tag color="purple" style={{ margin: 0, fontSize: 10 }}>机器人</Tag>}
                                  {x.uid === me?.id && <Tag style={{ margin: 0, fontSize: 10 }}>我</Tag>}
                                </Space>
                              </List.Item>
                            )} />
                        </div>
                      </div>
                    }>
                    <Tooltip title="提到某人（也可在输入框直接打 @）"><Button icon={<Typography.Text>@</Typography.Text>} /></Tooltip>
                  </Popover>
                  <Upload beforeUpload={doUpload} showUploadList={false} multiple>
                    <Tooltip title="发送附件（图片/视频/音频/文件），也可直接把文件拖进来"><Button icon={<PaperClipOutlined />} /></Tooltip>
                  </Upload>
                  <Input.TextArea ref={taRef} autoSize={{ minRows: 1, maxRows: 4 }} value={input}
                    onChange={(e) => onInputChange(e.target.value)}
                    onKeyDown={(e) => {
                      // @ 选择器开启时：回车选中第一个匹配 / Esc 关闭（QQ 式）
                      if (!atOpen) return
                      if (e.key === 'Escape') { setAtOpen(false); return }
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault()
                        if (atFiltered.length) handleMention(atFiltered[0].uid, atFiltered[0].name)
                        else setAtOpen(false)
                      }
                    }}
                    onPressEnter={(e) => { if (!e.shiftKey && !atOpen) { e.preventDefault(); send() } }}
                    placeholder="输入消息，Enter 发送，Shift+Enter 换行；@ 可提及成员或机器人" />
                  <Button type="primary" icon={<SendOutlined />} loading={sending} onClick={send}>发送</Button>
                  {detail.kind !== 'direct' && canAdmin && (
                    <Dropdown menu={{
                      items: [
                        { key: 'photo', label: '查看群相册/文件', icon: <FolderOutlined /> },
                        { type: 'divider' },
                        { key: 'info', label: '群资料', icon: <EditOutlined /> },
                        { key: 'members', label: '群成员与管理', icon: <UserOutlined /> },
                        { key: 'bots', label: '机器人', icon: <RobotOutlined /> },
                        { key: 'groupbot', label: '群管机器人', icon: <RobotOutlined /> },
                        { key: 'announcement', label: '设置群公告', icon: <PushpinOutlined /> },
                        { key: 'muteall', label: '全员禁言', icon: <AudioMutedOutlined /> },
                        { type: 'divider' },
                        { key: 'clear', label: '清空聊天记录', danger: true },
                      ],
                      onClick: ({ key }) => {
                        if (key === 'info') {
                          let nm = detail.name, an = detail.announcement || ''
                          Modal.confirm({
                            title: '群资料', icon: null, width: 480,
                            content: (
                              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
                                <span style={{ fontSize: 12, color: 'var(--color-text-2)' }}>群名称</span>
                                <Input defaultValue={nm} disabled={detail.is_default} onChange={(e) => { nm = e.target.value }} />
                                <span style={{ fontSize: 12, color: 'var(--color-text-2)' }}>群公告</span>
                                <Input.TextArea defaultValue={an} rows={3} onChange={(e) => { an = e.target.value }} />
                              </div>
                            ),
                            onOk: async () => {
                              const r = await chatRoomApi.updateRoom(detail.id, { name: nm, announcement: an })
                              setDetail({ ...detail, name: r.name || nm, announcement: an })
                              loadRooms(); message.success('已保存')
                            },
                          })
                        } else if (key === 'members') setMemberOpen(true)
                        else if (key === 'bots') setBotOpen(true)
                        else if (key === 'groupbot') setGroupBotOpen(true)
                        else if (key === 'photo') setFilesOpen(true)
                        else if (key === 'announcement') setAnnOpen(true)
                        else if (key === 'muteall') openMuteAll()
                        else if (key === 'clear') {
                          Modal.confirm({
                            title: '清空聊天记录？', content: '所有消息将被撤回（成员与群结构保留），不可恢复。',
                            okButtonProps: { danger: true },
                            onOk: async () => { await chatRoomApi.clearMessages(detail.id); setMsgs([]); message.success('已清空') },
                          })
                        }
                      },
                    }} trigger={['click']}>
                      <Tooltip title="群管理"><Button icon={<MoreOutlined />} /></Tooltip>
                    </Dropdown>
                  )}
                </div>
              </div>
            </>
          )}
        </Card>
      </div>

      {/* 新建群 */}
      <Modal title="新建群聊" open={newOpen} onOk={createRoom} onCancel={() => setNewOpen(false)} destroyOnClose>
        <Input placeholder="群名称" value={newName} onChange={(e) => setNewName(e.target.value)} style={{ marginBottom: 8 }} />
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>创建后可在「群管理 → 成员」拉人入群</Typography.Text>
      </Modal>

      {/* 成员管理 */}
      <MemberDrawer open={memberOpen} onClose={() => setMemberOpen(false)} detail={detail} users={users} me={me}
        canAdmin={canAdmin} isOwner={myRole === 'owner' || me?.is_admin}
        dispName={dispName} onRemark={editRemark} remarks={remarks}
        onProfile={(uid: number) => { setMemberOpen(false); setProfileUid(uid) }}
        onChanged={() => activeId && openRoom(activeId)}
        onPrivate={(m: any) => { setMemberOpen(false); startDirect(m.user_id) }}
        onLeave={async () => { await chatRoomApi.leaveRoom(detail.id); setMemberOpen(false); setActiveId(null); setDetail(null); loadRooms() }}
        onDissolve={async () => { await chatRoomApi.dissolveRoom(detail.id); setMemberOpen(false); setActiveId(null); setDetail(null); loadRooms() }} />

      {/* 机器人 */}
      <BotDrawer open={botOpen} onClose={() => setBotOpen(false)} detail={detail} agents={agents}
        onChanged={() => activeId && openRoom(activeId)} />

      {/* 群管机器人 */}
      <GroupBotDrawer open={groupBotOpen} onClose={() => setGroupBotOpen(false)} detail={detail}
        onChanged={() => activeId && openRoom(activeId)} />

      {/* 群文件 / 相册 */}
      <FilesDrawer open={filesOpen} onClose={() => setFilesOpen(false)} detail={detail} />

      {/* 群公告 */}
      <AnnouncementDrawer open={annOpen} onClose={() => setAnnOpen(false)} detail={detail}
        canAdmin={canAdmin} onChanged={() => activeId && openRoom(activeId)} />

      {/* 聊天记录搜索 */}
      <SearchDrawer open={searchOpen} onClose={() => setSearchOpen(false)} detail={detail}
        onJump={(mid: number) => { const el = document.getElementById(`msg-${mid}`); el?.scrollIntoView({ behavior: 'smooth', block: 'center' }) }} />

      {/* 成员资料卡 */}
      <ProfileDrawer open={profileUid != null} onClose={() => setProfileUid(null)} roomId={detail?.id} userId={profileUid}
        me={me} onSaved={(u: any) => setMe(u)} />
    </>
  )
}

/** 单条消息气泡 */
function Bubble({ m, me, canAdmin, canPin, displayName, onRevoke, onPin, onReply, onMention, onPrivate, onProfile }: any) {
  const mine = m.sender_type === 'user' && m.sender_id === me?.id
  const isBot = m.sender_type === 'agent'
  const shownName = displayName || m.sender_name
  const canRevoke = mine || canAdmin
  const canPrivate = m.sender_type === 'user' && m.sender_id !== me?.id
  if (m.revoked) {
    return <div style={{ textAlign: 'center', fontSize: 12, color: 'var(--color-text-3)', margin: '6px 0' }}>
      「{m.sender_name}」撤回了一条消息
    </div>
  }
  return (
    <div id={`msg-${m.id}`} style={{ display: 'flex', gap: 8, marginBottom: 12, flexDirection: mine ? 'row-reverse' : 'row' }}>
      <Tooltip title={m.sender_type === 'user' ? '点击查看资料' : ''}>
        <Avatar size={34} icon={isBot ? <RobotOutlined /> : <UserOutlined />}
          onClick={m.sender_type === 'user' ? onProfile : undefined}
          style={{ background: isBot ? '#7c3aed' : (mine ? '#2563eb' : '#8c8c8c'), flexShrink: 0, cursor: m.sender_type === 'user' ? 'pointer' : 'default' }} />
      </Tooltip>
      <div style={{ maxWidth: '68%', minWidth: 0 }}>
        <div style={{ fontSize: 12, color: 'var(--color-text-2)', textAlign: mine ? 'right' : 'left', marginBottom: 2 }}>
          {isBot && <Tag color="purple" style={{ marginRight: 4 }}>机器人</Tag>}
          {shownName}
          {!isBot && (m.sender_department || m.sender_username) && (
            <span style={{ marginLeft: 4, display: 'inline-flex', alignItems: 'center', gap: 4, verticalAlign: 'middle' }}>
              <DeptTag name={m.sender_department} />
              {m.sender_username && <span style={{ color: 'var(--color-text-3)' }}>@{m.sender_username}</span>}
            </span>
          )}
          {' '}<span style={{ color: 'var(--color-text-3)' }}>{fmtTime(m.created_at)}</span>
          {m.pinned && <PushpinOutlined style={{ color: 'var(--color-warn)', marginLeft: 4 }} />}
        </div>
        {/* 消息体：右键弹出操作菜单（回复/@/私聊/复制/置顶/撤回） */}
        <Dropdown trigger={['contextMenu']} menu={{
          items: [
            { key: 'reply', label: '回复' },
            { key: 'at', label: `@ ${m.sender_name}` },
            ...(m.sender_type === 'user' ? [{ key: 'profile', label: mine ? '我的资料' : '查看资料' }] : []),
            ...(canPrivate ? [{ key: 'private', label: '私聊' }] : []),
            { key: 'copy', label: '复制' },
            { type: 'divider' },
            ...(canPin ? [{ key: 'pin', label: m.pinned ? '取消置顶' : '置顶' }] : []),
            ...(canRevoke ? [{ key: 'revoke', label: '撤回', danger: true }] : []),
          ],
          onClick: ({ key }) => {
            if (key === 'reply') onReply()
            else if (key === 'at') onMention(m.sender_id, m.sender_name)
            else if (key === 'profile') onProfile()
            else if (key === 'private') onPrivate()
            else if (key === 'copy') { navigator.clipboard?.writeText(m.content || ''); message.success('已复制') }
            else if (key === 'pin') onPin()
            else if (key === 'revoke') Modal.confirm({ title: '撤回该消息？', onOk: onRevoke })
          },
        }}>
          <div style={{
            background: mine ? 'var(--color-primary-soft)' : 'var(--color-bg-subtle)',
            border: '1px solid var(--color-border)', borderRadius: 8, padding: '6px 10px',
            fontSize: 14, cursor: 'context-menu', maxWidth: '100%',
          }}>
            <MarkdownBody content={m.content || ''} />
            {m.attachments?.map((a: any, i: number) => <AttachmentView key={i} att={a} />)}
          </div>
        </Dropdown>
        <div style={{ fontSize: 12, textAlign: mine ? 'right' : 'left', marginTop: 2 }}>
          <Space size={8}>
            <a onClick={onReply}>回复</a>
            <Dropdown trigger={['click']} menu={{
              items: [
                { key: 'at', label: '提到 TA' },
                ...(canPin ? [{ key: 'pin', label: m.pinned ? '取消置顶' : '置顶' }] : []),
                ...(canRevoke ? [{ key: 'revoke', label: '撤回', danger: true }] : []),
              ],
              onClick: ({ key }) => {
                if (key === 'at') onMention(m.sender_id, m.sender_name)
                else if (key === 'pin') onPin()
                else if (key === 'revoke') { Modal.confirm({ title: '撤回该消息？', onOk: onRevoke }) }
              },
            }}>
              <a>更多</a>
            </Dropdown>
          </Space>
        </div>
      </div>
    </div>
  )
}

function MemberDrawer({ open, onClose, detail, users, me, canAdmin, isOwner, dispName, onRemark, remarks, onProfile, onChanged, onPrivate, onLeave, onDissolve }: any) {
  const [addOpen, setAddOpen] = useState(false)
  const [pick, setPick] = useState<number[]>([])
  const [q, setQ] = useState('')
  const remarksHas = (uid: number) => !!(uid && remarks && remarks[String(uid)])
  const members: any[] = detail?.members || []
  const isDefault = !!detail?.is_default
  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase()
    return s ? members.filter((m) => (m.name || '').toLowerCase().includes(s) || (m.username || '').toLowerCase().includes(s)) : members
  }, [members, q])
  const roleRank: Record<string, number> = { owner: 0, admin: 1, member: 2 }
  const sorted = useMemo(() => [...filtered].sort((a, b) => (roleRank[a.role] ?? 9) - (roleRank[b.role] ?? 9)), [filtered])
  const admins = members.filter((m) => m.role === 'admin').length

  const add = async () => {
    try { await chatRoomApi.addMembers(detail.id, pick); message.success('已添加'); setPick([]); setAddOpen(false); onChanged() }
    catch (e) { message.error(errMsg(e)) }
  }
  const setRole = async (m: any) => {
    try {
      const next = m.role === 'admin' ? 'member' : 'admin'
      if (m.is_agent) await chatRoomApi.setBotRole(detail.id, m.agent_id, next)
      else await chatRoomApi.setRole(detail.id, m.user_id, next)
      message.success(next === 'admin' ? '已设为群管理员' : '已取消群管理员'); onChanged()
    } catch (e) { message.error(errMsg(e)) }
  }
  const mute = async (m: any) => {
    const mins = window.prompt(`禁言「${m.name}」多少分钟？（0 = 解除）`, '10')
    if (mins == null) return
    try { const r = await chatRoomApi.mute(detail.id, m.user_id, Number(mins) || 0); message.success(r.message || '已操作'); onChanged() }
    catch (e) { message.error(errMsg(e)) }
  }
  const kick = async (m: any) => {
    try {
      if (m.is_agent) await chatRoomApi.removeBot(detail.id, m.agent_id)
      else await chatRoomApi.removeMember(detail.id, m.user_id)
      onChanged()
    }
    catch (e) { message.error(errMsg(e)) }
  }
  const transfer = async (m: any) => {
    try { await chatRoomApi.transferOwner(detail.id, m.user_id); message.success('已转让群主'); onChanged() }
    catch (e) { message.error(errMsg(e)) }
  }

  return (
    <Drawer title={`群成员（${members.length}）${admins ? ` · 管理员 ${admins}` : ''}`} width={480} open={open} onClose={onClose}
      extra={canAdmin && !isDefault && <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => setAddOpen(true)}>添加成员</Button>}>
      <Input.Search placeholder="搜索成员/机器人" allowClear value={q} onChange={(e) => setQ(e.target.value)} style={{ marginBottom: 10 }} />
      <List size="small" dataSource={sorted} renderItem={(m: any) => (
        <List.Item actions={[
          !m.is_agent && m.user_id !== me?.id && <a key="p" onClick={() => onPrivate?.(m)}>私聊</a>,
          !m.is_agent && m.user_id !== me?.id && <a key="rm" onClick={() => onRemark?.(m.user_id, m.name)}>{remarksHas(m.user_id) ? '改备注' : '备注'}</a>,
          ...(isOwner && m.role !== 'owner' && !m.is_agent ? [
            <a key="r" onClick={() => setRole(m)}>{m.role === 'admin' ? '取消管理' : '设为管理'}</a>,
            <Popconfirm key="t" title={`转让群主给「${dispName?.(m.user_id, m.name) || m.name}」？`} onConfirm={() => transfer(m)}><a>转让</a></Popconfirm>,
          ] : []),
          ...(isOwner && m.is_agent ? [
            <a key="ar" onClick={() => setRole(m)}>{m.role === 'admin' ? '取消管理' : '设为管理'}</a>,
          ] : []),
          ...(canAdmin && m.role !== 'owner' && m.user_id !== me?.id && !m.is_agent ? [
            <a key="m" onClick={() => mute(m)}>{m.muted_until && m.muted_until > Date.now() ? '解除禁言' : '禁言'}</a>,
          ] : []),
          ...(canAdmin && m.role !== 'owner' && !(m.user_id === me?.id) ? [
            <Popconfirm key="k" title={`把「${dispName?.(m.user_id, m.name) || m.name}」移出群？`} onConfirm={() => kick(m)}><a>移出</a></Popconfirm>,
          ] : []),
        ].filter(Boolean)}>
          <List.Item.Meta
            avatar={<Avatar size="small" icon={m.is_agent ? <RobotOutlined /> : <UserOutlined />}
              onClick={!m.is_agent ? () => onProfile?.(m.user_id) : undefined}
              style={{ background: m.role === 'owner' ? '#faad14' : m.is_agent ? '#7c3aed' : '#8c8c8c', cursor: !m.is_agent ? 'pointer' : 'default' }} />}
            title={<Space size={4} wrap>
              <span>{m.is_agent ? m.name : (dispName?.(m.user_id, m.name) || m.name)}</span>
              {!m.is_agent && remarksHas(m.user_id) && <span style={{ fontSize: 11, color: 'var(--color-text-3)' }}>（{m.name}）</span>}
              {m.user_id === me?.id && <Tag>我</Tag>}
              {m.is_agent && <Tag color="purple">机器人</Tag>}
              {m.role === 'owner' && <Tag color="gold">群主</Tag>}
              {m.role === 'admin' && <Tag color="blue">管理员</Tag>}
              {m.is_admin && <Tag color="geekblue">系统管理员</Tag>}
              {m.muted_until && m.muted_until > Date.now() && <Tag color="orange">禁言中</Tag>}
            </Space>}
            description={!m.is_agent && (m.department || m.username) ? (
              <Space size={6} style={{ fontSize: 12 }}>
                <DeptTag name={m.department} />
                {m.username && <span style={{ color: 'var(--color-text-3)' }}>@{m.username}</span>}
              </Space>
            ) : undefined} />
        </List.Item>
      )} />

      {!isDefault && (
        <div style={{ marginTop: 16, borderTop: '1px solid var(--color-border)', paddingTop: 12 }}>
          <Space direction="vertical" style={{ width: '100%' }} size={8}>
            {me?.id !== detail?.owner_id && (
              <Popconfirm title="确定退出该群？" onConfirm={() => onLeave?.()}>
                <Button danger block>退出群聊</Button>
              </Popconfirm>
            )}
            {(isOwner) && (
              <Popconfirm title="解散该群？所有成员将看不到该群" onConfirm={() => onDissolve?.()}>
                <Button danger block>解散该群</Button>
              </Popconfirm>
            )}
          </Space>
        </div>
      )}

      <Modal title="添加成员" open={addOpen} onOk={add} onCancel={() => setAddOpen(false)} destroyOnClose>
        <Select mode="multiple" style={{ width: '100%' }} placeholder="选择用户" value={pick} onChange={setPick}
          showSearch optionFilterProp="label"
          options={users.filter((u: any) => !members.some((m: any) => m.user_id === u.id)).map((u: any) => ({ value: u.id, label: u.label }))} />
      </Modal>
    </Drawer>
  )
}

/** 群文件 / 相册：按类型筛选本群所有带附件的消息。 */
function FilesDrawer({ open, onClose, detail }: any) {
  const [tab, setTab] = useState('image')
  const [items, setItems] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  useEffect(() => {
    if (!open || !detail?.id) return
    setLoading(true)
    chatRoomApi.files(detail.id, tab)
      .then((r: any[]) => setItems(r))
      .catch(() => setItems([]))
      .finally(() => setLoading(false))
  }, [open, detail?.id, tab])
  return (
    <Drawer title="群相册 / 文件" width={520} open={open} onClose={onClose}>
      <Tabs activeKey={tab} onChange={setTab} items={[
        { key: 'image', label: '图片' },
        { key: 'video', label: '视频' },
        { key: 'audio', label: '音频' },
        { key: 'file', label: '文件' },
      ]} />
      {loading ? <div style={{ textAlign: 'center', padding: 24 }}><Spin /></div> : (
        items.length === 0 ? <Empty description="暂无内容" /> : (
          tab === 'image' ? (
            <Image.PreviewGroup>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 8 }}>
                {items.map((it) => (
                  <div key={it.message_id + '-' + it.name} style={{ cursor: 'pointer' }}>
                    <AttachmentView att={it.att} />
                  </div>
                ))}
              </div>
            </Image.PreviewGroup>
          ) : (
            <List size="small" dataSource={items} renderItem={(it: any) => (
              <List.Item>
                <List.Item.Meta
                  title={<span style={{ fontSize: 13 }}>{it.name}</span>}
                  description={<span style={{ fontSize: 12 }}>{it.sender_name} · {fmtTime(it.created_at)}</span>} />
                <div style={{ maxWidth: 260 }}><AttachmentView att={it.att} /></div>
              </List.Item>
            )} />
          )
        )
      )}
    </Drawer>
  )
}

/** 群公告（QQ 式：多条记录，管理员可增删改）。 */
function AnnouncementDrawer({ open, onClose, detail, canAdmin, onChanged }: any) {
  const [list, setList] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [editId, setEditId] = useState<number | null>(null)   // null=不在编辑；0=新建
  const [draft, setDraft] = useState('')
  const [draftPinned, setDraftPinned] = useState(false)

  const load = async () => {
    if (!detail?.id) return
    setLoading(true)
    try { setList(await chatRoomApi.announcements(detail.id)) }
    catch { setList([]) } finally { setLoading(false) }
  }
  useEffect(() => { if (open) load() }, [open, detail?.id])

  const startNew = () => { setEditId(0); setDraft(''); setDraftPinned(false) }
  const startEdit = (a: any) => { setEditId(a.id); setDraft(a.content); setDraftPinned(!!a.pinned) }
  const cancel = () => { setEditId(null); setDraft(''); setDraftPinned(false) }
  const save = async () => {
    if (!draft.trim()) { message.warning('公告内容不能为空'); return }
    try {
      if (editId === 0) await chatRoomApi.setAnnouncement(detail.id, draft.trim(), draftPinned)
      else await chatRoomApi.updateAnnouncement(detail.id, editId as number, { content: draft.trim(), pinned: draftPinned })
      message.success('已保存'); cancel(); await load(); onChanged?.()
    } catch (e) { message.error(errMsg(e)) }
  }
  const remove = async (a: any) => {
    try { await chatRoomApi.deleteAnnouncement(detail.id, a.id); message.success('已删除'); await load(); onChanged?.() }
    catch (e) { message.error(errMsg(e)) }
  }
  const togglePin = async (a: any) => {
    try { await chatRoomApi.updateAnnouncement(detail.id, a.id, { pinned: !a.pinned }); await load(); onChanged?.() }
    catch (e) { message.error(errMsg(e)) }
  }

  return (
    <Drawer title="群公告" width={480} open={open} onClose={onClose}
      extra={canAdmin && editId === null && <Button size="small" type="primary" icon={<PlusOutlined />} onClick={startNew}>发布公告</Button>}>
      {canAdmin && editId !== null && (
        <div style={{ marginBottom: 12, padding: 10, border: '1px solid var(--color-border)', borderRadius: 6 }}>
          <Input.TextArea value={draft} rows={3} maxLength={2000} showCount
            placeholder="输入公告内容…" onChange={(e) => setDraft(e.target.value)} />
          <Space style={{ marginTop: 8 }}>
            <Space size={4}><Switch size="small" checked={draftPinned} onChange={setDraftPinned} /><span style={{ fontSize: 12 }}>置顶</span></Space>
            <Button size="small" type="primary" onClick={save}>保存</Button>
            <Button size="small" onClick={cancel}>取消</Button>
          </Space>
        </div>
      )}
      {loading ? <div style={{ textAlign: 'center', padding: 24 }}><Spin /></div> : (
        list.length === 0 ? <Empty description="暂无公告" /> : (
          <List dataSource={list} renderItem={(a: any) => (
            <List.Item actions={canAdmin ? [
              <a key="p" onClick={() => togglePin(a)}>{a.pinned ? '取消置顶' : '置顶'}</a>,
              <a key="e" onClick={() => startEdit(a)}>编辑</a>,
              <Popconfirm key="d" title="删除这条公告？" onConfirm={() => remove(a)}><a style={{ color: 'var(--color-error)' }}>删除</a></Popconfirm>,
            ] : []}>
              <List.Item.Meta
                title={<Space size={4}>
                  {a.pinned && <Tag color="orange">置顶</Tag>}
                  <span style={{ fontSize: 12, color: 'var(--color-text-3)' }}>{a.created_by_name || '管理员'} · {a.created_at ? fmtTime(a.created_at) : ''}</span>
                </Space>}
                description={<span style={{ whiteSpace: 'pre-wrap', color: 'var(--color-text-1)' }}>{a.content}</span>} />
            </List.Item>
          )} />
        )
      )}
    </Drawer>
  )
}

/** 聊天记录搜索：按关键词在群/私聊历史中检索，命中可直接跳转。 */
function SearchDrawer({ open, onClose, detail, onJump }: any) {
  const [q, setQ] = useState('')
  const [items, setItems] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [searched, setSearched] = useState(false)

  const doSearch = async () => {
    if (!detail?.id || !q.trim()) return
    setLoading(true); setSearched(true)
    try { const r = await chatRoomApi.searchMessages(detail.id, q.trim()); setItems(r.items || []) }
    catch (e) { message.error(errMsg(e)); setItems([]) }
    finally { setLoading(false) }
  }
  useEffect(() => { if (!open) { setQ(''); setItems([]); setSearched(false) } }, [open])

  return (
    <Drawer title="搜索聊天记录" width={480} open={open} onClose={onClose}>
      <Input.Search placeholder="输入关键词搜索" allowClear enterButton="搜索"
        value={q} onChange={(e) => setQ(e.target.value)} onSearch={doSearch} style={{ marginBottom: 12 }} />
      {loading ? <div style={{ textAlign: 'center', padding: 24 }}><Spin /></div> : (
        !searched ? <Empty description="输入关键词开始搜索" /> :
        items.length === 0 ? <Empty description="未找到匹配的消息" /> : (
          <List size="small" dataSource={items} renderItem={(m: any) => (
            <List.Item style={{ cursor: 'pointer' }} onClick={() => { onJump?.(m.id); onClose?.() }}>
              <List.Item.Meta
                avatar={<Avatar size="small" icon={m.sender_is_agent ? <RobotOutlined /> : <UserOutlined />} />}
                title={<Space size={6}><span style={{ fontSize: 13 }}>{m.sender_name}</span>
                  {!m.sender_is_agent && <DeptTag name={m.sender_department} style={{ fontSize: 10 }} />}
                  {!m.sender_is_agent && m.sender_username && <span style={{ fontSize: 11, color: 'var(--color-text-3)' }}>@{m.sender_username}</span>}
                  <span style={{ fontSize: 11, color: 'var(--color-text-3)' }}>{fmtTime(m.created_at)}</span></Space>}
                description={<span style={{ fontSize: 13 }}>{m.content?.slice(0, 100)}{m.attachments ? ' [附件]' : ''}</span>} />
            </List.Item>
          )} />
        )
      )}
    </Drawer>
  )
}

/** 成员资料卡：显示头像/部门/邮箱/电话/角色；查看自己时可编辑姓名/邮箱/电话/头像。 */
function ProfileDrawer({ open, onClose, roomId, userId, me, onSaved }: any) {
  const [p, setP] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [editing, setEditing] = useState(false)
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const isSelf = !!me && userId === me.id

  const load = () => {
    if (!roomId || !userId) return
    setLoading(true); setP(null)
    chatRoomApi.memberProfile(roomId, userId).then(setP).catch(() => setP(null)).finally(() => setLoading(false))
  }
  useEffect(() => { if (open) { setEditing(false); load() } /* eslint-disable-next-line */ }, [open, roomId, userId])

  const openEdit = () => {
    form.setFieldsValue({ display_name: p?.display_name, email: p?.email, phone: p?.phone, avatar: p?.avatar })
    setEditing(true)
  }
  const save = async () => {
    const v = await form.validateFields().catch(() => null)
    if (!v) return
    setSaving(true)
    try {
      const u = await authApi.updateProfile(v)
      onSaved?.(u)
      message.success('资料已保存'); setEditing(false); load()
    } catch (e) { message.error(errMsg(e)) } finally { setSaving(false) }
  }

  return (
    <Drawer title={isSelf ? '我的资料' : '成员资料'} width={380} open={open} onClose={onClose}
      extra={isSelf && !editing && !loading && p ? <Button size="small" icon={<EditOutlined />} onClick={openEdit}>编辑</Button> : null}>
      {loading ? <div style={{ textAlign: 'center', padding: 24 }}><Spin /></div> : !p ? <Empty description="暂无资料" /> : editing ? (
        <Form form={form} layout="vertical">
          <div style={{ textAlign: 'center', marginBottom: 12 }}>
            <Form.Item name="avatar" noStyle><AvatarInput /></Form.Item>
          </div>
          <Form.Item name="display_name" label="姓名/昵称" rules={[{ required: true, message: '请输入姓名' }]}><Input /></Form.Item>
          <Form.Item name="email" label="邮箱" rules={[{ type: 'email', message: '邮箱格式不正确' }]}><Input placeholder="可选" /></Form.Item>
          <Form.Item name="phone" label="电话"><Input placeholder="可选" /></Form.Item>
          <Space>
            <Button type="primary" loading={saving} onClick={save}>保存</Button>
            <Button onClick={() => setEditing(false)}>取消</Button>
          </Space>
          <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 8 }}>
            用户名、部门与角色由管理员维护，此处不可修改。
          </Typography.Paragraph>
        </Form>
      ) : (
        <div>
          <div style={{ textAlign: 'center', marginBottom: 16 }}>
            <Avatar size={72} src={p.avatar || undefined} icon={<UserOutlined />} style={{ background: '#2563eb' }} />
            <div style={{ fontSize: 18, fontWeight: 600, marginTop: 8 }}>{p.display_name}</div>
            <div style={{ fontSize: 12, color: 'var(--color-text-3)' }}>@{p.username}</div>
            <Space size={4} style={{ marginTop: 6 }} wrap>
              {isSelf && <Tag color="green">我</Tag>}
              {p.is_admin && <Tag color="geekblue">系统管理员</Tag>}
              {(p.roles || []).map((r: string) => <Tag key={r} color="blue">{r}</Tag>)}
              {p.user_type === 'external' && <Tag color="orange">外部用户</Tag>}
            </Space>
          </div>
          <Divider style={{ margin: '8px 0' }} />
          <Descriptions column={1} size="small" colon={false}>
            <Descriptions.Item label={<Space size={4}><ApartmentOutlined />部门</Space>}>{p.department_name || '—'}</Descriptions.Item>
            <Descriptions.Item label={<Space size={4}><MailOutlined />邮箱</Space>}>{p.email || '—'}</Descriptions.Item>
            <Descriptions.Item label={<Space size={4}><PhoneOutlined />电话</Space>}>{p.phone || '—'}</Descriptions.Item>
            <Descriptions.Item label="状态">{p.status === 'active' ? <Tag color="green">正常</Tag> : <Tag>停用</Tag>}</Descriptions.Item>
            <Descriptions.Item label="最近登录">{p.last_login_at ? fmtTime(new Date(p.last_login_at).getTime()) : '—'}</Descriptions.Item>
          </Descriptions>
        </div>
      )}
    </Drawer>
  )
}

/** 头像编辑：上传图片或直接填 URL。 */
function AvatarInput({ value, onChange }: any) {
  const [uploading, setUploading] = useState(false)
  const doUpload = async (file: File) => {
    setUploading(true)
    try {
      const att: any = await chatApi.uploadAttachment(file)
      onChange?.(att.file_key || att.url)
      message.success('头像已上传')
    } catch (e) { message.error(errMsg(e)) } finally { setUploading(false) }
    return false
  }
  return (
    <Space direction="vertical" align="center" style={{ width: '100%' }}>
      <Avatar size={72} src={value || undefined} icon={<UserOutlined />} style={{ background: '#2563eb' }} />
      <Upload beforeUpload={doUpload} showUploadList={false} accept="image/*">
        <Button size="small" loading={uploading}>上传头像</Button>
      </Upload>
      <Input value={value || ''} placeholder="或直接填图片 URL" onChange={(e) => onChange?.(e.target.value)} style={{ width: 260 }} />
    </Space>
  )
}

/** 群管机器人：把群内机器人升级为「群管」——一键订阅日报/周报/月报、定时禁言等。 */
function GroupBotDrawer({ open, onClose, detail, onChanged }: any) {
  const bots: any[] = (detail?.members || []).filter((m: any) => m.is_agent)
  const [botId, setBotId] = useState<number | null>(null)
  const [tasks, setTasks] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const roomId = detail?.id
  const bot = bots.find((b) => b.agent_id === botId) || bots[0]

  const loadTasks = async () => {
    if (!roomId) return
    setLoading(true)
    try { const all = await scheduledApi.list(); setTasks(all.filter((t: any) => t.room_id === roomId)) }
    catch { setTasks([]) } finally { setLoading(false) }
  }
  useEffect(() => { if (open) { setBotId(bots[0]?.agent_id ?? null); loadTasks() } /* eslint-disable-next-line */ }, [open, roomId])

  // 预设：一键创建群报表/定时禁言任务
  const PRESETS = [
    { key: 'daily', label: '每天日报', cron: '0 18 * * *', prompt: '请生成本群今日聊天日报：统计今日消息量、活跃成员、讨论要点，并给出简明总结。' },
    { key: 'weekly', label: '每周周报', cron: '0 9 * * 1', prompt: '请生成本群本周聊天周报：汇总本周消息量、活跃成员排行、主要议题，并给出总结。' },
    { key: 'monthly', label: '每月月报', cron: '0 9 1 * *', prompt: '请生成本群本月聊天月报：汇总本月消息量、活跃成员、主要议题与趋势，并给出总结。' },
    { key: 'mute_night', label: '每晚禁言', cron: '0 22 * * *', prompt: '请开启本群全员禁言，共 600 分钟。' },
  ]
  const subscribe = async (preset: any) => {
    if (!bot) { message.warning('请先把一个机器人拉进群'); return }
    try {
      await scheduledApi.create({
        name: `${preset.label}·${detail.name}`,
        agent_id: bot.agent_id, target_type: 'prompt', prompt: preset.prompt,
        schedule_kind: 'cron', cron_expr: preset.cron,
        room_id: roomId, room_bot_agent_id: bot.agent_id, notify_on: 'never', enabled: true,
      })
      message.success(`已订阅「${preset.label}」`); loadTasks()
    } catch (e) { message.error(errMsg(e)) }
  }
  const removeTask = async (t: any) => {
    try { await scheduledApi.remove(t.id); message.success('已取消'); loadTasks() } catch (e) { message.error(errMsg(e)) }
  }
  const toggleTask = async (t: any) => {
    try { await scheduledApi.enable(t.id, !t.enabled); loadTasks() } catch (e) { message.error(errMsg(e)) }
  }

  // 编辑/新建定时任务
  const [editOpen, setEditOpen] = useState(false)
  const [editTask, setEditTask] = useState<any>(null)   // null=新建
  const [tf] = Form.useForm()
  const openNewTask = () => { setEditTask(null); tf.setFieldsValue({ name: `${detail?.name}·自定义任务`, cron_expr: '0 9 * * *', prompt: '', enabled: true }); setEditOpen(true) }
  const openEditTask = (t: any) => { setEditTask(t); tf.setFieldsValue({ name: t.name, cron_expr: t.cron_expr || '', prompt: t.prompt || '', enabled: !!t.enabled }); setEditOpen(true) }
  const submitTask = async () => {
    const v = await tf.validateFields().catch(() => null)
    if (!v) return
    if (!bot) { message.warning('请先选择机器人'); return }
    try {
      if (editTask) {
        await scheduledApi.update(editTask.id, {
          name: v.name, cron_expr: v.cron_expr, schedule_kind: 'cron',
          prompt: v.prompt, enabled: v.enabled,
        })
      } else {
        await scheduledApi.create({
          name: v.name, agent_id: bot.agent_id, target_type: 'prompt', prompt: v.prompt,
          schedule_kind: 'cron', cron_expr: v.cron_expr,
          room_id: roomId, room_bot_agent_id: bot.agent_id, notify_on: 'never', enabled: v.enabled,
        })
      }
      message.success(editTask ? '已保存' : '已创建'); setEditOpen(false); loadTasks()
    } catch (e) { message.error(errMsg(e)) }
  }

  return (
    <Drawer title="群管机器人" width={520} open={open} onClose={onClose}>
      <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
        把群内机器人设为<b>群管理员</b>后，它就能在群里被 <b>@</b> 时替你执行群管理：
        禁言/踢人/设管理员/改公告/置顶/搜消息/查统计，并可按计划自动推送<b>日报 / 周报 / 月报</b>、定时开关禁言。
      </Typography.Paragraph>
      {bots.length === 0 ? <Empty description="群里还没有机器人，请先在「机器人」里添加" /> : (
        <>
          <div style={{ marginBottom: 8, fontSize: 12, color: 'var(--color-text-2)' }}>选择群管机器人</div>
          <Space.Compact style={{ width: '100%', marginBottom: 12 }}>
            <Select style={{ flex: 1 }} value={bot?.agent_id} onChange={setBotId}
              options={bots.map((b) => ({ value: b.agent_id, label: `${b.name}（${b.role === 'owner' ? '群主' : b.role === 'admin' ? '管理员' : '普通成员'}）` }))} />
            <Button onClick={() => window.open(`/agents/${bot?.agent_id}`, '_blank')}>编辑机器人</Button>
          </Space.Compact>
          {bot && bot.role !== 'admin' && bot.role !== 'owner' && (
            <Alert type="warning" showIcon style={{ marginBottom: 12 }}
              message={<span>该机器人当前是普通成员，管理类操作（禁言/踢人/改公告等）会被拒绝。
                <Button size="small" type="primary" style={{ marginLeft: 8 }}
                  onClick={async () => { await chatRoomApi.setBotRole(roomId, bot.agent_id, 'admin'); message.success('已设为群管理员'); onChanged?.() }}>
                  设为本群管理员
                </Button></span>} />
          )}

          <Divider titlePlacement="left" style={{ margin: '8px 0' }}>一键订阅</Divider>
          <Space wrap>
            {PRESETS.map((p) => <Button key={p.key} size="small" onClick={() => subscribe(p)}>{p.label}</Button>)}
            <Button size="small" type="dashed" icon={<PlusOutlined />} onClick={openNewTask}>自定义任务</Button>
          </Space>

          <Divider titlePlacement="left" style={{ margin: '16px 0 8px' }}>本群定时任务</Divider>
          {loading ? <div style={{ textAlign: 'center', padding: 16 }}><Spin /></div> : (
            tasks.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无群定时任务" /> : (
              <List size="small" dataSource={tasks} renderItem={(t: any) => (
                <List.Item actions={[
                  <a key="e" onClick={() => openEditTask(t)}>编辑</a>,
                  <a key="t" onClick={() => toggleTask(t)}>{t.enabled ? '停用' : '启用'}</a>,
                  <a key="run" onClick={async () => { try { await scheduledApi.runNow(t.id); message.success('已触发，稍后推送本群') } catch (e) { message.error(errMsg(e)) } }}>立即运行</a>,
                  <Popconfirm key="d" title="取消该任务？" onConfirm={() => removeTask(t)}><a style={{ color: 'var(--color-error)' }}>取消</a></Popconfirm>,
                ]}>
                  <List.Item.Meta
                    title={<Space size={4}><span>{t.name}</span>{t.enabled ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>}</Space>}
                    description={<span style={{ fontSize: 12 }}>{t.cron_expr} · 下次：{t.next_run_at ? fmtTime(t.next_run_at) : '—'}{t.last_status ? ` · 上次：${t.last_status}` : ''}</span>} />
                </List.Item>
              )} />
            )
          )}

          <Modal title={editTask ? '编辑定时任务' : '新建定时任务'} open={editOpen} onOk={submitTask}
            onCancel={() => setEditOpen(false)} destroyOnClose width={520}>
            <Form form={tf} layout="vertical">
              <Form.Item name="name" label="任务名称" rules={[{ required: true }]}><Input /></Form.Item>
              <Form.Item name="cron_expr" label="执行计划（cron：分 时 日 月 周）" rules={[{ required: true }]}
                extra="例：0 18 * * * = 每天18:00；0 9 * * 1 = 每周一9:00；0 9 1 * * = 每月1号9:00">
                <Input placeholder="0 18 * * *" />
              </Form.Item>
              <Form.Item name="prompt" label="到点执行的提示词" rules={[{ required: true }]}
                extra="机器人会按此提示词执行，结果自动推送到本群。可写「生成本群今日聊天日报」等">
                <Input.TextArea rows={4} />
              </Form.Item>
              <Form.Item name="enabled" label="启用" valuePropName="checked"><Switch /></Form.Item>
            </Form>
          </Modal>
        </>
      )}
    </Drawer>
  )
}

function BotDrawer({ open, onClose, detail, agents, onChanged }: any) {
  const [pick, setPick] = useState<number | undefined>()
  const bots = detail?.bots || []
  return (
    <Drawer title="群机器人" width={420} open={open} onClose={onClose}>
      <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
        把智能体拉进群作为机器人。群里 <b>@机器人名</b> 才会响应，回复会自动 @提问者。
      </Typography.Paragraph>
      <Space.Compact style={{ width: '100%', marginBottom: 12 }}>
        <Select style={{ flex: 1 }} placeholder="选择智能体" value={pick} onChange={setPick} showSearch optionFilterProp="label"
          options={agents.map((a: any) => ({ value: a.id, label: a.name }))} />
        <Button type="primary" onClick={async () => {
          if (!pick) return
          try { await chatRoomApi.addBot(detail.id, pick); setPick(undefined); message.success('已添加'); onChanged() }
          catch (e) { message.error(errMsg(e)) }
        }}>添加</Button>
      </Space.Compact>
      <List size="small" dataSource={bots} locale={{ emptyText: '暂无机器人' }}
        renderItem={(b: any) => (
          <List.Item actions={[<Popconfirm key="d" title="移出该机器人？" onConfirm={async () => { await chatRoomApi.removeBot(detail.id, b.agent_id); onChanged() }}><a>移出</a></Popconfirm>]}>
            <List.Item.Meta avatar={<Avatar size="small" icon={<RobotOutlined />} style={{ background: '#7c3aed' }} />} title={b.name} />
          </List.Item>
        )} />
    </Drawer>
  )
}
