import { useEffect, useState } from 'react'
import {
  Button, Card, Col, Form, Input, message, Modal, Popconfirm, Row, Select, Space, Tag, Typography,
} from 'antd'
import { PlusOutlined, RobotOutlined, DeleteOutlined, PlayCircleOutlined, EditOutlined, PartitionOutlined, CloudUploadOutlined, CopyOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { agentApi, kbApi, providerApi, type Agent, type KB, type ModelConfig } from '../../api'
import { errMsg } from '../../api/http'
import PageContainer from '../../components/PageContainer'
import EmptyState from '../../components/EmptyState'
import Can from '../../components/Can'
import { useAuth } from '../../stores/auth'

export default function AgentListPage() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [kbs, setKbs] = useState<KB[]>([])
  const [configs, setConfigs] = useState<ModelConfig[]>([])
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm()
  const nav = useNavigate()
  const hasPermission = useAuth((s) => s.hasPermission)
  const canEdit = hasPermission('agent:edit')
  const canRun = hasPermission('agent:run')

  const load = async () => {
    try {
      setAgents(await agentApi.list())
      setKbs(await kbApi.list())
      setConfigs(await providerApi.configs())
    } catch (e) {
      message.error(errMsg(e))
    }
  }
  useEffect(() => { load() }, [])

  const onCreate = async () => {
    const v = await form.validateFields()
    try {
      await agentApi.create({
        ...v,
        tool_config: {
          builtin: {
            knowledge_retrieval: { enabled: true },
            read_file: { enabled: true },
            list_conversation_files: { enabled: true },
            convert_file: { enabled: true },
            generate_file: { enabled: true },
            edit_file: { enabled: true },
            convert_file_to: { enabled: true },
          },
          max_turns: 4,
        },
      })
      message.success('创建成功')
      setOpen(false)
      form.resetFields()
      load()
    } catch (e) {
      message.error(errMsg(e))
    }
  }

  const chatConfigs = configs.filter((c) => c.purpose === 'chat')

  return (
    <PageContainer
      title="智能体"
      extra={<Can perm="agent:edit"><Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>新建智能体</Button></Can>}
    >
      {agents.length === 0 ? (
        <EmptyState description="暂无智能体，点击右上角创建" actionText={canEdit ? '新建智能体' : undefined} onAction={() => setOpen(true)} />
      ) : (
        <Row gutter={[16, 16]}>
          {agents.map((a) => (
            <Col key={a.id} xs={24} sm={12} md={8} lg={6}>
              <Card
                hoverable
                title={<Space><RobotOutlined />{a.name}</Space>}
                extra={<Tag color={a.type === 'workflow' ? 'purple' : 'blue'}>{a.type === 'workflow' ? '工作流' : '工具Agent'}</Tag>}
                actions={[
                  a.type === 'workflow' ? (
                    canEdit ? <PartitionOutlined key="wf" title="编排" onClick={() => nav(`/agents/${a.id}/workflow`)} /> : null
                  ) : (
                    canRun ? <PlayCircleOutlined key="run" title="运行" onClick={() => nav(`/agents/${a.id}/chat`)} /> : null
                  ),
                  a.type === 'workflow' ? (
                    canRun ? <PlayCircleOutlined key="run2" title="运行" onClick={() => nav(`/agents/${a.id}/workflow?panel=run`)} /> : null
                  ) : (
                    canEdit ? <EditOutlined key="edit" title="编辑" onClick={() => nav(`/agents/${a.id}/edit`)} /> : null
                  ),
                  a.status === 'published'
                    ? <Tag key="pub" color="green" style={{ marginBottom: 6 }}>已发布</Tag>
                    : (canEdit ? <CloudUploadOutlined key="pub" title="发布"
                        onClick={async () => { await agentApi.publish(a.id); message.success('已发布'); load() }} /> : null),
                  canEdit ? <CopyOutlined key="clone" title="复制"
                    onClick={async () => { await agentApi.clone(a.id); message.success('已复制'); load() }} /> : null,
                  canEdit ? (
                    <Popconfirm key="del" title="删除该智能体？" onConfirm={async () => { await agentApi.remove(a.id); load() }}>
                      <DeleteOutlined />
                    </Popconfirm>
                  ) : null,
                ].filter(Boolean)}
              >
                <Typography.Paragraph ellipsis={{ rows: 2 }} type="secondary" style={{ minHeight: 44 }}>
                  {a.description || '暂无描述'}
                </Typography.Paragraph>
                <Space size={4}>
                  <Tag color={a.status === 'published' ? 'green' : 'default'}>{a.status === 'published' ? '已发布' : '草稿'}</Tag>
                  {a.kb_ids?.length ? <Tag>{(a.kb_ids || []).length} 知识库</Tag> : null}
                </Space>
              </Card>
            </Col>
          ))}
        </Row>
      )}

      <Modal title="新建智能体" open={open} onOk={onCreate} onCancel={() => setOpen(false)} destroyOnClose>
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="如：写作助手 / 客服助手" />
          </Form.Item>
          <Form.Item name="description" label="描述"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="type" label="类型" initialValue="agent">
            <Select options={[
              { value: 'agent', label: '工具循环 Agent（LLM 自主调用工具）' },
              { value: 'workflow', label: '工作流编排（DAG）' },
            ]} />
          </Form.Item>
          <Form.Item name="system_prompt" label="系统提示词" initialValue="你是一个智能助手。">
            <Input.TextArea rows={4} placeholder="定义智能体的角色与行为" />
          </Form.Item>
          <Form.Item name="model_config_id" label="对话模型" extra="留空则用默认">
            <Select allowClear options={chatConfigs.map((c) => ({ value: c.id, label: c.display_name }))} />
          </Form.Item>
          <Form.Item name="kb_ids" label="知识库范围">
            <Select mode="multiple" options={kbs.map((k) => ({ value: k.id, label: k.name }))} />
          </Form.Item>
        </Form>
      </Modal>
    </PageContainer>
  )
}
