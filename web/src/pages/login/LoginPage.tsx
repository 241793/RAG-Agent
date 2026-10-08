import { useEffect, useState } from 'react'
import { Button, Card, Divider, Form, Input, message, Space } from 'antd'
import { UserOutlined, LockOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { authApi, ssoApi, type SsoProvider } from '../../api'
import { errMsg } from '../../api/http'
import { useAuth } from '../../stores/auth'

export default function LoginPage() {
  const [loading, setLoading] = useState(false)
  const [providers, setProviders] = useState<SsoProvider[]>([])
  const nav = useNavigate()
  const setUser = useAuth((s) => s.setUser)

  const finishLogin = async (access?: string, refresh?: string) => {
    if (access) localStorage.setItem('access_token', access)
    if (refresh) localStorage.setItem('refresh_token', refresh)
    const me = await authApi.me()
    setUser(me)
    message.success('登录成功')
    nav('/kb')
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

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'linear-gradient(135deg,#001529,#003a70)' }}>
      <Card style={{ width: 380 }} title="企业 RAG 知识库" bordered={false}>
        <Form onFinish={onFinish} layout="vertical" initialValues={{ username: 'admin', password: 'admin123' }}>
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名" size="large" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" size="large" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block size="large" loading={loading}>
            登录
          </Button>
        </Form>

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
    </div>
  )
}
