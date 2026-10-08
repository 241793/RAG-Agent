import { useEffect, useRef, useState } from 'react'
import {
  Button, Card, Col, Descriptions, Drawer, Empty, Form, Input, List, message, Modal, Popconfirm,
  Progress, Row, Select, Space, Statistic, Table, Tag, Typography,
} from 'antd'
import {
  PlayCircleOutlined, PlusOutlined, DeleteOutlined, DownloadOutlined, ReloadOutlined,
} from '@ant-design/icons'
import {
  evalApi, kbApi, type EvalDataset, type EvalQuestion, type EvalResult, type EvalRun, type KB,
} from '../../api'
import { errMsg } from '../../api/http'
import PageContainer from '../../components/PageContainer'
import Can from '../../components/Can'

function scoreTag(v?: number | null) {
  if (v == null) return <Tag>—</Tag>
  const color = v >= 4 ? 'green' : v >= 3 ? 'orange' : 'red'
  return <Tag color={color}>{v}</Tag>
}

export default function EvalPage() {
  const [datasets, setDatasets] = useState<EvalDataset[]>([])
  const [kbs, setKbs] = useState<KB[]>([])
  const [dsId, setDsId] = useState<number | undefined>()
  const [questions, setQuestions] = useState<EvalQuestion[]>([])
  const [run, setRun] = useState<EvalRun | null>(null)
  const [results, setResults] = useState<EvalResult[]>([])
  const [running, setRunning] = useState(false)
  const [dsModal, setDsModal] = useState(false)
  const [editDs, setEditDs] = useState<EvalDataset | null>(null)
  const [qModal, setQModal] = useState(false)
  const [qDrawer, setQDrawer] = useState(false)
  const [dsForm] = Form.useForm()
  const [qForm] = Form.useForm()
  const pollRef = useRef<any>(null)

  const loadDatasets = async () => {
    try {
      const list = await evalApi.datasets()
      setDatasets(list)
      if (!dsId && list.length) setDsId(list[0].id)
    } catch (e) { message.error(errMsg(e)) }
  }
  const loadQuestions = async () => {
    if (!dsId) { setQuestions([]); return }
    try { setQuestions(await evalApi.questions(dsId)) } catch (e) { message.error(errMsg(e)) }
  }
  useEffect(() => { loadDatasets(); kbApi.list().then(setKbs).catch(() => {}) }, [])
  useEffect(() => { loadQuestions(); setRun(null); setResults([]) }, [dsId])
  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current) }, [])

  const openDs = (d?: EvalDataset) => {
    setEditDs(d || null)
    if (d) dsForm.setFieldsValue({ name: d.name, description: d.description, kb_ids: d.kb_ids || [] })
    else dsForm.resetFields()
    setDsModal(true)
  }
  const saveDs = async () => {
    const v = await dsForm.validateFields().catch(() => null)
    if (!v) return
    try {
      if (editDs) await evalApi.updateDataset(editDs.id, v)
      else await evalApi.createDataset(v)
      message.success('已保存'); setDsModal(false); loadDatasets()
    } catch (e) { message.error(errMsg(e)) }
  }
  const removeDs = async (id: number) => {
    try { await evalApi.removeDataset(id); message.success('已删除'); setDsId(undefined); loadDatasets() }
    catch (e) { message.error(errMsg(e)) }
  }

  const openQ = (q?: EvalQuestion) => {
    if (q) qForm.setFieldsValue({ question: q.question, expected_answer: q.expected_answer, expected_doc_ids: (q.expected_doc_ids || []).join(',') })
    else qForm.resetFields()
    setQModal(true)
  }
  const saveQ = async () => {
    const v = await qForm.validateFields().catch(() => null)
    if (!v || !dsId) return
    const payload: any = { question: v.question, expected_answer: v.expected_answer }
    if (v.expected_doc_ids) {
      payload.expected_doc_ids = String(v.expected_doc_ids).split(',').map((s: string) => parseInt(s.trim(), 10)).filter((n: number) => !isNaN(n))
    }
    try { await evalApi.addQuestion(dsId, payload); message.success('已添加'); setQModal(false); loadQuestions() }
    catch (e) { message.error(errMsg(e)) }
  }
  const removeQ = async (id: number) => {
    try { await evalApi.removeQuestion(id); loadQuestions() } catch (e) { message.error(errMsg(e)) }
  }

  const startRun = async () => {
    if (!dsId) return
    try {
      const r = await evalApi.run(dsId)
      setRun(r); setResults([]); setRunning(true)
      message.success('评测已开始，正在逐题生成与打分…')
      if (pollRef.current) clearInterval(pollRef.current)
      pollRef.current = setInterval(async () => {
        try {
          const cur = await evalApi.getRun(r.id)
          setRun(cur)
          if (cur.status === 'done' || cur.status === 'failed') {
            clearInterval(pollRef.current); pollRef.current = null; setRunning(false)
            if (cur.status === 'done') {
              setResults(await evalApi.runResults(r.id))
              message.success('评测完成')
            } else message.error(cur.error || '评测失败')
          }
        } catch { /* 忽略轮询错误 */ }
      }, 2000)
    } catch (e) { message.error(errMsg(e)); setRunning(false) }
  }

  const downloadCsv = () => {
    if (!run) return
    const token = localStorage.getItem('access_token')
    fetch(evalApi.exportUrl(run.id), { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then((r) => r.blob())
      .then((b) => {
        const a = document.createElement('a')
        a.href = URL.createObjectURL(b); a.download = `eval_run_${run.id}.csv`; a.click()
      }).catch((e) => message.error(errMsg(e)))
  }

  const s = run?.summary || {}

  return (
    <PageContainer
      title="问答质量评估"
      subtitle="用一组测试问题批量跑 RAG 问答，由 AI 裁判打分（忠实度/相关性），并统计期望文档命中率——量化知识库答得准不准"
      extra={
        <Can perm="eval:manage">
          <Space>
            <Button icon={<PlusOutlined />} onClick={() => openDs()}>新建数据集</Button>
            <Button type="primary" icon={<PlayCircleOutlined />} loading={running}
              disabled={!dsId || !questions.length} onClick={startRun}>运行评测</Button>
          </Space>
        </Can>
      }
    >
      <Row gutter={16}>
        <Col xs={24} md={7}>
          <Card size="small" title="数据集" bordered={false}
            extra={<Button size="small" icon={<PlusOutlined />} onClick={() => openDs()} />}>
            {datasets.length === 0 ? <Empty description="暂无数据集" /> : (
              <List size="small" dataSource={datasets}
                renderItem={(d) => (
                  <List.Item
                    style={{ cursor: 'pointer', background: d.id === dsId ? '#e6f4ff' : undefined, paddingLeft: 8, borderRadius: 4 }}
                    onClick={() => setDsId(d.id)}
                    actions={[
                      <a key="e" onClick={(e) => { e.stopPropagation(); openDs(d) }}>改</a>,
                      <Popconfirm key="d" title="删除该数据集？" onConfirm={() => removeDs(d.id)}>
                        <a onClick={(e) => e.stopPropagation()}>删</a>
                      </Popconfirm>,
                    ]}>
                    <List.Item.Meta title={d.name}
                      description={<Typography.Text type="secondary" style={{ fontSize: 12 }}>{d.question_count ?? 0} 个问题</Typography.Text>} />
                  </List.Item>
                )} />
            )}
          </Card>
        </Col>

        <Col xs={24} md={17}>
          <Card size="small" bordered={false} title={`问题（${questions.length}）`}
            extra={<Can perm="eval:manage"><Button size="small" icon={<PlusOutlined />} disabled={!dsId} onClick={() => openQ()}>添加问题</Button></Can>}>
            <Table size="small" rowKey="id" dataSource={questions} pagination={{ pageSize: 8 }}
              locale={{ emptyText: '选择数据集后添加测试问题（问题 + 可选标准答案 + 期望命中文档）' }}
              columns={[
                { title: '问题', dataIndex: 'question', ellipsis: true },
                { title: '标准答案', dataIndex: 'expected_answer', ellipsis: true, width: 200,
                  render: (v) => v || <Typography.Text type="secondary">—</Typography.Text> },
                { title: '期望文档', dataIndex: 'expected_doc_ids', width: 110,
                  render: (v) => (v && v.length) ? v.join(',') : '—' },
                { title: '操作', width: 70, render: (_: any, r: EvalQuestion) => (
                  <Can perm="eval:manage"><a onClick={() => removeQ(r.id)}>删</a></Can>
                ) },
              ]} />
          </Card>

          {run && (
            <Card size="small" bordered={false} style={{ marginTop: 16 }} title="评测结果"
              extra={<Button size="small" icon={<DownloadOutlined />} disabled={run.status !== 'done'} onClick={downloadCsv}>导出 CSV</Button>}>
              {run.status === 'running' || run.status === 'pending' ? (
                <div style={{ padding: '8px 0' }}>
                  <Progress percent={run.total ? Math.round((run.progress / run.total) * 100) : 0}
                    status="active" />
                  <Typography.Text type="secondary">已处理 {run.progress}/{run.total} 题…</Typography.Text>
                </div>
              ) : run.status === 'failed' ? (
                <Typography.Text type="danger">{run.error || '评测失败'}</Typography.Text>
              ) : (
                <>
                  <Row gutter={16} style={{ marginBottom: 12 }}>
                    <Col span={6}><Statistic title="忠实度均值" value={s.faithfulness ?? '—'} suffix="/5" /></Col>
                    <Col span={6}><Statistic title="相关性均值" value={s.relevance ?? '—'} suffix="/5" /></Col>
                    <Col span={6}><Statistic title="期望文档命中率"
                      value={s.hit_rate == null ? '—' : `${Math.round(s.hit_rate * 100)}%`} /></Col>
                    <Col span={6}><Statistic title="已打分题数" value={s.scored ?? 0} /></Col>
                  </Row>
                  <Table size="small" rowKey="id" dataSource={results} pagination={{ pageSize: 8 }}
                    columns={[
                      { title: '问题', dataIndex: 'question', ellipsis: true },
                      { title: '回答', dataIndex: 'answer', ellipsis: true,
                        render: (v, r) => (
                          <a onClick={() => Modal.info({ title: r.question, width: 720,
                            content: <div style={{ whiteSpace: 'pre-wrap' }}>{r.answer || r.error || '（无）'}</div> })}>
                            {(v || r.error || '—').slice(0, 40)}
                          </a>
                        ) },
                      { title: '命中', dataIndex: 'hit_expected', width: 70,
                        render: (v) => v == null ? <Tag>—</Tag> : v ? <Tag color="green">是</Tag> : <Tag color="red">否</Tag> },
                      { title: '忠实度', dataIndex: 'faithfulness', width: 80, render: scoreTag },
                      { title: '相关性', dataIndex: 'relevance', width: 80, render: scoreTag },
                      { title: '耗时', dataIndex: 'latency_ms', width: 80, render: (v) => v ? `${v}ms` : '—' },
                    ]} />
                </>
              )}
            </Card>
          )}
        </Col>
      </Row>

      <Modal title={editDs ? '编辑数据集' : '新建数据集'} open={dsModal} onOk={saveDs}
        onCancel={() => setDsModal(false)} destroyOnClose width={560}>
        <Form form={dsForm} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input placeholder="如：产品文档问答集" /></Form.Item>
          <Form.Item name="description" label="说明"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="kb_ids" label="评测知识库" extra="评测时只在这些知识库里检索">
            <Select mode="multiple" options={kbs.map((k) => ({ value: k.id, label: k.name }))} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title="添加测试问题" open={qModal} onOk={saveQ}
        onCancel={() => setQModal(false)} destroyOnClose width={620}>
        <Form form={qForm} layout="vertical">
          <Form.Item name="question" label="问题" rules={[{ required: true }]}><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="expected_answer" label="标准答案（可选，供裁判参考）"><Input.TextArea rows={3} /></Form.Item>
          <Form.Item name="expected_doc_ids" label="期望命中文档 ID（可选，逗号分隔）"
            extra="用于计算命中率：检索结果是否包含这些文档。可在知识库详情页查文档 ID">
            <Input placeholder="如：12,15" />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer title="评测详情" open={qDrawer} onClose={() => setQDrawer(false)} width={640}>
        {run && <Descriptions column={1} size="small" bordered>
          <Descriptions.Item label="状态">{run.status}</Descriptions.Item>
          <Descriptions.Item label="进度">{run.progress}/{run.total}</Descriptions.Item>
          <Descriptions.Item label="汇总">{JSON.stringify(run.summary || {})}</Descriptions.Item>
        </Descriptions>}
      </Drawer>
    </PageContainer>
  )
}
