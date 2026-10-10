import { useState } from 'react'
import { Button, Card, Col, Descriptions, Form, Input, message, Modal, Row, Space, Tag, Typography } from 'antd'
import { EditOutlined, LockOutlined, UserOutlined } from '@ant-design/icons'
import { authApi } from '../../api'
import { errMsg } from '../../api/http'
import { useAuth } from '../../stores/auth'
import PageContainer from '../../components/PageContainer'

// 权限码 → 易读名（缺省回退原码）
const PERM_LABELS: Record<string, string> = {
  'kb:create': '创建知识库', 'kb:read': '查看知识库', 'kb:update': '编辑知识库',
  'kb:delete': '删除知识库', 'kb:member_manage': '管理知识库成员',
  'doc:upload': '上传文档', 'doc:read': '查看文档', 'doc:update': '编辑文档',
  'doc:delete': '删除文档', 'doc:download': '下载文档', 'doc:acl_manage': '管理文档权限',
  'chat:use': '使用问答', 'chat:read_all': '查看全部用户问答',
  'retrieval:query': '检索', 'model:read': '查看模型', 'model:manage': '管理模型',
  'agent:read': '查看智能体', 'agent:edit': '编辑智能体', 'agent:run': '运行智能体',
  'skill:read': '查看技能', 'skill:edit': '编辑技能',
  'tool:read': '查看工具', 'tool:manage': '管理工具',
  'schedule:read': '查看定时任务', 'schedule:manage': '管理定时任务',
  'channel:read': '查看外部渠道', 'channel:manage': '管理外部渠道',
  'workflow:read': '查看工作流', 'workflow:edit': '编辑工作流', 'workflow:run': '运行工作流',
  'user:read': '查看用户', 'user:manage': '管理用户',
  'role:read': '查看角色', 'role:manage': '管理角色',
  'dept:read': '查看部门', 'dept:manage': '管理部门',
  'group:read': '查看用户组', 'group:manage': '管理用户组',
  'audit:read': '查看审计日志', 'apikey:read': '查看密钥', 'apikey:manage': '管理密钥',
  'system:read': '查看系统日志', 'system:write': '管理系统日志',
  'sso:read': '查看 SSO', 'sso:manage': '管理 SSO', 'tenant:manage': '租户管理',
}

