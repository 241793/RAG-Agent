import type { ReactNode } from 'react'
import { Result, Spin } from 'antd'
import { Navigate } from 'react-router-dom'
import { useAuth } from '../stores/auth'

/** 路由级权限守卫：权限未就绪不判定；无权限展示 403。 */
export default function RequirePermission({ perm, children }: { perm?: string; children: ReactNode }) {
  const { user, loading, hasPermission } = useAuth()
  // 仅在用户信息真正加载中时转圈（避免「已加载完但没有用户」时无限转圈）
  if (loading) {
    return (
      <div style={{ height: '60vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Spin size="large" />
      </div>
    )
  }
  // 加载完成但无用户（未登录/凭证失效）→ 跳登录页，而非停在空白转圈
  if (!user) {
    return <Navigate to="/login" replace />
  }
  if (perm && !hasPermission(perm)) {
    return <Result status="403" title="403" subTitle="没有访问该页面的权限，请联系管理员。" />
  }
  return <>{children}</>
}
