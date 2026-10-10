import { useEffect, useState } from 'react'
import {
  Card, DatePicker, Descriptions, Drawer, Input, Select, Space, Table, Tag,
} from 'antd'
import dayjs from 'dayjs'
import { auditApi, type AuditLogItem } from '../../api'
import { errMsg } from '../../api/http'
import { message } from 'antd'
import PageContainer from '../../components/PageContainer'
import EmptyState from '../../components/EmptyState'

const actionColor = (a: string) =>
  a.includes('delete') || a.includes('revoke') ? 'red'
    : a.includes('create') || a.includes('grant') || a.includes('add') ? 'green'
      : a.includes('update') || a.includes('publish') ? 'blue'
        : 'default'

export default function AuditPage() {
  const [items, setItems] = useState<AuditLogItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [action, setAction] = useState<string | undefined>()
  const [result, setResult] = useState<string | undefined>()
  const [resourceType, setResourceType] = useState<string | undefined>()
  const [resourceId, setResourceId] = useState<string | undefined>()
  const [range, setRange] = useState<any>(null)
  const [detail, setDetail] = useState<AuditLogItem | null>(null)

  const load = async () => {
    try {
      const params: Record<string, any> = { page, page_size: 20 }
      if (action) params.action = action
      if (result) params.result = result
      if (resourceType) params.resource_type = resourceType
      if (resourceId) params.resource_id = resourceId
      if (range?.[0]) params.start = range[0].valueOf()
      if (range?.[1]) params.end = range[1].valueOf()
      const r = await auditApi.list(params)
      setItems(r.items); setTotal(r.total)
    } catch (e) { message.error(errMsg(e)) }
  }
  useEffect(() => { load() }, [page, action, result, resourceType, resourceId, range])

  // 点某个对象的「对象」列 → 按该对象过滤（追溯它的全部操作）
  const filterByObject = (r: AuditLogItem) => {
    if (!r.resource_type) return
    setResourceType(r.resource_type)
    setResourceId(r.resource_id != null ? String(r.resource_id) : undefined)
    setPage(1)
  }

  return (
    <PageContainer title="审计日志" subtitle="所有写操作与登录行为留痕。点击表格「对象」可追溯该对象的全部操作">
      <Card style={{ marginBottom: 16 }} size="small">
        <Space wrap>
          <Input.Search placeholder="按动作前缀过滤，如 user / role / doc"
            style={{ width: 240 }} allowClear
            onSearch={(v) => { setAction(v || undefined); setPage(1) }} />
          <Select placeholder="对象类型" allowClear style={{ width: 150 }}
            value={resourceType} onChange={(v) => { setResourceType(v); setPage(1) }}
            options={[
              { value: 'user', label: '用户' }, { value: 'user_role', label: '角色授予' },
              { value: 'role', label: '角色' }, { value: 'department', label: '部门' },
              { value: 'user_group', label: '用户组' }, { value: 'kb', label: '知识库' },
              { value: 'document', label: '文档' }, { value: 'agent', label: '智能体' },
              { value: 'skill', label: '技能' }, { value: 'tool', label: '工具' },
              { value: 'workflow', label: '工作流' }, { value: 'scheduled_task', label: '定时任务' },
              { value: 'model_provider', label: '模型 Provider' }, { value: 'system', label: '系统' },
            ]} />
          <Input placeholder="对象 ID" style={{ width: 120 }} allowClear
            value={resourceId} onChange={(e) => { setResourceId(e.target.value || undefined); setPage(1) }} />
          <Select placeholder="结果" allowClear style={{ width: 110 }}
            value={result} onChange={(v) => { setResult(v); setPage(1) }}
            options={[{ value: 'success', label: '成功' }, { value: 'failure', label: '失败' }]} />
          <DatePicker.RangePicker showTime value={range} onChange={setRange} />
        </Space>
      </Card>

      <Table
        rowKey="id" dataSource={items}
        scroll={{ x: 'max-content' }}
        pagination={{ current: page, pageSize: 20, total, onChange: setPage }}
        locale={{ emptyText: <EmptyState description="暂无审计记录" /> }}
        onRow={(r) => ({ onClick: () => setDetail(r), style: { cursor: 'pointer' } })}
        columns={[
          { title: '时间', dataIndex: 'created_at', width: 170,
            render: (v: number) => dayjs(v).format('YYYY-MM-DD HH:mm:ss') },
          { title: '操作者', dataIndex: 'actor_name', width: 120, render: (v) => v || '-' },
          { title: '动作', dataIndex: 'action', render: (v: string) => <Tag color={actionColor(v)}>{v}</Tag> },
          {
            title: '对象', width: 180,
            render: (_: any, r: AuditLogItem) => r.resource_type
              ? <a onClick={(e) => { e.stopPropagation(); filterByObject(r) }} title="点击追溯该对象的全部操作">
                {r.resource_type}#{r.resource_id ?? ''}
              </a>
              : '-',
          },
          { title: '结果', dataIndex: 'result', width: 90,
            render: (v: string) => <Tag color={v === 'success' ? 'green' : 'red'}>{v === 'success' ? '成功' : '失败'}</Tag> },
          { title: 'IP', dataIndex: 'ip', width: 130 },
        ]}
      />

      <Drawer title="审计详情" width={560} open={!!detail} onClose={() => setDetail(null)}>
        {detail && (
          <Descriptions column={1} size="small" bordered>
            <Descriptions.Item label="时间">{dayjs(detail.created_at).format('YYYY-MM-DD HH:mm:ss')}</Descriptions.Item>
            <Descriptions.Item label="操作者">{detail.actor_name || '-'}（{detail.actor_type}）</Descriptions.Item>
            <Descriptions.Item label="动作">{detail.action}</Descriptions.Item>
            <Descriptions.Item label="对象">{detail.resource_type}#{detail.resource_id}</Descriptions.Item>
            <Descriptions.Item label="结果">{detail.result}</Descriptions.Item>
            {detail.error && <Descriptions.Item label="错误">{detail.error}</Descriptions.Item>}
            <Descriptions.Item label="IP">{detail.ip}</Descriptions.Item>
            <Descriptions.Item label="User-Agent">{detail.user_agent}</Descriptions.Item>
            <Descriptions.Item label="Request ID">{detail.request_id}</Descriptions.Item>
            <Descriptions.Item label="变更前">
              <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{JSON.stringify(detail.before, null, 2)}</pre>
            </Descriptions.Item>
            <Descriptions.Item label="变更后">
              <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{JSON.stringify(detail.after, null, 2)}</pre>
            </Descriptions.Item>
          </Descriptions>
        )}
      </Drawer>
    </PageContainer>
  )
}
