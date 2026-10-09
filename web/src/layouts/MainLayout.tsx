import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Layout, Menu, Avatar, Badge, Dropdown, Spin, Breadcrumb, Drawer, Grid, Button, Tooltip } from 'antd'
import {
  DashboardOutlined, DatabaseOutlined, CommentOutlined, SettingOutlined, LogoutOutlined,
  UserOutlined, ExperimentOutlined, RobotOutlined, AppstoreOutlined,
  TeamOutlined, ClusterOutlined, UsergroupAddOutlined, FileSearchOutlined,
  KeyOutlined, SafetyOutlined, BarChartOutlined, SafetyCertificateOutlined,
  FolderOutlined, ClockCircleOutlined, ToolOutlined, MenuOutlined, ApiOutlined, BellOutlined, MailOutlined,
  CustomerServiceOutlined, FormOutlined, UserSwitchOutlined,
} from '@ant-design/icons'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../stores/auth'
import { ROUTE_PERMS } from '../router/routeMeta'
import NotificationBell from '../components/NotificationBell'
import { rbacApi } from '../api'

const { Header, Sider, Content } = Layout

interface NavItem {
  key: string
  icon: ReactNode
  label: string
  perm?: string
  /** 悬停提示：向新用户解释该项用途，避免与相邻项混淆 */
  tip?: string
  /** 需要显示角标的项（如待审核用户数）标识 */
  badgeKey?: string
}
interface NavGroup {
  key: string
  icon: ReactNode
  label: string
  children: NavItem[]
}

