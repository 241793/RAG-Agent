import { useEffect, useState } from 'react'
import {
  Button, Divider, Form, Input, InputNumber, message, Select, Space, Typography,
} from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { agentApi, channelApi, kbApi, notifyChannelApi, providerApi, type Agent, type ChannelItem, type KB, type ModelConfig, type NotifyChannelItem } from '../api'
import { NODE_META } from './WorkflowCanvas'

interface Props {
  node: { id: string; type: string; data: any } | null
  allNodeIds: string[]
  onChange: (nodeId: string, newId: string, newConfig: any) => void
  onDelete: (nodeId: string) => void
}

export default function PropertyPanel({ node, allNodeIds, onChange, onDelete }: Props) {
  const [config, setConfig] = useState<any>({})
  const [nodeId, setNodeId] = useState('')
  const [kbs, setKbs] = useState<KB[]>([])
  const [models, setModels] = useState<ModelConfig[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [notifyChannels, setNotifyChannels] = useState<NotifyChannelItem[]>([])
  const [extChannels, setExtChannels] = useState<ChannelItem[]>([])

  useEffect(() => {
    if (!node) return
    setConfig(node.data?.config || {})
    setNodeId(node.id)
  }, [node])

  useEffect(() => {
    kbApi.list().then(setKbs).catch(() => {})
    providerApi.configs().then(setModels).catch(() => {})
    agentApi.list().then(setAgents).catch(() => {})
    notifyChannelApi.list().then(setNotifyChannels).catch(() => {})
    channelApi.list().then(setExtChannels).catch(() => {})
  }, [])

  if (!node) {
    return (
      <div style={{ color: '#999', fontSize: 13, padding: 16 }}>
        点击画布中的节点以编辑其配置。
      </div>
    )
  }

  const meta = NODE_META[node.type] || { label: node.type, color: '#999', icon: '?' }
  const set = (k: string, v: any) => setConfig((c: any) => ({ ...c, [k]: v }))

  const commit = () => {
    if (!nodeId.trim()) { message.warning('节点 ID 不能为空'); return }
    // ID 变更需唯一
    if (nodeId !== node.id && allNodeIds.includes(nodeId)) {
      message.error(`节点 ID "${nodeId}" 已存在`); return
    }
    onChange(node.id, nodeId.trim(), config)
  }

  const varHint = () => (
    <Typography.Text type="secondary" style={{ fontSize: 11 }}>
      可用变量：{allNodeIds.filter((i) => i !== nodeId).map((i) => `{{${i}.output}}`).join('、') || '（无上游）'}
    </Typography.Text>
  )

  return (
    <div style={{ fontSize: 13 }}>
      <Space style={{ marginBottom: 12 }}>
        <span style={{ color: meta.color, fontWeight: 600 }}>{meta.icon} {meta.label}</span>
      </Space>

      <Form layout="vertical" size="small">
        <Form.Item label="节点 ID" style={{ marginBottom: 10 }}
          help="用于变量引用，如 {{id.output}}">
          <Input value={nodeId} onChange={(e) => setNodeId(e.target.value)}
            onBlur={commit} disabled={node.type === 'start' || node.type === 'end'} />
        </Form.Item>

        {/* start：声明输入 */}
        {node.type === 'start' && (
          <Form.Item label="输入参数">
            {(config.inputs || [{ name: 'query', type: 'string', required: true }]).map((inp: any, i: number) => (
              <Space key={i} style={{ display: 'flex', marginBottom: 6 }} align="baseline">
                <Input style={{ width: 110 }} value={inp.name} placeholder="名称"
                  onChange={(e) => { const arr = [...(config.inputs || [{ name: 'query', type: 'string', required: true }])]; arr[i] = { ...inp, name: e.target.value }; set('inputs', arr) }} />
                <Input style={{ width: 80 }} value={inp.type} placeholder="类型"
                  onChange={(e) => { const arr = [...(config.inputs || [])]; arr[i] = { ...inp, type: e.target.value }; set('inputs', arr) }} />
                <Button size="small" danger icon={<DeleteOutlined />}
                  onClick={() => { const arr = [...(config.inputs || [])]; arr.splice(i, 1); set('inputs', arr) }} />
              </Space>
            ))}
            <Button size="small" icon={<PlusOutlined />} onClick={() => set('inputs', [...(config.inputs || []), { name: '', type: 'string', required: false }])}>添加输入</Button>
          </Form.Item>
        )}

        {/* llm */}
        {node.type === 'llm' && (
          <>
            <Form.Item label="模型">
              <Select allowClear placeholder="默认模型" value={config.model_config_id}
                onChange={(v) => set('model_config_id', v)}
                options={models.filter((m) => m.purpose === 'chat').map((m) => ({ value: m.id, label: m.display_name || m.model_name }))} />
            </Form.Item>
            <Form.Item label="系统提示词">
              <Input.TextArea rows={3} value={config.system} onChange={(e) => set('system', e.target.value)} />
            </Form.Item>
            <Form.Item label="用户提示词" help={varHint()}>
              <Input.TextArea rows={4} value={config.prompt} onChange={(e) => set('prompt', e.target.value)}
                placeholder={'资料：{{ret.output}}\n\n问题：{{start.query}}'} />
            </Form.Item>
            <Form.Item label="温度">
              <InputNumber min={0} max={2} step={0.1} style={{ width: '100%' }}
                value={config.temperature ?? 0.3} onChange={(v) => set('temperature', v)} />
            </Form.Item>
          </>
        )}

        {/* knowledge_retrieval */}
        {node.type === 'knowledge_retrieval' && (
          <>
            <Form.Item label="检索语句" help={varHint()}>
              <Input.TextArea rows={2} value={config.query} onChange={(e) => set('query', e.target.value)}
                placeholder="{{start.query}}" />
            </Form.Item>
            <Form.Item label="知识库（留空=全部可访问）">
              <Select mode="multiple" allowClear value={config.kb_ids}
                onChange={(v) => set('kb_ids', v)}
                options={kbs.map((k) => ({ value: k.id, label: k.name }))} />
            </Form.Item>
            <Form.Item label="返回条数 top_k">
              <InputNumber min={1} max={50} style={{ width: '100%' }}
                value={config.top_k ?? 5} onChange={(v) => set('top_k', v)} />
            </Form.Item>
          </>
        )}

        {/* condition */}
        {node.type === 'condition' && (
          <Form.Item label="条件表达式" help="支持 == != > < >= <= contains in，可用 AND / OR 组合；两个出线分别连 true / false">
            <Input.TextArea rows={2} value={config.expression} onChange={(e) => set('expression', e.target.value)}
              placeholder="{{llm.output}} contains '无法回答' AND 1==1" />
          </Form.Item>
        )}

        {/* switch 多路分支 */}
        {node.type === 'switch' && (
          <Form.Item label="分支规则" help="按顺序求值，命中即走对应出线（sourceHandle=handle）；都不中走 default 出线">
            {(config.cases || []).map((c: any, i: number) => (
              <Space key={i} style={{ display: 'flex', marginBottom: 6 }} align="baseline">
                <Input style={{ width: 90 }} placeholder="handle" value={c.handle}
                  onChange={(e) => { const arr = [...config.cases]; arr[i] = { ...arr[i], handle: e.target.value }; set('cases', arr) }} />
                <Input style={{ width: 260 }} placeholder="表达式，如 {{start.env}} == 'prod'" value={c.expr}
                  onChange={(e) => { const arr = [...config.cases]; arr[i] = { ...arr[i], expr: e.target.value }; set('cases', arr) }} />
                <Button size="small" danger icon={<DeleteOutlined />}
                  onClick={() => set('cases', config.cases.filter((_: any, j: number) => j !== i))} />
              </Space>
            ))}
            <Button size="small" icon={<PlusOutlined />}
              onClick={() => set('cases', [...(config.cases || []), { handle: `case${(config.cases || []).length + 1}`, expr: '' }])}>
              添加分支
            </Button>
          </Form.Item>
        )}

        {/* parallel 并行网关 */}
        {node.type === 'parallel' && (
          <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
            把多条出线连接到不同的分支链，每条分支链需线性走到同一个「汇聚」节点。
            各分支会**并发执行**（独立会话），分支间不共享中间变量；分支内暂不支持条件/循环/审批节点。
          </Typography.Paragraph>
        )}

        {/* join 汇聚 */}
        {node.type === 'join' && (
          <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
            汇聚并行分支。各分支的末节点输出会归并到本节点：<br />
            <Typography.Text code>{'{{join_out_id.branches}}'}</Typography.Text> 为各分支输出数组。
          </Typography.Paragraph>
        )}

        {/* file */}
        {node.type === 'file' && (
          <>
            <Form.Item label="操作">
              <Select value={config.op || 'read'} onChange={(v) => set('op', v)}
                options={[
                  { value: 'read', label: '读取文件（file_key / doc_id）' },
                  { value: 'generate', label: '生成文件（docx/xlsx/pdf/pptx/md/csv/txt）' },
                  { value: 'convert', label: '转换格式（xlsx→csv / docx→pdf 等）' },
                ]} />
            </Form.Item>
            <Form.Item label="参数（JSON）" help={`可用变量：${allNodeIds.filter((i) => i !== nodeId).map((i) => `{{${i}.output}}`).join('、') || '（无上游）'}`}>
              <Input.TextArea rows={5} style={{ fontFamily: 'monospace', fontSize: 12 }}
                value={typeof config.args === 'string' ? config.args : JSON.stringify(config.args || {}, null, 2)}
                onChange={(e) => {
                  try { set('args', JSON.parse(e.target.value)) } catch { set('args', e.target.value) }
                }}
                placeholder={'读取: {"file_key": "{{start.file_key}}"}\n生成: {"filename":"报表.xlsx","format":"xlsx","rows":[...]}\n转换: {"file_key":"...","target_ext":"csv"}'} />
            </Form.Item>
          </>
        )}

        {/* http */}
        {node.type === 'http' && (
          <>
            <Form.Item label="URL" help={varHint()}>
              <Input value={config.url} onChange={(e) => set('url', e.target.value)} placeholder="https://..." />
            </Form.Item>
            <Form.Item label="方法">
              <Select value={config.method || 'GET'} onChange={(v) => set('method', v)}
                options={[{ value: 'GET' }, { value: 'POST' }]} />
            </Form.Item>
            <Form.Item label="请求体模板">
              <Input.TextArea rows={3} value={config.body_template} onChange={(e) => set('body_template', e.target.value)} />
            </Form.Item>
            <Form.Item label="超时（秒）">
              <InputNumber min={1} style={{ width: '100%' }} value={config.timeout ?? 20} onChange={(v) => set('timeout', v)} />
            </Form.Item>
          </>
        )}

        {/* variable */}
        {node.type === 'variable' && (
          <Form.Item label="变量赋值" help={varHint()}>
            {(config.assignments || []).map((a: any, i: number) => (
              <Space key={i} style={{ display: 'flex', marginBottom: 6 }} align="baseline">
                <Input style={{ width: 100 }} value={a.name} placeholder="变量名"
                  onChange={(e) => { const arr = [...(config.assignments || [])]; arr[i] = { ...a, name: e.target.value }; set('assignments', arr) }} />
                <Input style={{ width: 130 }} value={a.value} placeholder="值，可 {{引用}}"
                  onChange={(e) => { const arr = [...(config.assignments || [])]; arr[i] = { ...a, value: e.target.value }; set('assignments', arr) }} />
                <Button size="small" danger icon={<DeleteOutlined />}
                  onClick={() => { const arr = [...(config.assignments || [])]; arr.splice(i, 1); set('assignments', arr) }} />
              </Space>
            ))}
            <Button size="small" icon={<PlusOutlined />} onClick={() => set('assignments', [...(config.assignments || []), { name: '', value: '' }])}>添加变量</Button>
          </Form.Item>
        )}

        {/* code */}
        {node.type === 'code' && (
          <>
            <Form.Item label="Python 代码" help="从 stdin 读 {inputs,args,scope}，向 stdout 打印 JSON；-I -S 隔离非沙箱">
              <Input.TextArea rows={10} style={{ fontFamily: 'monospace', fontSize: 12 }}
                value={config.code} onChange={(e) => set('code', e.target.value)}
                placeholder={'import sys, json\npayload = json.load(sys.stdin)\nprint(json.dumps({"output": "hello"}))'} />
            </Form.Item>
            <Form.Item label="超时（秒）">
              <InputNumber min={1} max={60} style={{ width: '100%' }} value={config.timeout ?? 15} onChange={(v) => set('timeout', v)} />
            </Form.Item>
          </>
        )}

        {/* loop */}
        {node.type === 'loop' && (
          <>
            <Form.Item label="遍历数组" help={varHint()}>
              <Input value={config.items} onChange={(e) => set('items', e.target.value)} placeholder="{{start.list}}" />
            </Form.Item>
            <Form.Item label="循环项变量名">
              <Input value={config.item_var || 'item'} onChange={(e) => set('item_var', e.target.value)} />
            </Form.Item>
            <Form.Item label="最大迭代次数">
              <InputNumber min={1} max={200} style={{ width: '100%' }} value={config.max_iterations ?? 50} onChange={(v) => set('max_iterations', v)} />
            </Form.Item>
            <Form.Item label="循环体类型">
              <Select value={config.body?.op || 'template'} onChange={(v) => set('body', { ...(config.body || {}), op: v })}
                options={[{ value: 'template', label: '模板拼接' }, { value: 'llm', label: '大模型' }, { value: 'code', label: '代码' }]} />
            </Form.Item>
            {(config.body?.op || 'template') === 'template' && (
              <Form.Item label="模板" help="用 {{item}} 引用当前项">
                <Input.TextArea rows={3} value={config.body?.template} onChange={(e) => set('body', { ...(config.body || {}), template: e.target.value })} placeholder="处理：{{item}}" />
              </Form.Item>
            )}
            {config.body?.op === 'llm' && (
              <>
                <Form.Item label="系统提示词">
                  <Input.TextArea rows={2} value={config.body?.system} onChange={(e) => set('body', { ...(config.body || {}), system: e.target.value })} />
                </Form.Item>
                <Form.Item label="用户提示词">
                  <Input.TextArea rows={3} value={config.body?.prompt} onChange={(e) => set('body', { ...(config.body || {}), prompt: e.target.value })} placeholder="处理 {{item}}" />
                </Form.Item>
              </>
            )}
            {config.body?.op === 'code' && (
              <Form.Item label="Python 代码（item 注入 scope）">
                <Input.TextArea rows={5} style={{ fontFamily: 'monospace', fontSize: 12 }} value={config.body?.code} onChange={(e) => set('body', { ...(config.body || {}), code: e.target.value })} />
              </Form.Item>
            )}
          </>
        )}

        {/* approval */}
        {node.type === 'approval' && (
          <>
            <Form.Item label="审批标题">
              <Input value={config.title} onChange={(e) => set('title', e.target.value)} placeholder="需要人工审批" />
            </Form.Item>
            <Form.Item label="审批内容" help={varHint()}>
              <Input.TextArea rows={4} value={config.content} onChange={(e) => set('content', e.target.value)} placeholder="待确认内容，可引用上游 {{node.output}}" />
            </Form.Item>
          </>
        )}

        {/* agent */}
        {node.type === 'agent' && (
          <>
            <Form.Item label="目标智能体" rules={[{ required: true }]}>
              <Select placeholder="选择要调用的智能体" value={config.agent_id}
                onChange={(v) => set('agent_id', v)}
                options={agents.filter((a) => a.type === 'agent').map((a) => ({ value: a.id, label: a.name }))} />
            </Form.Item>
            <Form.Item label="输入模板" help={varHint()}>
              <Input.TextArea rows={3} value={config.input_template} onChange={(e) => set('input_template', e.target.value)}
                placeholder="{{start.query}}" />
            </Form.Item>
            <Form.Item label="最大调用深度（防循环）">
              <InputNumber min={1} max={5} style={{ width: '100%' }} value={config.max_depth ?? 3} onChange={(v) => set('max_depth', v)} />
            </Form.Item>
          </>
        )}

        {/* notify：消息推送 */}
        {node.type === 'notify' && (
          <>
            <Form.Item label="推送方式">
              <Select value={config.mode || 'notify_channel'} onChange={(v) => set('mode', v)} options={[
                { value: 'notify_channel', label: '通知渠道（站内/Webhook/企微/邮件/外部渠道…）' },
                { value: 'external_channel', label: '直接推外部渠道（QQ/微信/企微/飞书）' },
              ]} />
            </Form.Item>
            {(config.mode || 'notify_channel') === 'notify_channel' ? (
              <>
                <Form.Item label="通知渠道" rules={[{ required: true }]}>
                  <Select placeholder="选择通知渠道" value={config.channel_id} onChange={(v) => set('channel_id', v)}
                    options={notifyChannels.map((c) => ({ value: c.id, label: `${c.name}（${c.kind}）` }))} />
                </Form.Item>
                <Form.Item label="通知标题">
                  <Input value={config.title} onChange={(e) => set('title', e.target.value)} placeholder="工作流消息" />
                </Form.Item>
              </>
            ) : (
              <>
                <Form.Item label="外部渠道" rules={[{ required: true }]}>
                  <Select placeholder="选择已接入渠道" value={config.channel_id} onChange={(v) => set('channel_id', v)}
                    options={extChannels.map((c) => ({ value: c.id, label: `${c.name}（${c.kind}）` }))} />
                </Form.Item>
                <Form.Item label="接收对象类型">
                  <Select value={config.target_type || 'group'} onChange={(v) => set('target_type', v)}
                    options={[{ value: 'group', label: '群' }, { value: 'user', label: '个人' }]} />
                </Form.Item>
                <Form.Item label="接收对象 id"
                  help="群 id / 用户 id；可在渠道里发 /myuid 查看自己的 id">
                  <Input value={config.target} onChange={(e) => set('target', e.target.value)} placeholder="群 id 或用户 id" />
                </Form.Item>
              </>
            )}
            <Form.Item label="推送内容" help={varHint()}>
              <Input.TextArea rows={4} value={config.content} onChange={(e) => set('content', e.target.value)}
                placeholder="{{llm.output}}" />
            </Form.Item>
          </>
        )}

        {/* end */}
        {node.type === 'end' && (
          <Form.Item label="输出" help={varHint()}>
            <Input.TextArea rows={3} value={config.output} onChange={(e) => set('output', e.target.value)}
              placeholder="{{llm.output}}" />
          </Form.Item>
        )}

        {node.type !== 'start' && node.type !== 'end' && (
          <Form.Item label="失败重试次数" help="节点执行失败时重试次数（0=不重试）">
            <InputNumber min={0} max={5} style={{ width: '100%' }}
              value={config.retry ?? 0} onChange={(v) => set('retry', v)} />
          </Form.Item>
        )}

        <Divider style={{ margin: '8px 0' }} />
        <Space>
          <Button type="primary" size="small" onClick={commit}>应用</Button>
          <Button size="small" danger icon={<DeleteOutlined />}
            disabled={node.type === 'start' || node.type === 'end'}
            onClick={() => onDelete(node.id)}>删除节点</Button>
        </Space>
      </Form>
    </div>
  )
}
