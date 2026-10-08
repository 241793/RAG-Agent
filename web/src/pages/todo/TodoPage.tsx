import { useEffect, useState } from 'react'
import {
  Button, Card, DatePicker, Form, Input, InputNumber, List, message, Modal, Popconfirm, Select, Space,
  Switch, Tag, Typography,
} from 'antd'
import { PlusOutlined, CheckOutlined, DeleteOutlined, ClockCircleOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { reminderApi, rbacApi, type ReminderItem } from '../../api'
import { errMsg } from '../../api/http'
import PageContainer from '../../components/PageContainer'
import EmptyState from '../../components/EmptyState'
import { useAuth } from '../../stores/auth'

export default function TodoPage() {
  const me = useAuth((s) => s.user)
  const [items, setItems] = useState<ReminderItem[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [users, setUsers] = useState<{ id: number; username: string; display_name?: string }[]>([])
  const [form] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try { setItems(await reminderApi.list()) }
    catch (e) { message.error(errMsg(e)) } finally { setLoading(false) }
  }
  useEffect(() => {
    load()
    rbacApi.users(1, 200).then((r) => setUsers(r.items)).catch(() => {})
  }, [])

  const openModal = () => { form.resetFields(); form.setFieldsValue({ notify_on_due: true, remind_before_minutes: 0 }); setOpen(true) }
  const submit = async () => {
    const v = await form.validateFields().catch(() => null)
    if (!v) return
    try {
      await reminderApi.create({
        title: v.title, content: v.content,
        due_at: v.due_at ? v.due_at.valueOf() : null,
        assignee_id: v.assignee_id, notify_on_due: v.notify_on_due,
        remind_before_minutes: v.remind_before_minutes,
      })
      message.success('已创建'); setOpen(false); load()
    } catch (e) { message.error(errMsg(e)) }
  }
  const markDone = async (r: ReminderItem) => {
    try { await reminderApi.done(r.id); load() } catch (e) { message.error(errMsg(e)) }
  }

  // 到期判断：已过期且未完成 → 红色
  const now = Date.now()
  const pending = items.filter((x) => x.status === 'pending')
  const done = items.filter((x) => x.status !== 'pending')

  return (
    <PageContainer
      title="待办日程"
      subtitle="创建待办/日程，到点自动通过通知渠道提醒你（站内/企微/钉钉/邮件）"
      extra={<Button type="primary" icon={<PlusOutlined />} onClick={openModal}>新建待办</Button>}
    >
      <Card bordered={false} title={`待办（${pending.length}）`} style={{ marginBottom: 16 }}>
        <List
          loading={loading} dataSource={pending}
          locale={{ emptyText: <EmptyState description="暂无待办" /> }}
          renderItem={(r) => {
            const overdue = r.due_at && r.due_at < now
            return (
              <List.Item actions={[
                <Button key="d" size="small" icon={<CheckOutlined />} onClick={() => markDone(r)}>完成</Button>,
                <Popconfirm key="x" title="删除该待办？" onConfirm={async () => { await reminderApi.remove(r.id); load() }}>
                  <Button size="small" danger icon={<DeleteOutlined />} />
                </Popconfirm>,
              ]}>
                <List.Item.Meta
                  title={<Space><span>{r.title}</span>{r.repeat_cron && <Tag color="blue">重复</Tag>}
                    {overdue && <Tag color="red">已过期</Tag>}</Space>}
                  description={<Space size={8} style={{ fontSize: 12 }}>
                    <span><ClockCircleOutlined /> {r.due_at ? dayjs(r.due_at).format('YYYY-MM-DD HH:mm') : '无时间'}</span>
                    {r.content && <Typography.Text type="secondary">{r.content}</Typography.Text>}
                  </Space>} />
              </List.Item>
            )
          }}
        />
      </Card>
      {done.length > 0 && (
        <Card bordered={false} title={`已完成（${done.length}）`}>
          <List size="small" dataSource={done} renderItem={(r) => (
            <List.Item actions={[
              <Popconfirm key="x" title="删除？" onConfirm={async () => { await reminderApi.remove(r.id); load() }}>
                <Button size="small" danger icon={<DeleteOutlined />} />
              </Popconfirm>]}>
              <Typography.Text delete type="secondary">{r.title}</Typography.Text>
            </List.Item>
          )} />
        </Card>
      )}

      <Modal title="新建待办 / 日程" open={open} onOk={submit} onCancel={() => setOpen(false)} destroyOnClose width={560}>
        <Form form={form} layout="vertical">
          <Form.Item name="title" label="标题" rules={[{ required: true }]}><Input placeholder="如：提交周报" /></Form.Item>
          <Form.Item name="content" label="说明"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="due_at" label="到期时间"><DatePicker showTime style={{ width: '100%' }} /></Form.Item>
          <Space size={12} wrap>
            <Form.Item name="assignee_id" label="负责人">
              <Select style={{ width: 180 }} allowClear placeholder="（我）" showSearch optionFilterProp="label"
                options={users.map((u) => ({ value: u.id, label: u.display_name || u.username }))} />
            </Form.Item>
            <Form.Item name="remind_before_minutes" label="提前提醒（分钟）"><InputNumber min={0} max={10080} style={{ width: 120 }} /></Form.Item>
            <Form.Item name="notify_on_due" label="到点提醒" valuePropName="checked"><Switch /></Form.Item>
          </Space>
        </Form>
      </Modal>
    </PageContainer>
  )
}
