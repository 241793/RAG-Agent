import { useEffect, useRef, useState } from 'react'
import { Badge, Button, Drawer, Dropdown, message, Tooltip } from 'antd'
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
  const [hidden, setHidden] = useState(() => localStorage.getItem('chat_dock_hidden') === '1')
  const nav = useNavigate()
  const timer = useRef<any>(null)

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
    } catch (e) { message.error('操作失败') }
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
      {!open && !hidden && (
        <Dropdown trigger={['contextMenu']} menu={{
          items: [
            { key: 'open', label: '打开聊天', icon: <MessageOutlined /> },
            { key: 'page', label: '在独立页打开', icon: <ExpandOutlined /> },
            { key: 'read', label: '全部标为已读' },
            { type: 'divider' },
            { key: 'hide', label: '隐藏聊天球（可在菜单重新开启）' },
          ],
          onClick: ({ key, domEvent }) => {
            domEvent.stopPropagation()
            if (key === 'open') { setOpen(true); loadUnread() }
            else if (key === 'page') { setOpen(false); nav('/chat-room') }
            else if (key === 'read') markAllRead()
            else if (key === 'hide') { setHidden(true); localStorage.setItem('chat_dock_hidden', '1'); message.info('已隐藏，点击左下角小图标可重新显示') }
          },
        }}>
          <Tooltip title="企业聊天（右键更多操作）" placement="left">
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
