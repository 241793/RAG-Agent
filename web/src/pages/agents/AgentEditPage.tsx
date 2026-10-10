import { useEffect, useRef, useState } from 'react'
import {
  Button, Card, Drawer, Form, Input, InputNumber, message, Modal, Popconfirm, Select, Space, Switch, Table, Tabs, Tag, Typography,
} from 'antd'
import { ArrowLeftOutlined, PlusOutlined, DeleteOutlined, EditOutlined, PlayCircleOutlined, SendOutlined } from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import MarkdownBody from '../../components/MarkdownBody'
import JsonSchemaForm from '../../components/JsonSchemaForm'
import {
  agentApi, kbApi, providerApi, skillApi, streamChat, toolApi, API_BASE,
  type Agent, type AgentMode, type KB, type ModelConfig, type Skill,
} from '../../api'
import { errMsg } from '../../api/http'
import PageContainer from '../../components/PageContainer'

// 内置工具清单（与后端 registry 注册的一致）
const BUILTIN_TOOLS: { name: string; label: string; perm: string; write?: boolean }[] = [
  { name: 'knowledge_retrieval', label: '知识库检索', perm: 'chat:use' },
  { name: 'http_request', label: 'HTTP 请求', perm: 'tool:invoke', write: true },
  { name: 'read_file', label: '读取文件', perm: 'file:read' },
  { name: 'list_conversation_files', label: '列出会话文件', perm: 'file:read' },
  { name: 'convert_file', label: '文件转文本', perm: 'file:read' },
  { name: 'generate_file', label: '生成文件', perm: 'file:write', write: true },
  { name: 'generate_office_doc', label: '生成办公文档（纪要/周报/待办/公文）', perm: 'file:write', write: true },
  { name: 'edit_file', label: '改写文件', perm: 'file:write', write: true },
  { name: 'convert_file_to', label: '转换格式', perm: 'file:write', write: true },
]
const ADMIN_TOOLS_FALLBACK = [
  'list_skills', 'read_skill_file', 'list_kbs', 'list_documents', 'list_agents',
  'create_skill', 'write_skill_file', 'create_agent', 'write_document',
]

