import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Layout, Menu, Avatar, Dropdown, Spin, Breadcrumb, Drawer, Grid, Button } from 'antd'
import {
  DashboardOutlined, DatabaseOutlined, MessageOutlined, SettingOutlined, LogoutOutlined,
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

const { Header, Sider, Content } = Layout

interface NavItem {
  key: string
  icon: ReactNode
  label: string
  perm?: string
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
  const screens = Grid.useBreakpoint()
  const isMobile = !screens.lg
  const nav = useNavigate()
  const loc = useLocation()

  useEffect(() => {
    if (!user && loading) fetchMe()
  }, [])

  const groups: (NavItem | NavGroup)[] = [
    { key: '/dashboard', icon: <DashboardOutlined />, label: '工作台' },
    { key: '/chat', icon: <MessageOutlined />, label: '智能问答' },
    { key: '/kb', icon: <DatabaseOutlined />, label: '知识库' },
    { key: '/service-tickets', icon: <CustomerServiceOutlined />, label: '客服工单', perm: 'service:read' },
    { key: '/records', icon: <FormOutlined />, label: '智能录单', perm: 'record:read' },
    {
      key: 'g-agent',
      icon: <RobotOutlined />,
      label: '智能体',
      children: [
        { key: '/agents', icon: <RobotOutlined />, label: '智能体', perm: 'agent:read' },
        { key: '/skills', icon: <AppstoreOutlined />, label: '技能', perm: 'skill:read' },
        { key: '/admin/tools', icon: <ToolOutlined />, label: '工具', perm: 'tool:read' },
        { key: '/admin/mcp', icon: <ApiOutlined />, label: 'MCP 服务器', perm: 'mcp:read' },
        { key: '/scheduled', icon: <ClockCircleOutlined />, label: '定时任务', perm: 'schedule:read' },
        { key: '/channels', icon: <ApiOutlined />, label: '外部渠道', perm: 'channel:read' },
        { key: '/admin/channel-users', icon: <UserSwitchOutlined />, label: '渠道身份绑定', perm: 'channel:read' },
      ],
    },
    { key: '/retrieval', icon: <ExperimentOutlined />, label: '检索调试' },
    { key: '/eval', icon: <FileSearchOutlined />, label: '问答评测', perm: 'eval:read' },
    {
      key: 'g-org',
      icon: <TeamOutlined />,
      label: '组织权限',
      children: [
        { key: '/admin/users', icon: <UserOutlined />, label: '用户', perm: 'user:read' },
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
  const menuItems: any[] = []
  for (const g of groups) {
    if ('children' in g) {
      const kids = g.children.filter(canSee)
      if (kids.length) {
        menuItems.push({
          key: g.key, icon: g.icon, label: g.label,
          children: kids.map((k) => ({ key: k.key, icon: k.icon, label: k.label })),
        })
      }
    } else if (canSee(g as NavItem)) {
      menuItems.push({ key: g.key, icon: g.icon, label: g.label })
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
