import { useEffect, useState } from 'react'
import { Alert, Button, Card, Divider, Form, Input, message, Modal, Space, Typography } from 'antd'
import { UserOutlined, LockOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { authApi, ssoApi, type SsoProvider } from '../../api'
import { errMsg } from '../../api/http'
import { useAuth } from '../../stores/auth'

export default function LoginPage() {
  const [loading, setLoading] = useState(false)
  const [providers, setProviders] = useState<SsoProvider[]>([])
  const [regOpen, setRegOpen] = useState(false)
  const [regLoading, setRegLoading] = useState(false)
  const [regForm] = Form.useForm()
  const nav = useNavigate()
  const setUser = useAuth((s) => s.setUser)

  const finishLogin = async (access?: string, refresh?: string) => {
    if (access) localStorage.setItem('access_token', access)
    if (refresh) localStorage.setItem('refresh_token', refresh)
    const me = await authApi.me()
    setUser(me)
    message.success('登录成功')
    // 登录后进工作台（有概览/快捷入口/引导），而非直接落到可能为空的列表页
    nav('/dashboard')
  }

  // 处理 SSO 回调（token 在 URL fragment）
  useEffect(() => {
    const hash = window.location.hash
    if (hash.includes('access_token=')) {
      const params = new URLSearchParams(hash.slice(1))
      const access = params.get('access_token') || undefined
      const refresh = params.get('refresh_token') || undefined
      if (access) {
        window.history.replaceState(null, '', window.location.pathname)
        finishLogin(access, refresh).catch(() => message.error('SSO 登录失败'))
      }
    }
    // 拉取已启用的 SSO 提供者
    ssoApi.providers().then(setProviders).catch(() => {})
  }, [])

  const onFinish = async (v: { username: string; password: string }) => {
    setLoading(true)
    try {
      const data = await authApi.login(v.username, v.password)
      await finishLogin(data.access_token, data.refresh_token)
    } catch (e) {
      message.error(errMsg(e))
    } finally {
      setLoading(false)
    }
  }

  const doRegister = async () => {
    const v = await regForm.validateFields().catch(() => null)
    if (!v) return
    setRegLoading(true)
    try {
      const r = await authApi.register(v)
      setRegOpen(false); regForm.resetFields()
      Modal.success({
        title: '注册成功',
        content: r.pending
          ? '账号已创建，需管理员审核通过后才能登录。请等待管理员处理。'
          : '账号已创建，现在可以直接登录。',
      })
    } catch (e) { message.error(errMsg(e)) } finally { setRegLoading(false) }
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'linear-gradient(135deg,#001529,#003a70)' }}>
      <Card style={{ width: 380 }} title="企业 RAG 知识库" bordered={false}>
        {/* 不预填任何账号密码：避免生产环境保留默认管理员凭据 */}
        <Form onFinish={onFinish} layout="vertical">
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名" size="large" autoComplete="username" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" size="large" autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block size="large" loading={loading}>
            登录
          </Button>
        </Form>

        <div style={{ textAlign: 'center', marginTop: 12 }}>
          <Typography.Link onClick={() => setRegOpen(true)}>还没有账号？注册</Typography.Link>
        </div>

        {providers.length > 0 && (
          <>
            <Divider plain style={{ color: '#999', fontSize: 12 }}>或使用单点登录</Divider>
            <Space direction="vertical" style={{ width: '100%' }}>
              {providers.map((p) => (
                <Button key={p.provider} block size="large"
                  onClick={() => { window.location.href = ssoApi.loginUrl(p.provider) }}>
                  {p.name}
                </Button>
              ))}
            </Space>
          </>
        )}
      </Card>

      <Modal title="注册账号" open={regOpen} onOk={doRegister} confirmLoading={regLoading}
        onCancel={() => setRegOpen(false)} destroyOnClose okText="提交注册">
        <Alert type="info" showIcon style={{ marginBottom: 12 }}
          message="注册后需管理员审核通过才能登录" />
        <Form form={regForm} layout="vertical">
          <Form.Item name="username" label="用户名"
            rules={[{ required: true, message: '请输入用户名' }, { min: 2, max: 64, message: '2-64 个字符' },
              { pattern: /^[A-Za-z0-9_.@-]+$/, message: '仅允许字母、数字及 _ . @ -' }]}>
            <Input placeholder="登录用用户名" autoComplete="off" />
          </Form.Item>
          <Form.Item name="display_name" label="姓名/昵称">
            <Input placeholder="可选，展示用" />
          </Form.Item>
          <Form.Item name="email" label="邮箱"
            rules={[{ type: 'email', message: '邮箱格式不正确' }]}>
            <Input placeholder="可选" autoComplete="off" />
          </Form.Item>
          <Form.Item name="password" label="密码"
            rules={[{ required: true, message: '请输入密码' }, { min: 8, message: '至少 8 位' }]}
            extra="至少 8 位，需含大写字母、小写字母、数字、符号中的至少三类">
            <Input.Password placeholder="设置密码" autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="reason" label="申请理由">
            <Input.TextArea rows={2} placeholder="可选，供管理员审核参考，如：所属部门 / 用途" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
