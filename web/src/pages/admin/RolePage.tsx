import { useEffect, useMemo, useState } from 'react'
import {
  Alert, Button, Card, Checkbox, Collapse, Empty, Form, Input, message, Modal, Popconfirm, Segmented, Select, Space, Table, Tag, Tooltip, Typography,
} from 'antd'
import { PlusOutlined, DeleteOutlined, SafetyOutlined, EditOutlined, UnorderedListOutlined } from '@ant-design/icons'
import { rbacApi, type Role, type PermissionItem } from '../../api'
import { errMsg } from '../../api/http'
import PageContainer from '../../components/PageContainer'
import EmptyState from '../../components/EmptyState'
import { useAuth } from '../../stores/auth'

// 范围：英文 → 中文（含说明）
const SCOPE_META: Record<string, { label: string; color: string; hint: string }> = {
  platform: { label: '平台级', color: 'red', hint: '跨租户，最高权限' },
  tenant: { label: '租户级', color: 'blue', hint: '作用于本企业全部范围' },
  department: { label: '部门级', color: 'cyan', hint: '需授予到具体部门才生效' },
  kb: { label: '知识库级', color: 'green', hint: '需授予到具体知识库才生效' },
}
const SCOPE_ORDER = ['platform', 'tenant', 'department', 'kb']

// 权限资源 code → 中文名
const RES_LABEL: Record<string, string> = {
  kb: '知识库', doc: '文档', chat: '问答', retrieval: '检索', agent: '智能体',
  skill: '技能', tool: '工具', mcp: 'MCP', workflow: '工作流', app: '应用',
  model: '模型', eval: '评测', user: '用户', role: '角色', dept: '部门',
  group: '用户组', audit: '审计', system: '系统', file: '文件', apikey: 'API 密钥',
  sso: '单点登录', notify: '通知', channel: '渠道', service: '客服', record: '录单',
  schedule: '定时任务', tenant: '租户', task: '任务', security: '安全', artifact: '产物',
}

