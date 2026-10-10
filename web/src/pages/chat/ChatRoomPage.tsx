import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Avatar, Button, Card, Drawer, Dropdown, Empty, Input, List, message, Modal, Popconfirm, Select, Space, Switch, Tag, Tooltip, Typography, Upload,
} from 'antd'
import {
  SendOutlined, PlusOutlined, TeamOutlined, RobotOutlined, UserOutlined, PaperClipOutlined,
  PushpinOutlined, DeleteOutlined, MoreOutlined, ReloadOutlined, RollbackOutlined, SoundOutlined,
} from '@ant-design/icons'
import { chatRoomApi, rbacApi, agentApi, chatApi, type ChatRoomBrief, type ChatMsgItem } from '../../api'
import { errMsg } from '../../api/http'
import AttachmentView from '../../components/AttachmentView'
import PageContainer from '../../components/PageContainer'

const ROLE_LABEL: Record<string, string> = { owner: '群主', admin: '管理员', member: '成员' }

function fmtTime(ms: number) {
  const d = new Date(ms)
  const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  const hm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  return sameDay ? hm : `${d.getMonth() + 1}-${d.getDate()} ${hm}`
}

export default function ChatRoomPage() {
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
  const [mentionIds, setMentionIds] = useState<number[]>([])
  const [replyTo, setReplyTo] = useState<ChatMsgItem | null>(null)
  const [autoScroll, setAutoScroll] = useState(true)
  const [pendingCount, setPendingCount] = useState(0)

  const listRef = useRef<HTMLDivElement>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const activeIdRef = useRef<number | null>(null)
  const atBottomRef = useRef(true)
  const reconnectRef = useRef<any>(null)

  activeIdRef.current = activeId

  // 拉当前用户 / 可选成员 / 智能体
  useEffect(() => {
    fetchMe()
    rbacApi.users(1, 500).then((r) => setUsers(r.items.map((u) => ({ id: u.id, label: u.display_name || u.username })))).catch(() => {})
    agentApi.list().then((a) => setAgents(a.filter((x) => x.type === 'agent'))).catch(() => {})
  }, [])

  const fetchMe = async () => {
    try { const r = await import('../../api').then((m) => m.authApi.me()); setMe(r) } catch { /* ignore */ }
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
      setDetail((cur: any) => cur ? { ...cur, announcement: d.announcement } : cur)
    }
  }

  const doUpload = async (file: File) => {
    try {
      const att = await chatApi.uploadAttachment(file)
      setPendingAtts((a) => [...a, att])
    } catch (e) { message.error(errMsg(e)) }
    return false
  }

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

  const handleMention = (uid: number, name: string) => {
    setMentionIds((ids) => ids.includes(uid) ? ids : [...ids, uid])
    setInput((t) => (t.endsWith(' ') || !t ? t : t + ' ') + `@${name} `)
  }

  const mentionable = useMemo(() => [
    ...(detail?.members || []).filter((m: any) => m.user_id !== me?.id).map((m: any) => ({ uid: m.user_id, name: m.name })),
    ...(detail?.bots || []).map((b: any) => ({ uid: b.agent_id, name: b.name, agent: true })),
  ], [detail, me])

  return (
    <PageContainer title="企业聊天" subtitle="全员大群 / 群聊 / 私聊 · 支持 @机器人、附件、撤回与置顶">
      <div style={{ display: 'flex', gap: 12, height: 'calc(100vh - 190px)', minHeight: 480 }}>
        {/* 左：房间列表 */}
        <Card size="small" style={{ width: 260, flex: '0 0 auto', display: 'flex', flexDirection: 'column' }}
          styles={{ body: { padding: 8, display: 'flex', flexDirection: 'column', height: '100%' } }}
          title={<Space><TeamOutlined />会话</Space>}
          extra={<Tooltip title="新建群聊"><Button size="small" type="text" icon={<PlusOutlined />} onClick={() => setNewOpen(true)} /></Tooltip>}>
          <div style={{ flex: 1, overflowY: 'auto' }}>
            <List
              size="small" dataSource={rooms}
              locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="加载中…" /> }}
              renderItem={(r) => (
                <List.Item
                  style={{ cursor: 'pointer', padding: '6px 8px', borderRadius: 6, background: r.id === activeId ? 'var(--color-primary-soft)' : undefined }}
                  onClick={() => openRoom(r.id)}
                >
                  <div style={{ width: '100%', minWidth: 0 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 6 }}>
                      <Typography.Text ellipsis strong={!!r.unread} style={{ fontSize: 13 }}>
                        {r.kind === 'direct' ? <><UserOutlined /> </> : r.is_default ? '📢 ' : ''}{r.name}
                      </Typography.Text>
                      {!!r.unread && <Tag color="red" style={{ margin: 0 }}>{r.unread}</Tag>}
                    </div>
                    <Typography.Text type="secondary" ellipsis style={{ fontSize: 12 }}>{r.last_preview || '暂无消息'}</Typography.Text>
                  </div>
                </List.Item>
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
              {detail?.name || '选择会话'}
              {detail && <Tag color={ROLE_LABEL[myRole] === '群主' ? 'gold' : myRole === 'admin' ? 'blue' : 'default'}>{me?.is_admin && !myRole ? '管理员' : (ROLE_LABEL[myRole] || '成员')}</Tag>}
              {detail?.kind === 'direct' && <Tag>私聊</Tag>}
            </Space>
          }
          extra={
            <Space>
              <Tooltip title="自动滚动到最新"><span style={{ fontSize: 12, color: 'var(--color-text-3)' }}>自动跟随 <Switch size="small" checked={autoScroll} onChange={setAutoScroll} /></span></Tooltip>
              <Button size="small" icon={<ReloadOutlined />} onClick={() => activeId && openRoom(activeId)} />
            </Space>
          }>
          {!detail ? <Empty style={{ marginTop: 80 }} description="从左侧选择一个会话" /> : (
            <>
              {/* 群公告 */}
              {detail.announcement && (
                <div style={{ margin: '0 12px 8px', padding: '6px 10px', background: 'var(--color-warn-soft)', borderRadius: 6, fontSize: 13 }}>
                  <PushpinOutlined style={{ color: 'var(--color-warn)', marginRight: 6 }} />{detail.announcement}
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
                  onRevoke={() => revoke(m)} onPin={() => pin(m, !m.pinned)} onReply={() => setReplyTo(m)} onMention={handleMention} />)}
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
                  <Dropdown menu={{
                    items: [
                      { key: 'mention', label: '提到某人', type: 'group', children: mentionable.map((x) => ({ key: `m-${x.uid}`, label: `${x.agent ? '🤖 ' : ''}${x.name}` })) },
                    ],
                    onClick: ({ key }) => {
                      if (key.startsWith('m-')) { const x = mentionable.find((y) => `m-${y.uid}` === key); if (x) handleMention(x.uid, x.name) }
                    },
                  }} trigger={['click']}>
                    <Button icon={<Typography.Text>@</Typography.Text>} />
                  </Dropdown>
                  <Upload beforeUpload={doUpload} showUploadList={false} multiple>
                    <Tooltip title="发送附件（图片/视频/音频/文件）"><Button icon={<PaperClipOutlined />} /></Tooltip>
                  </Upload>
                  <Input.TextArea autoSize={{ minRows: 1, maxRows: 4 }} value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onPressEnter={(e) => { if (!e.shiftKey) { e.preventDefault(); send() } }}
                    placeholder="输入消息，Enter 发送，Shift+Enter 换行；@ 可提及成员或机器人" />
                  <Button type="primary" icon={<SendOutlined />} loading={sending} onClick={send}>发送</Button>
                  {detail.kind !== 'direct' && canAdmin && (
                    <Dropdown menu={{
                      items: [
                        { key: 'members', label: '成员与管理', icon: <UserOutlined /> },
                        { key: 'bots', label: '机器人', icon: <RobotOutlined /> },
                        { key: 'announcement', label: '设置群公告', icon: <PushpinOutlined /> },
                      ],
                      onClick: ({ key }) => {
                        if (key === 'members') setMemberOpen(true)
                        else if (key === 'bots') setBotOpen(true)
                        else if (key === 'announcement') {
                          let v = detail.announcement || ''
                          Modal.confirm({
                            title: '设置群公告', icon: null,
                            content: <Input.TextArea defaultValue={v} rows={3} onChange={(e) => { v = e.target.value }} />,
                            onOk: async () => { await chatRoomApi.setAnnouncement(detail.id, v); setDetail({ ...detail, announcement: v }) },
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
        onChanged={() => activeId && openRoom(activeId)} />

      {/* 机器人 */}
      <BotDrawer open={botOpen} onClose={() => setBotOpen(false)} detail={detail} agents={agents}
        onChanged={() => activeId && openRoom(activeId)} />
    </PageContainer>
  )
}

/** 单条消息气泡 */
function Bubble({ m, me, canAdmin, canPin, onRevoke, onPin, onReply, onMention }: any) {
  const mine = m.sender_type === 'user' && m.sender_id === me?.id
  const isBot = m.sender_type === 'agent'
  const canRevoke = mine || canAdmin
  if (m.revoked) {
    return <div style={{ textAlign: 'center', fontSize: 12, color: 'var(--color-text-3)', margin: '6px 0' }}>
      「{m.sender_name}」撤回了一条消息
    </div>
  }
  return (
    <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexDirection: mine ? 'row-reverse' : 'row' }}>
      <Avatar size={34} icon={isBot ? <RobotOutlined /> : <UserOutlined />}
        style={{ background: isBot ? '#7c3aed' : (mine ? '#2563eb' : '#8c8c8c'), flexShrink: 0 }} />
      <div style={{ maxWidth: '68%', minWidth: 0 }}>
        <div style={{ fontSize: 12, color: 'var(--color-text-2)', textAlign: mine ? 'right' : 'left', marginBottom: 2 }}>
          {isBot && <Tag color="purple" style={{ marginRight: 4 }}>机器人</Tag>}
          {m.sender_name} <span style={{ color: 'var(--color-text-3)' }}>{fmtTime(m.created_at)}</span>
          {m.pinned && <PushpinOutlined style={{ color: 'var(--color-warn)', marginLeft: 4 }} />}
        </div>
        <div style={{
          background: mine ? 'var(--color-primary-soft)' : 'var(--color-bg-subtle)',
          border: '1px solid var(--color-border)', borderRadius: 8, padding: '6px 10px',
          whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: 14,
        }}>
          {m.content}
          {m.attachments?.map((a: any, i: number) => <AttachmentView key={i} att={a} />)}
        </div>
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

function MemberDrawer({ open, onClose, detail, users, me, canAdmin, isOwner, onChanged }: any) {
  const [addOpen, setAddOpen] = useState(false)
  const [pick, setPick] = useState<number[]>([])
  const members = detail?.members || []
  const add = async () => {
    try { await chatRoomApi.addMembers(detail.id, pick); message.success('已添加'); setPick([]); setAddOpen(false); onChanged() }
    catch (e) { message.error(errMsg(e)) }
  }
  return (
    <Drawer title={`成员管理${detail ? `（${members.length}）` : ''}`} width={460} open={open} onClose={onClose}
      extra={canAdmin && <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => setAddOpen(true)}>添加成员</Button>}>
      <List size="small" dataSource={members} renderItem={(m: any) => (
        <List.Item actions={canAdmin ? [
          isOwner && m.role !== 'owner' && (
            <a key="r" onClick={async () => { await chatRoomApi.setRole(detail.id, m.user_id, m.role === 'admin' ? 'member' : 'admin'); onChanged() }}>
              {m.role === 'admin' ? '取消管理员' : '设为管理员'}
            </a>
          ),
          m.role !== 'owner' && <a key="m" onClick={async () => {
            const mins = window.prompt('禁言分钟数（0=解除）', '10'); if (mins == null) return
            await chatRoomApi.mute(detail.id, m.user_id, Number(mins) || 0); message.success('已操作')
          }}>禁言</a>,
          m.role !== 'owner' && <Popconfirm key="d" title="移出该成员？" onConfirm={async () => { await chatRoomApi.removeMember(detail.id, m.user_id); onChanged() }}><a>移出</a></Popconfirm>,
        ].filter(Boolean) : []}>
          <List.Item.Meta avatar={<Avatar size="small" icon={<UserOutlined />} />}
            title={<Space>{m.name}{m.user_id === me?.id && <Tag>我</Tag>}{m.role !== 'member' && <Tag color={m.role === 'owner' ? 'gold' : 'blue'}>{ROLE_LABEL[m.role]}</Tag>}</Space>} />
        </List.Item>
      )} />
      <Modal title="添加成员" open={addOpen} onOk={add} onCancel={() => setAddOpen(false)} destroyOnClose>
        <Select mode="multiple" style={{ width: '100%' }} placeholder="选择用户" value={pick} onChange={setPick}
          showSearch optionFilterProp="label"
          options={users.filter((u: any) => !members.some((m: any) => m.user_id === u.id)).map((u: any) => ({ value: u.id, label: u.label }))} />
      </Modal>
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
