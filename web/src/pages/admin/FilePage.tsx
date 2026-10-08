import { useEffect, useState } from 'react'
import { Button, Card, Drawer, Image, Input, message, Popconfirm, Select, Space, Table, Tag, Typography } from 'antd'
import {
  DownloadOutlined, DeleteOutlined, EyeOutlined, ClearOutlined,
  FileImageOutlined, FilePdfOutlined, FileWordOutlined, FileExcelOutlined,
  FilePptOutlined, FileTextOutlined, FileOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import MarkdownBody from '../../components/MarkdownBody'
import { fileApi, type FileItem } from '../../api'
import { errMsg } from '../../api/http'
import { getArtifactUrl, renderKind } from '../../api/signedUrl'
import PageContainer from '../../components/PageContainer'
import EmptyState from '../../components/EmptyState'

function fmtSize(n: number) {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(2)} MB`
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`
}

function extIcon(ext?: string) {
  const e = (ext || '').toLowerCase()
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg'].includes(e)) return <FileImageOutlined />
  if (e === 'pdf') return <FilePdfOutlined />
  if (['doc', 'docx'].includes(e)) return <FileWordOutlined />
  if (['xls', 'xlsx', 'csv'].includes(e)) return <FileExcelOutlined />
  if (['ppt', 'pptx'].includes(e)) return <FilePptOutlined />
  if (['txt', 'md', 'markdown', 'log', 'json'].includes(e)) return <FileTextOutlined />
  return <FileOutlined />
}

