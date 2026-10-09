import { useEffect, useState } from 'react'
import {
  Alert, Button, Card, Divider, Form, Input, message, Modal, Popconfirm, Select, Space, Table, Tag,
} from 'antd'
import { PlusOutlined, DeleteOutlined, UserAddOutlined, KeyOutlined } from '@ant-design/icons'
import { rbacApi, kbApi, type Role, type UserListItem, type UserRoleItem, type DeptNode } from '../../api'
import { errMsg } from '../../api/http'
import PageContainer from '../../components/PageContainer'
import { useAuth } from '../../stores/auth'

const scopeLabel: Record<string, string> = {
  platform: '平台', tenant: '租户', department: '部门', kb: '知识库',
}

function flattenDepts(nodes: DeptNode[], depth = 0): { value: number; label: string }[] {
  const out: { value: number; label: string }[] = []
  for (const n of nodes) {
    out.push({ value: n.id, label: '　'.repeat(depth) + n.name })
    if (n.children?.length) out.push(...flattenDepts(n.children, depth + 1))
  }
  return out
}

export default function UserPage() {
  const [users, setUsers] = useState<UserListItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [roles, setRoles] = useState<Role[]>([])
  const [depts, setDepts] = useState<{ value: number; label: string }[]>([])
  const [kbs, setKbs] = useState<{ value: number; label: string }[]>([])
  const [scopeType, setScopeType] = useState<string>('tenant')
  const [open, setOpen] = useState(false)
  const [editUser, setEditUser] = useState<UserListItem | null>(null)
  const [form] = Form.useForm()
  const hasPermission = useAuth((s) => s.hasPermission)
  const canManage = hasPermission('user:manage')

  const [roleOpen, setRoleOpen] = useState(false)
  const [curUser, setCurUser] = useState<UserListItem | null>(null)
  const [userRoles, setUserRoles] = useState<UserRoleItem[]>([])
  const [grantForm] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [pending, setPending] = useState<{ id: number; username: string; display_name: string; email: string | null; reason: string | null; registered_at: string | null }[]>([])

  const loadPending = async () => {
    try { setPending(await rbacApi.pendingUsers()) } catch { /* 无权或忽略 */ }
  }

  const reviewUser = async (id: number, approve: boolean, name: string) => {
    try {
      if (approve) await rbacApi.approveUser(id)
      else await rbacApi.rejectUser(id)
      message.success(`${approve ? '已通过' : '已拒绝'}「${name}」的注册申请`)
      load(); loadPending()
    } catch (e) { message.error(errMsg(e)) }
  }

  const load = async () => {
    setLoading(true)
    try {
      const r = await rbacApi.users(page, 20, search || undefined)
      setUsers(r.items); setTotal(r.total)
      setRoles(await rbacApi.roles())
      const tree = await rbacApi.deptTree()
      setDepts(flattenDepts(tree))
      kbApi.list().then((ks) => setKbs(ks.map((k) => ({ value: k.id, label: k.name })))).catch(() => {})
    } catch (e) { message.error(errMsg(e)) } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [page, search])
  useEffect(() => { loadPending() }, [])

  const openCreate = () => {
    setEditUser(null); form.resetFields(); setOpen(true)
  }

  const openEdit = (u: UserListItem) => {
    setEditUser(u)
    form.setFieldsValue({
      username: u.username, display_name: u.display_name, email: u.email,
      department_id: u.department_id,
    })
    setOpen(true)
  }

  const createUser = async () => {
    const v = await form.validateFields()
    try {
      if (editUser) {
        await rbacApi.updateUser(editUser.id, {
          display_name: v.display_name, email: v.email, department_id: v.department_id,
        })
        message.success('已保存')
      } else {
        await rbacApi.createUser(v)
        message.success('已创建')
      }
      setOpen(false); form.resetFields(); setEditUser(null); load()
    } catch (e) { message.error(errMsg(e)) }
  }

  const openRoles = async (u: UserListItem) => {
    setCurUser(u)
    try {
      setUserRoles(await rbacApi.userRoles(u.id))
      setRoleOpen(true)
    } catch (e) { message.error(errMsg(e)) }
  }

  const grant = async () => {
    if (!curUser) return
    const v = await grantForm.validateFields()
    try {
      await rbacApi.grantRole(curUser.id, v)
      message.success('已授予')
      grantForm.resetFields()
      setUserRoles(await rbacApi.userRoles(curUser.id))
    } catch (e) { message.error(errMsg(e)) }
  }

  return (
    <PageContainer
      title="用户管理"
      subtitle="管理租户内的用户、分配角色"
      extra={
        <Space>
          <Input.Search placeholder="搜索用户名/姓名" allowClear style={{ width: 220 }}
            onSearch={(v) => { setSearch(v); setPage(1) }} />
          {canManage && <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建用户</Button>}
        </Space>
      }
    >
      <Card bordered={false}>
      {pending.length > 0 && (
        <Alert type="warning" showIcon style={{ marginBottom: 16 }}
          message={`有 ${pending.length} 个注册申请待审核`}
          description={
            <Space direction="vertical" style={{ width: '100%' }} size={8}>
              {pending.map((p) => (
                <div key={p.id} style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                  <b>{p.display_name || p.username}</b>
                  <span style={{ color: 'var(--color-text-2)' }}>@{p.username}</span>
                  {p.email && <span style={{ color: 'var(--color-text-3)' }}>{p.email}</span>}
                  {p.reason && <Tag>理由：{p.reason}</Tag>}
                  {canManage && (
                    <Space>
                      <Button size="small" type="primary" onClick={() => reviewUser(p.id, true, p.display_name || p.username)}>通过</Button>
                      <Popconfirm title="拒绝该申请？" onConfirm={() => reviewUser(p.id, false, p.display_name || p.username)}>
                        <Button size="small" danger>拒绝</Button>
                      </Popconfirm>
                    </Space>
                  )}
                </div>
              ))}
            </Space>
          } />
      )}
      <Table
        rowKey="id" dataSource={users} loading={loading}
        pagination={{ current: page, pageSize: 20, total, onChange: setPage }}
        columns={[
          { title: '用户名', dataIndex: 'username' },
          { title: '姓名', dataIndex: 'display_name' },
          { title: '邮箱', dataIndex: 'email' },
          { title: '状态', dataIndex: 'status', width: 90, render: (v: string) => <Tag color={v === 'active' ? 'green' : 'red'}>{v}</Tag> },
          { title: '审核', dataIndex: 'approval_status', width: 90,
            render: (v: string) => v === 'pending' ? <Tag color="orange">待审核</Tag>
              : v === 'rejected' ? <Tag color="red">已拒绝</Tag> : <Tag color="green">已通过</Tag> },
          { title: '管理员', dataIndex: 'is_admin', width: 90, render: (v: boolean) => v ? <Tag color="gold">是</Tag> : '-' },
          {
            title: '操作', width: 260,
            render: (_: any, u: UserListItem) => (
              <Space>
                {canManage && (
                  <>
                    {u.approval_status === 'pending' && (
                      <>
                        <Button size="small" type="primary" onClick={() => reviewUser(u.id, true, u.display_name || u.username)}>通过</Button>
                        <Popconfirm title="拒绝该申请？" onConfirm={() => reviewUser(u.id, false, u.display_name || u.username)}>
                          <Button size="small" danger>拒绝</Button>
                        </Popconfirm>
                      </>
                    )}
                    <Button size="small" onClick={() => openEdit(u)}>编辑</Button>
                    <Button size="small" icon={<KeyOutlined />} onClick={() => openRoles(u)}>角色</Button>
                    <Popconfirm title="停用该用户？" onConfirm={async () => {
                      try { await rbacApi.updateUser(u.id, { status: u.status === 'active' ? 'disabled' : 'active' }); load() }
                      catch (e) { message.error(errMsg(e)) }
                    }}>
                      <Button size="small">{u.status === 'active' ? '停用' : '启用'}</Button>
                    </Popconfirm>
                  </>
                )}
              </Space>
            ),
          },
        ]}
      />
      </Card>

      <Modal title={editUser ? '编辑用户' : '新建用户'} open={open} onOk={createUser} onCancel={() => setOpen(false)} destroyOnClose>
        <Form form={form} layout="vertical">
          <Form.Item name="username" label="用户名" rules={[{ required: !editUser }]}>
            <Input disabled={!!editUser} />
          </Form.Item>
          {!editUser && (
            <Form.Item name="password" label="密码" rules={[{ required: true, min: 6 }]}><Input.Password /></Form.Item>
          )}
          <Form.Item name="display_name" label="姓名"><Input /></Form.Item>
          <Form.Item name="email" label="邮箱"><Input /></Form.Item>
          <Form.Item name="department_id" label="部门">
            <Select allowClear options={depts} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title={`角色授予：${curUser?.username || ''}`} open={roleOpen} onCancel={() => setRoleOpen(false)} footer={null} width={640}>
        <Table
          rowKey="id" size="small" dataSource={userRoles} pagination={false}
          columns={[
            { title: '角色', render: (_: any, r: UserRoleItem) => r.role_name || r.role_code || r.role_id },
            { title: '范围', dataIndex: 'scope_type', render: (v: string) => <Tag>{scopeLabel[v] || v}</Tag> },
            { title: 'scope_id', dataIndex: 'scope_id', width: 90 },
            {
              title: '操作', width: 80,
              render: (_: any, r: UserRoleItem) => (
                <Popconfirm title="撤销该角色？" onConfirm={async () => {
                  if (!curUser) return
                  try { await rbacApi.revokeRole(curUser.id, r.id); setUserRoles(await rbacApi.userRoles(curUser.id)) }
                  catch (e) { message.error(errMsg(e)) }
                }}>
                  <Button size="small" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              ),
            },
          ]}
        />
        <Divider />
        <Form form={grantForm} layout="inline" initialValues={{ scope_type: 'tenant', scope_id: 0 }}>
          <Form.Item name="role_id" rules={[{ required: true, message: '选角色' }]}>
            <Select placeholder="选择角色" style={{ width: 160 }} options={roles.map((r) => ({ value: r.id, label: `${r.name}（${r.scope}）` }))} />
          </Form.Item>
          <Form.Item name="scope_type">
            <Select style={{ width: 120 }} onChange={(v) => {
              setScopeType(v)
              // 切换范围类型时重置 scope_id，避免残留上一个类型的 id
              grantForm.setFieldValue('scope_id', v === 'department' ? undefined : 0)
            }} options={[
              { value: 'tenant', label: '租户' },
              { value: 'department', label: '部门' },
              { value: 'kb', label: '知识库' },
              { value: 'platform', label: '平台' },
            ]} />
          </Form.Item>
          <Form.Item name="scope_id" rules={[{ required: scopeType === 'department' || scopeType === 'kb', message: '请选择范围' }]}>
            {scopeType === 'department' ? (
              <Select placeholder="选择部门" style={{ width: 180 }} options={depts} showSearch optionFilterProp="label" />
            ) : scopeType === 'kb' ? (
              <Select placeholder="选择知识库" style={{ width: 180 }} options={kbs} showSearch optionFilterProp="label" />
            ) : (
              <Input type="number" style={{ width: 100 }} placeholder="scope_id"
                disabled={scopeType === 'tenant' || scopeType === 'platform'} />
            )}
          </Form.Item>
          <Button type="primary" icon={<UserAddOutlined />} onClick={grant}>授予</Button>
        </Form>
      </Modal>
    </PageContainer>
  )
}
