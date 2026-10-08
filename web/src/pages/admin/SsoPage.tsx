import { useEffect, useState } from 'react'
import {
  Alert, Button, Card, Form, Input, message, Modal, Select, Switch, Table, Tag,
} from 'antd'
import { PlusOutlined, EditOutlined } from '@ant-design/icons'
import { ssoApi, type SsoConfigItem } from '../../api'
import { errMsg } from '../../api/http'
import PageContainer from '../../components/PageContainer'
import EmptyState from '../../components/EmptyState'

const PROVIDERS = [
  { value: 'oidc', label: '通用 OIDC（Azure AD / Keycloak / Authentik 等）' },
  { value: 'wecom', label: '企业微信' },
  { value: 'dingtalk', label: '钉钉' },
  { value: 'feishu', label: '飞书' },
]

export default function SsoPage() {
  const [configs, setConfigs] = useState<SsoConfigItem[]>([])
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm()
  const provider = Form.useWatch('provider', form)

  const load = async () => {
    try { setConfigs(await ssoApi.configs()) }
    catch (e) { message.error(errMsg(e)) }
  }
  useEffect(() => { load() }, [])

  const save = async () => {
    const v = await form.validateFields()
    try {
      await ssoApi.saveConfig(v)
      message.success('已保存')
      setOpen(false); form.resetFields(); load()
    } catch (e) { message.error(errMsg(e)) }
  }

  const openEdit = (c?: SsoConfigItem) => {
    form.resetFields()
    if (c) form.setFieldsValue(c)
    setOpen(true)
  }

  return (
    <PageContainer
      title="单点登录（SSO）"
      subtitle="配置企业身份源，员工用公司账号登录"
      extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => openEdit()}>添加身份源</Button>}
    >
      <Alert
        type="info" showIcon style={{ marginBottom: 16 }}
        message="支持通用 OIDC（Azure AD / Keycloak / Authentik）、企业微信、钉钉、飞书。配置启用后，登录页会显示对应登录按钮。"
      />
      <Card bordered={false}>
        <Table
          rowKey="provider" dataSource={configs} pagination={false}
          locale={{ emptyText: <EmptyState description="暂无身份源" actionText="添加身份源" onAction={() => openEdit()} /> }}
          columns={[
            { title: '身份源', dataIndex: 'provider', render: (v: string) => PROVIDERS.find((p) => p.value === v)?.label || v },
            { title: '名称', dataIndex: 'name' },
            { title: '状态', dataIndex: 'enabled', width: 100, render: (v: boolean) => <Tag color={v ? 'green' : 'default'}>{v ? '已启用' : '未启用'}</Tag> },
            { title: 'Client ID', dataIndex: 'client_id', ellipsis: true },
            {
              title: '操作', width: 100,
              render: (_: any, r: SsoConfigItem) => (
                <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(r)}>编辑</Button>
              ),
            },
          ]}
        />
      </Card>

      <Modal title="配置身份源" open={open} onOk={save} onCancel={() => setOpen(false)} destroyOnClose width={640}>
        <Form form={form} layout="vertical" initialValues={{ enabled: true, auto_create_user: true }}>
          <Form.Item name="provider" label="身份源类型" rules={[{ required: true }]}>
            <Select options={PROVIDERS} disabled={!!form.getFieldValue('id')} />
          </Form.Item>
          <Form.Item name="name" label="显示名称" rules={[{ required: true }]}>
            <Input placeholder="如：企业微信登录" />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked"><Switch /></Form.Item>
          <Form.Item name="client_id" label="Client ID / AppID / CorpID" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="client_secret" label="Client Secret / AppSecret"><Input.Password /></Form.Item>
          <Form.Item name="redirect_uri" label="回调地址" extra="留空则用默认 /api/v1/auth/sso/{provider}/callback">
            <Input placeholder="http://your-host:6677/api/v1/auth/sso/{provider}/callback" />
          </Form.Item>

          {provider === 'oidc' && (
            <>
              <Form.Item name="authorize_url" label="Authorize URL"><Input /></Form.Item>
              <Form.Item name="token_url" label="Token URL"><Input /></Form.Item>
              <Form.Item name="userinfo_url" label="Userinfo URL"><Input /></Form.Item>
            </>
          )}
          {provider === 'wecom' && (
            <>
              <Form.Item name="corp_id" label="企业 CorpID"><Input /></Form.Item>
              <Form.Item name="agent_id" label="应用 AgentID"><Input /></Form.Item>
            </>
          )}
        </Form>
      </Modal>
    </PageContainer>
  )
}
