import { useEffect, useState } from 'react'
import {
  Alert, Button, Card, Col, Collapse, Form, Input, InputNumber, List, message, Modal, Popconfirm, Row, Segmented, Select, Space, Tag, Tooltip, Typography,
} from 'antd'
import { PlusOutlined, DatabaseOutlined, EditOutlined, DeleteOutlined, ApiOutlined, CloudServerOutlined, FileImageOutlined, SettingOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { kbApi, providerApi, type KB, type ModelConfig } from '../../api'
import { errMsg } from '../../api/http'
import PageContainer from '../../components/PageContainer'
import EmptyState from '../../components/EmptyState'
import Can from '../../components/Can'
import { useAuth } from '../../stores/auth'

const visColor: Record<string, string> = { public: 'green', internal: 'blue', private: 'orange' }
const visLabel: Record<string, string> = { public: '公开', internal: '内部', private: '私有' }

const STRATEGY_OPTIONS = [
  { value: 'fixed', label: '定长切分（fixed）' },
  { value: 'recursive', label: '递归切分（recursive）' },
  { value: 'parent_child', label: '父子块（parent_child，默认）' },
]

export const CONNECTOR_OPTIONS = [
  { value: 'generic_http', label: '通用 HTTP（自定义 REST 接口）' },
  { value: 'dify', label: 'Dify 数据集' },
  { value: 'ragflow', label: 'RAGFlow' },
  { value: 'fastgpt', label: 'FastGPT' },
  { value: 'mcp', label: 'MCP 知识服务' },
  { value: 'sql_db', label: 'SQL 数据库（表/视图当知识源）' },
  { value: 'feishu_sheet', label: '飞书表格（多维表格/电子表格）' },
  { value: 'google_sheet', label: 'Google Sheets' },
]

/** 各连接器类型的关键配置字段（用于动态表单 + 提示） */
const CONNECTOR_FIELDS: Record<string, { key: string; label: string; ph?: string; required?: boolean }[]> = {
  generic_http: [
    { key: 'base_url', label: 'Base URL', ph: 'https://api.example.com', required: true },
    { key: 'search_path', label: '检索路径', ph: '/search（可含 {query}）' },
    { key: 'method', label: '方法', ph: 'GET / POST（默认 POST）' },
    { key: 'api_key', label: 'API Key', ph: '可选' },
    { key: 'request_template', label: '请求体模板', ph: '留空默认 {"query":"{query}","top_k":{top_k}}' },
    { key: 'response_list_path', label: '结果数组路径', ph: '如 data.records' },
    { key: 'content_path', label: '内容字段', ph: '默认 content' },
    { key: 'title_path', label: '标题字段', ph: '如 title' },
    { key: 'score_path', label: '分数字段', ph: '如 score' },
    { key: 'url_path', label: '原文链接字段', ph: '如 url' },
  ],
  dify: [
    { key: 'base_url', label: 'Base URL', ph: 'https://api.dify.ai/v1', required: true },
    { key: 'api_key', label: 'Dataset API Key', required: true },
    { key: 'dataset_id', label: '数据集 ID', required: true },
    { key: 'search_method', label: '检索方式', ph: 'semantic_search / full_text_search / hybrid_search' },
  ],
  ragflow: [
    { key: 'base_url', label: 'Base URL', ph: 'http://ragflow:9380', required: true },
    { key: 'api_key', label: 'API Key', required: true },
    { key: 'dataset_ids', label: '知识库 IDs', ph: '多个用逗号分隔', required: true },
  ],
  fastgpt: [
    { key: 'base_url', label: 'Base URL', ph: 'https://fastgpt.example.com', required: true },
    { key: 'api_key', label: 'API Key', required: true },
    { key: 'dataset_id', label: '知识库 ID', required: true },
  ],
  mcp: [
    { key: 'base_url', label: 'MCP 端点', ph: 'https://mcp.example.com/rpc', required: true },
    { key: 'api_key', label: 'API Key', ph: '可选' },
    { key: 'tool_name', label: '工具名', ph: '默认 search' },
    { key: 'args_template', label: '参数模板(JSON)', ph: '留空默认 {"query":"{query}","top_k":{top_k}}' },
  ],
  sql_db: [
    { key: 'dsn', label: '连接串(DSN)', ph: 'postgresql://用户:密码@主机/库 或 mysql+pymysql://... 或 sqlite:///./other.db', required: true },
    { key: 'query_sql', label: '检索 SQL', ph: 'SELECT * FROM t WHERE content LIKE :query LIMIT {top_k}', required: true },
    { key: 'columns', label: '参与拼接的列', ph: '逗号分隔，留空=全部列' },
    { key: 'title_col', label: '标题列', ph: '如 name' },
    { key: 'url_col', label: '原文链接列', ph: '如 url' },
  ],
  feishu_sheet: [
    { key: 'mode', label: '类型', ph: 'bitable（多维表格，默认）/ sheet（电子表格）' },
    { key: 'app_id', label: '飞书 App ID', required: true },
    { key: 'app_secret', label: '飞书 App Secret', required: true },
    { key: 'base_token', label: 'app_token / spreadsheet_token', ph: 'bitable 用 app_token；sheet 用 spreadsheet_token', required: true },
    { key: 'table_id', label: 'table_id', ph: 'bitable 模式必填，如 tblxxxx' },
    { key: 'sheet_id', label: 'sheet_id', ph: 'sheet 模式必填，如 0b12ab' },
    { key: 'search_cols', label: '参与检索的列名', ph: '逗号分隔，留空=全部列' },
    { key: 'title_col', label: '标题列名', ph: '可选' },
  ],
  google_sheet: [
    { key: 'spreadsheet_id', label: '表格 ID', ph: 'URL 中 /d/<这里>/ 的部分', required: true },
    { key: 'gid', label: '工作表 gid', ph: '默认 0' },
    { key: 'api_key', label: 'Google API Key', ph: '可选；不填则用「公开分享」的 CSV 导出' },
    { key: 'search_cols', label: '参与检索的列名', ph: '逗号分隔，留空=全部列' },
    { key: 'title_col', label: '标题列名', ph: '可选' },
  ],
}

export default function KBListPage() {
  const [kbs, setKbs] = useState<KB[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [editKb, setEditKb] = useState<KB | null>(null)
  const [embedModels, setEmbedModels] = useState<ModelConfig[]>([])
  const [strategy, setStrategy] = useState<string>('recursive')
  const [sourceType, setSourceType] = useState<string>('local')
  const [indexMode, setIndexMode] = useState<string>('vector')
  const [connKind, setConnKind] = useState<string>('generic_http')
  const [connTesting, setConnTesting] = useState(false)
  const [connResult, setConnResult] = useState<{ count: number; items: any[] } | null>(null)
  const [form] = Form.useForm()
  const nav = useNavigate()
  const hasPermission = useAuth((s) => s.hasPermission)

  const load = async () => {
    setLoading(true)
    try {
      setKbs(await kbApi.list())
    } catch (e) {
      message.error(errMsg(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    providerApi.configs().then((cs) => setEmbedModels(cs.filter((c) => c.purpose === 'embedding'))).catch(() => {})
  }, [])

  const openModal = (kb?: KB) => {
    setEditKb(kb || null)
    form.resetFields()
    if (kb) {
      form.setFieldsValue(kb)
      setStrategy(kb.chunk_strategy?.type || 'parent_child')
      setSourceType(kb.source_type || 'local')
      setIndexMode(kb.index_mode || 'vector')
      setConnKind(kb.connector_kind || 'generic_http')
      if (kb.source_type === 'external') {
        // 拉取脱敏配置回填（api_key 为掩码，未改动则后端沿用旧值）
        kbApi.getConnector(kb.id).then((r) => {
          if (r.config) form.setFieldsValue({ connector_config: r.config })
        }).catch(() => {})
      }
    } else {
      form.setFieldsValue({ visibility: 'internal' })
      form.setFieldsValue({ chunk_strategy: { type: 'parent_child', child_size: 400, parent_size: 1500, overlap: 50 } })
      setStrategy('parent_child')
      setSourceType('local')
      setIndexMode('vector')
      setConnKind('generic_http')
    }
    setOpen(true)
  }

  const buildConnectorConfig = () => {
    const raw = form.getFieldValue('connector_config') || {}
    const cfg: Record<string, any> = {}
    for (const f of CONNECTOR_FIELDS[connKind] || []) {
      let v = raw[f.key]
      if (v === undefined || v === null || v === '') continue
      if (f.key === 'request_template' || f.key === 'args_template') {
        try { v = JSON.parse(v) } catch { throw new Error(`${f.label} 不是合法 JSON`) }
      }
      cfg[f.key] = v
    }
    return cfg
  }

  const onSubmit = async () => {
    const v = await form.validateFields()
    try {
      const payload: any = { ...v }
      if (sourceType === 'external') {
        payload.source_type = 'external'
        payload.connector_kind = connKind
        payload.connector_config = buildConnectorConfig()
        // 外部源不需要分块/向量模型
        delete payload.chunk_strategy
        delete payload.embedding_model_id
      } else if (sourceType === 'entry') {
        payload.source_type = 'entry'
        // 图文库用默认分块/向量模型
        delete payload.chunk_strategy
        delete payload.embedding_model_id
      } else {
        payload.source_type = 'local'
        payload.index_mode = indexMode
        // 纯关键词模式不需要向量模型
        if (indexMode === 'keyword') delete payload.embedding_model_id
      }
      if (editKb) await kbApi.update(editKb.id, payload)
      else await kbApi.create(payload)
      message.success('已保存')
      setOpen(false)
      load()
    } catch (e) {
      message.error(errMsg(e))
    }
  }

  const testConnector = async () => {
    setConnTesting(true)
    setConnResult(null)
    try {
      const cfg = buildConnectorConfig()
      const r = await kbApi.testConnectorConfig(connKind, cfg)
      setConnResult({ count: r.count, items: r.items })
      message.success(`连接成功，返回 ${r.count} 条`)
    } catch (e) {
      message.error(errMsg(e))
    } finally {
      setConnTesting(false)
    }
  }

  const isParentChild = strategy === 'parent_child'
  const isExternal = sourceType === 'external'
  const isEntry = sourceType === 'entry'

  return (
    <PageContainer
      title="知识库"
      extra={<Can perm="kb:create"><Button type="primary" icon={<PlusOutlined />} onClick={() => openModal()}>新建知识库</Button></Can>}
    >
      {kbs.length === 0 && !loading ? (
        <EmptyState description="暂无知识库，点击右上角创建" actionText={hasPermission('kb:create') ? '新建知识库' : undefined} onAction={() => openModal()} />
      ) : (
        <Row gutter={[16, 16]}>
          {kbs.map((kb) => (
            <Col key={kb.id} xs={24} sm={12} md={8} lg={6}>
              <Card
                hoverable
                onClick={() => nav(`/kb/${kb.id}`)}
                title={<Space>{(kb.source_type === 'external' ? <CloudServerOutlined /> : kb.source_type === 'entry' ? <FileImageOutlined /> : <DatabaseOutlined />)}{kb.name}</Space>}
                extra={
                  <Space className="kb-card-actions" onClick={(e) => e.stopPropagation()}>
                    {kb.source_type === 'external' && <Tag color="purple">外部</Tag>}
                    {kb.source_type === 'entry' && <Tag color="cyan">图文</Tag>}
                    {kb.source_type !== 'external' && kb.source_type !== 'entry' && kb.index_mode === 'keyword' && (
                      <Tag color="orange">关键词</Tag>
                    )}
                    <Tag color={visColor[kb.visibility]}>{visLabel[kb.visibility]}</Tag>
                    <Can perm="kb:update">
                      <Tooltip title="编辑">
                        <Button size="small" type="text" icon={<EditOutlined />} onClick={() => openModal(kb)} />
                      </Tooltip>
                    </Can>
                    <Can perm="kb:delete">
                      <Popconfirm title="删除该知识库？" onConfirm={async () => { await kbApi.remove(kb.id); message.success('已删除'); load() }}>
                        <Button size="small" type="text" danger icon={<DeleteOutlined />} />
                      </Popconfirm>
                    </Can>
                  </Space>
                }
              >
                <Typography.Paragraph ellipsis={{ rows: 2 }} type="secondary" style={{ minHeight: 44 }}>
                  {kb.description || '暂无描述'}
                </Typography.Paragraph>
                <Space split="|" style={{ fontSize: 12, color: '#888' }}>
                  {kb.source_type === 'external'
                    ? <span>{CONNECTOR_OPTIONS.find((c) => c.value === kb.connector_kind)?.label || kb.connector_kind || '外部源'}</span>
                    : kb.source_type === 'entry'
                      ? <span>{kb.doc_count} 条目</span>
                      : <><span>{kb.doc_count} 文档</span><span>{kb.chunk_count} 分块</span></>}
                </Space>
              </Card>
            </Col>
          ))}
        </Row>
      )}

      <Modal title={editKb ? '编辑知识库' : '新建知识库'} open={open} onOk={onSubmit} onCancel={() => setOpen(false)} destroyOnClose width={680}>
        <Form form={form} layout="vertical" initialValues={{ visibility: 'internal' }}>
          <Form.Item label="知识库类型" style={{ marginBottom: 16 }}>
            <Segmented block size="large" value={sourceType} onChange={(v) => setSourceType(v as string)}
              options={[
                { value: 'local', label: '向量知识库' },
                { value: 'entry', label: '图文知识库' },
                { value: 'external', label: '外部知识库' },
              ]} />
            <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 6 }}>
              {isExternal ? '对接外部 RAG 系统，检索时实时调用并融合排序，无需入库。'
                : isEntry ? '直接录入图文条目（一段文字 + 配套图片/附件），问题命中后自动把配套文件发给提问者。'
                  : '上传文档（PDF/Office/图片等）自动解析、分块、向量化，做检索增强问答。'}
            </Typography.Text>
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder={isEntry ? '如：产品图文手册' : isExternal ? '如：Dify 产品库' : '如：产品手册库'} />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} placeholder="可选" />
          </Form.Item>
          <Form.Item name="visibility" label="可见性" extra="公开/内部=本租户全员可见；私有=仅创建者与显式成员">
            <Select options={[
              { value: 'public', label: '公开' },
              { value: 'internal', label: '内部（默认）' },
              { value: 'private', label: '私有' },
            ]} />
          </Form.Item>

          {isExternal ? (
            <>
              <Form.Item label="连接器类型">
                <Select value={connKind} onChange={setConnKind} options={CONNECTOR_OPTIONS} />
              </Form.Item>
              {CONNECTOR_FIELDS[connKind].map((f) => (
                <Form.Item key={f.key} name={['connector_config', f.key]}
                  label={f.label} rules={f.required ? [{ required: true, message: `请填写${f.label}` }] : undefined}>
                  <Input placeholder={f.ph} />
                </Form.Item>
              ))}
              <Button icon={<ApiOutlined />} loading={connTesting} onClick={testConnector} block>
                测试连接（检索一次看返回）
              </Button>
              {connResult && (
                <List
                  size="small" bordered style={{ marginTop: 8, maxHeight: 200, overflow: 'auto' }}
                  dataSource={connResult.items}
                  locale={{ emptyText: '连接成功但无返回，请检查响应映射' }}
                  renderItem={(it: any) => (
                    <List.Item>
                      <div style={{ width: '100%' }}>
                        <Tag color="green">{it.title || '（无标题）'}</Tag>
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>{it.content}</Typography.Text>
                      </div>
                    </List.Item>
                  )}
                />
              )}
              <Alert type="info" showIcon style={{ marginTop: 8 }}
                message="外部知识库在检索时实时调用外部系统，与本地知识库一起排序融合，不需入库。" />
            </>
          ) : isEntry ? (
            <Alert type="info" showIcon style={{ marginTop: 4 }}
              message="图文知识库"
              description="创建后进入详情页「添加图文条目」：填写一段文字并上传配套图片/附件。当有人问到与这段文字相关的问题、被检索命中时，配套图片/附件会自动发送给提问者（渠道用户）。" />
          ) : (
            <>
              <Form.Item label="索引方式" style={{ marginBottom: 12 }}>
                <Segmented block value={indexMode} onChange={(v) => setIndexMode(v as string)}
                  options={[
                    { value: 'vector', label: '向量 + 关键词（推荐）' },
                    { value: 'keyword', label: '纯关键词' },
                  ]} />
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {indexMode === 'keyword'
                    ? '纯关键词（BM25）：不需要任何向量模型即可使用，适合术语 / 编号 / 短条目 / 问答话术；口语化长问的语义召回弱于向量。'
                    : '向量 + 关键词混合检索：语义理解更强，需要配置 embedding 向量模型。'}
                </Typography.Text>
              </Form.Item>
              {indexMode !== 'keyword' && (
                <Form.Item name="embedding_model_id" label="向量模型（Embedding）" extra="为空则用系统默认向量模型；不确定就留空">
                  <Select allowClear placeholder="默认向量模型"
                    options={embedModels.map((m) => ({ value: m.id, label: `${m.display_name || m.model_name}${m.embedding_dim ? `（${m.embedding_dim}维）` : ''}` }))} />
                </Form.Item>
              )}
              <Collapse ghost size="small" items={[{
                key: 'adv',
                label: <span style={{ fontSize: 13 }}><SettingOutlined /> 高级设置（分块策略，一般无需修改）</span>,
                children: (
                  <>
                    <Form.Item name={['chunk_strategy', 'type']} label="分块策略" style={{ marginBottom: 12 }}>
                      <Select options={STRATEGY_OPTIONS} onChange={(v) => setStrategy(v)} />
                    </Form.Item>
                    <Row gutter={12}>
                      <Col span={isParentChild ? 8 : 12}>
                        <Form.Item name={['chunk_strategy', 'child_size']} label="子块字数">
                          <InputNumber style={{ width: '100%' }} min={64} max={4096} placeholder="400" />
                        </Form.Item>
                      </Col>
                      {isParentChild && (
                        <Col span={8}>
                          <Form.Item name={['chunk_strategy', 'parent_size']} label="父块字数">
                            <InputNumber style={{ width: '100%' }} min={256} max={8192} placeholder="1500" />
                          </Form.Item>
                        </Col>
                      )}
                      <Col span={isParentChild ? 8 : 12}>
                        <Form.Item name={['chunk_strategy', 'overlap']} label="重叠字数">
                          <InputNumber style={{ width: '100%' }} min={0} max={1024} placeholder="50" />
                        </Form.Item>
                      </Col>
                    </Row>
                  </>
                ),
              }]} />
              {editKb && (
                <Alert type="warning" showIcon style={{ marginTop: 4 }}
                  message="修改索引方式 / 分块策略 / 向量模型后，已有文档需「重新处理」才会生效。" />
              )}
            </>
          )}
        </Form>
      </Modal>
    </PageContainer>
  )
}
