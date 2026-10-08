import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Background, Controls, MiniMap, ReactFlow, addEdge, applyEdgeChanges, applyNodeChanges,
  BaseEdge, EdgeLabelRenderer, getBezierPath, MarkerType, reconnectEdge, useReactFlow,
  type Connection, type Edge, type EdgeChange, type EdgeProps, type Node, type NodeChange, type ReactFlowInstance,
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

// 自定义边：悬停/选中时在连线中点显示一个「×」删除按钮；带箭头指示方向；线更粗、易点选。
function DeletableEdge({
  id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition,
  markerEnd, style, label, selected,
}: EdgeProps) {
  const { deleteElements } = useReactFlow()
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition,
  })
  return (
    <>
      <BaseEdge id={id} path={edgePath} markerEnd={markerEnd}
        style={{ ...style, strokeWidth: selected ? 3 : 2, stroke: selected ? '#1677ff' : (style as any)?.stroke }} />
      <EdgeLabelRenderer>
        <div
          className="wf-edge-tools nodrag nopan"
          style={{
            position: 'absolute',
            transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
            pointerEvents: 'all',
          }}
        >
          {label ? <span className="wf-edge-label">{label}</span> : null}
          <button
            className="wf-edge-del"
            title="删除连线"
            onClick={(e) => { e.stopPropagation(); deleteElements({ edges: [{ id }] }) }}
          >×</button>
        </div>
      </EdgeLabelRenderer>
    </>
  )
}

const edgeTypes = { deletable: DeletableEdge }

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
    type: 'deletable',
    label: e.sourceHandle || undefined,
    sourceHandle: e.sourceHandle || undefined,
    markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, color: '#b1b1b7' },
    reconnectable: true,
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

// 结构签名（用于判断外部图是否变化）——只取 id/type/连线端点
function graphSigs(graph: any): { node: string; full: string } {
  const node = JSON.stringify((graph?.nodes || []).map((x: any) => [x.id, x.type]))
  const edge = JSON.stringify((graph?.edges || []).map((x: any) => [x.source, x.target, x.sourceHandle]))
  return { node, full: node + '|' + edge }
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

  const initSig = graphSigs(graph)
  const lastEmitSig = useRef<string>('')   // 本画布上一帧向上发出的签名
  const lastSyncSig = useRef<string>(initSig.full)
  const lastSyncNodeSig = useRef<string>(initSig.node)

  // 向外发出：记录发出的签名，父母更新 graph 后据此识别「是不是自己回显」
  const emit = useCallback(
    (ns: Node[], es: Edge[]) => {
      const g = flowToGraph(ns, es)
      lastEmitSig.current = graphSigs(g).full
      onChange?.(g)
    },
    [onChange],
  )

  // 外部图变化才重同步（节点集合变化时才 fitView；连线变化不重排视图）
  const curSig = useMemo(() => graphSigs(graph), [graph])
  useEffect(() => {
    if (curSig.full === lastSyncSig.current) return
    if (curSig.full === lastEmitSig.current) { lastSyncSig.current = curSig.full; return } // 自己的回显，跳过
    lastSyncSig.current = curSig.full
    const f = graphToFlow(graph)
    setNodes(f.nodes)
    setEdges(f.edges)
    if (curSig.node !== lastSyncNodeSig.current) {
      lastSyncNodeSig.current = curSig.node
      setTimeout(() => instRef.current?.fitView({ padding: 0.3, maxZoom: 1.2 }), 60)
    }
  }, [curSig, graph])

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

  const onConnect = useCallback(
    (conn: Connection) => {
      setEdges((eds) => {
        const next = addEdge({ ...conn, type: 'deletable', reconnectable: true,
          markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, color: '#b1b1b7' } }, eds)
        emit(nodesRef.current, next)
        return next
      })
    },
    [emit],
  )

  // 拖拽连线端点重连（把一条线改接到别的节点）
  const onReconnect = useCallback(
    (oldEdge: Edge, newConn: Connection) => {
      setEdges((es) => {
        const next = reconnectEdge(oldEdge, newConn, es)
        emit(nodesRef.current, next)
        return next
      })
    },
    [emit],
  )

  const handleNodesChange = useCallback(
    (changes: NodeChange[]) => {
      setNodes((ns) => {
        const next = applyNodeChanges(changes, ns)
        // 仅当有实质结构变化（增/删）才向上 emit，拖动位置也需回写
        const structural = changes.some((c) => c.type === 'remove' || c.type === 'add' || (c.type === 'position' && (c as any).dragging === false))
        if (structural) emit(next, edgesRef.current)
        return next
      })
    },
    [emit],
  )

  const handleEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      setEdges((es) => {
        const next = applyEdgeChanges(changes, es)
        emit(nodesRef.current, next)
        return next
      })
    },
    [emit],
  )

  const onInit = useCallback((inst: ReactFlowInstance) => {
    instRef.current = inst
    setTimeout(() => inst.fitView({ padding: 0.3, maxZoom: 1.2 }), 80)
  }, [])

  return (
    <div style={{ height: 560, border: '1px solid #f0f0f0', borderRadius: 8, background: '#fafafa', position: 'relative' }}>
      <style>{`
        .wf-edge-tools { opacity: 0; transition: opacity .15s ease; display: flex; align-items: center; gap: 4px; }
        .react-flow__edge:hover .wf-edge-tools,
        .react-flow__edge.selected .wf-edge-tools { opacity: 1; }
        .wf-edge-del {
          width: 18px; height: 18px; border-radius: 50%; border: none;
          background: #ff4d4f; color: #fff; cursor: pointer; font-size: 13px; line-height: 1;
          display: flex; align-items: center; justify-content: center; padding: 0;
          box-shadow: 0 1px 4px rgba(0,0,0,.25);
        }
        .wf-edge-del:hover { background: #cf1322; }
        .wf-edge-label {
          background: #fff; border: 1px solid #d9d9d9; border-radius: 4px;
          padding: 0 4px; font-size: 11px; color: #666;
        }
      `}</style>
      <ReactFlow
        nodes={styledNodes}
        edges={edges}
        edgeTypes={edgeTypes}
        onInit={onInit}
        onNodesChange={handleNodesChange}
        onEdgesChange={handleEdgesChange}
        onConnect={onConnect}
        onReconnect={onReconnect}
        reconnectRadius={20}
        onNodeClick={(_, n) => onSelect?.(n.id)}
        onPaneClick={() => onSelect?.(null)}
        onNodesDelete={(deleted) => {
          const ids = new Set(deleted.map((d) => d.id))
          const nextNodes = nodesRef.current.filter((n) => !ids.has(n.id))
          // 同时移除连到被删节点的边，避免陈旧 edgesRef 让边「复活」
          const nextEdges = edgesRef.current.filter((e) => !ids.has(e.source) && !ids.has(e.target))
          setNodes(nextNodes)
          setEdges(nextEdges)
          emit(nextNodes, nextEdges)
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
