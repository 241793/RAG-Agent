import { useEffect, useState } from 'react'
import {
  Alert, Button, Card, Form, Input, InputNumber, message, Modal, Popconfirm, Select, Space, Switch,
  Table, Tag, Typography,
} from 'antd'
import { PlusOutlined, DeleteOutlined, EditOutlined, ExperimentOutlined, SyncOutlined, MailOutlined } from '@ant-design/icons'
import { emailSourceApi, kbApi, type EmailSourceItem, type KB } from '../../api'
import { errMsg } from '../../api/http'
import PageContainer from '../../components/PageContainer'
import EmptyState from '../../components/EmptyState'
import Can from '../../components/Can'
import { useAuth } from '../../stores/auth'

function fmtTime(ms?: number | null) {
  return ms ? new Date(ms).toLocaleString('zh-CN') : '-'
}

export default function EmailSourcePage() {
  const hasPermission = useAuth((s) => s.hasPermission)
  const canManage = hasPermission('kb:update')
  const [items, setItems] = useState<EmailSourceItem[]>([])
  const [kbs, setKbs] = useState<KB[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [edit, setEdit] = useState<EmailSourceItem | null>(null)
  const [busy, setBusy] = useState<number | null>(null)
  const [form] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try { setItems(await emailSourceApi.list()) }
    catch (e) { message.error(errMsg(e)) } finally { setLoading(false) }
  }
  useEffect(() => {
    load()
    kbApi.list().then(setKbs).catch(() => {})
  }, [])

  const openModal = (s?: EmailSourceItem) => {
    setEdit(s || null)
    if (s) form.setFieldsValue({ ...s, password: '' })
    else form.resetFields()
    setOpen(true)
  }

  const submit = async () => {
    const v = await form.validateFields().catch(() => null)
    if (!v) return
    const payload: Record<string, any> = { ...v }
    if (!payload.password) delete payload.password  // 留空不改密码
    try {
      if (edit) await emailSourceApi.update(edit.id, payload)
      else await emailSourceApi.create(payload)
      message.success('已保存'); setOpen(false); load()
    } catch (e) { message.error(errMsg(e)) }
  }

  const test = async (s: EmailSourceItem) => {
    setBusy(s.id)
    try {
      const r = await emailSourceApi.test(s.id)
      if (r.ok) message.success(r.message || '连接成功'); else message.error(r.message || '连接失败')
    } catch (e) { message.error(errMsg(e)) } finally { setBusy(null) }
  }

  const sync = async (s: EmailSourceItem) => {
    setBusy(s.id)
    try {
      const r = await emailSourceApi.sync(s.id)
      if (r.ok) message.success(r.message || '已拉取'); else message.error(r.message || '拉取失败')
      load()
    } catch (e) { message.error(errMsg(e)) } finally { setBusy(null) }
  }

  const kbName = (id: number) => kbs.find((k) => k.id === id)?.name || `#${id}`

  return (
    <PageContainer
      title="邮件入库"
      subtitle="配置邮箱（IMAP），把收到的邮件正文与附件自动入库到知识库——员工把资料发到该邮箱即可被检索"
      extra={<Can perm="kb:update"><Button type="primary" icon={<PlusOutlined />} onClick={() => openModal()}>新增邮件源</Button></Can>}
    >
      <Alert type="info" showIcon style={{ marginBottom: 16 }}
        message="只读拉取，不删除/不标记已读；按邮件 UID 去重，附件与正文分别入库。默认每 5 分钟轮询一次（可在系统设置调整）。" />
      <Card bordered={false}>
        <Table
          rowKey="id" dataSource={items} loading={loading} pagination={false}
          scroll={{ x: 'max-content' }}
          locale={{ emptyText: <EmptyState description="尚未配置邮件入库源" /> }}
          columns={[
            { title: '名称', dataIndex: 'name', render: (v) => <Space><MailOutlined />{v}</Space> },
            { title: '邮箱', dataIndex: 'username', ellipsis: true },
            { title: '服务器', render: (_: any, r) => <Typography.Text style={{ fontSize: 12 }}>{r.imap_host}:{r.imap_port}</Typography.Text> },
            { title: '目标知识库', dataIndex: 'kb_id', render: (v) => kbName(v) },
            { title: '入库范围', dataIndex: 'ingest_mode', width: 100,
              render: (v: string) => <Tag>{v === 'both' ? '正文+附件' : v === 'attach' ? '仅附件' : '仅正文'}</Tag> },
            { title: '已入库', dataIndex: 'ingested_count', width: 80 },
            { title: '状态', width: 100, render: (_: any, r) => (
              r.status === 'error' ? <Tag color="red" title={r.last_error || ''}>异常</Tag>
                : r.enabled ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>
            ) },
            { title: '上次同步', dataIndex: 'last_sync_at', width: 160, render: fmtTime },
            {
              title: '操作', width: 260, fixed: 'right',
              render: (_: any, r: EmailSourceItem) => (
                <Space>
                  <Button size="small" icon={<ExperimentOutlined />} loading={busy === r.id} onClick={() => test(r)}>测试</Button>
                  <Can perm="kb:update">
                    <Button size="small" icon={<SyncOutlined />} loading={busy === r.id} onClick={() => sync(r)}>立即拉取</Button>
                    <Button size="small" icon={<EditOutlined />} onClick={() => openModal(r)} />
                    <Popconfirm title="删除该邮件源？" onConfirm={async () => { await emailSourceApi.remove(r.id); message.success('已删除'); load() }}>
                      <Button size="small" danger icon={<DeleteOutlined />} />
                    </Popconfirm>
                  </Can>
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Modal title={edit ? '编辑邮件源' : '新增邮件源'} open={open} onOk={submit}
        onCancel={() => setOpen(false)} destroyOnClose width={620}>
        <Form form={form} layout="vertical" initialValues={{ imap_port: 993, use_ssl: true, folder: 'INBOX', ingest_mode: 'both', enabled: true }}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}><Input placeholder="如：客服资料邮箱" /></Form.Item>
          <Space size={12} wrap>
            <Form.Item name="imap_host" label="IMAP 服务器" rules={[{ required: true }]}><Input style={{ width: 260 }} placeholder="imap.example.com" /></Form.Item>
            <Form.Item name="imap_port" label="端口"><InputNumber style={{ width: 110 }} /></Form.Item>
            <Form.Item name="use_ssl" label="SSL" valuePropName="checked"><Switch /></Form.Item>
          </Space>
          <Form.Item name="username" label="邮箱账号" rules={[{ required: true }]}><Input placeholder="knowledge@example.com" /></Form.Item>
          <Form.Item name="password" label="密码/授权码" extra={edit?.password_set ? '已配置，留空则不变' : ''}>
            <Input.Password placeholder="邮箱登录密码或授权码" />
          </Form.Item>
          <Space size={12} wrap>
            <Form.Item name="folder" label="监听的文件夹"><Input style={{ width: 160 }} /></Form.Item>
            <Form.Item name="kb_id" label="入库到知识库" rules={[{ required: true, message: '请选择知识库' }]}>
              <Select style={{ width: 220 }} placeholder="选择知识库"
                options={kbs.map((k) => ({ value: k.id, label: k.name }))} />
            </Form.Item>
            <Form.Item name="ingest_mode" label="入库范围">
              <Select style={{ width: 140 }} options={[
                { value: 'both', label: '正文+附件' },
                { value: 'attach', label: '仅附件' },
                { value: 'body', label: '仅正文' },
              ]} />
            </Form.Item>
          </Space>
          <Form.Item name="allow_from" label="仅接收这些发件人（逗号分隔，可空）"><Input placeholder="留空=不限" /></Form.Item>
          <Form.Item name="subject_keywords" label="主题关键词过滤（逗号分隔，可空）"><Input placeholder="如：报告, 资料" /></Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked"><Switch /></Form.Item>
        </Form>
      </Modal>
    </PageContainer>
  )
}
