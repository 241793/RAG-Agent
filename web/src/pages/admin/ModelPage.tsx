import { useEffect, useState } from 'react'
import {
  Badge, Button, Card, Form, Input, InputNumber, message, Modal, Popconfirm, Select, Space, Switch, Table, Tag, Tooltip,
} from 'antd'
import {
  PlusOutlined, DeleteOutlined, EditOutlined, DownloadOutlined, StarOutlined,
  HeartOutlined, ExperimentOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { providerApi, type ModelConfig, type Provider } from '../../api'
import { errMsg } from '../../api/http'
import PageContainer from '../../components/PageContainer'
import EmptyState from '../../components/EmptyState'
import { useAuth } from '../../stores/auth'

const KIND_OPTS = [
  { value: 'openai', label: 'OpenAI 兼容（含中转站/vLLM）' },
  { value: 'anthropi', label: 'Anthropi (Claud)' },
  { value: 'ollama', label: 'Ollama（本地）' },
  { value: 'local_bge', label: '本地 bge（FlagEmbedding）' },
  { value: 'local_hash', label: '本地离线（自测/无网）' },
]

const PURPOSE_OPTS = [
  { value: 'chat', label: '对话 chat' },
  { value: 'embedding', label: '向量 embedding' },
  { value: 'rerank', label: '重排 rerank' },
  { value: 'vision', label: '视觉 vision（图片理解）' },
]

export default function ModelPage() {
  const [providers, setProviders] = useState<Provider[]>([])
  const [configs, setConfigs] = useState<ModelConfig[]>([])
  const [pOpen, setPOpen] = useState(false)
  const [pEdit, setPEdit] = useState<Provider | null>(null)
  const [cOpen, setCOpen] = useState(false)
  const [cEdit, setCEdit] = useState<ModelConfig | null>(null)
  const [pForm] = Form.useForm()
  const [cForm] = Form.useForm()
  const [testing, setTesting] = useState<number | null>(null)
  const [healthChecking, setHealthChecking] = useState<number | null>(null)
  const [testingConfig, setTestingConfig] = useState<number | null>(null)
  const [remoteModels, setRemoteModels] = useState<string[]>([])
  const [loadingModels, setLoadingModels] = useState(false)
  const hasPermission = useAuth((s) => s.hasPermission)
  const canManage = hasPermission('model:manage')

  const load = async () => {
    try {
      setProviders(await providerApi.list())
      setConfigs(await providerApi.configs())
    } catch (e) { message.error(errMsg(e)) }
  }
  useEffect(() => { load() }, [])

  // ---- Provider ----
  const openProvider = (p?: Provider) => {
    setPEdit(p || null)
    pForm.resetFields()
    if (p) {
      pForm.setFieldsValue({
        ...p,
        extra_headers: p.extra_headers ? JSON.stringify(p.extra_headers, null, 2) : '',
      })
    } else {
      pForm.setFieldsValue({ kind: 'openai', timeout: 60 })
    }
    setPOpen(true)
  }
  const saveProvider = async () => {
    const v: any = await pForm.validateFields()
    if (typeof v.extra_headers === 'string') {
      const s = v.extra_headers.trim()
      if (s) {
        try { v.extra_headers = JSON.parse(s) } catch { message.error('额外请求头不是合法 JSON'); return }
      } else { v.extra_headers = null }
    }
    try {
      if (pEdit) await providerApi.update(pEdit.id, v)
      else await providerApi.create(v)
      message.success('已保存'); setPOpen(false); load()
    } catch (e) { message.error(errMsg(e)) }
  }
  const test = async (p: Provider) => {
    setTesting(p.id)
    try {
      const r = await providerApi.test(p.id, 'chat')
      if (r.ok) message.success(`连接成功 (${r.latency_ms}ms): ${r.message}`)
      else message.error(`连接失败: ${r.message}`)
    } catch (e) { message.error(errMsg(e)) } finally { setTesting(null) }
  }

  const healthCheck = async (p: Provider, purpose = 'chat') => {
    setHealthChecking(p.id)
    try {
      const r = await providerApi.health(p.id, purpose)
      if (r.ok) message.success(`健康检查通过 (${r.latency_ms}ms): ${r.message}`)
      else message.error(`健康检查失败: ${r.message}`)
      load()
    } catch (e) { message.error(errMsg(e)) } finally { setHealthChecking(null) }
  }

  const testConfig = async (c: ModelConfig) => {
    setTestingConfig(c.id)
    try {
      const r = await providerApi.test(c.provider_id, c.purpose, c.model_name)
      if (r.ok) message.success(`${c.purpose} 测试通过 (${r.latency_ms}ms): ${r.message}`)
      else message.error(`${c.purpose} 测试失败: ${r.message}`)
    } catch (e) { message.error(errMsg(e)) } finally { setTestingConfig(null) }
  }

  // ---- 拉取远端模型列表 ----
  const fetchModels = async (providerId: number) => {
    setLoadingModels(true)
    try {
      const r = await providerApi.listModels(providerId)
      if (r.ok) { setRemoteModels(r.models.map((m) => m.id)); message.success(`获取到 ${r.models.length} 个模型`) }
      else { setRemoteModels([]); message.error(`获取失败: ${r.message || '该 Provider 不支持模型列表'}`) }
    } catch (e) { message.error(errMsg(e)) } finally { setLoadingModels(false) }
  }

  // ---- ModelConfig ----
  const openConfig = (c?: ModelConfig, presetProviderId?: number) => {
    setCEdit(c || null)
    setRemoteModels([])
    cForm.resetFields()
    if (c) cForm.setFieldsValue(c)
    else cForm.setFieldsValue({ purpose: 'chat', priority: 10, provider_id: presetProviderId })
    setCOpen(true)
  }
  const saveConfig = async () => {
    const v = await cForm.validateFields()
    try {
      if (cEdit) await providerApi.updateConfig(cEdit.id, v)
      else await providerApi.createConfig(v)
      message.success('已保存'); setCOpen(false); load()
    } catch (e) { message.error(errMsg(e)) }
  }
  const setDefault = async (c: ModelConfig) => {
    try { await providerApi.updateConfig(c.id, { is_default: true }); message.success('已设为默认'); load() }
    catch (e) { message.error(errMsg(e)) }
  }

  const providerName = (id: number) => providers.find((p) => p.id === id)?.name || id

  return (
    <PageContainer
      title="模型管理"
      extra={canManage ? <Button type="primary" icon={<PlusOutlined />} onClick={() => openProvider()}>添加 Provider</Button> : undefined}
    >
      <Card title="模型 Provider" style={{ marginBottom: 16 }}>
        <Table
          rowKey="id" size="small" dataSource={providers} pagination={false}
          scroll={{ x: 'max-content' }}
          locale={{ emptyText: <EmptyState description="暂无 Provider" /> }}
          columns={[
            { title: '名称', dataIndex: 'name' },
            { title: '类型', dataIndex: 'kind', render: (v) => <Tag>{v}</Tag> },
            { title: '地址', dataIndex: 'base_url', ellipsis: true },
            { title: 'Key', dataIndex: 'api_key_set', width: 90, render: (v) => v ? <Tag color="green">已配置</Tag> : <Tag>未配置</Tag> },
            {
              title: '健康', width: 130,
              render: (_: any, p: Provider) => {
                if (!p.last_check_at) return <Tag>未检查</Tag>
                const ok = p.health_status === 'ok'
                return (
                  <Tooltip title={`最近检查：${dayjs(p.last_check_at).format('MM-DD HH:mm')}`}>
                    <Badge status={ok ? 'success' : 'error'} text={ok ? '正常' : '异常'} />
                  </Tooltip>
                )
              },
            },
            {
              title: '操作', width: 330,
              render: (_: any, p: Provider) => (
                <Space>
                  <Button size="small" icon={<ExperimentOutlined />} loading={testing === p.id} onClick={() => test(p)}>测试</Button>
                  <Button size="small" icon={<HeartOutlined />} loading={healthChecking === p.id} onClick={() => healthCheck(p)}>健康</Button>
                  <Button size="small" icon={<DownloadOutlined />} onClick={() => { fetchModels(p.id); openConfig(undefined, p.id) }}>拉模型</Button>
                  {canManage && <>
                    <Button size="small" icon={<EditOutlined />} onClick={() => openProvider(p)} />
                    <Popconfirm title="删除该 Provider？其下模型配置需另行删除" onConfirm={async () => { await providerApi.remove(p.id); load() }}>
                      <Button size="small" danger icon={<DeleteOutlined />} />
                    </Popconfirm>
                  </>}
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Card
        title="模型配置（按用途，可多个并切换）"
        extra={canManage ? <Button size="small" icon={<PlusOutlined />} onClick={() => openConfig()}>添加模型</Button> : undefined}
      >
        <Table
          rowKey="id" size="small" dataSource={configs} pagination={false}
          scroll={{ x: 'max-content' }}
          locale={{ emptyText: <EmptyState description="暂无模型配置" /> }}
          columns={[
            { title: '用途', dataIndex: 'purpose', width: 110,
              render: (v) => <Tag color={v === 'chat' ? 'blue' : v === 'embedding' ? 'purple' : 'orange'}>{v}</Tag> },
            { title: '模型', dataIndex: 'display_name', render: (v, r) => v || r.model_name },
            { title: 'Provider', dataIndex: 'provider_id', width: 150, render: (v) => providerName(v) },
            { title: '维度', dataIndex: 'embedding_dim', width: 80, render: (v) => v || '-' },
            { title: '优先级', dataIndex: 'priority', width: 80 },
            { title: '默认', dataIndex: 'is_default', width: 90,
              render: (v, r) => v ? <Tag color="green">默认</Tag>
                : (canManage ? <Tooltip title="设为默认"><Button size="small" type="text" icon={<StarOutlined />} onClick={() => setDefault(r)} /></Tooltip> : '-') },
            {
              title: '操作', width: 160,
              render: (_: any, r: ModelConfig) => (
                <Space>
                  <Tooltip title="用该用途实测一次（embedding 会真调 /embeddings）">
                    <Button size="small" icon={<ExperimentOutlined />} loading={testingConfig === r.id}
                      onClick={() => testConfig(r)} />
                  </Tooltip>
                  {canManage && <>
                    <Button size="small" icon={<EditOutlined />} onClick={() => openConfig(r)} />
                    <Popconfirm title="删除该模型配置？" onConfirm={async () => { await providerApi.removeConfig(r.id); load() }}>
                      <Button size="small" danger icon={<DeleteOutlined />} />
                    </Popconfirm>
                  </>}
                </Space>
              ),
            },
          ]}
        />
      </Card>

      {/* Provider 弹窗 */}
      <Modal title={pEdit ? '编辑 Provider' : '添加 Provider'} open={pOpen} onOk={saveProvider} onCancel={() => setPOpen(false)} destroyOnClose>
        <Form form={pForm} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input placeholder="如：云端 GPT" /></Form.Item>
          <Form.Item name="kind" label="类型" rules={[{ required: true }]}><Select options={KIND_OPTS} /></Form.Item>
          <Form.Item name="base_url" label="Base URL" rules={[{ required: true }]} extra="OpenAI 兼容填到 /v1">
            <Input placeholder="https://api.openai.com/v1" />
          </Form.Item>
          <Form.Item name="api_key" label="API Key" extra={pEdit ? '留空则不修改' : ''}><Input.Password placeholder="sk-..." /></Form.Item>
          <Form.Item name="timeout" label="超时（秒）">
            <InputNumber style={{ width: '100%' }} min={1} max={600} placeholder="60" />
          </Form.Item>
          <Form.Item name="extra_headers" label="额外请求头（JSON，可选）"
            extra='如 {"AuthorizationType":"ilink_bot_token"}；本地 local_hash 驱动可用 {"dim":1024} 指定维度'>
            <Input.TextArea rows={2} style={{ fontFamily: 'monospace', fontSize: 12 }} placeholder='{"key":"value"}' />
          </Form.Item>
        </Form>
      </Modal>

      {/* 模型配置弹窗 */}
      <Modal title={cEdit ? '编辑模型' : '添加模型'} open={cOpen} onOk={saveConfig} onCancel={() => setCOpen(false)} destroyOnClose>
        <Form form={cForm} layout="vertical">
          <Form.Item name="provider_id" label="Provider" rules={[{ required: true }]}>
            <Select options={providers.map((p) => ({ value: p.id, label: `${p.name} (${p.kind})` }))} />
          </Form.Item>
          <Form.Item name="purpose" label="用途" rules={[{ required: true }]}><Select options={PURPOSE_OPTS} /></Form.Item>
          <Form.Item label="模型名">
            <Space.Compact style={{ width: '100%' }}>
              <Form.Item name="model_name" noStyle rules={[{ required: true }]}>
                <Select
                  showSearch allowClear placeholder="从 Provider 拉取或手动输入"
                  options={remoteModels.map((m) => ({ value: m, label: m }))}
                  dropdownRender={(menu) => (
                    <>
                      {menu}
                      <div style={{ padding: 4 }}>
                        <Button type="link" size="small" loading={loadingModels}
                          onClick={() => { const pid = cForm.getFieldValue('provider_id'); if (pid) fetchModels(pid); else message.warning('先选 Provider') }}>
                          从 Provider 获取模型列表
                        </Button>
                      </div>
                    </>
                  )}
                />
              </Form.Item>
              <Button icon={<DownloadOutlined />} loading={loadingModels}
                onClick={() => { const pid = cForm.getFieldValue('provider_id'); if (pid) fetchModels(pid); else message.warning('先选 Provider') }}>
                拉取
              </Button>
            </Space.Compact>
          </Form.Item>
          <Form.Item name="display_name" label="显示名（可选）"><Input placeholder="如：GPT-4o 主力模型" /></Form.Item>
          <Form.Item name="embedding_dim" label="向量维度（embedding 必填）" extra="bge-m3=1024, text-embedding-3-small=1536">
            <InputNumber style={{ width: '100%' }} placeholder="1024" />
          </Form.Item>
          <Form.Item name="priority" label="优先级（越小越优先，用于降级链）"><InputNumber style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="is_default" label="设为该用途的默认模型" valuePropName="checked"><Switch /></Form.Item>
        </Form>
      </Modal>
    </PageContainer>
  )
}
