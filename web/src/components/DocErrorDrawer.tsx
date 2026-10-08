import { Alert, Button, Descriptions, Drawer, Space, Tag, Typography } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import type { Doc } from '../api'

interface Props {
  doc: Doc | null
  onClose: () => void
  onReprocess?: (doc: Doc) => void
}

/** 文档处理失败的完整报错详情：结构化字段 + 修复建议 + 一键重试。 */
export default function DocErrorDrawer({ doc, onClose, onReprocess }: Props) {
  const d = doc?.error_detail || {}
  const hasDetail = doc && (doc.error_detail || doc.error_msg)

  return (
    <Drawer title={`失败详情：${doc?.title || ''}`} width={640} open={!!doc} onClose={onClose}>
      {!hasDetail ? (
        <Typography.Text type="secondary">该文档没有失败信息。</Typography.Text>
      ) : (
        <>
          {d.suggestion && (
            <Alert type="warning" showIcon style={{ marginBottom: 16 }}
              message="修复建议" description={d.suggestion} />
          )}
          <Descriptions column={1} size="small" bordered style={{ marginBottom: 16 }}>
            {d.stage && <Descriptions.Item label="失败阶段"><Tag color="red">{d.stage}</Tag></Descriptions.Item>}
            {d.summary && <Descriptions.Item label="摘要">{d.summary}</Descriptions.Item>}
            {d.provider && <Descriptions.Item label="模型">{d.provider}</Descriptions.Item>}
            {d.model && <Descriptions.Item label="模型名">{d.model}</Descriptions.Item>}
            {d.base_url && <Descriptions.Item label="上游地址"><code>{d.base_url}</code></Descriptions.Item>}
            {d.status_code && <Descriptions.Item label="HTTP 状态"><Tag color="red">{d.status_code}</Tag></Descriptions.Item>}
          </Descriptions>

          {d.detail && (
            <div style={{ marginBottom: 16 }}>
              <Typography.Text strong>详细错误</Typography.Text>
              <pre style={{
                background: '#f6f8fa', padding: 12, borderRadius: 6, marginTop: 6,
                fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-all', maxHeight: 240, overflow: 'auto',
              }}>{d.detail}</pre>
            </div>
          )}
          {d.raw && (
            <div style={{ marginBottom: 16 }}>
              <Typography.Text strong>上游响应原文</Typography.Text>
              <pre style={{
                background: '#fff2f0', padding: 12, borderRadius: 6, marginTop: 6,
                fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-all', maxHeight: 200, overflow: 'auto',
              }}>{d.raw}</pre>
            </div>
          )}
          {!d.detail && doc?.error_msg && (
            <div style={{ marginBottom: 16 }}>
              <Typography.Text strong>错误信息</Typography.Text>
              <pre style={{
                background: '#f6f8fa', padding: 12, borderRadius: 6, marginTop: 6,
                fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-all',
              }}>{doc.error_msg}</pre>
            </div>
          )}

          {onReprocess && doc && (
            <Space>
              <Button type="primary" icon={<ReloadOutlined />} onClick={() => { onReprocess(doc); onClose() }}>
                重新处理
              </Button>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                修复上游配置后点此重试，或到「模型管理」测试 embedding 连通性。
              </Typography.Text>
            </Space>
          )}
        </>
      )}
    </Drawer>
  )
}
