import { useEffect, useState } from 'react'
import {
  Button, Card, Form, Input, InputNumber, message, Modal, Popconfirm, Select, Space, Switch,
  Table, Tag, Typography,
} from 'antd'
import {
  PlusOutlined, DeleteOutlined, EditOutlined, ExperimentOutlined,
  BellOutlined, ApiOutlined, WechatOutlined, MailOutlined, UserOutlined, SendOutlined,
} from '@ant-design/icons'
import { channelApi, notifyChannelApi, type ChannelItem, type NotifyChannelItem } from '../../api'
import { errMsg } from '../../api/http'
import PageContainer from '../../components/PageContainer'
import EmptyState from '../../components/EmptyState'
import Can from '../../components/Can'
import { useAuth } from '../../stores/auth'

const KIND_META: Record<string, { label: string; color: string; icon: any }> = {
  inapp: { label: '站内消息', color: 'blue', icon: <UserOutlined /> },
  webhook: { label: 'Webhook', color: 'geekblue', icon: <ApiOutlined /> },
  wecom: { label: '企业微信', color: 'cyan', icon: <WechatOutlined /> },
  dingtalk: { label: '钉钉', color: 'purple', icon: <WechatOutlined /> },
  smtp: { label: '邮件', color: 'orange', icon: <MailOutlined /> },
  external: { label: '外部渠道', color: 'green', icon: <SendOutlined /> },
}

