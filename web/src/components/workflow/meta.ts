// 工作流节点元数据：与旧版 NODE_META 保持一致，供画布 / 属性面板 / 运行面板共用。

export interface NodeMeta {
  label: string
  color: string
  icon: string
}

export const NODE_META: Record<string, NodeMeta> = {
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

/** 添加新节点时的默认 data（与旧版 defaultData 对齐） */
export function defaultData(type: string): any {
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

/** 运行状态 → 描边色 */
export const STATUS_COLOR: Record<string, string> = {
  running: '#1677ff',
  success: '#52c41a',
  failed: '#ff4d4f',
  skipped: '#d9d9d9',
  waiting: '#faad14',
}
