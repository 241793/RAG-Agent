import { useEffect, useState } from 'react'
import {
  Alert, Button, Card, Descriptions, Drawer, Form, Input, InputNumber, List, message, Modal,
  Popconfirm, Select, Space, Switch, Table, Tag, Typography,
} from 'antd'
import {
  PlusOutlined, DeleteOutlined, EditOutlined, ExperimentOutlined, SyncOutlined,
  ApiOutlined, PlayCircleOutlined,
} from '@ant-design/icons'
import { mcpApi, type McpServerItem, type McpToolItem } from '../../api'
import { errMsg } from '../../api/http'
import PageContainer from '../../components/PageContainer'
import EmptyState from '../../components/EmptyState'
import JsonSchemaForm from '../../components/JsonSchemaForm'
import Can from '../../components/Can'

const TRANSPORT_META: Record<string, { label: string; color: string }> = {
  http: { label: 'HTTP', color: 'blue' },
  sse: { label: 'SSE', color: 'purple' },
  stdio: { label: '本地进程', color: 'orange' },
}

function statusTag(s: McpServerItem) {
  if (!s.enabled) return <Tag>已停用</Tag>
  if (s.status === 'error') return <Tag color="red">异常</Tag>
  return <Tag color="green">正常</Tag>
}

function ToolRunner({ server, tool, onClose }: { server: McpServerItem; tool: McpToolItem; onClose: () => void }) {
  const [form] = Form.useForm()
  const [result, setResult] = useState('')
  const [loading, setLoading] = useState(false)
  const schema = tool.inputSchema || { type: 'object', properties: {} }

  const run = async (vals: Record<string, any>) => {
    setLoading(true)
    try {
      const r = await mcpApi.call(server.id, tool.name, vals || {})
      setResult(r.content || '')
      if (r.ok) message.success('调用成功')
      else message.warning('工具返回错误')
    } catch (e) { setResult('失败：' + errMsg(e)) } finally { setLoading(false) }
  }

  return (
    <Modal title={`试跑：${tool.name}`} open onCancel={onClose} footer={null} width={600} destroyOnClose>
      <Form form={form} layout="vertical" onFinish={run}>
        <JsonSchemaForm schema={schema} />
        <Button type="primary" htmlType="submit" loading={loading}>执行</Button>
      </Form>
      {result && (
        <pre style={{ marginTop: 12, maxHeight: 300, overflow: 'auto', background: '#f6f8fa', padding: 10, borderRadius: 6, fontSize: 12 }}>
          {result}
        </pre>
      )}
    </Modal>
  )
}

