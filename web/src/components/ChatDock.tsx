import { useEffect, useRef, useState } from 'react'
import { Badge, Button, Drawer, Dropdown, message, Tooltip } from 'antd'
import { MessageOutlined, CloseOutlined, ExpandOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { chatRoomApi } from '../api'
import { ChatRoomCore } from '../pages/chat/ChatRoomPage'

const BALL_SIZE = 52
const POS_KEY = 'chat_dock_pos'

/** 把坐标夹取到视口内（留 4px 边距） */
function clampPos(x: number, y: number) {
  const maxX = Math.max(4, window.innerWidth - BALL_SIZE - 4)
  const maxY = Math.max(4, window.innerHeight - BALL_SIZE - 4)
  return { x: Math.min(Math.max(4, x), maxX), y: Math.min(Math.max(4, y), maxY) }
}

function loadPos(): { x: number; y: number } | null {
  try {
    const s = localStorage.getItem(POS_KEY)
    if (s) {
      const p = JSON.parse(s)
      if (typeof p?.x === 'number' && typeof p?.y === 'number') return p
    }
  } catch { /* ignore */ }
  return null
}

/**
 * 全局聊天悬浮球：默认显示为一个圆形按钮（有未读时显示数量徽标），
 * 点击展开全屏/大窗聊天；可再跳转独立页。
 *
 * 支持按住拖动：位置持久化到 localStorage，拖动结束后不会误触打开。
 * 未读数来源：轻量轮询拉房间未读总数，避免为角标单独开 WS。
 */
export default function ChatDock() {
  const [unread, setUnread] = useState(0)
  const [open, setOpen] = useState(false)
  const [hidden, setHidden] = useState(() => localStorage.getItem('chat_dock_hidden') === '1')
  // 悬浮球坐标（left/top）；为空时用右下角默认位
  const [pos, setPos] = useState<{ x: number; y: number } | null>(() => loadPos())
  const nav = useNavigate()
  const timer = useRef<any>(null)

  // 拖动状态
  const dragging = useRef(false)
  const moved = useRef(false)
  const startPt = useRef({ mx: 0, my: 0, px: 0, py: 0 })

  const defaultPos = () => ({
    x: Math.max(24, window.innerWidth - BALL_SIZE - 24),
    y: Math.max(24, window.innerHeight - BALL_SIZE - 24),
  })
  const cur = pos ?? defaultPos()

  const loadUnread = async () => {
    try {
      const rooms = await chatRoomApi.list()
      setUnread(rooms.reduce((s, r) => s + (r.unread || 0), 0))
    } catch { /* 未登录/无权限忽略 */ }
  }

  const markAllRead = async () => {
    try {
      const rooms = await chatRoomApi.list()
      await Promise.all(rooms.filter((r) => r.unread).map((r) => chatRoomApi.read(r.id)))
      setUnread(0); message.success('已全部标为已读')
    } catch { message.error('操作失败') }
  }

  useEffect(() => {
    loadUnread()
    const interval = open ? 5000 : 15000
    timer.current = setInterval(loadUnread, interval)
    return () => { if (timer.current) clearInterval(timer.current) }
  }, [open])

  // 视口变化时把悬浮球拉回可视范围
  useEffect(() => {
    const onResize = () => setPos((p) => (p ? clampPos(p.x, p.y) : p))
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const onDragStart = (e: React.MouseEvent) => {
    if (e.button !== 0) return // 仅左键拖动（右键留给上下文菜单）
    dragging.current = true
    moved.current = false
    startPt.current = { mx: e.clientX, my: e.clientY, px: cur.x, py: cur.y }
    const onMove = (ev: MouseEvent) => {
      if (!dragging.current) return
      const dx = ev.clientX - startPt.current.mx
      const dy = ev.clientY - startPt.current.my
      if (Math.abs(dx) > 4 || Math.abs(dy) > 4) moved.current = true
      setPos(clampPos(startPt.current.px + dx, startPt.current.py + dy))
    }
    const onUp = () => {
      dragging.current = false
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      if (moved.current) {
        setPos((p) => {
          if (p) localStorage.setItem(POS_KEY, JSON.stringify(p))
          return p
        })
      }
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  return (
    <>
      {/* 悬浮球 */}
      {!open && !hidden && (
        <Dropdown trigger={['contextMenu']} menu={{
          items: [
            { key: 'open', label: '打开聊天', icon: <MessageOutlined /> },
            { key: 'page', label: '在独立页打开', icon: <ExpandOutlined /> },
            { key: 'read', label: '全部标为已读' },
            { type: 'divider' },
            { key: 'reset', label: '重置悬浮球位置' },
            { key: 'hide', label: '隐藏聊天球（可在菜单重新开启）' },
          ],
          onClick: ({ key, domEvent }) => {
            domEvent.stopPropagation()
            if (key === 'open') { setOpen(true); loadUnread() }
            else if (key === 'page') { setOpen(false); nav('/chat-room') }
            else if (key === 'read') markAllRead()
            else if (key === 'reset') { setPos(null); localStorage.removeItem(POS_KEY); message.success('已重置到右下角') }
            else if (key === 'hide') { setHidden(true); localStorage.setItem('chat_dock_hidden', '1'); message.info('已隐藏，点击左下角小图标可重新显示') }
          },
        }}>
          <Tooltip title="按住可拖动 · 右键更多操作" placement="left">
            <div
              onMouseDown={onDragStart}
              onClick={() => { if (moved.current) return; setOpen(true); loadUnread() }}
              style={{
                position: 'fixed', left: cur.x, top: cur.y, zIndex: 1000,
                width: BALL_SIZE, height: BALL_SIZE, borderRadius: '50%',
                cursor: 'grab', touchAction: 'none', userSelect: 'none',
                background: 'linear-gradient(135deg,#2563eb,#3b82f6)', color: '#fff',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                boxShadow: '0 6px 20px rgba(37,99,235,0.4)',
              }}
            >
              <Badge count={unread} size="small" offset={[2, -2]}>
                <MessageOutlined style={{ fontSize: 22 }} />
              </Badge>
            </div>
          </Tooltip>
        </Dropdown>
      )}

      {/* 隐藏后：左下角小提示，可重新开启 */}
      {!open && hidden && (
        <Tooltip title="显示企业聊天球" placement="left">
          <div onClick={() => { setHidden(false); localStorage.removeItem('chat_dock_hidden') }}
            style={{
              position: 'fixed', right: 8, bottom: 8, zIndex: 1000, cursor: 'pointer',
              width: 22, height: 22, borderRadius: '50%', opacity: 0.35,
              background: '#8c8c8c', color: '#fff', display: 'flex', alignItems: 'center',
              justifyContent: 'center', fontSize: 12,
            }}><MessageOutlined /></div>
        </Tooltip>
      )}

      {/* 大窗聊天（覆盖式，占屏 80%） */}
      <Drawer
        placement="right" width="min(1100px, 92vw)" open={open}
        onClose={() => setOpen(false)}
        title="企业聊天"
        extra={
          <Button size="small" icon={<ExpandOutlined />}
            onClick={() => { setOpen(false); nav('/chat-room') }}>
            独立页打开
          </Button>
        }
        styles={{ body: { padding: 12 } }}
        closeIcon={<CloseOutlined />}
      >
        {open && <ChatRoomCore height="calc(100vh - 120px)" compact />}
      </Drawer>
    </>
  )
}
