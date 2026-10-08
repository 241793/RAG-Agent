import { Drawer, List, Typography, Tag } from 'antd'
import { UserOutlined, RobotOutlined } from '@ant-design/icons'

export interface OutlineItem {
  index: number
  role: 'user' | 'assistant'
  text: string
}

interface Props {
  open: boolean
  onClose: () => void
  items: OutlineItem[]
  onJump: (index: number) => void
}

/** 对话消息目录：一键跳转到某条消息。 */
export default function MessageOutline({ open, onClose, items, onJump }: Props) {
  return (
    <Drawer title="对话目录（点击跳转）" placement="right" width={320} open={open} onClose={onClose} destroyOnClose>
      {items.length === 0 ? (
        <Typography.Text type="secondary">暂无消息</Typography.Text>
      ) : (
        <List
          size="small"
          dataSource={items}
          renderItem={(it) => (
            <List.Item
              style={{ cursor: 'pointer' }}
              onClick={() => { onJump(it.index); onClose() }}
            >
              <List.Item.Meta
                avatar={it.role === 'user' ? <UserOutlined /> : <RobotOutlined style={{ color: '#1677ff' }} />}
                title={
                  <Tag color={it.role === 'user' ? 'blue' : 'default'} style={{ marginRight: 6 }}>
                    {it.role === 'user' ? '我' : 'AI'}
                  </Tag>
                }
                description={
                  <Typography.Text ellipsis style={{ fontSize: 12 }}>
                    {it.text || '(空)'}
                  </Typography.Text>
                }
              />
            </List.Item>
          )}
        />
      )}
    </Drawer>
  )
}
