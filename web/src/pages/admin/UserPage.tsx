import { useEffect, useState } from 'react'
import {
  Alert, Button, Card, Divider, Form, Input, message, Modal, Popconfirm, Select, Space, Table, Tag, Tooltip,
} from 'antd'
import { PlusOutlined, DeleteOutlined, UserAddOutlined, KeyOutlined, LockOutlined } from '@ant-design/icons'
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
  const me = useAuth((s) => s.user)
  const canManage = hasPermission('user:manage')

  const [roleOpen, setRoleOpen] = useState(false)
  const [curUser, setCurUser] = useState<UserListItem | null>(null)
  const [userRoles, setUserRoles] = useState<UserRoleItem[]>([])
  const [grantForm] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [pending, setPending] = useState<{ id: number; username: string; display_name: string; email: string | null; department_id?: number | null; department_name?: string | null; reason: string | null; registered_at: string | null }[]>([])

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

  // 管理员重置用户密码（会强制该用户下线）
  const resetPwd = (u: UserListItem) => {
    let pwd = ''
    Modal.confirm({
      title: `重置「${u.display_name || u.username}」的密码`,
      icon: null,
      content: (
        <div>
          <Input.Password autoFocus placeholder="输入新密码（≥8 位，含字母/数字/符号至少两类）"
            onChange={(e) => { pwd = e.target.value }} />
          <div style={{ fontSize: 12, color: 'var(--color-text-3)', marginTop: 6 }}>
            重置后该用户会被强制下线，需用新密码重新登录
          </div>
        </div>
      ),
      okText: '重置', cancelText: '取消',
      onOk: async () => {
        if (!pwd || pwd.length < 8) { message.warning('密码至少 8 位'); throw new Error('bad') }
        try { await rbacApi.resetUserPassword(u.id, pwd); message.success('密码已重置，该用户需重新登录') }
        catch (e) { message.error(errMsg(e)); throw e }
      },
    })
  }

  // 删除用户（物理删除，带后果说明）
  const removeUser = (u: UserListItem) => {
    Modal.confirm({
      title: `删除用户「${u.display_name || u.username}」？`,
      okText: '删除', okButtonProps: { danger: true }, cancelText: '取消',
      content: (
        <div style={{ fontSize: 13 }}>
          <p style={{ marginTop: 8 }}>该操作<strong>不可恢复</strong>，将同时清除其角色授予与站内通知。</p>
          <p style={{ marginBottom: 0, color: 'var(--color-text-3)' }}>
            若只是想临时禁用，请改用「停用」。
          </p>
        </div>
      ),
      onOk: async () => {
        try { const r = await rbacApi.removeUser(u.id); message.success(r.message || '已删除'); load(); loadPending() }
        catch (e) { message.error(errMsg(e)); throw e }
      },
    })
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
                  {p.department_name && <Tag color="blue">部门：{p.department_name}</Tag>}
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
            title: '操作', width: 320, fixed: 'right' as const,
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
                    <Tooltip title="重置密码（会强制该用户下线）">
                      <Button size="small" icon={<LockOutlined />} disabled={u.id === me?.id} onClick={() => resetPwd(u)} />
                    </Tooltip>
                    <Popconfirm title="停用该用户？" onConfirm={async () => {
                      try { await rbacApi.updateUser(u.id, { status: u.status === 'active' ? 'disabled' : 'active' }); load() }
                      catch (e) { message.error(errMsg(e)) }
                    }}>
                      <Button size="small">{u.status === 'active' ? '停用' : '启用'}</Button>
                    </Popconfirm>
                    <Tooltip title={u.id === me?.id ? '不能删除自己' : '删除用户（不可恢复）'}>
                      <Button size="small" danger icon={<DeleteOutlined />} disabled={u.id === me?.id}
                        onClick={() => removeUser(u)} />
                    </Tooltip>
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
            <Select placeholder="选择角色" style={{ width: 220 }}
              onChange={(v) => {
                // 角色决定作用范围：选角色后自动切换 scope_type，避免「角色×范围」错配
                const r = roles.find((x) => x.id === v)
                const sc = r?.scope || 'tenant'
                setScopeType(sc)
                grantForm.setFieldValue('scope_type', sc)
                grantForm.setFieldValue('scope_id', sc === 'tenant' || sc === 'platform' ? 0 : undefined)
              }}
              options={roles.map((r) => ({
                value: r.id,
                label: `${r.name}（${scopeLabel[r.scope] || r.scope}）${r.is_system ? '' : ' · 自定义'}`,
              }))} />
          </Form.Item>
          <Form.Item name="scope_type" hidden><Input /></Form.Item>
          {scopeType === 'department' && (
            <Form.Item name="scope_id" rules={[{ required: true, message: '请选择部门' }]}
              extra="须与用户所属部门一致才生效">
              <Select placeholder="选择部门" style={{ width: 200 }} options={depts} showSearch optionFilterProp="label" />
            </Form.Item>
          )}
          {scopeType === 'kb' && (
            <Form.Item name="scope_id" rules={[{ required: true, message: '请选择知识库' }]}>
              <Select placeholder="选择知识库" style={{ width: 200 }} options={kbs} showSearch optionFilterProp="label" />
            </Form.Item>
          )}
          {(scopeType === 'tenant' || scopeType === 'platform') && (
            <Form.Item>
              <span style={{ fontSize: 12, color: 'var(--color-text-3)' }}>
                该角色作用于{scopeLabel[scopeType] || scopeType}，无需指定具体对象
              </span>
            </Form.Item>
          )}
          <Button type="primary" icon={<UserAddOutlined />} onClick={grant}>授予</Button>
        </Form>
      </Modal>
    </PageContainer>
  )
}
