import { useEffect, useState } from 'react'
import { Button, Card, Form, message, Modal, Popconfirm, Space, Table, Tag, Typography } from 'antd'
import { DeleteOutlined, PlayCircleOutlined, ReloadOutlined } from '@ant-design/icons'
import { toolApi, type ToolItem } from '../../api'
import { errMsg } from '../../api/http'
import PageContainer from '../../components/PageContainer'
import EmptyState from '../../components/EmptyState'
import JsonSchemaForm from '../../components/JsonSchemaForm'
import { useAuth } from '../../stores/auth'

function TestForm({ tool, onSubmit }: { tool: ToolItem; onSubmit: (args: Record<string, any>) => void }) {
  const [form] = Form.useForm()
  const schema = (tool.parameters as any) || { type: 'object', properties: {} }
  return (
    <Form form={form} layout="vertical" onFinish={(vals) => onSubmit(vals)}>
      <JsonSchemaForm schema={schema} />
      <Button type="primary" htmlType="submit">执行</Button>
    </Form>
  )
}

export default function ToolPage() {
  const [tools, setTools] = useState<ToolItem[]>([])
  const [loading, setLoading] = useState(false)
  const [testTool, setTestTool] = useState<ToolItem | null>(null)
  const [testResult, setTestResult] = useState<string>('')
  const hasPermission = useAuth((s) => s.hasPermission)
  const canManage = hasPermission('tool:manage')

  const load = async () => {
    setLoading(true)
    try { setTools(await toolApi.list()) }
    catch (e) { message.error(errMsg(e)) } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  const doTest = async (args: Record<string, any>) => {
    if (!testTool) return
    try {
      const r = await toolApi.test(testTool.id, args)
      setTestResult(JSON.stringify(r, null, 2))
    } catch (e) { setTestResult('失败：' + errMsg(e)) }
  }

  const builtin = tools.filter((t) => t.builtin)
  const custom = tools.filter((t) => !t.builtin)

  return (
    <PageContainer
      title="工具管理"
      subtitle="内置工具（代码注册，只读）与自定义工具（HTTP 可调用）"
      extra={<Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>}
    >
      <Card title="内置工具" bordered={false} style={{ marginBottom: 16 }}>
        <Table
          rowKey={(r) => `b-${r.id}`} dataSource={builtin} loading={loading} pagination={false} size="small"
          locale={{ emptyText: <EmptyState description="无内置工具" /> }}
          columns={[
            { title: '名称', dataIndex: 'name' },
            { title: '描述', dataIndex: 'description', ellipsis: true },
            { title: '启用', dataIndex: 'enabled', width: 80, render: (v: boolean) => v ? <Tag color="green">是</Tag> : <Tag>否</Tag> },
          ]}
        />
      </Card>

      <Card title="自定义工具" bordered={false}
        extra={<Typography.Text type="secondary" style={{ fontSize: 12 }}>自定义工具通过技能/智能体绑定后供 AI 调用</Typography.Text>}>
        <Table
          rowKey="id" dataSource={custom} loading={loading} pagination={false} size="small"
          locale={{ emptyText: <EmptyState description="暂无自定义工具" /> }}
          columns={[
            { title: '名称', dataIndex: 'name' },
            { title: '显示名', dataIndex: 'display_name', width: 140 },
            { title: '描述', dataIndex: 'description', ellipsis: true },
            { title: '类型', dataIndex: 'kind', width: 90, render: (v: string) => <Tag>{v}</Tag> },
            {
              title: '操作', width: 160,
              render: (_: any, r: ToolItem) => (
                <Space>
                  <Button size="small" icon={<PlayCircleOutlined />} onClick={() => { setTestTool(r); setTestResult('') }}>试跑</Button>
                  {canManage && (
                    <Popconfirm title="删除该工具？" onConfirm={async () => { await toolApi.remove(r.id); load() }}>
                      <Button size="small" danger icon={<DeleteOutlined />} />
                    </Popconfirm>
                  )}
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Modal title={`试跑工具：${testTool?.display_name || testTool?.name || ''}`} open={!!testTool}
        onCancel={() => setTestTool(null)} footer={null} destroyOnClose width={560}>
        {testTool && (
          <>
            <TestForm tool={testTool} onSubmit={doTest} />
            {testResult && (
              <pre style={{ marginTop: 12, maxHeight: 240, overflow: 'auto', background: '#f6f8fa', padding: 10, borderRadius: 6, fontSize: 12 }}>
                {testResult}
              </pre>
            )}
          </>
        )}
      </Modal>
    </PageContainer>
  )
}