export default function McpPage() {
  const [servers, setServers] = useState<McpServerItem[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [edit, setEdit] = useState<McpServerItem | null>(null)
  const [transport, setTransport] = useState<string>('http')
  const [testing, setTesting] = useState<number | null>(null)
  const [syncing, setSyncing] = useState<number | null>(null)
  const [form] = Form.useForm()
  const [toolsServer, setToolsServer] = useState<McpServerItem | null>(null)
  const [tools, setTools] = useState<McpToolItem[]>([])
  const [runTool, setRunTool] = useState<McpToolItem | null>(null)

  const load = async () => {
    setLoading(true)
    try { setServers(await mcpApi.list()) }
    catch (e) { message.error(errMsg(e)) } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  const openModal = (s?: McpServerItem) => {
    setEdit(s || null)
    setTransport(s?.transport || 'http')
    if (s) {
      form.setFieldsValue({
        ...s,
        argsText: (s.args || []).join(' '),
        envText: s.env ? JSON.stringify(s.env, null, 2) : '',
        headersText: s.headers ? JSON.stringify(s.headers, null, 2) : '',
      })
    } else form.resetFields()
    setOpen(true)
  }

  const parseJson = (t?: string) => {
    if (!t || !t.trim()) return undefined
    try { return JSON.parse(t) } catch { throw new Error('JSON 格式错误') }
  }

  const submit = async () => {
    const v = await form.validateFields()
    try {
      const payload: Record<string, any> = {
        name: v.name, transport, enabled: v.enabled !== false, timeout: v.timeout || undefined,
      }
      if (transport === 'stdio') {
        payload.command = v.command
        payload.args = (v.argsText || '').trim() ? v.argsText.trim().split(/\s+/) : []
        payload.env = parseJson(v.envText)
      } else {
        payload.url = v.url
        payload.headers = parseJson(v.headersText)
        payload.auth_token = v.auth_token || undefined
      }
      if (edit) await mcpApi.update(edit.id, payload)
      else await mcpApi.create(payload)
      message.success('已保存')
      setOpen(false); load()
    } catch (e) { if ((e as any)?.errorFields) return; message.error(errMsg(e)) }
  }

  const test = async (s: McpServerItem) => {
    setTesting(s.id)
    try {
      const r = await mcpApi.test(s.id)
      if (r.ok) message.success(`连接成功，发现 ${r.tools_count} 个工具（${r.latency_ms}ms）`)
      else message.error(`连接失败：${r.message}`)
      load()
    } catch (e) { message.error(errMsg(e)) } finally { setTesting(null) }
  }

  const sync = async (s: McpServerItem) => {
    setSyncing(s.id)
    try {
      const r = await mcpApi.sync(s.id)
      message.success(`已同步 ${r.tools_count} 个工具`)
      load()
    } catch (e) { message.error(errMsg(e)) } finally { setSyncing(null) }
  }

  const viewTools = async (s: McpServerItem) => {
    setToolsServer(s)
    try { setTools(await mcpApi.tools(s.id)) } catch (e) { message.error(errMsg(e)) }
  }

  return (
    <PageContainer
      title="MCP 服务器"
      subtitle="连接外部 MCP（Model Context Protocol）服务，同步其工具并自动注册为 AI 可调用工具"
      extra={<Can perm="mcp:manage"><Button type="primary" icon={<PlusOutlined />} onClick={() => openModal()}>接入 MCP 服务器</Button></Can>}
    >
      <Alert
        type="info" showIcon style={{ marginBottom: 16 }}
        message="在智能体的 tool_config 中启用 mcp 后，同步到的工具即可供 AI 调用（调用走人工确认，除非开启自动写操作）。"
      />
      <Card bordered={false}>
        <Table
          rowKey="id" dataSource={servers} loading={loading} pagination={false}
          scroll={{ x: 'max-content' }}
          locale={{ emptyText: <EmptyState description="尚未接入 MCP 服务器" /> }}
          columns={[
            { title: '名称', dataIndex: 'name', render: (v, r) => <Space><ApiOutlined />{v}</Space> },
            { title: '传输', dataIndex: 'transport', width: 110,
              render: (v: string) => <Tag color={TRANSPORT_META[v]?.color}>{TRANSPORT_META[v]?.label || v}</Tag> },
            { title: '地址/命令', ellipsis: true,
              render: (_: any, r: McpServerItem) => <Typography.Text style={{ fontSize: 12 }} ellipsis>
                {r.transport === 'stdio' ? `${r.command || ''} ${(r.args || []).join(' ')}` : r.url}
              </Typography.Text> },
            { title: '工具数', dataIndex: 'tools_count', width: 80 },
            { title: '状态', width: 90, render: (_: any, r) => statusTag(r) },
            {
              title: '操作', width: 320, fixed: 'right',
              render: (_: any, r: McpServerItem) => (
                <Space>
                  <Button size="small" icon={<ExperimentOutlined />} loading={testing === r.id} onClick={() => test(r)}>测试</Button>
                  <Can perm="mcp:manage">
                    <Button size="small" icon={<SyncOutlined />} loading={syncing === r.id} onClick={() => sync(r)}>同步</Button>
                  </Can>
                  <Button size="small" onClick={() => viewTools(r)}>工具</Button>
                  <Can perm="mcp:manage">
                    <Button size="small" icon={<EditOutlined />} onClick={() => openModal(r)} />
                    <Popconfirm title="删除该 MCP 服务器？" onConfirm={async () => { await mcpApi.remove(r.id); message.success('已删除'); load() }}>
                      <Button size="small" danger icon={<DeleteOutlined />} />
                    </Popconfirm>
                  </Can>
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        title={edit ? '编辑 MCP 服务器' : '接入 MCP 服务器'} open={open} onOk={submit} onCancel={() => setOpen(false)}
        destroyOnClose width={640}
      >
        <Form form={form} layout="vertical" initialValues={{ transport: 'http', enabled: true }}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}><Input /></Form.Item>
          <Form.Item name="transport" label="传输方式" rules={[{ required: true }]}>
            <Select onChange={(v) => setTransport(v)} options={[
              { value: 'http', label: 'HTTP（streamable-http）' },
              { value: 'sse', label: 'SSE（Server-Sent Events）' },
              { value: 'stdio', label: '本地进程（stdio，需开启 MCP_ALLOW_STDIO）' },
            ]} />
          </Form.Item>
          {transport === 'stdio' ? (
            <>
              <Form.Item name="command" label="命令" rules={[{ required: true, message: '如 python / npx' }]}
                extra="首 token 需在白名单内（python/python3/node/npx/uvx）">
                <Input placeholder="npx" />
              </Form.Item>
              <Form.Item name="argsText" label="参数（空格分隔）">
                <Input placeholder="-y @modelcontextprotocol/server-filesystem /data" />
              </Form.Item>
              <Form.Item name="envText" label="环境变量（JSON，可含密钥）" extra="如 {&quot;API_KEY&quot;:&quot;xxx&quot;}">
                <Input.TextArea rows={3} placeholder='{"API_KEY":"xxx"}' />
              </Form.Item>
            </>
          ) : (
            <>
              <Form.Item name="url" label="服务地址" rules={[{ required: true, message: '请输入地址' }]}>
                <Input placeholder="https://mcp.example.com/mcp" />
              </Form.Item>
              <Form.Item name="auth_token" label="Bearer Token" extra={edit?.auth_token_set ? '已配置，留空则不变' : '可选'}>
                <Input.Password placeholder="留空则不使用" />
              </Form.Item>
              <Form.Item name="headersText" label="附加请求头（JSON）">
                <Input.TextArea rows={2} placeholder='{"X-Custom":"value"}' />
              </Form.Item>
            </>
          )}
          <Space>
            <Form.Item name="timeout" label="超时（秒）"><InputNumber min={1} max={300} placeholder="默认 30" /></Form.Item>
            <Form.Item name="enabled" label="启用" valuePropName="checked"><Switch /></Form.Item>
          </Space>
        </Form>
      </Modal>

      {/* 工具清单 */}
      <Drawer title={`工具：${toolsServer?.name || ''}`} width={640} open={!!toolsServer}
        onClose={() => setToolsServer(null)}>
        {tools.length === 0 ? (
          <EmptyState description="暂无工具，请先「同步」" />
        ) : (
          <List
            dataSource={tools}
            renderItem={(t) => (
              <List.Item
                actions={[
                  <Button key="r" size="small" icon={<PlayCircleOutlined />} onClick={() => setRunTool(t)}>试跑</Button>,
                ]}
              >
                <List.Item.Meta
                  title={<Space><code>{t.name}</code></Space>}
                  description={<Typography.Text type="secondary" style={{ fontSize: 12 }}>{t.description}</Typography.Text>}
                />
              </List.Item>
            )}
          />
        )}
      </Drawer>

      {runTool && toolsServer && (
        <ToolRunner server={toolsServer} tool={runTool} onClose={() => setRunTool(null)} />
      )}
    </PageContainer>
  )
}
