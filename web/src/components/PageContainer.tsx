import type { CSSProperties, ReactNode } from 'react'

interface Props {
  title?: ReactNode
  subtitle?: ReactNode
  /** 标题旁的徽标或状态标签 */
  tags?: ReactNode
  extra?: ReactNode
  children: ReactNode
  /** 是否给内容加统一卡片外框 */
  card?: boolean
  /** 卡片额外样式 */
  cardStyle?: CSSProperties
  /** 紧凑沉浸模式（无外层边距包裹） */
  compact?: boolean
  style?: CSSProperties
  className?: string
}

/**
 * 商业级统一页面容器：标题 + 标签 + 副标题 + 右侧操作区 + 内容区。
 * 保持全站各页面的间距、标题字级、操作栏一致性。
 */
export default function PageContainer({
  title,
  subtitle,
  tags,
  extra,
  children,
  card = false,
  cardStyle,
  compact = false,
  style,
  className,
}: Props) {
  return (
    <div
      className={`page-container ${className || ''}`}
      style={{
        maxWidth: compact ? '100%' : '1440px',
        margin: '0 auto',
        paddingBottom: compact ? 0 : 24,
        ...style,
      }}
    >
      {(title || extra || tags) && (
        <div
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'space-between',
            marginBottom: 20,
            gap: 16,
            flexWrap: 'wrap',
          }}
        >
          <div style={{ flex: '1 1 auto', minWidth: 240 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              {title && <h2 className="page-title">{title}</h2>}
              {tags}
            </div>
            {subtitle && <div className="page-subtitle">{subtitle}</div>}
          </div>
          {extra && (
            <div
              style={{
                display: 'flex',
                gap: 10,
                alignItems: 'center',
                flexWrap: 'wrap',
                flexShrink: 0,
              }}
            >
              {extra}
            </div>
          )}
        </div>
      )}
      {card ? (
        <div
          className="app-card"
          style={{
            padding: 24,
            ...cardStyle,
          }}
        >
          {children}
        </div>
      ) : (
        children
      )}
    </div>
  )
}
