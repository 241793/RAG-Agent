import { Navigate, Route, Routes } from 'react-router-dom'
import type { ReactNode } from 'react'
import MainLayout from './layouts/MainLayout'
import LoginPage from './pages/login/LoginPage'
import KBListPage from './pages/kb/KBListPage'
import KBDetailPage from './pages/kb/KBDetailPage'
import RetrievalDebugPage from './pages/kb/RetrievalDebugPage'
import EvalPage from './pages/kb/EvalPage'
import ChatPage from './pages/chat/ChatPage'
import ModelPage from './pages/admin/ModelPage'
import RolePage from './pages/admin/RolePage'
import UserPage from './pages/admin/UserPage'
import DeptPage from './pages/admin/DeptPage'
import GroupPage from './pages/admin/GroupPage'
import AuditPage from './pages/admin/AuditPage'
import LogPage from './pages/admin/LogPage'
import ApiKeyPage from './pages/admin/ApiKeyPage'
import SsoPage from './pages/admin/SsoPage'
import UsagePage from './pages/admin/UsagePage'
import SecurityPage from './pages/admin/SecurityPage'
import FilePage from './pages/admin/FilePage'
import ToolPage from './pages/admin/ToolPage'
import McpPage from './pages/admin/McpPage'
import SettingsPage from './pages/admin/SettingsPage'
import SystemOpsPage from './pages/admin/SystemOpsPage'
import NotifyChannelPage from './pages/admin/NotifyChannelPage'
import EventSubscriptionPage from './pages/admin/EventSubscriptionPage'
import AgentListPage from './pages/agents/AgentListPage'
import AgentChatPage from './pages/agents/AgentChatPage'
import AgentEditPage from './pages/agents/AgentEditPage'
import WorkflowEditPage from './pages/agents/WorkflowEditPage'
import SkillPage from './pages/skills/SkillPage'
import DashboardPage from './pages/dashboard/DashboardPage'
import ScheduledTasksPage from './pages/scheduled/ScheduledTasksPage'
import ChannelListPage from './pages/channels/ChannelListPage'
import ChannelUsersPage from './pages/admin/ChannelUsersPage'
import AccountPage from './pages/account/AccountPage'
import EmailSourcePage from './pages/admin/EmailSourcePage'
import ServiceTicketPage from './pages/service/ServiceTicketPage'
import RecordPage from './pages/record/RecordPage'
import RequirePermission from './components/RequirePermission'
import { ROUTE_PERMS } from './router/routeMeta'

