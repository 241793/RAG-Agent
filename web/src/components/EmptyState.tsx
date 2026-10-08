import { Button, Empty, Typography } from 'antd'
import type { ReactNode } from 'react'

interface Props {
  description?: ReactNode
  actionText?: string
  onAction?: () => void
  icon?: ReactNode
}

/** 统一空状态 */
export default function EmptyState({ description, actionText, onAction, icon }: Props) {
  return (
    <div style={{ padding: '48px 0', textAlign: 'center' }}>
      <Empty
        image={icon || Empty.PRESENTED_IMAGE_SIMPLE}
        description={<Typography.Text type="secondary">{description || '暂无数据'}</Typography.Text>}
      >
        {actionText && (
          <Button type="primary" onClick={onAction}>
            {actionText}
          </Button>
        )}
      </Empty>
    </div>
  )
}
