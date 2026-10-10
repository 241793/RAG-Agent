import { useEffect, useRef, useState } from 'react'
import { Badge, Button, Drawer, Tooltip } from 'antd'
import { MessageOutlined, CloseOutlined, ExpandOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { chatRoomApi } from '../api'
import { ChatRoomCore } from '../pages/chat/ChatRoomPage'

/**
 * 全局聊天悬浮球：默认显示为一个圆形按钮（有未读时显示数量徽标），
 * 点击展开全屏/大窗聊天；可再跳转独立页。
 *
 * 未读数来源：WS 推送的 message 事件（与聊天核心共用同一条 WS 会重复连接，
 * 这里用一个轻量轮询拉房间未读总数，避免为角标单独开 WS）。
 */
export default function ChatDock() {
  const [unread, setUnread] = useState(0)
  const [open, setOpen] = useState(false)
  const nav = useNavigate()
  const timer = useRef<any>(null)

  const loadUnread = async () => {
    try {
      const rooms = await chatRoomApi.list()
      setUnread(rooms.reduce((s, r) => s + (r.unread || 0), 0))
    } catch { /* 未登录/无权限忽略 */ }
  }

  useEffect(() => {
    loadUnread()
    // 打开时更频繁，关闭时低频即可
    const interval = open ? 5000 : 15000
    timer.current = setInterval(loadUnread, interval)
    return () => { if (timer.current) clearInterval(timer.current) }
  }, [open])

  return (
    <>
      {/* 悬浮球 */}
      {!open && (
        <Tooltip title="企业聊天" placement="left">
          <div
            onClick={() => { setOpen(true); loadUnread() }}
            style={{
              position: 'fixed', right: 24, bottom: 24, zIndex: 1000,
              width: 52, height: 52, borderRadius: '50%', cursor: 'pointer',
              background: 'linear-gradient(135deg,#2563eb,#3b82f6)', color: '#fff',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              boxShadow: '0 6px 20px rgba(37,99,235,0.4)', transition: 'transform .15s',
            }}
            onMouseEnter={(e) => (e.currentTarget.style.transform = 'scale(1.06)')}
            onMouseLeave={(e) => (e.currentTarget.style.transform = 'scale(1)')}
          >
            <Badge count={unread} size="small" offset={[2, -2]}>
              <MessageOutlined style={{ fontSize: 22 }} />
            </Badge>
          </div>
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
