import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Layout, Menu, Avatar, Badge, Dropdown, Spin, Breadcrumb, Drawer, Grid, Button, Tooltip, Tag } from 'antd'
import {
  DashboardOutlined, DatabaseOutlined, CommentOutlined, SettingOutlined, LogoutOutlined,
  UserOutlined, ExperimentOutlined, RobotOutlined, AppstoreOutlined,
  TeamOutlined, ClusterOutlined, UsergroupAddOutlined, FileSearchOutlined,
  KeyOutlined, SafetyOutlined, BarChartOutlined, SafetyCertificateOutlined,
  FolderOutlined, ClockCircleOutlined, ToolOutlined, MenuOutlined, ApiOutlined, BellOutlined, MailOutlined,
  CustomerServiceOutlined, FormOutlined, UserSwitchOutlined, MenuFoldOutlined, MenuUnfoldOutlined,
  SearchOutlined,
} from '@ant-design/icons'
import { Outlet, useLocation, useNavigate, Link } from 'react-router-dom'
import { useAuth } from '../stores/auth'
import { ROUTE_PERMS } from '../router/routeMeta'
import NotificationBell from '../components/NotificationBell'
import ChatDock from '../components/ChatDock'
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
    { key: '/chat-room', icon: <TeamOutlined />, label: '企业聊天', tip: '与同事聊天：全员大群/群聊/私聊，支持 @机器人、附件、撤回置顶' },
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
      <div style={{
        height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: 'var(--color-bg-canvas)', flexDirection: 'column', gap: 16,
      }}>
        <div style={{
          width: 40, height: 40, borderRadius: 12, background: 'linear-gradient(135deg,#2563eb,#3b82f6)',
          color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontWeight: 700, fontSize: 18, boxShadow: '0 4px 12px -2px rgba(37,99,235,0.4)',
        }}>R</div>
        <Spin size="default" />
      </div>
    )
  }

  // 面包屑：父组 > 当前项（可点击跳转，对齐商业 SaaS 导航预期）
  const crumbItems: any[] = [{ title: <Link to="/dashboard">工作台</Link> }]
  if (parentKey) {
    const grp = groups.find((g) => g.key === parentKey) as NavGroup
    crumbItems.push({ title: <span style={{ color: 'var(--color-text-secondary)' }}>{grp.label}</span> })
  }
  const current = allLeaves.find((i) => i.key === selected)
  if (current && current.key !== '/dashboard') {
    crumbItems.push({
      title: <span style={{ color: 'var(--color-text-secondary)' }}>{current.label}</span>,
    })
  }

  const menuNode = (
    <Menu
      mode="inline"
      selectedKeys={[selected]}
      openKeys={collapsed && !isMobile ? undefined : openKeys}
      onOpenChange={(keys) => setOpenKeys(keys as string[])}
      items={menuItems}
      style={{
        borderRight: 0, paddingTop: 8, paddingInline: 4,
        background: 'transparent', fontSize: 13.5,
      }}
      onClick={(e) => { if (e.key.startsWith('/')) { nav(e.key); setMobileNavOpen(false) } }}
    />
  )

  return (
    <Layout style={{ height: '100vh' }}>
      <Header
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          background: 'var(--color-bg-surface)', paddingInline: isMobile ? 12 : 24,
          borderBottom: '1px solid var(--color-border)', flexShrink: 0,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: isMobile ? 8 : 16, minWidth: 0 }}>
          {isMobile && (
            <Button type="text" icon={<MenuOutlined />} onClick={() => setMobileNavOpen(true)} />
          )}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, cursor: 'pointer' }} onClick={() => nav('/dashboard')}>
            <div style={{
              width: 32, height: 32, borderRadius: 10, background: 'linear-gradient(135deg,#2563eb,#3b82f6)',
              color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontWeight: 700, fontSize: 16, flexShrink: 0, letterSpacing: '-0.03em',
              boxShadow: '0 2px 6px -1px rgba(37,99,235,0.35)',
            }}>R</div>
            {!isMobile && <span style={{ fontSize: 16, fontWeight: 600, color: 'var(--color-text-title)', letterSpacing: '-0.015em' }}>企业 RAG 知识库</span>}
          </div>
          {!isMobile && <Breadcrumb items={crumbItems} style={{ marginLeft: 16, fontSize: 13 }} />}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: isMobile ? 4 : 12 }}>
          {/* 全局快捷搜索入口（预留交互位，对齐 Linear / Vercel 的 ⌘K 检索体验） */}
          {!isMobile && (
            <div
              onClick={() => nav('/chat')}
              style={{
                display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer',
                padding: '5px 12px', borderRadius: 9999,
                border: '1px solid var(--color-border)', background: 'var(--color-bg-subtle)',
                color: 'var(--color-text-muted)', fontSize: 13,
                transition: 'border-color 0.2s, background 0.2s',
              }}
            >
              <SearchOutlined />
              <span>搜索知识或发起提问</span>
              <Tag
                color="default"
                style={{ margin: 0, fontSize: 11, borderRadius: 4, padding: '0 4px', lineHeight: '18px' }}
              >
                ⌘K
              </Tag>
            </div>
          )}
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
            <div style={{
              cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8,
              padding: '4px 8px', borderRadius: 9999, border: '1px solid transparent',
            }}>
              <Avatar size={28} style={{ background: 'linear-gradient(135deg,#2563eb,#3b82f6)' }}>
                {(user?.display_name || user?.username || 'U').slice(0, 1).toUpperCase()}
              </Avatar>
              {!isMobile && (
                <span style={{ color: 'var(--color-text-title)', fontWeight: 500, fontSize: 13 }}>
                  {user?.display_name || user?.username}
                </span>
              )}
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
            width={232} theme="light" collapsible collapsed={collapsed}
            onCollapse={setCollapsed}
            trigger={null}
            style={{
              borderRight: '1px solid var(--color-border)',
              overflowY: 'auto', height: '100%',
              background: 'var(--color-bg-surface)',
            }}
          >
            <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
              <div style={{ flex: 1, overflowY: 'auto' }}>{menuNode}</div>
              {/* 底部精致折叠控制条 */}
              <div style={{
                flexShrink: 0, borderTop: '1px solid var(--color-border-subtle)', padding: '6px 0',
              }}>
                <Button
                  type="text" block
                  icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
                  onClick={() => setCollapsed(!collapsed)}
                  style={{
                    color: 'var(--color-text-secondary)', height: 36,
                    fontSize: 13, fontWeight: 500,
                  }}
                >
                  {!collapsed && <span style={{ marginLeft: 2 }}>收起侧边栏</span>}
                </Button>
              </div>
            </div>
          </Sider>
        )}
        <Content style={{ padding: 24, background: 'var(--color-bg-canvas)', overflow: 'auto', minHeight: 0 }}>
          <Outlet />
        </Content>
      </Layout>
      {/* 全局聊天悬浮球：在「企业聊天」页本身不显示，避免与页面内容重复 */}
      {loc.pathname !== '/chat-room' && (isAdmin || perms.includes('chat:use') || perms.includes('*')) && <ChatDock />}
    </Layout>
  )
}