export default function MainLayout() {
  const { user, loading, fetchMe, logout } = useAuth()
  const [collapsed, setCollapsed] = useState(false)
  const [openKeys, setOpenKeys] = useState<string[]>([])
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const [pendingUsers, setPendingUsers] = useState(0)
  const screens = Grid.useBreakpoint()
  const isMobile = !screens.lg
  const nav = useNavigate()
  const loc = useLocation()

  useEffect(() => {
    if (!user && loading) fetchMe()
  }, [])

  // 待审核用户数角标：仅对可查看用户的账号拉取（30s 轮询，失败静默）
  useEffect(() => {
    if (!user || !(user.is_admin || (user.permissions || []).includes('user:read'))) return
    const load = () => rbacApi.pendingUsers().then((r) => setPendingUsers(r.length)).catch(() => {})
    load()
    const t = setInterval(load, 30000)
    return () => clearInterval(t)
  }, [user])

  const groups: (NavItem | NavGroup)[] = [
    { key: '/dashboard', icon: <DashboardOutlined />, label: '工作台', tip: '概览、趋势与快捷入口' },
    { key: '/chat', icon: <CommentOutlined />, label: '智能问答', tip: '直接向知识库提问，支持引用溯源、多模型、图片/文件' },
    { key: '/kb', icon: <DatabaseOutlined />, label: '知识库', tip: '上传/录入资料，构建可检索的知识' },
    { key: '/service-tickets', icon: <CustomerServiceOutlined />, label: '客服工单', perm: 'service:read', tip: '处理外部渠道进来的客户会话与工单' },
    { key: '/records', icon: <FormOutlined />, label: '智能录单', perm: 'record:read', tip: '用 AI 从文本中抽取结构化成表单数据' },
    {
      key: 'g-agent',
      icon: <RobotOutlined />,
      label: '智能体',
      children: [
        { key: '/agents', icon: <RobotOutlined />, label: '智能体', perm: 'agent:read', tip: '可自定义角色/工具/知识库范围的 AI 助手（比问答更可编排）' },
        { key: '/skills', icon: <AppstoreOutlined />, label: '技能', perm: 'skill:read' },
        { key: '/admin/tools', icon: <ToolOutlined />, label: '工具', perm: 'tool:read' },
        { key: '/admin/mcp', icon: <ApiOutlined />, label: 'MCP 服务器', perm: 'mcp:read' },
        { key: '/scheduled', icon: <ClockCircleOutlined />, label: '定时任务', perm: 'schedule:read' },
        { key: '/channels', icon: <ApiOutlined />, label: '外部渠道', perm: 'channel:read' },
        { key: '/admin/channel-users', icon: <UserSwitchOutlined />, label: '渠道身份绑定', perm: 'channel:read' },
      ],
    },
    { key: '/todo', icon: <FormOutlined />, label: '待办日程', tip: '待办事项与日程提醒' },
    { key: '/approvals', icon: <SafetyCertificateOutlined />, label: '审批中心', perm: 'workflow:read', tip: 'AI 发起写操作时的待人工确认项' },
    {
      key: 'g-dev',
      icon: <ExperimentOutlined />,
      label: '高级 / 开发者',
      children: [
        { key: '/retrieval', icon: <ExperimentOutlined />, label: '检索调试', tip: '查看检索命中的分块与分数，用于排查答得不准' },
        { key: '/eval', icon: <FileSearchOutlined />, label: '问答评测', perm: 'eval:read', tip: '用测试问题集批量评估回答质量' },
      ],
    },
    {
      key: 'g-org',
      icon: <TeamOutlined />,
      label: '组织权限',
      children: [
        { key: '/admin/users', icon: <UserOutlined />, label: '用户', perm: 'user:read', badgeKey: 'pendingUsers' },
        { key: '/admin/roles', icon: <TeamOutlined />, label: '角色', perm: 'role:read' },
        { key: '/admin/depts', icon: <ClusterOutlined />, label: '部门', perm: 'dept:read' },
        { key: '/admin/groups', icon: <UsergroupAddOutlined />, label: '用户组', perm: 'group:read' },
      ],
    },
    {
      key: 'g-system',
      icon: <SettingOutlined />,
      label: '系统设置',
      children: [
        { key: '/admin/settings', icon: <SettingOutlined />, label: '系统设置', perm: 'system:manage' },
        { key: '/admin/system-ops', icon: <DatabaseOutlined />, label: '数据库与运维', perm: 'system:manage' },
        { key: '/admin/notify-channels', icon: <BellOutlined />, label: '通知渠道', perm: 'notify:read' },
        { key: '/admin/event-subscriptions', icon: <BellOutlined />, label: '事件订阅', perm: 'notify:read' },
        { key: '/admin/email-sources', icon: <MailOutlined />, label: '邮件入库', perm: 'kb:read' },
        { key: '/admin/models', icon: <SettingOutlined />, label: '模型管理' },
        { key: '/admin/api-keys', icon: <KeyOutlined />, label: 'API 密钥', perm: 'apikey:read' },
        { key: '/admin/sso', icon: <SafetyOutlined />, label: '单点登录', perm: 'sso:read' },
      ],
    },
    {
      key: 'g-govern',
      icon: <FolderOutlined />,
      label: '安全与审计',
      children: [
        { key: '/admin/security', icon: <SafetyCertificateOutlined />, label: '内容安全', perm: 'audit:read' },
        { key: '/admin/audit', icon: <FileSearchOutlined />, label: '审计日志', perm: 'audit:read' },
        { key: '/admin/logs', icon: <FileSearchOutlined />, label: '系统日志', perm: 'system:read' },
        { key: '/admin/usage', icon: <BarChartOutlined />, label: '用量统计', perm: 'model:read' },
        { key: '/admin/files', icon: <FolderOutlined />, label: '文件管理', perm: 'file:manage' },
      ],
    },
  ]

  const perms = user?.permissions || []
  const isAdmin = user?.is_admin
  // 权限单一事实源：路由映射表（缺省回退到菜单项自带 perm）
  const permOf = (item: NavItem) => ROUTE_PERMS[item.key] || item.perm
  const canSee = (item: NavItem) => {
    const p = permOf(item)
    return !p || isAdmin || perms.includes(p) || perms.includes('*')
  }

  // 生成 antd 菜单项（过滤无权限项；组内为空则隐藏）
  const wrapLabel = (item: NavItem) => {
    let node: ReactNode = item.label
    if (item.tip) node = <Tooltip title={item.tip} placement="right"><span>{node}</span></Tooltip>
    if (item.badgeKey === 'pendingUsers' && pendingUsers > 0) {
      node = <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
        {node}<Badge count={pendingUsers} size="small" />
      </span>
    }
    return node
  }
  const menuItems: any[] = []
  for (const g of groups) {
    if ('children' in g) {
      const kids = g.children.filter(canSee)
      if (kids.length) {
        menuItems.push({
          key: g.key, icon: g.icon, label: g.label,
          children: kids.map((k) => ({ key: k.key, icon: k.icon, label: wrapLabel(k) })),
        })
      }
    } else if (canSee(g as NavItem)) {
      menuItems.push({ key: g.key, icon: g.icon, label: wrapLabel(g as NavItem) })
    }
  }

  const allLeaves = groups.flatMap((g) => ('children' in g ? g.children : [g])) as NavItem[]
  const selected = allLeaves
    .filter((i) => loc.pathname === i.key || loc.pathname.startsWith(i.key + '/'))
    .sort((a, b) => b.key.length - a.key.length)[0]?.key || '/dashboard'
  const parentKey = (groups.find((g) => 'children' in g && g.children.some((c) => c.key === selected)) as NavGroup | undefined)?.key

  // 默认全部收起；仅当选中项位于某分组内时，自动展开该分组（不影响手动开合）
  useEffect(() => {
    if (parentKey) setOpenKeys((ks) => (ks.includes(parentKey) ? ks : [...ks, parentKey]))
  }, [parentKey])

  if (loading && !user) {
    return (
      <div style={{ height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Spin size="large" />
      </div>
    )
  }

  // 面包屑：父组 > 当前项
  const crumbItems: { title: string }[] = [{ title: '首页' }]
  if (parentKey) {
    const grp = groups.find((g) => g.key === parentKey) as NavGroup
    crumbItems.push({ title: grp.label })
  }
  const current = allLeaves.find((i) => i.key === selected)
  if (current && current.key !== '/dashboard') crumbItems.push({ title: current.label })

  const menuNode = (
    <Menu
      mode="inline"
      selectedKeys={[selected]}
      openKeys={collapsed && !isMobile ? undefined : openKeys}
      onOpenChange={(keys) => setOpenKeys(keys as string[])}
      items={menuItems}
      style={{ borderRight: 0, paddingTop: 8 }}
      onClick={(e) => { if (e.key.startsWith('/')) { nav(e.key); setMobileNavOpen(false) } }}
    />
  )

  return (
    <Layout style={{ height: '100vh' }}>
      <Header
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          background: '#fff', paddingInline: isMobile ? 12 : 20, borderBottom: '1px solid #eef0f3', flexShrink: 0,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: isMobile ? 8 : 16, minWidth: 0 }}>
          {isMobile && (
            <Button type="text" icon={<MenuOutlined />} onClick={() => setMobileNavOpen(true)} />
          )}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }} onClick={() => nav('/dashboard')}>
            <div style={{
              width: 30, height: 30, borderRadius: 8, background: 'linear-gradient(135deg,#2563eb,#3b82f6)',
              color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontWeight: 700, fontSize: 15, flexShrink: 0,
            }}>R</div>
            {!isMobile && <span style={{ fontSize: 17, fontWeight: 600, color: '#1f2937' }}>企业 RAG 知识库</span>}
          </div>
          {!isMobile && <Breadcrumb items={crumbItems} style={{ marginLeft: 8 }} />}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: isMobile ? 6 : 12 }}>
          <NotificationBell />
          <Dropdown
            menu={{
              items: [
                { key: 'account', icon: <UserOutlined />, label: '我的账号' },
                { type: 'divider' },
                { key: 'logout', icon: <LogoutOutlined />, label: '退出登录' },
              ],
              onClick: ({ key }) => {
                if (key === 'logout') { logout(); nav('/login') }
                else if (key === 'account') nav('/account')
              },
            }}
          >
            <div style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8, padding: '4px 8px', borderRadius: 8 }}>
              <Avatar size="small" style={{ background: '#2563eb' }} icon={<UserOutlined />} />
              {!isMobile && <span style={{ color: '#1f2937' }}>{user?.display_name || user?.username}</span>}
            </div>
          </Dropdown>
        </div>
      </Header>
      <Layout style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
        {isMobile ? (
          <Drawer
            placement="left" open={mobileNavOpen} onClose={() => setMobileNavOpen(false)}
            width={240} styles={{ body: { padding: 0 } }} title="导航菜单"
          >
            {menuNode}
          </Drawer>
        ) : (
          <Sider
            width={216} theme="light" collapsible collapsed={collapsed}
            onCollapse={setCollapsed}
            style={{ borderRight: '1px solid #eef0f3', overflowY: 'auto', height: '100%' }}
          >
            {menuNode}
          </Sider>
        )}
        <Content style={{ padding: 24, background: '#f5f7fa', overflow: 'auto', minHeight: 0 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
