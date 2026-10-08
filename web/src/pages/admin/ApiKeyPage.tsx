import { useEffect, useState } from 'react'
import {
  Alert, Button, Card, Form, Input, InputNumber, message, Modal, Popconfirm, Select, Space, Table, Tag,
} from 'antd'
import { PlusOutlined, DeleteOutlined, CopyOutlined } from '@ant-design/icons'
import { apiKeyApi, kbApi, type ApiKeyItem, type KB } from '../../api'
import { errMsg } from '../../api/http'
import PageContainer from '../../components/PageContainer'
import EmptyState from '../../components/EmptyState'
import { useAuth } from '../../stores/auth'

const SCOPE_OPTS = [
  { value: 'chat:use', label: '对话 chat:use' },
  { value: 'retrieval:query', label: '检索 retrieval:query' },
  { value: '*', label: '全部 *' },
]

export default function ApiKeyPage() {
  const [keys, setKeys] = useState<ApiKeyItem[]>([])
  const [kbs, setKbs] = useState<KB[]>([])
  const [open, setOpen] = useState(false)
  const [newKey, setNewKey] = useState<string | null>(null)
  const [form] = Form.useForm()
  const hasPermission = useAuth((s) => s.hasPermission)
  const canManage = hasPermission('apikey:manage')

  const load = async () => {
    try {
      setKeys(await apiKeyApi.list())
      setKbs(await kbApi.list())
    } catch (e) { message.error(errMsg(e)) }
  }
  useEffect(() => { load() }, [])

  const create = async () => {
    const v = await form.validateFields()
    try {
      const r = await apiKeyApi.create(v)
      setNewKey(r.key)
      setOpen(false)
      form.resetFields()
      load()
    } catch (e) { message.error(errMsg(e)) }
  }

  return (
    <PageContainer
      title="API 密钥"
      subtitle="供内部系统调用本平台接口（OpenAI 兼容）"
      extra={canManage ? <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>创建密钥</Button> : undefined}
    >
      <Alert
        type="info" showIcon style={{ marginBottom: 16 }}
        message="内部系统接入"
        description="用本密钥调用 OpenAI 兼容端点：Base URL = 本服务地址 + /v1，API Key = 生成的密钥。示例：openai.OpenAI(base_url='http://<host>:6677/v1', api_key='sk-rag-...')"
      />

      <Card bordered={false}>
      <Table
        rowKey="id" dataSource={keys} pagination={false}
        locale={{ emptyText: <EmptyState description="暂无密钥" actionText={canManage ? '创建密钥' : undefined} onAction={() => setOpen(true)} /> }}
        columns={[
          { title: '名称', dataIndex: 'name' },
          { title: '前缀', dataIndex: 'key_prefix', render: (v: string) => <code>{v}...</code> },
          { title: '范围', dataIndex: 'scopes', render: (v: string[]) => (v || []).map((s) => <Tag key={s}>{s}</Tag>) },
          { title: '限流', dataIndex: 'rate_limit', width: 90, render: (v: number) => `${v}/分` },
          { title: '状态', dataIndex: 'status', width: 90, render: (v: string) => <Tag color={v === 'active' ? 'green' : 'red'}>{v === 'active' ? '正常' : '已吊销'}</Tag> },
          { title: '最后使用', dataIndex: 'last_used_at', render: (v) => v ? v.slice(0, 19).replace('T', ' ') : '未使用' },
          ...(canManage ? [{
            title: '操作', width: 90,
            render: (_: any, r: ApiKeyItem) => (
              r.status === 'active' ? (
                <Popconfirm title="吊销该密钥？" onConfirm={async () => { await apiKeyApi.revoke(r.id); load() }}>
                  <Button size="small" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              ) : null
            ),
          }] : []),
        ]}
      />
      </Card>

      <Modal title="创建 API 密钥" open={open} onOk={create} onCancel={() => setOpen(false)} destroyOnClose>
        <Form form={form} layout="vertical" initialValues={{ scopes: ['chat:use', 'retrieval:query'], rate_limit: 60 }}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input placeholder="如：内部 CRM 系统" /></Form.Item>
          <Form.Item name="scopes" label="权限范围"><Select mode="multiple" options={SCOPE_OPTS} /></Form.Item>
          <Form.Item name="kb_ids" label="限制知识库（可选）">
            <Select mode="multiple" allowClear options={kbs.map((k) => ({ value: k.id, label: k.name }))} />
          </Form.Item>
          <Form.Item name="rate_limit" label="限流（每分钟请求数）"><InputNumber min={0} /></Form.Item>
        </Form>
      </Modal>

      <Modal
        title="密钥已创建（仅显示一次）" open={!!newKey} onCancel={() => setNewKey(null)}
        footer={<Button type="primary" onClick={() => setNewKey(null)}>我已保存</Button>}
      >
        <Alert type="warning" showIcon message="请立即复制保存，关闭后无法再次查看" style={{ marginBottom: 12 }} />
        <Space.Compact style={{ width: '100%' }}>
          <Input value={newKey || ''} readOnly />
          <Button icon={<CopyOutlined />} onClick={() => { navigator.clipboard?.writeText(newKey || ''); message.success('已复制') }}>复制</Button>
        </Space.Compact>
      </Modal>
    </PageContainer>
  )
}
