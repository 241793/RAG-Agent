import { useEffect, useState } from 'react'
import {
  Alert, Badge, Button, Card, Col, Descriptions, Drawer, Form, Input, List, message, Modal,
  Popconfirm, Row, Select, Space, Switch, Tag, Typography,
} from 'antd'
import {
  PlusOutlined, DeleteOutlined, EditOutlined, ApiOutlined, WechatOutlined,
  QqOutlined, CloudServerOutlined, TeamOutlined, ExperimentOutlined, QrcodeOutlined, LinkOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { agentApi, channelApi, kbApi, type Agent, type ChannelItem, type KB } from '../../api'
import { errMsg } from '../../api/http'
import PageContainer from '../../components/PageContainer'
import EmptyState from '../../components/EmptyState'
import Can from '../../components/Can'
import { useAuth } from '../../stores/auth'
import WxclawScanLoginModal from '../../components/WxclawScanLoginModal'

const KIND_META: Record<string, { label: string; icon: any; color: string; hint: string }> = {
  qqbot: { label: 'QQ 机器人', icon: <QqOutlined />, color: 'blue', hint: 'QQ 官方 Bot（WebSocket 长连接）' },
  wxclaw: { label: '微信（非官方）', icon: <WechatOutlined />, color: 'green', hint: 'iLink 协议，HTTP 轮询；非官方，可能受上游变更影响' },
  wework: { label: '企业微信', icon: <TeamOutlined />, color: 'cyan', hint: '企微智能机器人群/私聊（长连接）' },
  feishu: { label: '飞书', icon: <CloudServerOutlined />, color: 'purple', hint: '飞书自建应用（lark-oapi 长连接，需安装 lark-oapi）' },
}

/** 各渠道的配置字段 */
const CONFIG_FIELDS: Record<string, { key: string; label: string; ph?: string; required?: boolean }[]> = {
  qqbot: [
    { key: 'app_id', label: 'AppID', required: true },
    { key: 'client_secret', label: 'Client Secret', required: true },
  ],
  wxclaw: [
    // api 地址固定为 ilinkai.weixin.qq.com，不在此暴露；token 通过"扫码登录"获取或手填
    { key: 'token', label: 'Token', ph: '可点「扫码登录」自动获取，或手动填写' },
    { key: 'poll_interval_sec', label: '轮询间隔(秒)', ph: '默认 2' },
    { key: 'x_wechat_uin', label: 'X-WECHAT-UIN', ph: '可选' },
  ],
  wework: [
    { key: 'bot_id', label: 'Bot ID', required: true },
    { key: 'secret', label: 'Secret', required: true },
    { key: 'ws_url', label: 'WS 地址', ph: '默认 wss://openws.work.weixin.qq.com' },
  ],
  feishu: [
    { key: 'app_id', label: 'App ID', required: true },
    { key: 'app_secret', label: 'App Secret', required: true },
  ],
}

export default function ChannelListPage() {
  const navigate = useNavigate()
  const [channels, setChannels] = useState<ChannelItem[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [kbs, setKbs] = useState<KB[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [edit, setEdit] = useState<ChannelItem | null>(null)
  const [kind, setKind] = useState<string>('qqbot')
  const [form] = Form.useForm()
  const [usersChannel, setUsersChannel] = useState<ChannelItem | null>(null)
  const [users, setUsers] = useState<any[]>([])
  const [scanChannel, setScanChannel] = useState<ChannelItem | null>(null)
  const [formScan, setFormScan] = useState(false)
  const [wxToken, setWxToken] = useState('')  // 微信 token（扫码回填；渲染时同步到表单）
  const hasPermission = useAuth((s) => s.hasPermission)
  const canManage = hasPermission('channel:manage')

  const load = async () => {
    setLoading(true)
    try {
      setChannels(await channelApi.list())
      setAgents(await agentApi.list())
      setKbs(await kbApi.list())
    } catch (e) { message.error(errMsg(e)) }
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  const openModal = (c?: ChannelItem) => {
    setEdit(c || null)
    form.resetFields()
    setWxToken('')
    if (c) {
      setKind(c.kind)
      form.setFieldsValue({ ...c, config: c.config })
      setWxToken(String(c.config?.token ?? ''))
    } else {
      setKind('qqbot')
      form.setFieldsValue({ enabled: true, reply_mode: 'rag', command_prefix: '/', kb_mode: 'auto', service_mode: 'qa', default_kb_ids: [] })
    }
    setOpen(true)
  }

  const buildConfig = () => {
    const raw = form.getFieldValue('config') || {}
    const cfg: Record<string, any> = {}
    for (const f of CONFIG_FIELDS[kind] || []) {
      const v = raw[f.key]
      if (v === undefined || v === null || v === '') continue
      cfg[f.key] = v
    }
    // 微信 token 优先用受控 state（扫码回填不依赖 antd 内部更新）
    if (kind === 'wxclaw' && wxToken) cfg.token = wxToken
    return cfg
  }

  const submit = async () => {
    const v = await form.validateFields()
    const payload: any = { ...v, kind, config: buildConfig() }
    if (payload.kb_mode !== 'custom') payload.default_kb_ids = []
    try {
      if (edit) await channelApi.update(edit.id, payload)
      else await channelApi.create(payload)
      message.success('已保存')
      setOpen(false); load()
    } catch (e) { message.error(errMsg(e)) }
  }

  const testConn = async (c: ChannelItem) => {
    try {
      const r = await channelApi.test(c.id)
      if (r.ok) message.success(`连接正常：${r.message}（${r.latency_ms}ms）`)
      else message.error(`连接失败：${r.message}`)
    } catch (e) { message.error(errMsg(e)) }
  }

  const openUsers = async (c: ChannelItem) => {
    setUsersChannel(c)
    try { setUsers(await channelApi.users(c.id)) } catch (e) { message.error(errMsg(e)) }
  }

  return (
    <PageContainer
      title="外部渠道"
      subtitle="让团队通过 QQ / 微信 / 企业微信 / 飞书 直接跟本平台对话（知识库问答 + 智能体 + 指令）"
      extra={<Can perm="channel:manage"><Button type="primary" icon={<PlusOutlined />} onClick={() => openModal()}>接入渠道</Button></Can>}
    >
      {channels.length === 0 && !loading ? (
        <EmptyState description="尚未接入任何外部渠道" actionText={canManage ? '接入渠道' : undefined} onAction={() => openModal()} />
      ) : (
        <Row gutter={[16, 16]}>
          {channels.map((c) => {
            const meta = KIND_META[c.kind] || { label: c.kind, icon: <ApiOutlined />, color: 'default', hint: '' }
            return (
              <Col key={c.id} xs={24} md={12} xl={8}>
                <Card
                  title={<Space>{meta.icon}{c.name}<Tag color={meta.color}>{meta.label}</Tag></Space>}
                  extra={
                    <Space>
                      <Badge status={c.connected ? 'success' : c.enabled ? 'warning' : 'default'}
                        text={c.connected ? '已连接' : c.enabled ? '连接中' : '已停用'} />
                      {c.kind === 'wxclaw' && canManage && (
                        <Button size="small" type="primary" ghost icon={<QrcodeOutlined />}
                          data-testid="wx-scan-btn" onClick={() => setScanChannel(c)}>扫码</Button>
                      )}
                    </Space>
                  }
                  actions={[
                    <ExperimentOutlined key="t" title="测试连接" onClick={() => testConn(c)} />,
                    <TeamOutlined key="u" title="查看用户" onClick={() => openUsers(c)} />,
                    canManage ? <EditOutlined key="e" title="编辑" onClick={() => openModal(c)} /> : null,
                    canManage ? (
                      <Popconfirm key="d" title="删除该渠道？" onConfirm={async () => { await channelApi.remove(c.id); message.success('已删除'); load() }}>
                        <DeleteOutlined />
                      </Popconfirm>
                    ) : null,
                  ].filter(Boolean)}
                >
                  <Typography.Paragraph type="secondary" style={{ fontSize: 12, minHeight: 36 }}>
                    {meta.hint}
                  </Typography.Paragraph>
                  <Descriptions column={1} size="small">
                    <Descriptions.Item label="回复模式">{c.reply_mode === 'agent' ? '智能体' : '知识库问答'}</Descriptions.Item>
                    <Descriptions.Item label="检索范围">
                      {c.kb_mode === 'off' ? '不检索（纯聊天）'
                        : c.kb_mode === 'custom' ? `指定 ${(c.default_kb_ids || []).length} 个库`
                          : '自动（全部有权库）'}
                    </Descriptions.Item>
                    <Descriptions.Item label="指令前缀"><code>{c.command_prefix}</code></Descriptions.Item>
                  </Descriptions>
                  {c.last_error && <Alert type="error" showIcon style={{ marginTop: 8 }} message={c.last_error} />}
                </Card>
              </Col>
            )
          })}
        </Row>
      )}

      <Modal title={edit ? '编辑渠道' : '接入渠道'} open={open} onOk={submit} onCancel={() => setOpen(false)} destroyOnClose width={620}>
        <Form form={form} layout="vertical">
          <Form.Item label="渠道类型" required>
            <Select value={kind} onChange={setKind} disabled={!!edit}
              options={Object.entries(KIND_META).map(([v, m]) => ({ value: v, label: m.label }))} />
          </Form.Item>
          {KIND_META[kind] && <Alert type="info" showIcon style={{ marginBottom: 16 }} message={KIND_META[kind].hint} />}
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input placeholder="如：客服机器人群" /></Form.Item>
          {(CONFIG_FIELDS[kind] || []).map((f) => (
            kind === 'wxclaw' && f.key === 'token' ? (
              // 微信 token：完全受控（扫码回填不依赖 antd Form 内部更新）
              <Form.Item key={f.key} label={f.label}>
                <Space.Compact style={{ width: '100%' }}>
                  <Input placeholder={f.ph} value={wxToken} onChange={(e) => setWxToken(e.target.value)} />
                  <Button icon={<QrcodeOutlined />} onClick={() => setFormScan(true)}>扫码获取</Button>
                </Space.Compact>
              </Form.Item>
            ) : (
              <Form.Item key={f.key} name={['config', f.key]} label={f.label}
                rules={f.required && !edit ? [{ required: true, message: `请填写${f.label}` }] : undefined}>
                <Input placeholder={f.ph} />
              </Form.Item>
            )
          ))}
          <Form.Item name="reply_mode" label="回复模式" extra="不选知识库/智能体时 = 纯聊天（和「智能问答」一样用模型自身知识回答）">
            <Select options={[
              { value: 'rag', label: '知识库问答（可选知识库，不选则纯聊天）' },
              { value: 'agent', label: '智能体（选定智能体后由其回答）' },
            ]} />
          </Form.Item>
          <Form.Item name="service_mode" label="服务模式"
            extra="只答=纯咨询，用户说「转人工」也当普通问题；客服=识别转人工关键词并生成工单，由客服跟进">
            <Select options={[
              { value: 'qa', label: '只答（纯咨询，不转人工）' },
              { value: 'support', label: '客服（可转人工建工单）' },
            ]} />
          </Form.Item>
          <Form.Item name="default_lang" label="默认回答语言（多语言客服）"
            extra="客户没明说语言时用此语言；客户可发 /lang en 自行切换。留空=自动判断">
            <Select allowClear placeholder="自动判断" options={[
              { value: 'zh', label: '中文' }, { value: 'en', label: 'English' },
              { value: 'ja', label: '日本語' }, { value: 'ko', label: '한국어' },
              { value: 'es', label: 'Español' }, { value: 'fr', label: 'Français' },
              { value: 'de', label: 'Deutsch' }, { value: 'ru', label: 'Русский' },
              { value: 'pt', label: 'Português' },
            ]} />
          </Form.Item>
          <Form.Item name="kb_mode" label="检索范围"
            extra="与「智能问答」一致：自动=按该渠道用户权限检索其全部有权知识库">
            <Select options={[
              { value: 'auto', label: '自动（全部有权知识库）' },
              { value: 'custom', label: '指定知识库' },
              { value: 'off', label: '不检索（纯聊天）' },
            ]} />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(p, c) => p.kb_mode !== c.kb_mode}>
            {({ getFieldValue }) => getFieldValue('kb_mode') === 'custom' && (
              <Form.Item name="default_kb_ids" label="指定知识库" rules={[{ required: true, message: '请选择至少一个知识库' }]}>
                <Select mode="multiple" allowClear placeholder="选择知识库"
                  options={kbs.map((k) => ({ value: k.id, label: k.name }))} />
              </Form.Item>
            )}
          </Form.Item>
          <Form.Item name="default_agent_id" label="默认智能体（可空）"
            extra="仅当「回复模式=智能体」时生效；留空则用上面的检索逻辑">
            <Select allowClear placeholder="不选 = 不使用智能体"
              options={agents.map((a) => ({ value: a.id, label: a.name }))} />
          </Form.Item>
          <Form.Item name="command_prefix" label="指令前缀"><Input style={{ width: 100 }} /></Form.Item>
          <Form.Item name="greeting" label="欢迎语（用户首次对话时发送）"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked"><Switch /></Form.Item>
        </Form>
      </Modal>

      <Drawer title={`渠道用户：${usersChannel?.name || ''}`} width={620}
        open={!!usersChannel} onClose={() => setUsersChannel(null)}>
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          通过该渠道首次发消息的用户会自动建档（只读外部客户）。要提升为内部权限，请在
          「渠道身份绑定」页把该身份绑定到内部账号——绑定后即继承该账号全部权限。
        </Typography.Paragraph>
        <Can perm="channel:manage">
          <Button size="small" icon={<LinkOutlined />} style={{ marginBottom: 12 }}
            onClick={() => navigate('/admin/channel-users')}>前往「渠道身份绑定」</Button>
        </Can>
        <List
          dataSource={users} locale={{ emptyText: '暂无用户' }}
          renderItem={(u: any) => (
            <List.Item>
              <Space wrap>
                <Tag>{u.display_name || u.external_id}</Tag>
                {u.bound_user_id
                  ? <Tag color="green" icon={<LinkOutlined />}>{u.bound_user_name || `账号 #${u.bound_user_id}`}（内部）</Tag>
                  : <Tag color="default">外部客户（只读）</Tag>}
                {u.bind_code && <Tag color="blue">绑定码 {u.bind_code}</Tag>}
                {u.agent_id && <Tag color="purple">智能体 #{u.agent_id}</Tag>}
              </Space>
            </List.Item>
          )}
        />
      </Drawer>

      <WxclawScanLoginModal
        channelId={scanChannel?.id ?? null}
        channelName={scanChannel?.name}
        onClose={() => setScanChannel(null)}
        onSuccess={() => load()}
      />

      {/* 新建/编辑表单内扫码：拿到 token 填回表单 */}
      <WxclawScanLoginModal
        open={formScan}
        channelName="新建微信渠道"
        onClose={() => setFormScan(false)}
        onToken={(token) => {
          setWxToken(token)
          form.setFieldValue(['config', 'token'], token)
          message.success('token 已填入，可继续填写其它项并保存')
        }}
      />
    </PageContainer>
  )
}
