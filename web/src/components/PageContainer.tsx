import type { ReactNode } from 'react'

interface Props {
  title?: ReactNode
  subtitle?: ReactNode
  extra?: ReactNode
  children: ReactNode
  /** 是否给内容加统一卡片外框 */
  card?: boolean
}

/**
 * 统一页面容器：标题 + 副标题 + 右上操作区 + 内容。
 * 全站列表/表单页复用它，保证间距与标题级别一致。
 */
export default function PageContainer({ title, subtitle, extra, children, card = false }: Props) {
  return (
    <div className="page-container">
      {(title || extra) && (
        <div
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'space-between',
            marginBottom: 16,
            gap: 12,
            flexWrap: 'wrap',
          }}
        >
          <div>
            {title && <h2 className="page-title">{title}</h2>}
            {subtitle && <div className="page-subtitle">{subtitle}</div>}
          </div>
          {extra && <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>{extra}</div>}
        </div>
      )}
      {card ? <div className="app-card" style={{ padding: 20 }}>{children}</div> : children}
    </div>
  )
}
