import { useEffect, useState } from 'react'
import {
  Button, Form, Input, message, Modal, Popconfirm, Select, Space, Table,
} from 'antd'
import { PlusOutlined, DeleteOutlined, ApartmentOutlined } from '@ant-design/icons'
import { rbacApi, type DeptNode } from '../../api'
import { errMsg } from '../../api/http'
import PageContainer from '../../components/PageContainer'
import EmptyState from '../../components/EmptyState'
import { useAuth } from '../../stores/auth'

export default function DeptPage() {
  const [tree, setTree] = useState<DeptNode[]>([])
  const [open, setOpen] = useState(false)
  const [parentId, setParentId] = useState<number | null>(null)
  const [editDept, setEditDept] = useState<DeptNode | null>(null)
  const [form] = Form.useForm()
  const hasPermission = useAuth((s) => s.hasPermission)
  const canManage = hasPermission('dept:manage')

  const load = async () => {
    try { setTree(await rbacApi.deptTree()) }
    catch (e) { message.error(errMsg(e)) }
  }
  useEffect(() => { load() }, [])

  // 摊平用于父部门选择
  const flat: { value: number; label: string }[] = []
  const walk = (nodes: DeptNode[], depth = 0) => {
    for (const n of nodes) {
      flat.push({ value: n.id, label: '　'.repeat(depth) + n.name })
      if (n.children?.length) walk(n.children, depth + 1)
    }
  }
  walk(tree)

  const openCreate = (pid: number | null) => {
    setEditDept(null); setParentId(pid); form.resetFields(); setOpen(true)
  }
  const openEdit = (d: DeptNode) => {
    setEditDept(d); setParentId(d.parent_id ?? null)
    form.setFieldsValue({ name: d.name, code: d.code })
    setOpen(true)
  }

  const submit = async () => {
    const v = await form.validateFields()
    try {
      if (editDept) await rbacApi.updateDept(editDept.id, v)
      else await rbacApi.createDept({ ...v, parent_id: parentId })
      message.success('已保存')
      setOpen(false); form.resetFields(); setParentId(null); setEditDept(null); load()
    } catch (e) { message.error(errMsg(e)) }
  }

  return (
    <PageContainer
      title="部门管理"
      extra={canManage ? <Button type="primary" icon={<PlusOutlined />} onClick={() => openCreate(null)}>
        新建部门
      </Button> : undefined}
    >
      <Table
        rowKey="id" dataSource={tree} pagination={false}
        scroll={{ x: 'max-content' }}
        defaultExpandAllRows
        expandable={{ defaultExpandAllRows: true }}
        locale={{ emptyText: <EmptyState description="暂无部门" /> }}
        columns={[
          { title: '部门', dataIndex: 'name', render: (v: string) => <Space><ApartmentOutlined />{v}</Space> },
          { title: '标识', dataIndex: 'code' },
          { title: 'path', dataIndex: 'path', width: 140 },
          { title: '层级', dataIndex: 'depth', width: 70 },
          {
            title: '操作', width: 260,
            render: (_: any, r: DeptNode) => (
              <Space>
                {canManage && (
                  <>
                    <Button size="small" icon={<PlusOutlined />} onClick={() => openCreate(r.id)}>子部门</Button>
                    <Button size="small" onClick={() => openEdit(r)}>编辑</Button>
                    <Popconfirm title="删除该部门？" onConfirm={async () => {
                      try { await rbacApi.removeDept(r.id); message.success('已删除'); load() }
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

      <Modal
        title={editDept ? '编辑部门' : (parentId ? `新建子部门（父：${flat.find((f) => f.value === parentId)?.label.trim()}）` : '新建部门')}
        open={open} onOk={submit} onCancel={() => setOpen(false)} destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="部门名" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="code" label="标识（可选）"><Input /></Form.Item>
          {!parentId && (
            <Form.Item label="上级部门">
              <Select allowClear placeholder="留空=顶级部门" options={flat}
                onChange={(v) => setParentId(v ?? null)} />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </PageContainer>
  )
}
