import { Button, Empty, Typography } from 'antd'
import type { ReactNode } from 'react'
import type { CSSProperties } from 'react'

interface Props {
  description?: ReactNode
  /** 主标题（可选，用于更正式的空状态引导） */
  title?: ReactNode
  actionText?: string
  onAction?: () => void
  /** 自定义行动按钮或节点（优先于 actionText） */
  action?: ReactNode
  icon?: ReactNode
  /** 紧凑模式：减少上下留白，适合卡片内嵌 */
  compact?: boolean
  style?: CSSProperties
}

/** 统一空状态（商业级：支持主标题 + 引导动作） */
export default function EmptyState({
  description,
  title,
  actionText,
  onAction,
  action,
  icon,
  compact = false,
  style,
}: Props) {
  return (
    <div
      style={{
        padding: compact ? '24px 0' : '48px 0',
        textAlign: 'center',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        ...style,
      }}
    >
      <Empty
        image={icon || Empty.PRESENTED_IMAGE_SIMPLE}
        description={
          <>
            {title && (
              <div style={{
                fontSize: 14, fontWeight: 500, color: 'var(--color-text-body)', marginBottom: 4,
              }}>
                {title}
              </div>
            )}
            {description && (
              <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                {description}
              </Typography.Text>
            )}
          </>
        }
      >
        {action || (actionText && (
          <Button type="primary" onClick={onAction}>
            {actionText}
          </Button>
        ))}
      </Empty>
    </div>
  )
}
