import { useEffect, useState } from 'react'
import {
  Button, Card, Checkbox, Form, Input, message, Modal, Popconfirm, Select, Space, Table, Tag, Typography,
} from 'antd'
import { PlusOutlined, DeleteOutlined, SafetyOutlined, EditOutlined } from '@ant-design/icons'
import { rbacApi, type Role, type PermissionItem } from '../../api'
import { errMsg } from '../../api/http'
import PageContainer from '../../components/PageContainer'
import EmptyState from '../../components/EmptyState'
import { useAuth } from '../../stores/auth'

const scopeColor: Record<string, string> = { platform: 'red', tenant: 'blue', department: 'cyan', kb: 'green' }

export default function RolePage() {
  const [roles, setRoles] = useState<Role[]>([])
  const [permissions, setPermissions] = useState<PermissionItem[]>([])
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
      setRoles(await rbacApi.roles())
      setPermissions(await rbacApi.permissions())
    } catch (e) { message.error(errMsg(e)) }
  }
  useEffect(() => { load() }, [])

  // 按 resource 分组权限
  const grouped = permissions.reduce<Record<string, PermissionItem[]>>((acc, p) => {
    (acc[p.resource] = acc[p.resource] || []).push(p)
    return acc
  }, {})

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
      setPermOpen(false)
    } catch (e) { message.error(errMsg(e)) }
  }

  return (
    <PageContainer
      title="角色管理"
      extra={canManage ? <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditRole(null); form.resetFields(); setOpen(true) }}>
        新建角色
      </Button> : undefined}
    >
      <Table
        rowKey="id" dataSource={roles} pagination={false}
        scroll={{ x: 'max-content' }}
        locale={{ emptyText: <EmptyState description="暂无角色" /> }}
        columns={[
          { title: '角色', dataIndex: 'name', render: (v: string, r: Role) => <Space>{v}{r.is_system && <Tag color="gold">内置</Tag>}</Space> },
          { title: '标识', dataIndex: 'code' },
          { title: '范围', dataIndex: 'scope', width: 110, render: (v: string) => <Tag color={scopeColor[v]}>{v}</Tag> },
          { title: '描述', dataIndex: 'description', ellipsis: true },
          {
            title: '操作', width: 200,
            render: (_: any, r: Role) => (
              <Space>
                <Button size="small" icon={<SafetyOutlined />} onClick={() => openPerm(r)}>{canManage ? '权限' : '查看权限'}</Button>
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

      <Modal title={editRole ? '编辑角色' : '新建角色'} open={open} onOk={submit} onCancel={() => setOpen(false)} destroyOnClose>
        <Form form={form} layout="vertical" initialValues={{ scope: 'tenant' }}>
          <Form.Item name="name" label="角色名" rules={[{ required: true }]}><Input /></Form.Item>
          {!editRole && (
            <>
              <Form.Item name="code" label="标识（英文）" rules={[{ required: true }]}><Input placeholder="如 kb_manager" /></Form.Item>
              <Form.Item name="scope" label="范围" extra="platform/tenant/department/kb">
                <Select options={[
                  { value: 'tenant', label: 'tenant' },
                  { value: 'platform', label: 'platform' },
                  { value: 'department', label: 'department' },
                  { value: 'kb', label: 'kb' },
                ]} />
              </Form.Item>
            </>
          )}
          <Form.Item name="description" label="描述"><Input.TextArea rows={2} /></Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`权限矩阵：${permRole?.name || ''}`}
        open={permOpen} onOk={savePerm} onCancel={() => setPermOpen(false)}
        width={720}
        footer={permRole?.is_system ? [<Button key="c" onClick={() => setPermOpen(false)}>关闭</Button>] : undefined}
      >
        {permRole?.is_system && <Typography.Paragraph type="warning">内置角色权限不可修改（只读查看）</Typography.Paragraph>}
        {Object.entries(grouped).map(([resource, perms]) => (
          <Card key={resource} size="small" title={resource} style={{ marginBottom: 12 }}
            styles={{ body: { padding: 12 } }}>
            <Checkbox.Group
              value={checked}
              disabled={permRole?.is_system}
              onChange={(vals) => setChecked(vals as number[])}
            >
              <Space wrap>
                {perms.map((p) => (
                  <Checkbox key={p.id} value={p.id}>{p.name}</Checkbox>
                ))}
              </Space>
            </Checkbox.Group>
          </Card>
        ))}
      </Modal>
    </PageContainer>
  )
}
