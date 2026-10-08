import { useEffect, useState } from 'react'
import {
  Alert, Button, Card, Form, Input, message, Modal, Popconfirm, Select, Space, Switch, Table, Tag,
  Typography,
} from 'antd'
import {
  PlusOutlined, DeleteOutlined, EditOutlined, FileExcelOutlined,
  ThunderboltOutlined, MinusCircleOutlined,
} from '@ant-design/icons'
import { recordApi, type RecordTemplateItem } from '../../api'
import { errMsg } from '../../api/http'
import PageContainer from '../../components/PageContainer'
import EmptyState from '../../components/EmptyState'
import Can from '../../components/Can'
import { useAuth } from '../../stores/auth'

const FIELD_TYPES = [
  { value: 'text', label: '文本' }, { value: 'number', label: '数字' },
  { value: 'date', label: '日期' }, { value: 'phone', label: '电话' }, { value: 'enum', label: '枚举' },
]

export default function RecordPage() {
  const hasPermission = useAuth((s) => s.hasPermission)
  const canManage = hasPermission('record:manage')
  const [templates, setTemplates] = useState<RecordTemplateItem[]>([])
  const [loading, setLoading] = useState(false)
  const [tOpen, setTOpen] = useState(false)
  const [edit, setEdit] = useState<RecordTemplateItem | null>(null)
  const [tForm] = Form.useForm()

  // 抽取面板
  const [cur, setCur] = useState<RecordTemplateItem | null>(null)
  const [text, setText] = useState('')
  const [extracting, setExtracting] = useState(false)
  const [entries, setEntries] = useState<{ id: number; data: Record<string, any>; status: string }[]>([])

  const load = async () => {
    setLoading(true)
    try { setTemplates(await recordApi.listTemplates()) }
    catch (e) { message.error(errMsg(e)) } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  const openTemplate = (t?: RecordTemplateItem) => {
    setEdit(t || null)
    tForm.setFieldsValue(t ? { ...t, fields: t.fields || [{ name: '', label: '', type: 'text' }] }
      : { enabled: true, fields: [{ name: '', label: '', type: 'text' }] })
    setTOpen(true)
  }

  const saveTemplate = async () => {
    const v = await tForm.validateFields().catch(() => null)
    if (!v) return
    const fields = (v.fields || []).filter((f: any) => f?.name)
    if (!fields.length) { message.error('至少定义一个字段（name）'); return }
    const payload = { ...v, fields }
    try {
      if (edit) await recordApi.updateTemplate(edit.id, payload)
      else await recordApi.createTemplate(payload)
      message.success('已保存'); setTOpen(false); load()
    } catch (e) { message.error(errMsg(e)) }
  }

  const openPanel = async (t: RecordTemplateItem) => {
    setCur(t); setText(''); setEntries([])
    try { setEntries(await recordApi.entries(t.id)) } catch { /* ignore */ }
  }

  const doExtract = async () => {
    if (!cur || !text.trim()) { message.info('请输入要抽取的文本'); return }
    setExtracting(true)
    try {
      const r = await recordApi.extract({ template_id: cur.id, text: text.trim(), save: true })
      message.success(`已抽取 ${r.count} 条记录`)
      setText(''); setEntries(await recordApi.entries(cur.id))
    } catch (e) { message.error(errMsg(e)) } finally { setExtracting(false) }
  }

  const exportLedger = (fmt: 'xlsx' | 'csv' | 'md') => {
    if (!cur) return
    const token = localStorage.getItem('access_token') || ''
    fetch(recordApi.exportUrl(cur.id, fmt), { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => { if (!r.ok) throw new Error('导出失败'); return r.blob() })
      .then((blob) => {
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url; a.download = `${cur.name}-台账.${fmt}`; a.click(); URL.revokeObjectURL(url)
      })
      .catch((e) => message.error(errMsg(e)))
  }

  const cols = (cur?.fields || []).map((f) => ({
    title: f.label || f.name, dataIndex: ['data', f.name], ellipsis: true,
    render: (v: any) => (v === null || v === undefined || v === '') ? '-' : String(v),
  }))

  return (
    <PageContainer
      title="智能录单"
      subtitle="定义录单模板（字段），把通话记录/聊天/邮件等文本交给 AI 自动抽成结构化台账，可导出 Excel/CSV"
      extra={<Can perm="record:manage"><Button type="primary" icon={<PlusOutlined />} onClick={() => openTemplate()}>新建模板</Button></Can>}
    >
      <Card bordered={false} style={{ marginBottom: 16 }}>
        <Table
          rowKey="id" dataSource={templates} loading={loading} pagination={false}
          locale={{ emptyText: <EmptyState description="暂无录单模板，点右上角新建" /> }}
          columns={[
            { title: '模板', dataIndex: 'name', render: (v, r) => <Space>{v}<Tag>{(r.fields || []).length} 字段</Tag></Space> },
            { title: '字段', render: (_: any, r) => <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {(r.fields || []).map((f) => f.label || f.name).join('、') || '-'}</Typography.Text> },
            { title: '说明', dataIndex: 'description', ellipsis: true },
            { title: '启用', dataIndex: 'enabled', width: 80, render: (v) => v ? <Tag color="green">是</Tag> : <Tag>否</Tag> },
            {
              title: '操作', width: 220, fixed: 'right',
              render: (_: any, r: RecordTemplateItem) => (
                <Space>
                  <Button size="small" type="primary" ghost icon={<ThunderboltOutlined />} onClick={() => openPanel(r)}>录入</Button>
                  <Can perm="record:manage">
                    <Button size="small" icon={<EditOutlined />} onClick={() => openTemplate(r)} />
                    <Popconfirm title="删除模板及其所有记录？" onConfirm={async () => { await recordApi.removeTemplate(r.id); message.success('已删除'); load() }}>
                      <Button size="small" danger icon={<DeleteOutlined />} />
                    </Popconfirm>
                  </Can>
                </Space>
              ),
            },
          ]}
        />
      </Card>

      {cur && (
        <Card title={`录入：${cur.name}`}
          extra={<Space>
            <Button icon={<FileExcelOutlined />} onClick={() => exportLedger('xlsx')}>导出 Excel</Button>
            <Button onClick={() => exportLedger('csv')}>CSV</Button>
            <Button onClick={() => exportLedger('md')}>Markdown</Button>
          </Space>}>
          <Alert type="info" showIcon style={{ marginBottom: 12 }}
            message="把原始文本粘进来（可含多条），AI 会按模板字段抽取并存为台账记录。" />
          <Input.TextArea rows={5} value={text} onChange={(e) => setText(e.target.value)}
            placeholder="例：\n客户张三，电话138xxxx0001，下单 A123，金额199，2026-01-05\n客户李四，电话138xxxx0002，下单 A124，金额88" />
          <Button type="primary" icon={<ThunderboltOutlined />} loading={extracting} onClick={doExtract}
            style={{ marginTop: 12 }}>抽取并保存</Button>

          <Table
            style={{ marginTop: 16 }} rowKey="id" dataSource={entries} pagination={false} size="small"
            locale={{ emptyText: '暂无记录' }}
            columns={[
              ...cols,
              { title: '状态', dataIndex: 'status', width: 80,
                render: (v: string) => <Tag color={v === 'confirmed' ? 'green' : 'default'}>{v === 'confirmed' ? '已确认' : '草稿'}</Tag> },
              {
                title: '操作', width: 120,
                render: (_: any, r) => (
                  <Space>
                    <Can perm="record:manage">
                      <Popconfirm title="标记为已确认？" onConfirm={async () => {
                        await recordApi.updateEntry(r.id, r.data, 'confirmed')
                        setEntries(await recordApi.entries(cur.id))
                      }}>
                        <Button size="small" type="link">确认</Button>
                      </Popconfirm>
                      <Popconfirm title="删除该记录？" onConfirm={async () => {
                        await recordApi.removeEntry(r.id)
                        setEntries(await recordApi.entries(cur.id))
                      }}>
                        <Button size="small" type="link" danger>删除</Button>
                      </Popconfirm>
                    </Can>
                  </Space>
                ),
              },
            ]}
          />
        </Card>
      )}

      <Modal title={edit ? '编辑模板' : '新建录单模板'} open={tOpen} onOk={saveTemplate}
        onCancel={() => setTOpen(false)} destroyOnClose width={720}>
        <Form form={tForm} layout="vertical">
          <Form.Item name="name" label="模板名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="如：销售订单" />
          </Form.Item>
          <Form.Item name="description" label="说明"><Input placeholder="可选" /></Form.Item>
          <Form.Item name="instructions" label="业务背景提示（帮助 AI 理解）">
            <Input.TextArea rows={2} placeholder="如：这是电商订单，金额只保留数字" />
          </Form.Item>

          <Typography.Title level={5}>字段定义</Typography.Title>
          <Form.List name="fields">
            {(fs, { add, remove }) => (
              <>
                {fs.map((f, i) => (
                  <Space key={f.key} align="baseline" style={{ display: 'flex', marginBottom: 6 }} wrap>
                    <Form.Item {...f} name={[f.name, 'name']} rules={[{ required: true, message: '填字段名' }]} style={{ marginBottom: 0 }}>
                      <Input style={{ width: 130 }} placeholder="字段名(英文)" />
                    </Form.Item>
                    <Form.Item {...f} name={[f.name, 'label']} style={{ marginBottom: 0 }}>
                      <Input style={{ width: 120 }} placeholder="显示名" />
                    </Form.Item>
                    <Form.Item {...f} name={[f.name, 'type']} initialValue="text" style={{ marginBottom: 0 }}>
                      <Select style={{ width: 90 }} options={FIELD_TYPES} />
                    </Form.Item>
                    <Form.Item {...f} name={[f.name, 'required']} valuePropName="checked" style={{ marginBottom: 0 }}>
                      <Switch checkedChildren="必填" unCheckedChildren="可选" />
                    </Form.Item>
                    <MinusCircleOutlined onClick={() => remove(f.name)} style={{ color: '#999' }} />
                  </Space>
                ))}
                <Button type="dashed" onClick={() => add({ type: 'text' })} icon={<PlusOutlined />} block>添加字段</Button>
              </>
            )}
          </Form.List>
          <Form.Item name="enabled" label="启用" valuePropName="checked" style={{ marginTop: 12 }}><Switch /></Form.Item>
        </Form>
      </Modal>
    </PageContainer>
  )
}