export default function AccountPage() {
  const user = useAuth((s) => s.user)
  const setUser = useAuth((s) => s.setUser)
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const [editProfile, setEditProfile] = useState(false)
  const [profileForm] = Form.useForm()
  const [profileSaving, setProfileSaving] = useState(false)

  const changePassword = async () => {
    const v = await form.validateFields()
    setSaving(true)
    try {
      await authApi.changePassword(v.old_password, v.new_password)
      message.success('密码已修改，请重新登录')
      form.resetFields()
      // 密码修改会吊销旧 token，主动登出并跳登录页
      setTimeout(() => { useAuth.getState().logout(); window.location.href = '/login' }, 1200)
    } catch (e) { message.error(errMsg(e)) } finally { setSaving(false) }
  }

  const openProfileEdit = () => {
    profileForm.setFieldsValue({ display_name: user?.display_name, email: user?.email })
    setEditProfile(true)
  }

  const saveProfile = async () => {
    const v = await profileForm.validateFields().catch(() => null)
    if (!v) return
    setProfileSaving(true)
    try {
      const u = await authApi.updateProfile(v)
      setUser(u)
      message.success('资料已保存')
      setEditProfile(false)
    } catch (e) { message.error(errMsg(e)) } finally { setProfileSaving(false) }
  }

  const refresh = async () => {
    try { setUser(await authApi.me()) } catch { /* ignore */ }
  }

  return (
    <PageContainer
      title="我的账号"
      subtitle="查看你的资料、角色与权限，可修改姓名/邮箱与登录密码"
      extra={<Button onClick={refresh}>刷新</Button>}
    >
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={14}>
          <Card title={<Space><UserOutlined />账号资料</Space>}
            extra={<Button size="small" icon={<EditOutlined />} onClick={openProfileEdit}>编辑资料</Button>}
            style={{ marginBottom: 16 }}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="用户名">{user?.username}</Descriptions.Item>
              <Descriptions.Item label="姓名">{user?.display_name || '-'}</Descriptions.Item>
              <Descriptions.Item label="邮箱">{user?.email || '-'}</Descriptions.Item>
              <Descriptions.Item label="部门">{user?.department_name || '-'}</Descriptions.Item>
              <Descriptions.Item label="账号类型">
                {user?.is_admin ? <Tag color="gold">管理员</Tag> : <Tag>普通用户</Tag>}
              </Descriptions.Item>
              <Descriptions.Item label="角色">
                <Space wrap>
                  {(user?.roles || []).length
                    ? user!.roles!.map((r) => <Tag key={r.id} color="blue">{r.name}</Tag>)
                    : '-'}
                </Space>
              </Descriptions.Item>
            </Descriptions>
            <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 8, marginBottom: 0 }}>
              用户名、部门与角色由管理员维护；姓名与邮箱可自行修改。
            </Typography.Paragraph>
          </Card>

          <Card title={<Space><LockOutlined />修改密码</Space>}>
            <Form form={form} layout="vertical" style={{ maxWidth: 420 }}>
              <Form.Item name="old_password" label="原密码" rules={[{ required: true, message: '请输入原密码' }]}>
                <Input.Password autoComplete="current-password" />
              </Form.Item>
              <Form.Item name="new_password" label="新密码"
                rules={[{ required: true, message: '请输入新密码' }, { min: 8, message: '至少 8 位' }]}
                extra="至少 8 位，需含字母、数字、符号中的至少两类（大小写不限）">
                <Input.Password autoComplete="new-password" />
              </Form.Item>
              <Form.Item name="confirm" label="确认新密码" dependencies={['new_password']}
                rules={[
                  { required: true, message: '请再次输入新密码' },
                  ({ getFieldValue }) => ({
                    validator(_, value) {
                      if (!value || getFieldValue('new_password') === value) return Promise.resolve()
                      return Promise.reject(new Error('两次输入不一致'))
                    },
                  }),
                ]}>
                <Input.Password autoComplete="new-password" />
              </Form.Item>
              <Button type="primary" loading={saving} onClick={changePassword}>保存</Button>
              <Typography.Text type="secondary" style={{ fontSize: 12, marginLeft: 12 }}>
                修改后需重新登录
              </Typography.Text>
            </Form>
          </Card>
        </Col>

        <Col xs={24} lg={10}>
          <Card title="我的权限">
            <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
              以下为你当前拥有的权限码，决定你能看到与操作的功能：
            </Typography.Paragraph>
            {user?.is_admin ? (
              <Tag color="gold">全部权限（管理员）</Tag>
            ) : (user?.permissions || []).length ? (
              <Space wrap>
                {(user!.permissions || []).map((p) => (
                  <Tag key={p} color={p === '*' ? 'gold' : 'default'}>{p === '*' ? '全部权限' : (PERM_LABELS[p] || p)}</Tag>
                ))}
              </Space>
            ) : <Typography.Text type="secondary">暂无权限，请联系管理员分配角色</Typography.Text>}
          </Card>
        </Col>
      </Row>

      <Modal title="编辑资料" open={editProfile} onOk={saveProfile} confirmLoading={profileSaving}
        onCancel={() => setEditProfile(false)} destroyOnClose>
        <Form form={profileForm} layout="vertical">
          <Form.Item name="display_name" label="姓名/昵称" rules={[{ required: true, message: '请输入姓名' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="email" label="邮箱" rules={[{ type: 'email', message: '邮箱格式不正确' }]}>
            <Input placeholder="可选" />
          </Form.Item>
        </Form>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          用户名、部门与角色由管理员维护，此处不可修改。
        </Typography.Text>
      </Modal>
    </PageContainer>
  )
}
