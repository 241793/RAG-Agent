import { useEffect, useRef, useState } from 'react'
import { Badge, Button, Empty, List, Popover, Space, Tag, Typography, message } from 'antd'
import { BellOutlined, CheckOutlined, DeleteOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import { notificationApi, type NotificationItem } from '../api'
import { errMsg } from '../api/http'

const LEVEL_COLOR: Record<string, string> = {
  info: 'blue', success: 'green', warning: 'orange', error: 'red',
}
const KIND_LABEL: Record<string, string> = {
  system: '系统', task: '定时任务', workflow: '工作流', chat: '消息',
}

/** Header 铃铛：未读徽标 + 弹出消息列表。 */
export default function NotificationBell() {
  const [open, setOpen] = useState(false)
  const [unread, setUnread] = useState(0)
  const [items, setItems] = useState<NotificationItem[]>([])
  const [loading, setLoading] = useState(false)
  const nav = useNavigate()
  const timer = useRef<any>(null)

  const refreshCount = async () => {
    try { setUnread((await notificationApi.unreadCount()).unread) } catch { /* 未登录/无权限忽略 */ }
  }

  const load = async () => {
    setLoading(true)
    try {
      const r = await notificationApi.list(1, 20)
      setItems(r.items)
      setUnread(r.unread)
    } catch (e) { message.error(errMsg(e)) }
    finally { setLoading(false) }
  }

  useEffect(() => {
    refreshCount()
    timer.current = setInterval(refreshCount, 30000)  // 30s 轮询未读数
    return () => { if (timer.current) clearInterval(timer.current) }
  }, [])

  const onOpenChange = (o: boolean) => {
    setOpen(o)
    if (o) load()
  }

  const onClickItem = async (n: NotificationItem) => {
    if (!n.read) {
      try { await notificationApi.markRead([n.id]); setItems((arr) => arr.map((x) => x.id === n.id ? { ...x, read: true } : x)); setUnread((u) => Math.max(0, u - 1)) } catch { /* ignore */ }
    }
    setOpen(false)
    if (n.link) nav(n.link)
  }

  const markAll = async () => {
    try { await notificationApi.markAllRead(); setItems((arr) => arr.map((x) => ({ ...x, read: true }))); setUnread(0) }
    catch (e) { message.error(errMsg(e)) }
  }

  const content = (
    <div style={{ width: 360 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <Typography.Text strong>消息通知</Typography.Text>
        <Button size="small" type="link" icon={<CheckOutlined />} onClick={markAll} disabled={!unread}>全部已读</Button>
      </div>
      {items.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无消息" style={{ padding: '20px 0' }} />
      ) : (
        <List
          size="small" loading={loading} dataSource={items}
          style={{ maxHeight: 420, overflowY: 'auto' }}
          renderItem={(n) => (
            <List.Item
              style={{ cursor: 'pointer', opacity: n.read ? 0.6 : 1, padding: '8px 4px' }}
              onClick={() => onClickItem(n)}
              actions={[
                <DeleteOutlined key="d" onClick={async (e) => {
                  e.stopPropagation()
                  try { await notificationApi.remove(n.id); setItems((arr) => arr.filter((x) => x.id !== n.id)); if (!n.read) setUnread((u) => Math.max(0, u - 1)) } catch { /* ignore */ }
                }} />,
              ]}
            >
              <div style={{ width: '100%' }}>
                <Space size={4} style={{ marginBottom: 2 }}>
                  <Tag color={LEVEL_COLOR[n.level]} style={{ marginRight: 0 }}>{KIND_LABEL[n.kind] || n.kind}</Tag>
                  <Typography.Text strong style={{ fontSize: 13 }}>{n.title}</Typography.Text>
                  {!n.read && <Badge status="processing" />}
                </Space>
                {n.body && (
                  <Typography.Paragraph style={{ fontSize: 12, color: '#8c8c8c', margin: '2px 0 0' }} ellipsis={{ rows: 2 }}>
                    {n.body}
                  </Typography.Paragraph>
                )}
                <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                  {n.created_at ? dayjs(n.created_at).format('MM-DD HH:mm') : ''}
                </Typography.Text>
              </div>
            </List.Item>
          )}
        />
      )}
    </div>
  )

  return (
    <Popover
      content={content} trigger="click" open={open} onOpenChange={onOpenChange}
      placement="bottomRight" arrow={false}
    >
      <Badge count={unread} size="small" offset={[-2, 2]}>
        <Button type="text" icon={<BellOutlined style={{ fontSize: 17 }} />} style={{ cursor: 'pointer' }} />
      </Badge>
    </Popover>
  )
}