export default function RolePage() {
  const [roles, setRoles] = useState<Role[]>([])
  const [permissions, setPermissions] = useState<PermissionItem[]>([])
  const [tab, setTab] = useState<string>('all')
  const [open, setOpen] = useState(false)
  const [editRole, setEditRole] = useState<Role | null>(null)
  const [permOpen, setPermOpen] = useState(false)
  const [permRole, setPermRole] = useState<Role | null>(null)
  const [checked, setChecked] = useState<number[]>([])
  const [form] = Form.useForm()
  const hasPermission = useAuth((s) => s.hasPermission)
  const canManage = hasPermission('role:manage')

  const load = async () => {
    try {
      const [rs, ps] = await Promise.all([rbacApi.roles(), rbacApi.permissions()])
      setRoles(rs)
      setPermissions(ps)
    } catch (e) { message.error(errMsg(e)) }
  }
  useEffect(() => { load() }, [])

  // 按资源分组权限（中文标题，固定顺序）
  const grouped = useMemo(() => {
    const g: Record<string, PermissionItem[]> = {}
    for (const p of permissions) (g[p.resource] = g[p.resource] || []).push(p)
    const order = Object.keys(RES_LABEL)
    return Object.keys(g)
      .sort((a, b) => {
        const ia = order.indexOf(a), ib = order.indexOf(b)
        return (ia < 0 ? 999 : ia) - (ib < 0 ? 999 : ib)
      })
      .map((res) => ({ res, label: RES_LABEL[res] || res, perms: g[res] }))
  }, [permissions])

  // 按范围分组（Tab 切换）
  const counts = useMemo(() => {
    const c: Record<string, number> = { all: roles.length }
    for (const r of roles) c[r.scope] = (c[r.scope] || 0) + 1
    return c
  }, [roles])
  const shown = useMemo(
    () => (tab === 'all' ? roles : roles.filter((r) => r.scope === tab)),
    [roles, tab],
  )

  const submit = async () => {
    const v = await form.validateFields()
    try {
      if (editRole) await rbacApi.updateRole(editRole.id, { name: v.name, description: v.description })
      else await rbacApi.createRole(v)
      message.success('已保存')
      setOpen(false); form.resetFields(); setEditRole(null); load()
    } catch (e) { message.error(errMsg(e)) }
  }

  const openPerm = async (r: Role) => {
    setPermRole(r)
    try {
      setChecked(await rbacApi.rolePermissions(r.id))
      setPermOpen(true)
    } catch (e) { message.error(errMsg(e)) }
  }

  const savePerm = async () => {
    if (!permRole) return
    try {
      await rbacApi.setRolePermissions(permRole.id, checked)
      message.success('权限已保存')
      setPermOpen(false); load()
    } catch (e) { message.error(errMsg(e)) }
  }

  // 某资源分组全选/取消
  const toggleResource = (perms: PermissionItem[], on: boolean) => {
    const ids = perms.map((p) => p.id)
    setChecked((cur) => on ? Array.from(new Set([...cur, ...ids])) : cur.filter((id) => !ids.includes(id)))
  }

  return (
    <PageContainer
      title="角色管理"
      subtitle="角色决定用户能做什么。新用户默认给「普通用户」；需要建库/管理能力再授予对应角色"
      extra={canManage ? <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditRole(null); form.resetFields(); setOpen(true) }}>
        新建角色
      </Button> : undefined}
    >
      <Card bordered={false}>
        <Segmented
          style={{ marginBottom: 16 }}
          value={tab}
          onChange={(v) => setTab(v as string)}
          options={[
            { value: 'all', label: `全部（${counts.all || 0}）` },
            ...SCOPE_ORDER.filter((s) => counts[s]).map((s) => ({
              value: s, label: `${SCOPE_META[s]?.label || s}（${counts[s]}）`,
            })),
          ]}
        />
        <Table
          rowKey="id" dataSource={shown} pagination={false}
          scroll={{ x: 'max-content' }}
          locale={{ emptyText: <EmptyState description="暂无角色" /> }}
          columns={[
            {
              title: '角色', dataIndex: 'name', width: 220,
              render: (v: string, r: Role) => (
                <Space>
                  <span style={{ fontWeight: 500 }}>{v}</span>
                  {r.is_system
                    ? <Tag color="gold">内置</Tag>
                    : <Tag color="purple">自定义</Tag>}
                </Space>
              ),
            },
            {
              title: '范围', dataIndex: 'scope', width: 120,
              render: (v: string) => {
                const m = SCOPE_META[v]
                return <Tooltip title={m?.hint}><Tag color={m?.color || 'default'}>{m?.label || v}</Tag></Tooltip>
              },
            },
            {
              title: '用途说明', dataIndex: 'description', ellipsis: true,
              render: (v: string) => v
                ? <Typography.Text style={{ fontSize: 13 }}>{v}</Typography.Text>
                : <Typography.Text type="secondary">—</Typography.Text>,
            },
            {
              title: '权限项', dataIndex: 'permission_count', width: 90, align: 'center' as const,
              render: (v: number) => <Tag>{v ?? 0}</Tag>,
            },
            {
              title: '已授予', dataIndex: 'user_count', width: 90, align: 'center' as const,
              render: (v: number) => (v ? <Tag color="blue">{v} 人</Tag> : <Typography.Text type="secondary">0</Typography.Text>),
            },
            {
              title: '操作', width: 180, fixed: 'right' as const,
              render: (_: any, r: Role) => (
                <Space>
                  <Button size="small" icon={<SafetyOutlined />} onClick={() => openPerm(r)}>
                    {canManage && !r.is_system ? '权限' : '查看权限'}
                  </Button>
                  {!r.is_system && canManage && (
                    <>
                      <Button size="small" icon={<EditOutlined />} onClick={() => { setEditRole(r); form.setFieldsValue(r); setOpen(true) }} />
                      <Popconfirm title="删除该角色？" onConfirm={async () => {
                        try { await rbacApi.removeRole(r.id); message.success('已删除'); load() }
                        catch (e) { message.error(errMsg(e)) }
                      }}>
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

      <Modal title={editRole ? '编辑角色' : '新建角色'} open={open} onOk={submit} onCancel={() => setOpen(false)} destroyOnClose>
        <Form form={form} layout="vertical" initialValues={{ scope: 'tenant' }}>
          <Form.Item name="name" label="角色名" rules={[{ required: true }]}><Input /></Form.Item>
          {!editRole && (
            <>
              <Form.Item name="code" label="标识（英文）" rules={[{ required: true }]}
                extra="系统内部使用，创建后不可改，如 kb_manager">
                <Input placeholder="如 kb_manager" />
              </Form.Item>
              <Form.Item name="scope" label="作用范围"
                extra="租户级=作用于全企业；部门级/知识库级需再授予到具体对象">
                <Select options={SCOPE_ORDER.map((s) => ({
                  value: s, label: `${SCOPE_META[s].label}（${SCOPE_META[s].hint}）`,
                }))} />
              </Form.Item>
            </>
          )}
          <Form.Item name="description" label="用途说明" extra="会显示在列表里，说明这个角色能做什么">
            <Input.TextArea rows={2} placeholder="如：可管理全部知识库，但不能管理用户" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={<Space><SafetyOutlined />权限设置：{permRole?.name || ''}
          {permRole && <Tag color={SCOPE_META[permRole.scope]?.color}>{SCOPE_META[permRole.scope]?.label}</Tag>}
        </Space>}
        open={permOpen} onOk={savePerm} onCancel={() => setPermOpen(false)}
        width={760}
        footer={permRole?.is_system ? [<Button key="c" onClick={() => setPermOpen(false)}>关闭</Button>] : undefined}
      >
        {permRole?.is_system && (
          <Alert type="warning" showIcon style={{ marginBottom: 12 }}
            message="内置角色权限不可修改（只读查看）" />
        )}
        {!permRole?.is_system && (
          <Space style={{ marginBottom: 12 }}>
            <Button size="small" onClick={() => setChecked(permissions.map((p) => p.id))}>全选</Button>
            <Button size="small" onClick={() => setChecked([])}>清空</Button>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>已选 {checked.length} / {permissions.length}</Typography.Text>
          </Space>
        )}
        {grouped.length === 0
          ? <Empty description="暂无权限项" />
          : (
            <Collapse
              defaultActiveKey={grouped.slice(0, 3).map((g) => g.res)}
              items={grouped.map((g) => {
                const allOn = g.perms.every((p) => checked.includes(p.id))
                const someOn = g.perms.some((p) => checked.includes(p.id))
                return {
                  key: g.res,
                  label: (
                    <Space>
                      <UnorderedListOutlined />
                      <span>{g.label}</span>
                      <Tag color={allOn ? 'green' : someOn ? 'blue' : 'default'}>
                        {g.perms.filter((p) => checked.includes(p.id)).length}/{g.perms.length}
                      </Tag>
                    </Space>
                  ),
                  extra: !permRole?.is_system && (
                    <a onClick={(e) => { e.stopPropagation(); toggleResource(g.perms, !allOn) }}>
                      {allOn ? '取消全选' : '全选'}
                    </a>
                  ),
                  children: (
                    <Checkbox.Group value={checked} disabled={permRole?.is_system}
                      onChange={(vals) => setChecked(vals as number[])}>
                      <Space wrap>
                        {g.perms.map((p) => (
                          <Checkbox key={p.id} value={p.id}>
                            <Tooltip title={p.code}>{p.name}</Tooltip>
                          </Checkbox>
                        ))}
                      </Space>
                    </Checkbox.Group>
                  ),
                }
              })}
            />
          )}
      </Modal>
    </PageContainer>
  )
}
