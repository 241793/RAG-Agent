import { useEffect, useState } from 'react'
import {
  Button, Card, Descriptions, Drawer, Form, Input, InputNumber, List, message, Modal, Popconfirm,
  Select, Space, Switch, Table, Tag, Tooltip, Typography,
} from 'antd'
import {
  PlusOutlined, DeleteOutlined, PlayCircleOutlined, EditOutlined, HistoryOutlined,
  LinkOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
import { agentApi, scheduledApi, type Agent, type ScheduledTask, type ScheduleValue } from '../../api'
import { errMsg } from '../../api/http'
import PageContainer from '../../components/PageContainer'
import EmptyState from '../../components/EmptyState'
import Can from '../../components/Can'
import { useAuth } from '../../stores/auth'
import SchedulePicker from '../../components/SchedulePicker'

function fmtTime(ms?: number | null) {
  return ms ? new Date(ms).toLocaleString('zh-CN') : '-'
}

function describe(t: ScheduledTask) {
  if (t.trigger_kind === 'event') return `当事件「${t.event_name || '-'}」发生时`
  if (t.schedule_kind === 'once') return `仅一次：${fmtTime(t.run_at)}`
  if (t.schedule_kind === 'interval') return `每 ${Math.round((t.interval_seconds || 0) / 60)} 分钟`
  return t.cron_expr || '-'
}

export default function ScheduledTasksPage() {
  const [tasks, setTasks] = useState<ScheduledTask[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [open, setOpen] = useState(false)
  const [edit, setEdit] = useState<ScheduledTask | null>(null)
  const [schedule, setSchedule] = useState<ScheduleValue>({ schedule_kind: 'cron', cron_expr: '0 9 * * *' })
  const [form] = Form.useForm()
  const targetType = Form.useWatch('target_type', form)
  const triggerKind = Form.useWatch('trigger_kind', form)
  const [historyTask, setHistoryTask] = useState<ScheduledTask | null>(null)
  const [runs, setRuns] = useState<any[]>([])
  const [runsLoading, setRunsLoading] = useState(false)
  const [hookTask, setHookTask] = useState<ScheduledTask | null>(null)
  const [hookTokens, setHookTokens] = useState<any[]>([])
  const [newHook, setNewHook] = useState<string>('')
  const hasPermission = useAuth((s) => s.hasPermission)
  const canManage = hasPermission('schedule:manage')

  const load = async () => {
    try {
      setTasks(await scheduledApi.list())
      setAgents(await agentApi.list())
    } catch (e) { message.error(errMsg(e)) }
  }
  useEffect(() => { load() }, [])

  const openCreate = () => {
    setEdit(null); form.resetFields()
    form.setFieldsValue({ target_type: 'prompt', enabled: true, trigger_kind: 'schedule', notify_on: 'fail', max_retries: 0, retry_interval_seconds: 60 })
    setSchedule({ schedule_kind: 'cron', cron_expr: '0 9 * * *' })
    setOpen(true)
  }
  const openEdit = (t: ScheduledTask) => {
    setEdit(t)
    form.setFieldsValue({ ...t, inputs: t.inputs ? JSON.stringify(t.inputs, null, 2) : undefined })
    setSchedule({
      schedule_kind: (t.schedule_kind as any) || 'cron',
      cron_expr: t.cron_expr || undefined,
      interval_seconds: t.interval_seconds || undefined,
      run_at: t.run_at || undefined,
    })
    setOpen(true)
  }

  const submit = async () => {
    const v = await form.validateFields()
    let inputs = v.inputs
    if (typeof inputs === 'string' && inputs.trim()) {
      try { inputs = JSON.parse(inputs) } catch { message.error('工作流输入不是合法 JSON'); return }
    }
    const payload: any = { ...v, ...schedule, inputs }
    if (payload.trigger_kind === 'event') { payload.schedule_kind = 'cron'; payload.cron_expr = undefined }
    try {
      if (edit) await scheduledApi.update(edit.id, payload)
      else await scheduledApi.create(payload)
      message.success('已保存'); setOpen(false); load()
    } catch (e) { message.error(errMsg(e)) }
  }

  const openHistory = async (t: ScheduledTask) => {
    setHistoryTask(t); setRunsLoading(true); setRuns([])
    try {
      const r = await scheduledApi.runs(t.id)
      setRuns(r.items)
    } catch (e) { message.error(errMsg(e)) }
    finally { setRunsLoading(false) }
  }

  const openHook = async (t: ScheduledTask) => {
    setHookTask(t); setNewHook('')
    try { setHookTokens(await (scheduledApi as any).webhookTokens(t.id)) } catch { /* ignore */ }
  }
  const genHook = async () => {
    if (!hookTask) return
    try {
      const r = await (scheduledApi as any).createWebhook(hookTask.id)
      setNewHook(r.token)
      setHookTokens(await (scheduledApi as any).webhookTokens(hookTask.id))
      message.success('已生成，token 仅显示一次')
    } catch (e) { message.error(errMsg(e)) }
  }

  const statusTag = (s?: string | null) => {
    const color = s === 'success' ? 'green' : s === 'failed' ? 'red' : s === 'running' ? 'processing' : 'default'
    const label = s === 'success' ? '成功' : s === 'failed' ? '失败' : s === 'running' ? '运行中' : '未运行'
    return <Tag color={color}>{label}</Tag>
  }

  return (
    <PageContainer
      title="定时任务"
      subtitle="按时间或事件自动触发提示词（智能体）/工作流，支持失败重试与完成通知"
      extra={<Can perm="schedule:manage"><Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建定时任务</Button></Can>}
    >
      <Card bordered={false}>
        <Table
          rowKey="id" dataSource={tasks} pagination={false}
          loading={!tasks.length && runsLoading}
          scroll={{ x: 'max-content' }}
          locale={{ emptyText: <EmptyState description="暂无定时任务" actionText={canManage ? '新建' : undefined} onAction={openCreate} /> }}
          columns={[
            { title: '名称', dataIndex: 'name', width: 160, ellipsis: true },
            { title: '触发', width: 110,
              render: (_: any, r: ScheduledTask) => r.trigger_kind === 'event'
                ? <Tag color="gold" icon={<ThunderboltOutlined />}>事件</Tag>
                : <Tag color="blue">定时</Tag> },
            { title: '目标', dataIndex: 'target_type', width: 150,
              render: (v: string, r: ScheduledTask) => {
                const ag = agents.find((a) => a.id === r.agent_id)
                return <Tooltip title={ag?.name || `智能体 #${r.agent_id}`}>
                  <Tag color={v === 'workflow' ? 'purple' : 'blue'}>
                    {v === 'workflow' ? '工作流' : '提示词'}·{ag?.name || `#${r.agent_id}`}
                  </Tag>
                </Tooltip>
              } },
            { title: '频率', width: 220, ellipsis: true, render: (_: any, r: ScheduledTask) => <code>{describe(r)}</code> },
            { title: '下次运行', dataIndex: 'next_run_at', width: 170, render: fmtTime },
            { title: '上次', width: 170,
              render: (_: any, r: ScheduledTask) => (
                <Space direction="vertical" size={0}>
                  {statusTag(r.last_status)}
                  {r.retry_count ? <Typography.Text type="warning" style={{ fontSize: 11 }}>已重试 {r.retry_count}</Typography.Text> : null}
                  <Typography.Text type="secondary" style={{ fontSize: 11 }}>{fmtTime(r.last_run_at)}</Typography.Text>
                </Space>
              ) },
            { title: '启用', dataIndex: 'enabled', width: 70,
              render: (v: boolean, r: ScheduledTask) => (
                <Switch checked={v} disabled={!canManage} onChange={async (c) => { await scheduledApi.enable(r.id, c); load() }} />
              ) },
            {
              title: '操作', width: 240, fixed: 'right',
              render: (_: any, r: ScheduledTask) => (
                <Space>
                  <Tooltip title="立即运行"><Button size="small" icon={<PlayCircleOutlined />} disabled={!canManage}
                    onClick={async () => { await scheduledApi.runNow(r.id); message.success('已触发'); }} /></Tooltip>
                  <Tooltip title="执行历史"><Button size="small" icon={<HistoryOutlined />} onClick={() => openHistory(r)} /></Tooltip>
                  {canManage && (
                    <>
                      <Tooltip title="Webhook"><Button size="small" icon={<LinkOutlined />} onClick={() => openHook(r)} /></Tooltip>
                      <Tooltip title="编辑"><Button size="small" icon={<EditOutlined />} onClick={() => openEdit(r)} /></Tooltip>
                      <Popconfirm title="删除该定时任务？" onConfirm={async () => { await scheduledApi.remove(r.id); load() }}>
                        <Button size="small" danger icon={<DeleteOutlined />} />
                      </Popconfirm>
                    </>
                  )}
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Modal title={edit ? '编辑定时任务' : '新建定时任务'} open={open} onOk={submit}
        onCancel={() => setOpen(false)} destroyOnClose width={640}>
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input placeholder="如：每日早报" /></Form.Item>
          <Form.Item name="agent_id" label="目标智能体/工作流" rules={[{ required: true }]}>
            <Select placeholder="选择智能体"
              options={agents.map((a) => ({ value: a.id, label: `${a.name}（${a.type === 'workflow' ? '工作流' : '智能体'}）` }))} />
          </Form.Item>
          <Form.Item name="target_type" label="触发类型">
            <Select options={[{ value: 'prompt', label: '运行提示词（智能体）' }, { value: 'workflow', label: '运行工作流' }]} />
          </Form.Item>
          {targetType === 'workflow' ? (
            <Form.Item name="inputs" label="工作流输入（JSON）" extra='如 {"query":"生成今日报表"}'>
              <Input.TextArea rows={3} style={{ fontFamily: 'monospace', fontSize: 12 }} />
            </Form.Item>
          ) : (
            <Form.Item name="prompt" label="要执行的提示词" rules={[{ required: true }]}>
              <Input.TextArea rows={3} placeholder="如：总结昨天的工作进展" />
            </Form.Item>
          )}
          <Form.Item name="trigger_kind" label="触发方式">
            <Select options={[{ value: 'schedule', label: '按时间' }, { value: 'event', label: '按事件' }]} />
          </Form.Item>
          {triggerKind === 'event' ? (
            <Form.Item name="event_name" label="事件名" extra="事件触发：当指定事件发生时运行本任务" rules={[{ required: true }]}>
              <Select placeholder="选择事件" options={[
                { value: 'document.ready', label: 'document.ready（文档入库完成）' },
                { value: 'document.failed', label: 'document.failed（文档入库失败）' },
                { value: 'workflow.completed', label: 'workflow.completed（工作流运行成功）' },
                { value: 'workflow.failed', label: 'workflow.failed（工作流运行失败）' },
              ]} />
            </Form.Item>
          ) : (
            <Form.Item label="运行时间">
              <SchedulePicker onChange={setSchedule} />
            </Form.Item>
          )}
          <Space size={16} wrap>
            <Form.Item name="max_retries" label="失败重试次数">
              <InputNumber min={0} max={10} style={{ width: 120 }} />
            </Form.Item>
            <Form.Item name="retry_interval_seconds" label="重试间隔（秒）">
              <InputNumber min={10} max={3600} style={{ width: 120 }} />
            </Form.Item>
            <Form.Item name="timeout_seconds" label="超时（秒，可空）">
              <InputNumber min={10} max={7200} style={{ width: 120 }} />
            </Form.Item>
          </Space>
          <Space size={16} wrap>
            <Form.Item name="notify_on" label="通知时机"
              extra="执行结果只在「执行历史」留存，不占用问答会话"
              tooltip="选择何时向配置的通知渠道（站内/企微/钉钉/邮件等）发送通知">
              <Select style={{ width: 160 }} options={[
                { value: 'fail', label: '仅失败时' },
                { value: 'success', label: '仅成功时' },
                { value: 'always', label: '总是' },
                { value: 'never', label: '从不' },
              ]} />
            </Form.Item>
            <Form.Item name="enabled" label="启用" valuePropName="checked"><Switch /></Form.Item>
          </Space>
          <Form.Item name="depends_on_task_id" label="前置任务（可选）"
            extra="配置后：本任务不再按时间/事件触发，而是在「前置任务」成功后自动运行（A→B 依赖链）">
            <Select allowClear placeholder="无（独立运行）" showSearch optionFilterProp="label"
              options={tasks.filter((t) => t.id !== edit?.id).map((t) => ({ value: t.id, label: t.name }))} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 执行历史 */}
      <Drawer title={`执行历史：${historyTask?.name || ''}`} width={640}
        open={!!historyTask} onClose={() => setHistoryTask(null)}>
        <List
          loading={runsLoading} dataSource={runs}
          locale={{ emptyText: <EmptyState description="暂无执行记录" /> }}
          renderItem={(r: any) => (
            <List.Item>
              <div style={{ width: '100%' }}>
                <Space size={6} wrap>
                  {statusTag(r.status)}
                  <Tag>耗时 {r.duration_ms != null ? `${(r.duration_ms / 1000).toFixed(1)}s` : '-'}</Tag>
                  {r.attempt > 1 && <Tag color="orange">第 {r.attempt} 次尝试</Tag>}
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>{fmtTime(r.started_at)}</Typography.Text>
                </Space>
                {r.error && (
                  <Typography.Paragraph type="danger" style={{ fontSize: 12, marginTop: 6, marginBottom: 0 }}>
                    {r.error}
                  </Typography.Paragraph>
                )}
                {!r.error && r.output && (
                  <Typography.Paragraph style={{ fontSize: 12, marginTop: 6, marginBottom: 0, whiteSpace: 'pre-wrap', maxHeight: 160, overflow: 'auto' }}>
                    {r.output}
                  </Typography.Paragraph>
                )}
              </div>
            </List.Item>
          )}
        />
      </Drawer>

      {/* Webhook */}
      <Drawer title={`Webhook：${hookTask?.name || ''}`} width={560}
        open={!!hookTask} onClose={() => setHookTask(null)}>
        <Descriptions column={1} size="small" style={{ marginBottom: 12 }}>
          <Descriptions.Item label="用途">外部系统 POST 到该地址即可触发本任务</Descriptions.Item>
        </Descriptions>
        <Button type="primary" icon={<PlusOutlined />} onClick={genHook}>生成令牌</Button>
        {newHook && (          <div style={{ marginTop: 12, padding: 10, background: '#f6f8fa', borderRadius: 6 }}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>完整调用地址（仅显示一次，请立即保存）：</Typography.Text>
            <Typography.Paragraph copyable style={{ marginBottom: 0, fontFamily: 'monospace', fontSize: 12, wordBreak: 'break-all' }}>
              {location.origin}/api/v1/hooks/{newHook}
            </Typography.Paragraph>
          </div>
        )}
        <List
          size="small" style={{ marginTop: 12 }} dataSource={hookTokens}
          locale={{ emptyText: '暂无令牌' }}
          renderItem={(t: any) => (
            <List.Item actions={[
              <Popconfirm key="d" title="删除该令牌？" onConfirm={async () => {
                await (scheduledApi as any).removeWebhook(t.id)
                if (hookTask) setHookTokens(await (scheduledApi as any).webhookTokens(hookTask.id))
              }}>
                <Button size="small" danger icon={<DeleteOutlined />} />
              </Popconfirm>,
            ]}>
              <Space><Tag>{t.name}</Tag><Tag color={t.enabled ? 'green' : 'default'}>{t.enabled ? '启用' : '停用'}</Tag></Space>
            </List.Item>
          )}
        />
      </Drawer>
    </PageContainer>
  )
}
