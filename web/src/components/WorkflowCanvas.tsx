import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Background, Controls, MiniMap, ReactFlow, addEdge, applyEdgeChanges, applyNodeChanges,
  type Connection, type Edge, type EdgeChange, type Node, type NodeChange, type ReactFlowInstance,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

// 节点类型 → 展示信息
export const NODE_META: Record<string, { label: string; color: string; icon: string }> = {
  start: { label: '开始', color: '#52c41a', icon: '▶' },
  llm: { label: '大模型', color: '#1677ff', icon: '🤖' },
  knowledge_retrieval: { label: '知识库检索', color: '#722ed1', icon: '📚' },
  condition: { label: '条件分支', color: '#fa8c16', icon: '⑂' },
  switch: { label: '多路分支', color: '#fa8c16', icon: '⑃' },
  parallel: { label: '并行网关', color: '#08979c', icon: '⋔' },
  join: { label: '汇聚', color: '#08979c', icon: '⋈' },
  http: { label: 'HTTP 请求', color: '#13c2c2', icon: '🌐' },
  file: { label: '文件处理', color: '#eb2f96', icon: '📄' },
  variable: { label: '变量赋值', color: '#8c8c8c', icon: '🔤' },
  code: { label: '代码执行', color: '#2f54eb', icon: '⌨' },
  loop: { label: '循环批量', color: '#08979c', icon: '🔁' },
  approval: { label: '人工审批', color: '#d46b08', icon: '✋' },
  agent: { label: '调用智能体', color: '#2f54eb', icon: '🧩' },
  notify: { label: '消息推送', color: '#fa541c', icon: '📤' },
  end: { label: '结束', color: '#f5222d', icon: '⏹' },
}

function flowStyle(type: string) {
  const meta = NODE_META[type] || { color: '#999' }
  return {
    background: '#fff',
    border: `2px solid ${meta.color}`,
    borderRadius: 8,
    padding: '10px 10px',
    fontSize: 13,
    width: 170,
    textAlign: 'center' as const,
    whiteSpace: 'pre-line' as const,
  }
}

// graph JSON → xyflow（保留 type 与 data，不再丢失）
export function graphToFlow(graph: any): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = (graph?.nodes || []).map((n: any, i: number) => {
    const meta = NODE_META[n.type] || { label: n.type, color: '#999', icon: '?' }
    return {
      id: String(n.id),
      type: 'default',
      position: n.position || { x: (i % 4) * 240 + 60, y: Math.floor(i / 4) * 200 + 60 },
      data: {
        nodeType: n.type,
        config: n.data || {},
        label: `${meta.icon} ${n.id}\n${meta.label}`,
      },
      style: flowStyle(n.type),
    }
  })
  const edges: Edge[] = (graph?.edges || []).map((e: any, i: number) => ({
    id: e.id || `e-${e.source}-${e.target}-${i}`,
    source: String(e.source),
    target: String(e.target),
    label: e.sourceHandle || undefined,
    sourceHandle: e.sourceHandle || undefined,
    animated: true,
  }))
  return { nodes, edges }
}

// xyflow → graph JSON（正确回写 type/data/position/sourceHandle）
export function flowToGraph(nodes: Node[], edges: Edge[]): any {
  return {
    nodes: nodes.map((n) => ({
      id: n.id,
      type: (n.data as any).nodeType || 'llm',
      position: n.position,
      data: (n.data as any).config || {},
    })),
    edges: edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      sourceHandle: e.sourceHandle || (typeof e.label === 'string' ? e.label : undefined),
    })),
  }
}

interface Props {
  graph: any
  onChange?: (graph: any) => void
  status?: Record<string, string>
  onSelect?: (id: string | null) => void
}

const statusColor: Record<string, string> = {
  running: '#1677ff', success: '#52c41a', failed: '#ff4d4f', skipped: '#d9d9d9',
}

export default function WorkflowCanvas({ graph, onChange, status, onSelect }: Props) {
  const initial = useMemo(() => graphToFlow(graph), []) // eslint-disable-line react-hooks/exhaustive-deps
  const [nodes, setNodes] = useState<Node[]>(initial.nodes)
  const [edges, setEdges] = useState<Edge[]>(initial.edges)
  const instRef = useRef<ReactFlowInstance | null>(null)
  const nodesRef = useRef(nodes)
  const edgesRef = useRef(edges)
  nodesRef.current = nodes
  edgesRef.current = edges

  // 结构签名：节点集合或连线变化时才从外部图重同步
  const sig = useMemo(
    () => JSON.stringify({
      n: (graph?.nodes || []).map((x: any) => [x.id, x.type]),
      e: (graph?.edges || []).map((x: any) => [x.source, x.target, x.sourceHandle]),
    }),
    [graph],
  )
  const lastSig = useRef(sig)

  useEffect(() => {
    if (sig === lastSig.current) return
    lastSig.current = sig
    const f = graphToFlow(graph)
    setNodes(f.nodes)
    setEdges(f.edges)
    // 图结构变化后重新适配视图（修复"空白/堆角落"）
    setTimeout(() => instRef.current?.fitView({ padding: 0.3, maxZoom: 1.2 }), 60)
  }, [sig, graph, setNodes, setEdges])

  // 运行状态描色
  const styledNodes = useMemo(() => {
    if (!status) return nodes
    return nodes.map((n) => ({
      ...n,
      style: {
        ...(n.style || {}),
        boxShadow: status[n.id] ? `0 0 0 3px ${statusColor[status[n.id]] || '#d9d9d9'}` : undefined,
      },
    }))
  }, [nodes, status])

  const emit = useCallback(
    (ns: Node[], es: Edge[]) => onChange?.(flowToGraph(ns, es)),
    [onChange],
  )

  const onConnect = useCallback(
    (conn: Connection) => {
      setEdges((eds) => {
        const next = addEdge(conn, eds)
        emit(nodesRef.current, next)
        return next
      })
    },
    [setEdges, emit],
  )

  const handleNodesChange = useCallback(
    (changes: NodeChange[]) => {
      setNodes((ns) => {
        const next = applyNodeChanges(changes, ns)
        emit(next, edgesRef.current)
        return next
      })
    },
    [setNodes, emit],
  )

  const handleEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      setEdges((es) => {
        const next = applyEdgeChanges(changes, es)
        emit(nodesRef.current, next)
        return next
      })
    },
    [setEdges, emit],
  )

  const onInit = useCallback((inst: ReactFlowInstance) => {
    instRef.current = inst
    setTimeout(() => inst.fitView({ padding: 0.3, maxZoom: 1.2 }), 80)
  }, [])

  return (
    <div style={{ height: 560, border: '1px solid #f0f0f0', borderRadius: 8, background: '#fafafa' }}>
      <ReactFlow
        nodes={styledNodes}
        edges={edges}
        onInit={onInit}
        onNodesChange={handleNodesChange}
        onEdgesChange={handleEdgesChange}
        onConnect={onConnect}
        onNodeClick={(_, n) => onSelect?.(n.id)}
        onPaneClick={() => onSelect?.(null)}
        onNodesDelete={(deleted) => {
          const ids = new Set(deleted.map((d) => d.id))
          const next = nodesRef.current.filter((n) => !ids.has(n.id))
          setNodes(next)
          emit(next, edgesRef.current)
          onSelect?.(null)
        }}
        fitView
        minZoom={0.2}
        deleteKeyCode={['Delete', 'Backspace']}
      >
        <Background />
        <Controls />
        <MiniMap />
      </ReactFlow>
    </div>
  )
}