export default function FilePage() {
  const nav = useNavigate()
  const [items, setItems] = useState<FileItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [source, setSource] = useState<string | undefined>()
  const [q, setQ] = useState('')
  const [sort, setSort] = useState('created_at')
  const [order, setOrder] = useState('desc')
  const [selected, setSelected] = useState<number[]>([])
  const [loading, setLoading] = useState(false)
  const [preview, setPreview] = useState<{ item: FileItem; url: string; kind: string; text?: string | null } | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const r = await fileApi.list({ page, page_size: 20, source, q: q || undefined, sort, order })
      setItems(r.items); setTotal(r.total)
    } catch (e) { message.error(errMsg(e)) } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [page, source, sort, order])

  const download = async (f: FileItem) => {
    try {
      const r = await fileApi.signUrl(f.id)
      const a = document.createElement('a')
      a.href = r.download_url.startsWith('http') ? r.download_url : r.download_url
      a.download = f.file_name
      document.body.appendChild(a); a.click(); a.remove()
    } catch (e) { message.error(errMsg(e)) }
  }

  const openPreview = async (f: FileItem) => {
    try {
      const url = await getArtifactUrl(f.id)
      const kind = renderKind(f.file_name, f.mime)
      let text: string | null = null
      if (kind === 'text') {
        const resp = await fetch(url)
        text = await resp.text()
      }
      setPreview({ item: f, url, kind, text })
    } catch (e) { message.error(errMsg(e)) }
  }

  const doCleanup = async () => {
    try {
      const r = await fileApi.cleanup()
      message.success(r.message || '已清理'); load()
    } catch (e) { message.error(errMsg(e)) }
  }

  const batchDelete = async () => {
    try {
      for (const id of selected) await fileApi.remove(id)
      message.success(`已删除 ${selected.length} 个文件`)
      setSelected([]); load()
    } catch (e) { message.error(errMsg(e)) }
  }

  const renderPreviewBody = () => {
    if (!preview) return null
    if (preview.kind === 'image') return <Image src={preview.url} style={{ maxWidth: '100%' }} />
    if (preview.kind === 'pdf') return <iframe src={preview.url} style={{ width: '100%', height: 'calc(100vh - 160px)', border: 0 }} />
    if (preview.kind === 'video') return <video controls src={preview.url} style={{ maxWidth: '100%' }} />
    if (preview.kind === 'text') return <MarkdownBody content={preview.text || ''} />
    return <Typography.Text type="secondary">该类型不支持在线预览，请下载查看。</Typography.Text>
  }

  return (
    <PageContainer
      title="文件管理"
      subtitle="查看与管理 AI 生成的文件、用户上传的文件（含下载、预览与清理）"
      extra={
        <Space>
          <Input.Search placeholder="搜索文件名" allowClear style={{ width: 200 }}
            onSearch={(v) => { setQ(v); setPage(1); load() }} />
          <Popconfirm title="清理所有已过期文件？" onConfirm={doCleanup}>
            <Button icon={<ClearOutlined />}>清理过期</Button>
          </Popconfirm>
        </Space>
      }
    >
      <Space style={{ marginBottom: 12 }}>
        <Select placeholder="来源" allowClear style={{ width: 140 }} value={source}
          onChange={(v) => { setSource(v); setPage(1) }}
          options={[{ value: 'generated', label: 'AI 生成' }, { value: 'upload', label: '用户上传' }]} />
        {selected.length > 0 && (
          <Popconfirm title={`删除选中的 ${selected.length} 个文件？`} onConfirm={batchDelete}>
            <Button danger>批量删除（{selected.length}）</Button>
          </Popconfirm>
        )}
      </Space>
      <Card bordered={false}>
        <Table
          rowKey="id" dataSource={items} loading={loading}
          rowSelection={{ selectedRowKeys: selected, onChange: (ks) => setSelected(ks as number[]) }}
          locale={{ emptyText: <EmptyState description="暂无文件" /> }}
          pagination={{ current: page, pageSize: 20, total, onChange: setPage }}
          onChange={(_p, _f, sorter: any) => {
            if (sorter?.field && sorter?.order) {
              setSort(sorter.field === 'size' ? 'size' : 'created_at')
              setOrder(sorter.order === 'ascend' ? 'asc' : 'desc')
              setPage(1)
            }
          }}
          columns={[
            { title: '文件名', dataIndex: 'file_name', ellipsis: true },
            {
              title: '类型', dataIndex: 'file_ext', width: 100,
              render: (v: string) => v ? <Tag icon={extIcon(v)}>{v}</Tag> : '-',
            },
            {
              title: '来源', dataIndex: 'source', width: 110,
              render: (v: string) => v === 'generated' ? <Tag color="blue">AI 生成</Tag> : <Tag color="green">用户上传</Tag>,
            },
            { title: '创建人', dataIndex: 'user_name', width: 110, render: (v: string) => v || '-' },
            { title: '大小', dataIndex: 'size', width: 110, sorter: true, render: (v: number) => fmtSize(v) },
            {
              title: '创建时间', dataIndex: 'created_at', width: 170, sorter: true,
              render: (v: string) => (v ? new Date(v).toLocaleString('zh-CN') : '-'),
            },
            {
              title: '状态', dataIndex: 'expires_at', width: 90,
              render: (v: number | null) => {
                if (!v) return <Tag>长期</Tag>
                if (v < Date.now()) return <Tag color="red">已过期</Tag>
                if (v < Date.now() + 24 * 3600 * 1000) return <Tag color="orange">即将过期</Tag>
                return <Tag>有效</Tag>
              },
            },
            {
              title: '所属会话', dataIndex: 'conversation_id', width: 100,
              render: (v: number) => v ? <a onClick={() => nav(`/chat?conv=${v}`)}>#{v}</a> : '-',
            },
            {
              title: '操作', width: 200,
              render: (_: unknown, r: FileItem) => (
                <Space>
                  <Button size="small" icon={<EyeOutlined />} onClick={() => openPreview(r)}>预览</Button>
                  <Button size="small" icon={<DownloadOutlined />} onClick={() => download(r)}>下载</Button>
                  <Popconfirm title="删除该文件？" onConfirm={async () => { await fileApi.remove(r.id); load() }}>
                    <Button size="small" danger icon={<DeleteOutlined />} />
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Drawer title={preview?.item.file_name || '文件预览'} width={760} open={!!preview} onClose={() => setPreview(null)}>
        {renderPreviewBody()}
      </Drawer>
    </PageContainer>
  )
}
