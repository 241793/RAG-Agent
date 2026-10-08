import { useEffect, useMemo, useState } from 'react'
import {
  Button, Card, Input, message, Space, Tag, Typography,
} from 'antd'
import {
  ArrowLeftOutlined, PlayCircleOutlined, SaveOutlined, CloudUploadOutlined, PlusOutlined,
} from '@ant-design/icons'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { agentApi, workflowApi, type Agent } from '../../api'
import { errMsg } from '../../api/http'
import WorkflowCanvas, { NODE_META } from '../../components/WorkflowCanvas'
import PropertyPanel from '../../components/PropertyPanel'
import WorkflowRunPanel from '../../components/WorkflowRunPanel'

const SAMPLE_GRAPH = {
  nodes: [
    { id: 'start', type: 'start', position: { x: 80, y: 120 }, data: { inputs: [{ name: 'query', type: 'string', required: true }] } },
    { id: 'ret', type: 'knowledge_retrieval', position: { x: 340, y: 120 }, data: { query: '{{start.query}}', top_k: 5 } },
    { id: 'llm', type: 'llm', position: { x: 600, y: 120 }, data: { system: '你是企业助手，依据资料回答。', prompt: '资料：\n{{ret.output}}\n\n问题：{{start.query}}' } },
    { id: 'end', type: 'end', position: { x: 860, y: 120 }, data: { output: '{{llm.output}}' } },
  ],
  edges: [
    { id: 'e1', source: 'start', target: 'ret' },
    { id: 'e2', source: 'ret', target: 'llm' },
    { id: 'e3', source: 'llm', target: 'end' },
  ],
}

// 添加新节点时的默认 data
function defaultData(type: string): any {
  switch (type) {
    case 'start': return { inputs: [{ name: 'query', type: 'string', required: true }] }
    case 'llm': return { system: '', prompt: '', temperature: 0.3 }
    case 'knowledge_retrieval': return { query: '{{start.query}}', top_k: 5 }
    case 'condition': return { expression: '' }
    case 'switch': return { cases: [{ handle: 'case1', expr: '' }, { handle: 'case2', expr: '' }] }
    case 'parallel': return {}
    case 'join': return {}
    case 'http': return { url: '', method: 'GET', timeout: 20 }
    case 'file': return { op: 'read', args: {} }
    case 'variable': return { assignments: [{ name: 'var', value: '' }] }
    case 'code': return { code: '', timeout: 15 }
    case 'loop': return { items: '{{start.query}}', item_var: 'item', max_iterations: 50, body: { op: 'template', template: '{{item}}' } }
    case 'approval': return { title: '需要人工审批', content: '' }
    case 'agent': return { agent_id: null, input_template: '{{start.query}}', mode_id: null, max_depth: 3 }
    case 'end': return { output: '' }
    default: return {}
  }
}

