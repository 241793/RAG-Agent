import { useEffect, useState } from 'react'
import {
  Button, Card, Form, Input, message, Modal, Popconfirm, Select, Space, Table,
} from 'antd'
import { PlusOutlined, DeleteOutlined, TeamOutlined } from '@ant-design/icons'
import { rbacApi, type UserListItem } from '../../api'
import { errMsg } from '../../api/http'
import PageContainer from '../../components/PageContainer'
import EmptyState from '../../components/EmptyState'
import { useAuth } from '../../stores/auth'

interface Group {
  id: number
  name: string
  description?: string
}

export default function GroupPage() {
  const [groups, setGroups] = useState<Group[]>([])
  const [users, setUsers] = useState<UserListItem[]>([])
  const [open, setOpen] = useState(false)
  const [editGroup, setEditGroup] = useState<Group | null>(null)
  const [form] = Form.useForm()
  const hasPermission = useAuth((s) => s.hasPermission)
  const canManage = hasPermission('group:manage')

  const [memOpen, setMemOpen] = useState(false)
  const [curGroup, setCurGroup] = useState<Group | null>(null)
  const [members, setMembers] = useState<number[]>([])

  const load = async () => {
    try {
      setGroups(await rbacApi.groups())
      const r = await rbacApi.users(1, 100)
      setUsers(r.items)
    } catch (e) { message.error(errMsg(e)) }
  }
  useEffect(() => { load() }, [])

  const openCreate = () => { setEditGroup(null); form.resetFields(); setOpen(true) }
  const openEdit = (g: Group) => { setEditGroup(g); form.setFieldsValue(g); setOpen(true) }

  const saveGroup = async () => {
    const v = await form.validateFields()
    try {
      if (editGroup) await rbacApi.updateGroup(editGroup.id, v)
      else await rbacApi.createGroup(v)
      message.success('已保存')
      setOpen(false); form.resetFields(); setEditGroup(null); load()
    } catch (e) { message.error(errMsg(e)) }
  }

  const openMembers = async (g: Group) => {
    setCurGroup(g)
    try {
      setMembers(await rbacApi.groupMembers(g.id))
      setMemOpen(true)
    } catch (e) { message.error(errMsg(e)) }
  }

  const saveMembers = async () => {
    if (!curGroup) return
    try {
      await rbacApi.setGroupMembers(curGroup.id, members)
      message.success('成员已保存')
      setMemOpen(false)
    } catch (e) { message.error(errMsg(e)) }
  }

  return (
    <PageContainer
      title="用户组"
      subtitle="把用户分组，便于批量授权（可被知识库成员、文档 ACL 引用）"
      extra={canManage ? <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建用户组</Button> : undefined}
    >
      <Card bordered={false}>
      <Table
        rowKey="id" dataSource={groups} pagination={false}
        locale={{ emptyText: <EmptyState description="暂无用户组" actionText={canManage ? '新建用户组' : undefined} onAction={openCreate} /> }}
        columns={[
          { title: '组名', dataIndex: 'name', render: (v: string) => <Space><TeamOutlined />{v}</Space> },
          { title: '描述', dataIndex: 'description', ellipsis: true },
          {
            title: '操作', width: 240,
            render: (_: any, g: Group) => (
              <Space>
                <Button size="small" onClick={() => openMembers(g)}>成员</Button>
                {canManage && (
                  <>
                    <Button size="small" onClick={() => openEdit(g)}>编辑</Button>
                    <Popconfirm title="删除该用户组？" onConfirm={async () => {
                      try { await rbacApi.removeGroup(g.id); message.success('已删除'); load() }
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

      <Modal title={editGroup ? '编辑用户组' : '新建用户组'} open={open} onOk={saveGroup} onCancel={() => setOpen(false)} destroyOnClose>
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="组名" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="description" label="描述"><Input.TextArea rows={2} /></Form.Item>
        </Form>
      </Modal>

      <Modal title={`成员管理：${curGroup?.name || ''}`} open={memOpen} onOk={saveMembers} onCancel={() => setMemOpen(false)}>
        <Select
          mode="multiple" style={{ width: '100%' }} placeholder="选择成员"
          value={members} onChange={setMembers}
          options={users.map((u) => ({ value: u.id, label: `${u.display_name || u.username}（${u.username}）` }))}
        />
      </Modal>
    </PageContainer>
  )
}
