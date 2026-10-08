import { useEffect, useState } from 'react'
import { Progress, Tag, Tooltip } from 'antd'
import { docApi, type Doc } from '../api'

const STATUS_COLOR: Record<string, string> = {
  pending: 'default', parsing: 'processing', chunking: 'processing',
  embedding: 'processing', ready: 'success', failed: 'error', disabled: 'default',
}
const STATUS_LABEL: Record<string, string> = {
  pending: '待处理', parsing: '解析中', chunking: '分块中',
  embedding: '向量化', ready: '就绪', failed: '失败', disabled: '已停用',
}

/** 上传文档后的入库进度（轮询文档状态，就绪/失败时停表）。 */
export default function PendingAttachmentProgress({ docId }: { docId: number }) {
  const [doc, setDoc] = useState<Doc | null>(null)

  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setInterval> | null = null
    const poll = async () => {
      try {
        const d = await docApi.get(docId)
        if (!alive) return
        setDoc(d)
        if (['ready', 'failed'].includes(d.status) && timer) { clearInterval(timer); timer = null }
      } catch { /* ignore */ }
    }
    poll()
    timer = setInterval(poll, 1500)
    return () => { alive = false; if (timer) clearInterval(timer) }
  }, [docId])

  if (!doc) return null
  const color = STATUS_COLOR[doc.status] || 'default'
  return (
    <Tooltip title={doc.error_msg || STATUS_LABEL[doc.status] || doc.status}>
      <span style={{ marginLeft: 6 }}>
        <Tag color={color} style={{ marginInlineEnd: 0 }}>
          {STATUS_LABEL[doc.status] || doc.status}
        </Tag>
        {!['ready', 'failed'].includes(doc.status) && (
          <Progress percent={doc.progress} size="small" style={{ width: 80, display: 'inline-block', marginLeft: 4 }} />
        )}
      </span>
    </Tooltip>
  )
}