export default function AgentEditPage() {
  const { id } = useParams()
  const agentId = Number(id)
  const nav = useNavigate()
  const [agent, setAgent] = useState<Agent | null>(null)
  const [kbs, setKbs] = useState<KB[]>([])
  const [configs, setConfigs] = useState<ModelConfig[]>([])
  const [skills, setSkills] = useState<Skill[]>([])
  const [modes, setModes] = useState<AgentMode[]>([])
  const [versions, setVersions] = useState<{ id: number; version: number; note?: string; created_at: string }[]>([])
  const [modeOpen, setModeOpen] = useState(false)
  const [editMode, setEditMode] = useState<AgentMode | null>(null)
  const [testOpen, setTestOpen] = useState(false)
  const [testMsgs, setTestMsgs] = useState<{ role: string; content: string }[]>([])
  const [testInput, setTestInput] = useState('')
  const [testStreaming, setTestStreaming] = useState(false)
  const [adminTools, setAdminTools] = useState<string[]>(ADMIN_TOOLS_FALLBACK)
  const [form] = Form.useForm()
  const [toolForm] = Form.useForm()
  const [modeForm] = Form.useForm()
  const testListRef = useRef<HTMLDivElement>(null)

  const load = async () => {
    try {
      const a = await agentApi.get(agentId)
      setAgent(a)
      const tc = a.tool_config || {}
      const builtinVals: Record<string, boolean> = {}
      for (const t of BUILTIN_TOOLS) builtinVals[`bt_${t.name}`] = tc.builtin?.[t.name]?.enabled ?? false
      form.setFieldsValue({
        name: a.name, description: a.description, system_prompt: a.system_prompt,
        visibility: a.visibility || 'private',
        model_config_id: a.model_config_id, kb_ids: a.kb_ids || [], skill_ids: a.skill_ids || [],
        temperature: a.config?.temperature ?? 0.3,
        greeting: a.config?.greeting,
        max_turns: tc.max_turns ?? 4,
      })
      // 工具开关：独立表单实例（避免与基础配置共用实例导致字段互相覆盖）
      toolForm.setFieldsValue({
        ...builtinVals,
        admin_enabled: tc.admin?.enabled ?? false,
        admin_tools: tc.admin?.tools ?? [],
      })
      // 技能参数（按技能 slug 命名空间回填）
      form.setFieldValue('skill_params', (a.config as any)?.params || {})
      setKbs(await kbApi.list())
      setConfigs(await providerApi.configs())
      setSkills(await skillApi.list())
      setModes(await agentApi.modes(agentId))
      setVersions(await agentApi.versions(agentId).catch(() => []))
      toolApi.adminList().then((list) => setAdminTools(list.map((x) => x.name))).catch(() => {})
    } catch (e) { message.error(errMsg(e)) }
  }
  useEffect(() => { load() }, [agentId])

  const save = async () => {
    const v = await form.validateFields()
    const tv = await toolForm.validateFields()
    try {
      // 合并而非覆盖：保留现有 tool_config 中未在本页编辑的字段，避免抹掉其它工具配置
      const prev = agent?.tool_config || {}
      const builtin: Record<string, any> = { ...(prev.builtin || {}) }
      for (const t of BUILTIN_TOOLS) {
        builtin[t.name] = { ...(builtin[t.name] || {}), enabled: !!tv[`bt_${t.name}`] }
      }
      const toolConfig = {
        ...prev,
        builtin,
        admin: { ...(prev.admin || {}), enabled: !!tv.admin_enabled, tools: tv.admin_tools || [] },
        max_turns: v.max_turns,
      }
      await agentApi.update(agentId, {
        name: v.name, description: v.description, system_prompt: v.system_prompt,
        visibility: v.visibility,
        model_config_id: v.model_config_id, kb_ids: v.kb_ids, skill_ids: v.skill_ids,
        config: { temperature: v.temperature, greeting: v.greeting, params: v.skill_params || {} },
        tool_config: toolConfig,
      })
      message.success('已保存'); load()
    } catch (e) { message.error(errMsg(e)) }
  }

  const openAddMode = () => {
    setEditMode(null); modeForm.resetFields()
    modeForm.setFieldsValue({ is_default: false, sort: 0 })
    setModeOpen(true)
  }
  const openEditMode = (m: AgentMode) => {
    setEditMode(m)
    modeForm.setFieldsValue({
      name: m.name, system_prompt: m.system_prompt, is_default: m.is_default,
      kb_ids: m.kb_ids || [], skill_ids: m.skill_ids || [],
    })
    setModeOpen(true)
  }
  const submitMode = async () => {
    const v = await modeForm.validateFields()
    try {
      if (editMode) {
        await agentApi.updateMode(agentId, editMode.id, v)
      } else {
        await agentApi.createMode(agentId, v)
      }
      message.success('已保存模式'); setModeOpen(false); load()
    } catch (e) { message.error(errMsg(e)) }
  }

  const sendTest = async () => {
    const text = testInput.trim()
    if (!text) return
    setTestInput('')
    setTestMsgs((m) => [...m, { role: 'user', content: text }, { role: 'assistant', content: '' }])
    setTestStreaming(true)
    try {
      await streamChat(
        { kb_ids: agent?.kb_ids || [], message: text },
        {
          onDelta: (t) => setTestMsgs((m) => {
            const c = [...m]; const last = c.length - 1
            c[last] = { ...c[last], content: c[last].content + t }; return c
          }),
          onError: (msg) => message.error(msg),
        },
        undefined,
        `${API_BASE}/agents/${agentId}/run`,
      )
    } catch (e) { message.error(errMsg(e)) }
    setTestStreaming(false)
    setTimeout(() => testListRef.current?.scrollTo({ top: 99999 }), 100)
  }

  const chatConfigs = configs.filter((c) => c.purpose === 'chat')
  const selectedSkillIds: number[] = Form.useWatch('skill_ids', form) || []
  const skillsWithParams = selectedSkillIds
    .map((id) => skills.find((s) => s.id === id))
    .filter((s): s is Skill => !!s && s.kind === 'prompt_pack' && !!(s as any).params_schema)

  return (
    <PageContainer
      title={`编辑智能体：${agent?.name || ''}`}
      subtitle="配置智能体的角色、知识库范围、可调用的技能与工具、行为模式"
      extra={<>
        <Button icon={<ArrowLeftOutlined />} onClick={() => nav('/agents')}>返回</Button>
        <Button type="primary" icon={<PlayCircleOutlined />} onClick={() => setTestOpen(true)}>测试对话</Button>
      </>}
    >
      <Tabs
        destroyOnHidden={false}
        items={[
          {
            key: 'basic', label: '基础配置',
            forceRender: true,
            children: (
              <Card>
                <Form form={form} layout="vertical" style={{ maxWidth: 720 }}>
                  <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
                  <Form.Item name="description" label="描述"><Input.TextArea rows={2} /></Form.Item>
                  <Form.Item name="visibility" label="可见性">
                    <Select options={[{ value: 'private', label: '仅自己' }, { value: 'tenant', label: '全租户可见' }]} />
                  </Form.Item>
                  <Form.Item name="system_prompt" label="系统提示词"><Input.TextArea rows={6} /></Form.Item>
                  <Form.Item name="greeting" label="开场白（新对话时展示）"><Input.TextArea rows={2} /></Form.Item>
                  <Form.Item name="model_config_id" label="对话模型">
                    <Select allowClear options={chatConfigs.map((c) => ({ value: c.id, label: c.display_name }))} />
                  </Form.Item>
                  <Form.Item name="temperature" label="温度"><InputNumber min={0} max={2} step={0.1} style={{ width: 200 }} /></Form.Item>
                  <Form.Item name="kb_ids" label="知识库范围（留空=自动检索全部有权库）">
                    <Select mode="multiple" options={kbs.map((k) => ({ value: k.id, label: k.name }))} />
                  </Form.Item>
                  <Form.Item name="skill_ids" label="启用技能（能力包/工具/集合）">
                    <Select mode="multiple" options={skills.filter((s) => !s.parent_id).map((s) => ({
                      value: s.id,
                      label: `${s.name}（${s.kind === 'prompt_pack' ? '能力包' : s.kind === 'collection' ? '技能集合' : '工具'}）`,
                    }))} />
                  </Form.Item>
                  {skillsWithParams.map((s) => (
                    <Card key={s.id} size="small" title={`技能参数：${s.name}`} style={{ marginBottom: 12 }}>
                      <JsonSchemaForm
                        schema={(s as any).params_schema}
                        namePrefix={['skill_params', s.slug]}
                      />
                    </Card>
                  ))}
                  <Form.Item name="max_turns" label="最大工具调用轮次"><InputNumber style={{ width: 200 }} /></Form.Item>
                  <div style={{ marginBottom: 8, color: '#8c8c8c', fontSize: 12 }}>
                    工具开关见「可用工具」页签（含文件处理、管理类工具）
                  </div>
                  <Button type="primary" onClick={save}>保存</Button>
                </Form>
              </Card>
            ),
          },
          {
            key: 'modes', label: '行为模式',
            children: (
              <Card title="行为模式（切换时换提示词/知识库/技能）"
                extra={<Button icon={<PlusOutlined />} onClick={openAddMode}>添加模式</Button>}>
                <Table
                  rowKey="id" dataSource={modes} pagination={false} size="small"
                  columns={[
                    { title: '名称', dataIndex: 'name' },
                    { title: '提示词', dataIndex: 'system_prompt', ellipsis: true },
                    { title: '知识库覆盖', dataIndex: 'kb_ids', width: 120, render: (v: number[]) => v?.length ? `${v.length} 个` : '继承' },
                    { title: '技能覆盖', dataIndex: 'skill_ids', width: 120, render: (v: number[]) => v?.length ? `${v.length} 个` : '继承' },
                    { title: '默认', dataIndex: 'is_default', width: 70, render: (v: boolean) => v ? <Tag color="green">是</Tag> : '-' },
                    {
                      title: '操作', width: 160,
                      render: (_: any, r: AgentMode) => (
                        <Space>
                          <Button size="small" icon={<EditOutlined />} onClick={() => openEditMode(r)} />
                          <Button size="small" onClick={async () => { await agentApi.update(agentId, { default_mode_id: r.id } as any); message.success('已设为默认模式'); load() }}>设为默认</Button>
                          <Popconfirm title="删除该模式？" onConfirm={async () => { await agentApi.removeMode(agentId, r.id); load() }}>
                            <Button size="small" danger icon={<DeleteOutlined />} />
                          </Popconfirm>
                        </Space>
                      ),
                    },
                  ]}
                />
              </Card>
            ),
          },
          {
            key: 'tools', label: '可用工具',
            forceRender: true,
            children: (
              <Card>
                <Form form={toolForm} layout="vertical" style={{ maxWidth: 720 }}>
                  <Typography.Title level={5} style={{ marginTop: 0 }}>内置工具</Typography.Title>
                  {BUILTIN_TOOLS.map((t) => (
                    <Form.Item key={t.name} name={`bt_${t.name}`} valuePropName="checked"
                      style={{ marginBottom: 8 }}>
                      <Switch checkedChildren="开" unCheckedChildren="关" />
                      <span style={{ marginLeft: 10 }}>{t.label}</span>
                      <Tag style={{ marginLeft: 8 }} color={t.write ? 'orange' : 'default'}>
                        {t.perm}{t.write ? ' · 需人工确认' : ''}
                      </Tag>
                    </Form.Item>
                  ))}
                  <Typography.Title level={5}>管理类工具</Typography.Title>
                  <Form.Item name="admin_enabled" valuePropName="checked" style={{ marginBottom: 8 }}>
                    <Switch checkedChildren="开" unCheckedChildren="关" />
                    <span style={{ marginLeft: 10 }}>启用管理类工具（创建技能/智能体、写文档等）</span>
                  </Form.Item>
                  <Form.Item name="admin_tools" label="限定可用工具（留空=全部）">
                    <Select mode="multiple" allowClear placeholder="留空=全部管理工具"
                      showSearch optionFilterProp="value"
                      options={adminTools.map((n) => ({ value: n, label: n }))} />
                  </Form.Item>
                  <Button type="primary" onClick={save}>保存工具配置</Button>
                </Form>
              </Card>
            ),
          },
          {
            key: 'versions', label: '版本',
            children: (
              <Card title="版本快照（可回滚）"
                extra={<Button icon={<PlusOutlined />} onClick={async () => {
                  const note = window.prompt('版本备注（可选）', '') ?? undefined
                  await agentApi.snapshot(agentId, note); message.success('已生成快照'); load()
                }}>生成快照</Button>}>
                <Table
                  rowKey="id" dataSource={versions} pagination={false} size="small"
                  locale={{ emptyText: '暂无版本快照' }}
                  columns={[
                    { title: '版本', dataIndex: 'version', width: 90, render: (v: number) => <Tag>v{v}</Tag> },
                    { title: '备注', dataIndex: 'note', render: (v: string) => v || '-' },
                    { title: '时间', dataIndex: 'created_at', render: (v: string) => v ? String(v).slice(0, 19).replace('T', ' ') : '-' },
                    {
                      title: '操作', width: 100,
                      render: (_: any, r: any) => (
                        <Popconfirm title={`回滚到 v${r.version}？将覆盖当前配置`}
                          onConfirm={async () => { await agentApi.rollback(agentId, r.id); message.success('已回滚'); load() }}>
                          <Button size="small">回滚</Button>
                        </Popconfirm>
                      ),
                    },
                  ]}
                />
              </Card>
            ),
          },
        ]}
      />

      {/* 行为模式编辑（含全字段） */}
      <Modal title={editMode ? '编辑模式' : '添加模式'} open={modeOpen} onOk={submitMode}
        onCancel={() => setModeOpen(false)} destroyOnClose width={640}>
        <Form form={modeForm} layout="vertical" initialValues={{ is_default: false, sort: 0 }}>
          <Form.Item name="name" label="模式名称" rules={[{ required: true }]}><Input placeholder="如：写作模式 / 审核模式" /></Form.Item>
          <Form.Item name="system_prompt" label="该模式提示词（叠加在基础提示词后）"><Input.TextArea rows={5} /></Form.Item>
          <Form.Item name="kb_ids" label="知识库覆盖（留空=继承）">
            <Select mode="multiple" allowClear options={kbs.map((k) => ({ value: k.id, label: k.name }))} />
          </Form.Item>
          <Form.Item name="skill_ids" label="技能覆盖（留空=继承）">
            <Select mode="multiple" allowClear options={skills.map((s) => ({ value: s.id, label: s.name }))} />
          </Form.Item>
          <Form.Item name="is_default" label="设为默认" valuePropName="checked"><Switch /></Form.Item>
        </Form>
      </Modal>

      {/* 就地测试对话 */}
      <Drawer title="测试对话" width={520} open={testOpen} onClose={() => setTestOpen(false)}>
        <div ref={testListRef} style={{ height: 'calc(100vh - 200px)', overflowY: 'auto', marginBottom: 12 }}>
          {testMsgs.length === 0 && <Typography.Paragraph type="secondary">输入消息测试该智能体（保存后生效）。</Typography.Paragraph>}
          {testMsgs.map((m, i) => (
            <div key={i} style={{ marginBottom: 12 }}>
              <Tag color={m.role === 'user' ? 'blue' : 'green'}>{m.role === 'user' ? '你' : '智能体'}</Tag>
              <div style={{ marginTop: 4 }}>
                {m.role === 'assistant'
                  ? <MarkdownBody content={m.content || (testStreaming ? '…' : '')} />
                  : <div className="md-body">{m.content}</div>}
              </div>
            </div>
          ))}
        </div>
        <Space.Compact style={{ width: '100%' }}>
          <Input value={testInput} onChange={(e) => setTestInput(e.target.value)}
            placeholder="输入测试消息" onPressEnter={sendTest} />
          <Button type="primary" icon={<SendOutlined />} loading={testStreaming} onClick={sendTest}>发送</Button>
        </Space.Compact>
      </Drawer>
    </PageContainer>
  )
}
