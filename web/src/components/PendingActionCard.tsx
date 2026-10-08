import { useState } from 'react'
import { Button, Card, Collapse, Space, Tag, Typography } from 'antd'
import { WarningOutlined, CheckOutlined, CloseOutlined } from '@ant-design/icons'
import type { PendingActionEvt } from '../api'

interface Props {
  action: PendingActionEvt
  onConfirm: (actionId: number, decision: 'approve' | 'reject') => void
  resolved?: boolean
}

/** AI 写操作待确认卡片（HITL）：管理员确认后才真正执行。 */
export default function PendingActionCard({ action, onConfirm, resolved }: Props) {
  const [busy, setBusy] = useState(false)

  const handle = (d: 'approve' | 'reject') => {
    setBusy(true)
    onConfirm(action.action_id, d)
  }

  return (
    <Card
      size="small"
      style={{ borderColor: '#faad14', background: '#fffbe6', maxWidth: 560 }}
      title={
        <Space>
          <WarningOutlined style={{ color: '#faad14' }} />
          <span>待确认操作</span>
          <Tag color="orange">{action.tool_name}</Tag>
        </Space>
      }
    >
      <Typography.Paragraph style={{ marginBottom: 8 }}>
        {action.summary || `AI 请求执行 ${action.tool_name}`}
      </Typography.Paragraph>
      {action.arguments && Object.keys(action.arguments).length > 0 && (
        <Collapse
          size="small"
          ghost
          items={[
            {
              key: 'args',
              label: '查看参数',
              children: (
                <pre style={{ margin: 0, fontSize: 12, whiteSpace: 'pre-wrap', maxHeight: 200, overflow: 'auto' }}>
                  {JSON.stringify(action.arguments, null, 2)}
                </pre>
              ),
            },
          ]}
        />
      )}
      <Space style={{ marginTop: 8 }}>
        <Button
          type="primary" icon={<CheckOutlined />} loading={busy} disabled={resolved}
          onClick={() => handle('approve')}
        >
          确认执行
        </Button>
        <Button icon={<CloseOutlined />} disabled={busy || resolved} onClick={() => handle('reject')}>
          拒绝
        </Button>
        {resolved && <Tag color="default">已处理</Tag>}
      </Space>
    </Card>
  )
}