export default function NotifyChannelPage() {
  const hasPermission = useAuth((s) => s.hasPermission)
  const canManage = hasPermission('notify:manage')
  const [channels, setChannels] = useState<NotifyChannelItem[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [edit, setEdit] = useState<NotifyChannelItem | null>(null)
  const [kind, setKind] = useState<string>('webhook')
  const [testing, setTesting] = useState<number | null>(null)
  const [extChannels, setExtChannels] = useState<ChannelItem[]>([])
  const [form] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try { setChannels(await notifyChannelApi.list()) }
    catch (e) { message.error(errMsg(e)) } finally { setLoading(false) }
  }
  useEffect(() => {
    load()
    channelApi.list().then(setExtChannels).catch(() => {})
  }, [])

  const openModal = (c?: NotifyChannelItem) => {
    setEdit(c || null)
    setKind(c?.kind || 'webhook')
    if (c) form.setFieldsValue({ ...(c.config || {}), name: c.name, enabled: c.enabled, events: c.events })
    else form.resetFields()
    setOpen(true)
  }

  const submit = async () => {
    const v = await form.validateFields().catch(() => null)
    if (!v) return
    const cfg: Record<string, any> = {}
    if (kind === 'webhook') {
      cfg.url = v.url
      if (v.headers) { try { cfg.headers = JSON.parse(v.headers) } catch { message.error('请求头不是合法 JSON'); return } }
      if (v.template) { try { cfg.template = JSON.parse(v.template) } catch { message.error('模板不是合法 JSON'); return } }
    } else if (kind === 'wecom' || kind === 'dingtalk') {
      cfg.webhook_url = v.webhook_url
      if (kind === 'dingtalk' && v.secret) cfg.secret = v.secret
    } else if (kind === 'smtp') {
      Object.assign(cfg, {
        host: v.host, port: v.port, username: v.username, password: v.password,
        use_ssl: v.use_ssl !== false, from_addr: v.from_addr, to_addrs: v.to_addrs,
      })
    } else if (kind === 'external') {
      cfg.channel_id = v.channel_id
      cfg.target = v.target
      cfg.target_type = v.target_type || 'group'
    }
    const payload = { kind, name: v.name, enabled: v.enabled !== false, events: v.events || undefined, config: cfg }
    try {
      if (edit) await notifyChannelApi.update(edit.id, payload)
      else await notifyChannelApi.create(payload)
      message.success('已保存'); setOpen(false); load()
    } catch (e) { message.error(errMsg(e)) }
  }

  const test = async (c: NotifyChannelItem) => {
    setTesting(c.id)
    try {
      const r = await notifyChannelApi.test(c.id)
      if (r.ok) message.success(r.message || '测试通知已发送')
      else message.error(r.message || '发送失败')
    } catch (e) { message.error(errMsg(e)) } finally { setTesting(null) }
  }

  return (
    <PageContainer
      title="通知渠道"
      subtitle="配置定时任务/工作流等结果的通知出口：站内消息、Webhook、企业微信/钉钉群机器人、邮件"
      extra={<Can perm="notify:manage"><Button type="primary" icon={<PlusOutlined />} onClick={() => openModal()}>新建渠道</Button></Can>}
    >
      <Card bordered={false}>
        <Table
          rowKey="id" dataSource={channels} loading={loading} pagination={false}
          locale={{ emptyText: <EmptyState description="尚未配置通知渠道（站内消息默认可用）" /> }}
          columns={[
            { title: '名称', dataIndex: 'name', render: (v, r) => (
              <Space>{KIND_META[r.kind]?.icon}{v}</Space>
            ) },
            { title: '类型', dataIndex: 'kind', width: 120,
              render: (v: string) => <Tag color={KIND_META[v]?.color}>{KIND_META[v]?.label || v}</Tag> },
            { title: '订阅事件', dataIndex: 'events', render: (v: string) => v || <Typography.Text type="secondary">全部</Typography.Text> },
            { title: '启用', dataIndex: 'enabled', width: 80,
              render: (v: boolean) => v ? <Tag color="green">启用</Tag> : <Tag>停用</Tag> },
            {
              title: '操作', width: 220,
              render: (_: any, r: NotifyChannelItem) => (
                <Space>
                  <Button size="small" icon={<ExperimentOutlined />} loading={testing === r.id} onClick={() => test(r)}>测试</Button>
                  <Can perm="notify:manage">
                    <Button size="small" icon={<EditOutlined />} onClick={() => openModal(r)} />
                    <Popconfirm title="删除该渠道？" onConfirm={async () => { await notifyChannelApi.remove(r.id); message.success('已删除'); load() }}>
                      <Button size="small" danger icon={<DeleteOutlined />} />
                    </Popconfirm>
                  </Can>
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Modal title={edit ? '编辑通知渠道' : '新建通知渠道'} open={open} onOk={submit}
        onCancel={() => setOpen(false)} destroyOnClose width={620}>
        <Form form={form} layout="vertical" initialValues={{ enabled: true, use_ssl: true, kind: 'webhook' }}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}><Input /></Form.Item>
          <Form.Item label="类型" required>
            <Select value={kind} onChange={(v) => setKind(v)} disabled={!!edit} options={[
              { value: 'inapp', label: '站内消息（Header 铃铛）' },
              { value: 'webhook', label: 'Webhook（POST JSON）' },
              { value: 'wecom', label: '企业微信群机器人' },
              { value: 'dingtalk', label: '钉钉群机器人' },
              { value: 'smtp', label: '邮件（SMTP）' },
              { value: 'external', label: '外部渠道（QQ/微信/企微/飞书）' },
            ]} />
          </Form.Item>

          {kind === 'inapp' && (
            <Typography.Paragraph type="secondary">站内消息发送到任务所有者，无需额外配置。新建后默认启用即可。</Typography.Paragraph>
          )}
          {kind === 'external' && (
            <>
              <Form.Item name="channel_id" label="外部渠道" rules={[{ required: true, message: '请选择渠道' }]}>
                <Select placeholder="选择已接入的渠道"
                  options={extChannels.map((c) => ({ value: c.id, label: `${c.name}（${c.kind}）` }))} />
              </Form.Item>
              <Form.Item name="target_type" label="接收对象类型" initialValue="group">
                <Select options={[{ value: 'group', label: '群' }, { value: 'user', label: '个人' }]} />
              </Form.Item>
              <Form.Item name="target" label="接收对象 id" rules={[{ required: true, message: '请填写 id' }]}
                extra="群 id / 用户 id；可让目标在渠道里发 /myuid 查看自己的 id">
                <Input placeholder="群 id 或用户 id" />
              </Form.Item>
              <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
                注意：微信（非官方）需 24h 内互动过才能推送；QQ 主动消息有频次限制；企业微信/飞书最可靠。
                推送复用渠道的长连接，请确保该渠道已启用且在线。
              </Typography.Paragraph>
            </>
          )}
          {kind === 'webhook' && (
            <>
              <Form.Item name="url" label="Webhook URL" rules={[{ required: true }]}><Input placeholder="https://example.com/hook" /></Form.Item>
              <Form.Item name="headers" label="附加请求头（JSON，可空）"><Input.TextArea rows={2} placeholder='{"X-Token":"xxx"}' /></Form.Item>
              <Form.Item name="template" label="请求体模板（JSON，可空）"
                extra="占位：{title} {body} {level} {kind}；留空则发默认 JSON">
                <Input.TextArea rows={2} placeholder='{"text":"{title}: {body}"}' />
              </Form.Item>
            </>
          )}
          {(kind === 'wecom' || kind === 'dingtalk') && (
            <>
              <Form.Item name="webhook_url" label="机器人 Webhook URL" rules={[{ required: true }]}>
                <Input placeholder={kind === 'wecom' ? 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...' : 'https://oapi.dingtalk.com/robot/send?access_token=...'} />
              </Form.Item>
              {kind === 'dingtalk' && (
                <Form.Item name="secret" label="加签密钥（可选）" extra="钉钉机器人若开启加签，需填 secret">
                  <Input.Password placeholder="SEC... " />
                </Form.Item>
              )}
            </>
          )}
          {kind === 'smtp' && (
            <>
              <Space size={12} wrap>
                <Form.Item name="host" label="SMTP 服务器" rules={[{ required: true }]}><Input style={{ width: 240 }} placeholder="smtp.example.com" /></Form.Item>
                <Form.Item name="port" label="端口"><InputNumber style={{ width: 120 }} placeholder="465/587" /></Form.Item>
                <Form.Item name="use_ssl" label="SSL" valuePropName="checked"><Switch /></Form.Item>
              </Space>
              <Space size={12} wrap>
                <Form.Item name="username" label="用户名"><Input style={{ width: 240 }} /></Form.Item>
                <Form.Item name="password" label="密码/授权码"><Input.Password style={{ width: 240 }} /></Form.Item>
              </Space>
              <Form.Item name="from_addr" label="发件人" ><Input placeholder="noreply@example.com" /></Form.Item>
              <Form.Item name="to_addrs" label="收件人（逗号分隔）" rules={[{ required: true }]}><Input placeholder="a@x.com,b@y.com" /></Form.Item>
            </>
          )}

          <Space size={16}>
            <Form.Item name="events" label="订阅事件" tooltip="留空=接收全部；可按需填 task / workflow / system">
              <Input style={{ width: 240 }} placeholder="留空表示全部" />
            </Form.Item>
            <Form.Item name="enabled" label="启用" valuePropName="checked"><Switch /></Form.Item>
          </Space>
        </Form>
      </Modal>
    </PageContainer>
  )
}