export default function WorkflowEditPage() {
  const { id } = useParams()
  const agentId = Number(id)
  const nav = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [agent, setAgent] = useState<Agent | null>(null)
  const [version, setVersion] = useState(1)
  const [graph, setGraph] = useState<any>({ nodes: [], edges: [] })
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [runPanelOpen, setRunPanelOpen] = useState(searchParams.get('panel') === 'run')
  const [nodeStatus, setNodeStatus] = useState<Record<string, string>>({})
  const [showJson, setShowJson] = useState(false)
  const [jsonText, setJsonText] = useState('')

  const load = async () => {
    try {
      setAgent(await agentApi.get(agentId))
      const wf = await workflowApi.get(agentId)
      setVersion(wf.version)
      const hasNodes = wf.graph?.nodes?.length
      setGraph(hasNodes ? wf.graph : SAMPLE_GRAPH)
    } catch (e) { message.error(errMsg(e)) }
  }
  useEffect(() => { load() }, [agentId])

  const allNodeIds = useMemo(() => (graph.nodes || []).map((n: any) => n.id), [graph])

  const selectedNode = useMemo(() => {
    if (!selectedId) return null
    const n = (graph.nodes || []).find((x: any) => x.id === selectedId)
    return n ? { id: n.id, type: n.type, data: n.data } : null
  }, [graph, selectedId])

  // 添加节点（点击节点面板）
  const addNode = (type: string) => {
    const used = new Set(allNodeIds)
    let n = 1
    let id = type === 'start' ? 'start' : type === 'end' ? 'end' : `${type}_${n}`
    while (used.has(id)) { n += 1; id = `${type}_${n}` }
    const newNode = { id, type, position: { x: 120 + (allNodeIds.length % 5) * 220, y: 100 + Math.floor(allNodeIds.length / 5) * 160 }, data: defaultData(type) }
    setGraph((g: any) => ({ ...g, nodes: [...(g.nodes || []), newNode] }))
    setSelectedId(id)
  }

  // 属性面板改动
  const changeNode = (oldId: string, newId: string, config: any) => {
    setGraph((g: any) => {
      const nodes = (g.nodes || []).map((n: any) => n.id === oldId ? { ...n, id: newId, data: config } : n)
      // 更新引用旧 id 的边
      const edges = (g.edges || []).map((e: any) => ({
        ...e,
        source: e.source === oldId ? newId : e.source,
        target: e.target === oldId ? newId : e.target,
      }))
      return { nodes, edges }
    })
    setSelectedId(newId)
  }

  const deleteNode = (nid: string) => {
    setGraph((g: any) => ({
      nodes: (g.nodes || []).filter((n: any) => n.id !== nid),
      edges: (g.edges || []).filter((e: any) => e.source !== nid && e.target !== nid),
    }))
    if (selectedId === nid) setSelectedId(null)
  }

  const save = async () => {
    try {
      await workflowApi.save(agentId, graph)
      message.success('已保存')
    } catch (e) { message.error(errMsg(e)) }
  }

  const publish = async () => {
    try {
      await workflowApi.save(agentId, graph)
      const r = await workflowApi.publish(agentId)
      setVersion(r.version)
      message.success('已发布 v' + r.version)
    } catch (e) { message.error(errMsg(e)) }
  }

  const openRunPanel = () => {
    setSearchParams({ panel: 'run' })
    setRunPanelOpen(true)
  }

  // JSON 视图切换
  const openJson = () => { setJsonText(JSON.stringify(graph, null, 2)); setShowJson(true) }
  const applyJson = () => {
    try {
      const g = JSON.parse(jsonText)
      setGraph(g); setShowJson(false); message.success('已应用')
    } catch (e) { message.error('JSON 格式错误') }
  }

  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => nav('/agents')}>返回</Button>
        <Typography.Title level={4} style={{ margin: 0 }}>工作流编排：{agent?.name}</Typography.Title>
        <Tag>v{version}</Tag>
      </Space>

      <div style={{ display: 'flex', gap: 12, height: 'calc(100vh - 180px)' }}>
        {/* 左：节点面板 */}
        <Card size="small" title="节点" style={{ width: 150, flex: '0 0 auto', overflowY: 'auto' }}>
          <Space direction="vertical" style={{ width: '100%' }}>
            {Object.entries(NODE_META).map(([type, meta]) => (
              <Button key={type} block size="small" icon={<PlusOutlined />}
                style={{ justifyContent: 'flex-start', borderColor: meta.color, color: meta.color }}
                onClick={() => addNode(type)}>
                {meta.icon} {meta.label}
              </Button>
            ))}
          </Space>
        </Card>

        {/* 中：画布 */}
        <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
          <Space style={{ marginBottom: 8 }}>
            <Button icon={<SaveOutlined />} onClick={save}>保存</Button>
            <Button icon={<CloudUploadOutlined />} onClick={publish}>发布</Button>
            <Button type="primary" icon={<PlayCircleOutlined />} onClick={openRunPanel}>运行</Button>
            <Button type="link" onClick={showJson ? () => setShowJson(false) : openJson}>
              {showJson ? '返回画布' : 'JSON 视图'}
            </Button>
          </Space>

          {showJson ? (
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
              <Input.TextArea value={jsonText} onChange={(e) => setJsonText(e.target.value)}
                style={{ flex: 1, fontFamily: 'monospace', fontSize: 12 }} />
              <Button type="primary" onClick={applyJson} style={{ marginTop: 8 }}>应用 JSON</Button>
            </div>
          ) : (
            <WorkflowCanvas
              graph={graph}
              onChange={setGraph}
              status={nodeStatus}
              onSelect={setSelectedId}
            />
          )}

          <Typography.Paragraph type="secondary" style={{ marginTop: 8, fontSize: 12 }}>
            点击「运行」在右侧面板中运行、查看实时日志与历史（不再跳转聊天）。
          </Typography.Paragraph>
        </div>

        {/* 右：属性面板 */}
        <Card size="small" title="节点配置" style={{ width: 320, flex: '0 0 auto', overflowY: 'auto' }}>
          <PropertyPanel
            node={selectedNode}
            allNodeIds={allNodeIds}
            onChange={changeNode}
            onDelete={deleteNode}
          />
        </Card>
      </div>

      <WorkflowRunPanel
        agentId={agentId}
        graph={graph}
        open={runPanelOpen}
        onClose={() => { setRunPanelOpen(false); setSearchParams({}) }}
        onNodeStatus={setNodeStatus}
      />
    </div>
  )
}