function RequireAuth({ children }: { children: ReactNode }) {
  const token = localStorage.getItem('access_token')
  return token ? children : <Navigate to="/login" replace />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <MainLayout />
          </RequireAuth>
        }
      >
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<RequirePermission perm={ROUTE_PERMS['/dashboard']}><DashboardPage /></RequirePermission>} />
        <Route path="account" element={<AccountPage />} />
        <Route path="kb" element={<RequirePermission perm={ROUTE_PERMS['/kb']}><KBListPage /></RequirePermission>} />
        <Route path="kb/:id" element={<RequirePermission perm={ROUTE_PERMS['/kb']}><KBDetailPage /></RequirePermission>} />
        <Route path="retrieval" element={<RequirePermission perm={ROUTE_PERMS['/retrieval']}><RetrievalDebugPage /></RequirePermission>} />
        <Route path="eval" element={<RequirePermission perm={ROUTE_PERMS['/eval']}><EvalPage /></RequirePermission>} />
        <Route path="chat" element={<RequirePermission perm={ROUTE_PERMS['/chat']}><ChatPage /></RequirePermission>} />
        <Route path="agents" element={<RequirePermission perm={ROUTE_PERMS['/agents']}><AgentListPage /></RequirePermission>} />
        <Route path="agents/:id/chat" element={<RequirePermission perm={ROUTE_PERMS['/agents']}><AgentChatPage /></RequirePermission>} />
        <Route path="agents/:id/edit" element={<RequirePermission perm="agent:edit"><AgentEditPage /></RequirePermission>} />
        <Route path="agents/:id/workflow" element={<RequirePermission perm="workflow:edit"><WorkflowEditPage /></RequirePermission>} />
        <Route path="skills" element={<RequirePermission perm={ROUTE_PERMS['/skills']}><SkillPage /></RequirePermission>} />
        <Route path="scheduled" element={<RequirePermission perm={ROUTE_PERMS['/scheduled']}><ScheduledTasksPage /></RequirePermission>} />
        <Route path="channels" element={<RequirePermission perm={ROUTE_PERMS['/channels']}><ChannelListPage /></RequirePermission>} />
        <Route path="admin/channel-users" element={<RequirePermission perm={ROUTE_PERMS['/admin/channel-users']}><ChannelUsersPage /></RequirePermission>} />
        <Route path="admin/tools" element={<RequirePermission perm={ROUTE_PERMS['/admin/tools']}><ToolPage /></RequirePermission>} />
        <Route path="admin/mcp" element={<RequirePermission perm={ROUTE_PERMS['/admin/mcp']}><McpPage /></RequirePermission>} />
        <Route path="admin/settings" element={<RequirePermission perm={ROUTE_PERMS['/admin/settings']}><SettingsPage /></RequirePermission>} />
        <Route path="admin/system-ops" element={<RequirePermission perm={ROUTE_PERMS['/admin/system-ops']}><SystemOpsPage /></RequirePermission>} />
        <Route path="admin/notify-channels" element={<RequirePermission perm={ROUTE_PERMS['/admin/notify-channels']}><NotifyChannelPage /></RequirePermission>} />
        <Route path="admin/event-subscriptions" element={<RequirePermission perm={ROUTE_PERMS['/admin/event-subscriptions']}><EventSubscriptionPage /></RequirePermission>} />
        <Route path="admin/email-sources" element={<RequirePermission perm={ROUTE_PERMS['/admin/email-sources']}><EmailSourcePage /></RequirePermission>} />
        <Route path="service-tickets" element={<RequirePermission perm={ROUTE_PERMS['/service-tickets']}><ServiceTicketPage /></RequirePermission>} />
        <Route path="records" element={<RequirePermission perm={ROUTE_PERMS['/records']}><RecordPage /></RequirePermission>} />
        <Route path="admin/models" element={<RequirePermission perm={ROUTE_PERMS['/admin/models']}><ModelPage /></RequirePermission>} />
        <Route path="admin/roles" element={<RequirePermission perm={ROUTE_PERMS['/admin/roles']}><RolePage /></RequirePermission>} />
        <Route path="admin/users" element={<RequirePermission perm={ROUTE_PERMS['/admin/users']}><UserPage /></RequirePermission>} />
        <Route path="admin/depts" element={<RequirePermission perm={ROUTE_PERMS['/admin/depts']}><DeptPage /></RequirePermission>} />
        <Route path="admin/groups" element={<RequirePermission perm={ROUTE_PERMS['/admin/groups']}><GroupPage /></RequirePermission>} />
        <Route path="admin/audit" element={<RequirePermission perm={ROUTE_PERMS['/admin/audit']}><AuditPage /></RequirePermission>} />
        <Route path="admin/logs" element={<RequirePermission perm={ROUTE_PERMS['/admin/logs']}><LogPage /></RequirePermission>} />
        <Route path="admin/api-keys" element={<RequirePermission perm={ROUTE_PERMS['/admin/api-keys']}><ApiKeyPage /></RequirePermission>} />
        <Route path="admin/sso" element={<RequirePermission perm={ROUTE_PERMS['/admin/sso']}><SsoPage /></RequirePermission>} />
        <Route path="admin/usage" element={<RequirePermission perm={ROUTE_PERMS['/admin/usage']}><UsagePage /></RequirePermission>} />
        <Route path="admin/security" element={<RequirePermission perm={ROUTE_PERMS['/admin/security']}><SecurityPage /></RequirePermission>} />
        <Route path="admin/files" element={<RequirePermission perm={ROUTE_PERMS['/admin/files']}><FilePage /></RequirePermission>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
