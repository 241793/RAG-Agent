import { useEffect, useState } from 'react'
import { Button, Card, Drawer, Image, Modal, Space, Tag, Typography, message } from 'antd'
import {
  FileImageOutlined, FilePdfOutlined, FileWordOutlined, FileExcelOutlined,
  FilePptOutlined, FileTextOutlined, FileOutlined, DownloadOutlined, PaperClipOutlined,
} from '@ant-design/icons'
import { API_BASE } from '../api'
import { errMsg } from '../api/http'
import { getAttachmentUrl, getArtifactUrl, renderKind, fileExt } from '../api/signedUrl'

type AttLike = { file_key?: string; artifact_id?: number; name: string; type?: string; mime?: string; size?: number }

function absUrl(u: string) {
  return u.startsWith('http') ? u : `${API_BASE.replace('/api/v1', '')}${u}`
}

function fmtSize(n?: number) {
  if (!n) return ''
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(2)} MB`
}

function extIcon(ext: string) {
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg'].includes(ext)) return <FileImageOutlined />
  if (ext === 'pdf') return <FilePdfOutlined />
  if (['doc', 'docx'].includes(ext)) return <FileWordOutlined />
  if (['xls', 'xlsx', 'csv'].includes(ext)) return <FileExcelOutlined />
  if (['ppt', 'pptx'].includes(ext)) return <FilePptOutlined />
  if (['txt', 'md', 'markdown', 'log', 'json'].includes(ext)) return <FileTextOutlined />
  return <FileOutlined />
}

/** 对话附件 / AI 产物：按类型渲染（图片内嵌、视频播放、PDF iframe、文本预览、Office 下载）。 */
export default function AttachmentView({ att, artifact = false }: { att: AttLike; artifact?: boolean }) {
  const [url, setUrl] = useState<string>()
  const [text, setText] = useState<string | null>(null)
  const kind = renderKind(att.name, att.type)
  const ext = fileExt(att.name)

  useEffect(() => {
    let alive = true
    const load = artifact && att.artifact_id
      ? getArtifactUrl(att.artifact_id)
      : att.file_key ? getAttachmentUrl(att.file_key) : Promise.resolve(undefined)
    load.then((u) => { if (alive) setUrl(u) }).catch(() => {})
    return () => { alive = false }
  }, [att.file_key, att.artifact_id, artifact])

  const download = async (dlUrl?: string) => {
    try {
      const u = dlUrl || (artifact && att.artifact_id ? await getArtifactUrl(att.artifact_id, true) : url)
      if (!u) return
      const a = document.createElement('a')
      a.href = absUrl(u); a.download = att.name
      if (u.startsWith('http')) a.target = '_blank'
      document.body.appendChild(a); a.click(); a.remove()
    } catch (e) { message.error(errMsg(e)) }
  }

  const openText = async () => {
    if (!url) return
    try {
      const resp = await fetch(absUrl(url))
      if (!resp.ok) throw new Error('读取失败')
      setText(await resp.text())
    } catch (e) { message.error(errMsg(e)) }
  }

  // HTML 弹框预览状态
  const [htmlOpen, setHtmlOpen] = useState(false)
  const [htmlUrl, setHtmlUrl] = useState<string>()

  const openHtml = async () => {
    try {
      const u = artifact && att.artifact_id
        ? await getArtifactUrl(att.artifact_id)
        : (url || (att.file_key ? await getAttachmentUrl(att.file_key) : undefined))
      if (!u) { message.warning('链接未就绪，请稍候重试'); return }
      setHtmlUrl(absUrl(u))
      setHtmlOpen(true)
    } catch (e) { message.error(errMsg(e)) }
  }

  const isHtml = ['html', 'htm'].includes(ext)

  const fileCard = (
    <Space align="center" style={{ marginTop: 6 }}>
      <Tag icon={<PaperClipOutlined />} style={{ margin: 0 }}>{att.name}{fmtSize(att.size) ? ` (${fmtSize(att.size)})` : ''}</Tag>
      <Button size="small" type="link" icon={<DownloadOutlined />} onClick={() => download()}>下载</Button>
    </Space>
  )

  let body
  if (kind === 'image') {
    body = url
      ? <Image src={absUrl(url)} width={180} style={{ borderRadius: 6, marginTop: 6 }} />
      : <Tag style={{ marginTop: 6 }}>图片加载中…</Tag>
  } else if (kind === 'video') {
    body = url ? (
      ext.startsWith('mp') || ['mp3', 'wav', 'm4a'].includes(ext)
        ? <audio controls src={absUrl(url)} style={{ marginTop: 6, maxWidth: 320 }} />
        : <video controls src={absUrl(url)} style={{ maxWidth: 360, marginTop: 6, borderRadius: 6 }} />
    ) : <Tag style={{ marginTop: 6 }}>媒体加载中…</Tag>
  } else if (kind === 'pdf') {
    body = url ? (
      <div style={{ marginTop: 6 }}>
        <iframe src={absUrl(url)} style={{ width: '100%', maxWidth: 640, height: 420, border: '1px solid #f0f0f0', borderRadius: 6 }} />
        <div><Button size="small" type="link" icon={<DownloadOutlined />} onClick={() => download()}>下载 PDF</Button></div>
      </div>
    ) : <Tag style={{ marginTop: 6 }}>PDF 加载中…</Tag>
  } else if (isHtml) {
    // HTML 网页：点击弹框内嵌预览（iframe），或下载 / 新标签打开
    body = (
      <>
        <Space style={{ marginTop: 6 }} wrap>
          <Tag icon={<FileTextOutlined />} color="blue" style={{ cursor: 'pointer' }}
            onClick={openHtml}>{att.name}</Tag>
          <Button size="small" type="link" onClick={openHtml}>预览</Button>
          <Button size="small" type="link" icon={<DownloadOutlined />} onClick={() => download()}>下载</Button>
        </Space>
        <Modal title={att.name} open={htmlOpen} onCancel={() => setHtmlOpen(false)} footer={null}
          width="min(1000px, 92vw)" styles={{ body: { padding: 0 } }} destroyOnClose>
          {htmlUrl && (
            <iframe src={htmlUrl} title={att.name}
              sandbox="allow-scripts allow-same-origin"
              style={{ width: '100%', height: '76vh', border: 0, borderRadius: 6 }} />
          )}
        </Modal>
      </>
    )
  } else if (kind === 'text') {
    body = (
      <Space style={{ marginTop: 6 }}>
        <Tag icon={<FileTextOutlined />} style={{ cursor: 'pointer' }} onClick={openText}>{att.name}</Tag>
        <Button size="small" type="link" icon={<DownloadOutlined />} onClick={() => download()}>下载</Button>
        <Drawer title={att.name} width={640} open={text !== null} onClose={() => setText(null)}>
          <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', fontSize: 13 }}>{text}</Typography.Paragraph>
        </Drawer>
      </Space>
    )
  } else {
    body = (
      <Space align="center" style={{ marginTop: 6 }}>
        <Tag icon={extIcon(ext)} style={{ margin: 0 }}>{att.name}{fmtSize(att.size) ? ` (${fmtSize(att.size)})` : ''}</Tag>
        <Button size="small" type="link" icon={<DownloadOutlined />} onClick={() => download()}>下载</Button>
      </Space>
    )
  }

  return (kind === 'image' || kind === 'video' || kind === 'pdf')
    ? <div>{body}</div>
    : (artifact
        ? <Card size="small" style={{ marginTop: 4, display: 'inline-block' }}>{body}</Card>
        : fileCard)
}
