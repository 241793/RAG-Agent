import { useEffect, useState } from 'react'
import {
  Alert, Button, Card, Form, Input, message, Modal, Popconfirm, Select, Space, Switch, Table, Tag, Typography,
} from 'antd'
import { PlusOutlined, DeleteOutlined, EditOutlined, ExperimentOutlined, ThunderboltOutlined, CopyOutlined } from '@ant-design/icons'
import { eventSubApi, type EventSubItem } from '../../api'
import { errMsg } from '../../api/http'
import PageContainer from '../../components/PageContainer'
import EmptyState from '../../components/EmptyState'
import Can from '../../components/Can'
import { useAuth } from '../../stores/auth'

export default function EventSubscriptionPage() {
  const canManage = useAuth((s) => s.hasPermission)('notify:manage')
  const [items, setItems] = useState<EventSubItem[]>([])
  const [events, setEvents] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [edit, setEdit] = useState<EventSubItem | null>(null)
  const [testing, setTesting] = useState<number | null>(null)
  const [form] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try { setItems(await eventSubApi.list()) }
    catch (e) { message.error(errMsg(e)) } finally { setLoading(false) }
  }
  useEffect(() => {
    load()
    eventSubApi.events().then(setEvents).catch(() => {})
  }, [])

  const openModal = (s?: EventSubItem) => {
    setEdit(s || null)
    if (s) form.setFieldsValue({ name: s.name, url: s.url, events: s.events || [], enabled: s.enabled })
    else form.resetFields()
    setOpen(true)
  }

  const submit = async () => {
    const v = await form.validateFields().catch(() => null)
    if (!v) return
    const payload: any = {
      name: v.name, url: v.url, enabled: v.enabled !== false,
      events: Array.isArray(v.events) && v.events.length ? v.events.join(',') : null,
    }
    if (v.secret) payload.secret = v.secret
    try {
      if (edit) await eventSubApi.update(edit.id, payload)
      else await eventSubApi.create(payload)
      message.success('已保存'); setOpen(false); load()
    } catch (e) { message.error(errMsg(e)) }
  }

  const test = async (s: EventSubItem) => {
    setTesting(s.id)
    try {
      const r = await eventSubApi.test(s.id)
      if (r.ok) message.success(r.message || '已送达'); else message.error(r.message || '投递失败')
    } catch (e) { message.error(errMsg(e)) } finally { setTesting(null) }
  }

  return (
    <PageContainer
      title="事件订阅"
      subtitle="让外部系统订阅平台事件（工单创建、文档入库完成、工作流完成等），事件发生时平台主动 POST 回调到你的 URL（带 HMAC 签名）"
      extra={<Can perm="notify:manage"><Button type="primary" icon={<PlusOutlined />} onClick={() => openModal()}>新建订阅</Button></Can>}
    >
      <Alert type="info" showIcon style={{ marginBottom: 16 }}
        message="回调格式"
        description={<>
          平台向订阅 URL POST <Typography.Text code>{'{"event":"ticket.created","tenant_id":1,"ts":1700000000000,"data":{...}}'}</Typography.Text>；
          若配置了密钥，会带请求头 <Typography.Text code>X-Signature: sha256=HMAC(secret, "{ts}.{body}")</Typography.Text>、
          <Typography.Text code>X-Timestamp</Typography.Text>，供你校验来源与防重放。
        </>} />
      <Card bordered={false}>
        <Table
          rowKey="id" dataSource={items} loading={loading} pagination={false}
          locale={{ emptyText: <EmptyState description="尚未配置事件订阅" /> }}
          columns={[
            { title: '名称', dataIndex: 'name', render: (v) => <Space><ThunderboltOutlined />{v}</Space> },
            { title: '回调 URL', dataIndex: 'url', ellipsis: true },
            { title: '订阅事件', dataIndex: 'events',
              render: (v: string) => v ? v.split(',').map((e) => <Tag key={e}>{e}</Tag>) : <Typography.Text type="secondary">全部事件</Typography.Text> },
            { title: '签名', dataIndex: 'secret_set', width: 80,
              render: (v: boolean) => v ? <Tag color="green">已配置</Tag> : <Tag>无</Tag> },
            { title: '启用', dataIndex: 'enabled', width: 80,
              render: (v: boolean) => v ? <Tag color="green">启用</Tag> : <Tag>停用</Tag> },
            {
              title: '操作', width: 220,
              render: (_: any, r: EventSubItem) => (
                <Space>
                  <Button size="small" icon={<ExperimentOutlined />} loading={testing === r.id} onClick={() => test(r)}>测试</Button>
                  <Can perm="notify:manage">
                    <Button size="small" icon={<EditOutlined />} onClick={() => openModal(r)} />
                    <Popconfirm title="删除该订阅？" onConfirm={async () => { await eventSubApi.remove(r.id); message.success('已删除'); load() }}>
                      <Button size="small" danger icon={<DeleteOutlined />} />
                    </Popconfirm>
                  </Can>
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Modal title={edit ? '编辑事件订阅' : '新建事件订阅'} open={open} onOk={submit}
        onCancel={() => setOpen(false)} destroyOnClose width={620}>
        <Form form={form} layout="vertical" initialValues={{ enabled: true }}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="如：CRM 系统回传" />
          </Form.Item>
          <Form.Item name="url" label="回调 URL" rules={[{ required: true, message: '请输入 URL' }]}
            extra="平台会向此地址 POST 事件 JSON（须为公网可达的 http/https）">
            <Input placeholder="https://crm.example.com/hooks/rag" prefix={<CopyOutlined />} />
          </Form.Item>
          <Form.Item name="events" label="订阅事件" extra="留空 = 订阅全部事件">
            <Select mode="multiple" allowClear placeholder="留空=全部"
              options={events.map((e) => ({ value: e, label: e }))} />
          </Form.Item>
          <Form.Item name="secret" label="签名密钥（可选）"
            extra={edit?.secret_set ? '已配置，留空则不修改' : '配置后回调会带 X-Signature 头供你校验来源'}>
            <Input.Password placeholder="用于 HMAC-SHA256 签名" />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked"><Switch /></Form.Item>
        </Form>
      </Modal>
    </PageContainer>
  )
}
