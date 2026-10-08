import { useEffect, useState } from 'react'
import {
  Alert, Button, Card, Empty, Input, List, message, Modal, Space, Tag, Typography,
} from 'antd'
import { CheckOutlined, CloseOutlined, ReloadOutlined, AuditOutlined } from '@ant-design/icons'
import { workflowApi } from '../../api'
import { errMsg } from '../../api/http'
import PageContainer from '../../components/PageContainer'
import EmptyState from '../../components/EmptyState'

interface PendingItem {
  run_id: number
  agent_id: number
  agent_name: string
  pending_node_id?: string | null
  input?: any
  created_at?: string
}

export default function ApprovalPage() {
  const [items, setItems] = useState<PendingItem[]>([])
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState<number | null>(null)

  const load = async () => {
    setLoading(true)
    try { setItems(await workflowApi.pendingApprovals()) }
    catch (e) { message.error(errMsg(e)) } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  const [rejectFor, setRejectFor] = useState<number | null>(null)
  const [rejectComment, setRejectComment] = useState('')

  const doDecide = async (runId: number, decision: 'approve' | 'reject', comment = '') => {
    setBusy(runId)
    try {
      const token = localStorage.getItem('access_token')
      const resp = await fetch(workflowApi.approveUrl(runId), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({ decision, comment }),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      message.success(decision === 'approve' ? '已批准' : '已驳回')
      setRejectFor(null); setRejectComment(''); load()
    } catch (e) { message.error(errMsg(e)) } finally { setBusy(null) }
  }

  const fmtInput = (input: any) => {
    if (!input) return '（无输入）'
    try { return JSON.stringify(input).slice(0, 200) } catch { return String(input) }
  }

  return (
    <PageContainer
      title="审批中心"
      subtitle="工作流中「人工审批」节点挂起的运行，在此统一批准/驳回"
      extra={<Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>}
    >
      <Alert type="info" showIcon style={{ marginBottom: 16 }}
        message="这里汇总所有等待审批的工作流运行，无需逐个进入工作流页面。" />
      <Card bordered={false}>
        {items.length === 0 && !loading ? (
          <EmptyState description="暂无待审批项" />
        ) : (
          <List
            loading={loading} dataSource={items}
            renderItem={(it) => (
              <List.Item actions={[
                <Button key="a" type="primary" icon={<CheckOutlined />} loading={busy === it.run_id}
                  onClick={() => doDecide(it.run_id, 'approve')}>批准</Button>,
                <Button key="r" danger icon={<CloseOutlined />} loading={busy === it.run_id}
                  onClick={() => { setRejectFor(it.run_id); setRejectComment('') }}>驳回</Button>,
              ]}>
                <List.Item.Meta
                  avatar={<AuditOutlined style={{ fontSize: 20, color: '#d46b08' }} />}
                  title={<Space><span>{it.agent_name}</span><Tag color="orange">运行 #{it.run_id}</Tag>
                    {it.pending_node_id && <Tag>节点 {it.pending_node_id}</Tag>}</Space>}
                  description={<Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    输入：{fmtInput(it.input)}
                  </Typography.Text>} />
              </List.Item>
            )}
          />
        )}
      </Card>

      <Modal title="驳回审批" open={rejectFor !== null} onCancel={() => setRejectFor(null)}
        okText="确认驳回" okButtonProps={{ danger: true }}
        onOk={() => rejectFor !== null && doDecide(rejectFor, 'reject', rejectComment)}
        confirmLoading={busy === rejectFor} destroyOnClose>
        <Input.TextArea rows={3} value={rejectComment} onChange={(e) => setRejectComment(e.target.value)}
          placeholder="驳回原因（可选）" />
      </Modal>
    </PageContainer>
  )
}
