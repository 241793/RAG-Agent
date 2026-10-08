import type { ReactNode } from 'react'
import { Result, Spin } from 'antd'
import { useAuth } from '../stores/auth'

/** 路由级权限守卫：权限未就绪不判定；无权限展示 403。 */
export default function RequirePermission({ perm, children }: { perm?: string; children: ReactNode }) {
  const { user, loading, hasPermission } = useAuth()
  if (loading || !user) {
    return (
      <div style={{ height: '60vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Spin size="large" />
      </div>
    )
  }
  if (perm && !hasPermission(perm)) {
    return <Result status="403" title="403" subTitle="没有访问该页面的权限，请联系管理员。" />
  }
  return <>{children}</>
}
