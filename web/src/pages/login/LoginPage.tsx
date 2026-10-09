import { useEffect, useState } from 'react'
import { Alert, Button, Card, Checkbox, Divider, Form, Input, message, Modal, Select, Space, Typography } from 'antd'
import { UserOutlined, LockOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { authApi, ssoApi, type SsoProvider } from '../../api'
import { errMsg } from '../../api/http'
import { useAuth } from '../../stores/auth'

// 记住密码：仅存用户名 + 一个混淆后的密码串（非明文，避免直接可读）
const RK_USER = 'rag_remember_user'
const RK_PASS = 'rag_remember_pass'
const RK_FLAG = 'rag_remember_flag'
function encodePass(p: string): string {
  try { return btoa(unescape(encodeURIComponent(p))) } catch { return '' }
}
function decodePass(s: string): string {
  try { return decodeURIComponent(escape(atob(s))) } catch { return '' }
}

export default function LoginPage() {
  const [loading, setLoading] = useState(false)
  const [providers, setProviders] = useState<SsoProvider[]>([])
  const [regOpen, setRegOpen] = useState(false)
  const [regLoading, setRegLoading] = useState(false)
  const [regForm] = Form.useForm()
  const [depts, setDepts] = useState<{ id: number; name: string; depth: number }[]>([])
  const [remember, setRemember] = useState(false)
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
      // 记住密码：勾选则保存，取消则清除
      if (remember) {
        localStorage.setItem(RK_FLAG, '1')
        localStorage.setItem(RK_USER, v.username)
        localStorage.setItem(RK_PASS, encodePass(v.password))
      } else {
        localStorage.removeItem(RK_FLAG)
        localStorage.removeItem(RK_USER)
        localStorage.removeItem(RK_PASS)
      }
      await finishLogin(data.access_token, data.refresh_token)
    } catch (e) {
      message.error(errMsg(e))
    } finally {
      setLoading(false)
    }
  }

  const openRegister = () => {
    setRegOpen(true)
    authApi.registerDepartments().then(setDepts).catch(() => setDepts([]))
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
        <Form onFinish={onFinish} layout="vertical"
          initialValues={{
            username: localStorage.getItem(RK_USER) || '',
            password: localStorage.getItem(RK_FLAG) ? decodePass(localStorage.getItem(RK_PASS) || '') : '',
          }}>
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名" size="large" autoComplete="username" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" size="large" autoComplete="current-password" />
          </Form.Item>
          <Form.Item style={{ marginBottom: 12 }}>
            <Checkbox checked={remember} onChange={(e) => setRemember(e.target.checked)}>记住密码</Checkbox>
          </Form.Item>
          <Button type="primary" htmlType="submit" block size="large" loading={loading}>
            登录
          </Button>
        </Form>

        <div style={{ textAlign: 'center', marginTop: 12 }}>
          <Typography.Link onClick={openRegister}>还没有账号？注册</Typography.Link>
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
          <Form.Item name="department_id" label="所属部门"
            extra={depts.length > 0
              ? '可选，管理员在「部门管理」中配置的部门'
              : '管理员尚未配置部门；可留空，待审核通过后由管理员分配'}>
            <Select allowClear showSearch optionFilterProp="label"
              placeholder={depts.length > 0 ? '请选择部门（可选）' : '暂无部门可选'}
              disabled={depts.length === 0}
              notFoundContent="暂无部门"
              options={depts.map((d) => ({ value: d.id, label: '　'.repeat(d.depth || 0) + d.name }))} />
          </Form.Item>
          <Form.Item name="password" label="密码"
            rules={[{ required: true, message: '请输入密码' }, { min: 8, message: '至少 8 位' }]}
            extra="至少 8 位，需含字母、数字、符号中的至少两类（大小写不限）">
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
