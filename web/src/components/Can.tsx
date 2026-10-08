import type { ReactNode } from 'react'
import { useAuth } from '../stores/auth'

/**
 * 按钮/区块级权限门：无权限则不渲染（默认隐藏）。
 * 与路由级 RequirePermission 互补——路由决定"进不进得来"，Can 决定"看不看得见按钮"。
 */
export default function Can({
  perm,
  fallback = null,
  children,
}: {
  perm?: string
  fallback?: ReactNode
  children: ReactNode
}) {
  const hasPermission = useAuth((s) => s.hasPermission)
  if (perm && !hasPermission(perm)) return <>{fallback}</>
  return <>{children}</>
}
