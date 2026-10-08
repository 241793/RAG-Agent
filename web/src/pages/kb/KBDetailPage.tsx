import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert, Button, Card, Descriptions, Divider, Drawer, Dropdown, Empty, Form, Input, List, message, Modal, Popconfirm, Progress,
  Segmented, Select, Space, Spin, Switch, Table, Tabs, Tag, Tooltip, Typography, Upload,
} from 'antd'
import {
  UploadOutlined, ReloadOutlined, DeleteOutlined, ArrowLeftOutlined,
  AppstoreOutlined, UserAddOutlined, FolderAddOutlined, LockOutlined, EditOutlined, ScissorOutlined,
  EyeOutlined, TagOutlined, PieChartOutlined, ApiOutlined, DownloadOutlined, FileTextOutlined, PaperClipOutlined,
  SafetyCertificateOutlined, ArrowUpOutlined, ArrowDownOutlined, HistoryOutlined,
  SyncOutlined, SettingOutlined,
} from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import ReactECharts from 'echarts-for-react'
import { docApi, kbApi, providerApi, rbacApi, type Doc, type KB, type KBStats, type KBMember, type ConnectorInfo } from '../../api'
import { errMsg } from '../../api/http'
import DocErrorDrawer from '../../components/DocErrorDrawer'

const statusColor: Record<string, string> = {
  pending: 'default', parsing: 'processing', chunking: 'processing',
  embedding: 'processing', ready: 'success', failed: 'error', disabled: 'warning',
}
const statusLabel: Record<string, string> = {
  pending: '等待', parsing: '解析中', chunking: '切分中', embedding: '向量化',
  ready: '就绪', failed: '失败', disabled: '停用',
}
const VIS_LABEL: Record<string, string> = { inherit: '继承', public: '公开', restricted: '受限' }

function humanSize(n: number): string {
  if (!n) return '0 B'
  const u = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let v = n
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${u[i]}`
}

// 可内联预览的类型
const IMG_EXT = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp'])
const TEXT_EXT = new Set(['txt', 'text', 'md', 'markdown', 'csv', 'log', 'html', 'htm'])

function DocPreviewBody({ doc }: { doc: Doc }) {
  const ext = (doc.file_ext || '').toLowerCase()
  const [text, setText] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (IMG_EXT.has(ext) || ext === 'pdf') return
    setLoading(true)
    docApi.content(doc.id)
      .then((r) => setText(r.content))
      .catch((e) => message.error(errMsg(e)))
      .finally(() => setLoading(false))
  }, [doc.id, ext])

  const url = docApi.rawUrl(doc.id)
  if (IMG_EXT.has(ext)) return <img src={url} alt={doc.title} style={{ maxWidth: '100%' }} />
  if (ext === 'pdf') return <iframe src={url} title={doc.title} style={{ width: '100%', height: '72vh', border: 0 }} />
  if (TEXT_EXT.has(ext)) {
    if (ext === 'html' || ext === 'htm') {
      return <iframe src={url} title={doc.title} sandbox="" style={{ width: '100%', height: '72vh', border: '1px solid #eee' }} />
    }
    return (
      <Spin spinning={loading}>
        <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', fontFamily: 'ui-monospace, Consolas, monospace', fontSize: 13 }}>
          {text || '(无内容)'}
        </Typography.Paragraph>
      </Spin>
    )
  }
  return (
    <div>
      <Typography.Paragraph type="secondary">
        该类型（.{ext || '未知'}）暂不支持内联预览，可下载后查看；以下为解析出的文本内容：
      </Typography.Paragraph>
      <Button type="link" href={url} target="_blank" style={{ paddingLeft: 0 }}>下载原文件</Button>
      <Spin spinning={loading}>
        <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', fontSize: 13, maxHeight: '60vh', overflow: 'auto' }}>
          {text || '(无文本)'}
        </Typography.Paragraph>
      </Spin>
    </div>
  )
}

export default function KBDetailPage() {
  const { id } = useParams()
  const kbId = Number(id)
  const [kb, setKb] = useState<KB | null>(null)
  const [docs, setDocs] = useState<Doc[]>([])
  const [loading, setLoading] = useState(false)
  const [preview, setPreview] = useState<Doc | null>(null)
  const [chunks, setChunks] = useState<{ doc: Doc; total: number; items: any[] } | null>(null)
  const [chunkEdit, setChunkEdit] = useState<{ id: number; text: string } | null>(null)
  const [members, setMembers] = useState<KBMember[]>([])
  const [users, setUsers] = useState<any[]>([])
  const [roles, setRoles] = useState<any[]>([])
  const [groups, setGroups] = useState<any[]>([])
  const [depts, setDepts] = useState<any[]>([])
  const [memberOpen, setMemberOpen] = useState(false)
  const [memberForm] = Form.useForm()
  const [folders, setFolders] = useState<{ id: number; name: string; parent_id: number | null }[]>([])
  const [folderFilter, setFolderFilter] = useState<number | 'all' | 'root'>('all')
  const [selectedDocIds, setSelectedDocIds] = useState<number[]>([])
  const [aclDoc, setAclDoc] = useState<Doc | null>(null)
  const [aclList, setAclList] = useState<{ id: number; principal_id: number; effect: string }[]>([])
  const [entryOpen, setEntryOpen] = useState(false)
  const [entryEdit, setEntryEdit] = useState<Doc | null>(null)
  const [entryTitle, setEntryTitle] = useState('')
  const [entryContent, setEntryContent] = useState('')
  const [entryFiles, setEntryFiles] = useState<File[]>([])
  const [entryBusy, setEntryBusy] = useState(false)
  const [audit, setAudit] = useState<any>(null)
  const [auditLoading, setAuditLoading] = useState(false)
  const [misses, setMisses] = useState<{ query: string; count: number }[] | null>(null)
  const [missLoading, setMissLoading] = useState(false)
  const loadAudit = async () => {
    setAuditLoading(true)
    try { setAudit(await kbApi.audit(kbId)) } catch (e) { message.error(errMsg(e)) }
    finally { setAuditLoading(false) }
  }
  const loadMisses = async () => {
    setMissLoading(true)
    try { setMisses(await kbApi.missedQueries(30)) } catch (e) { message.error(errMsg(e)) }
    finally { setMissLoading(false) }
  }
  const [aclType, setAclType] = useState<string>('user')
  const [aclPid, setAclPid] = useState<number | undefined>()
  const [aclEffect, setAclEffect] = useState<string>('allow')
  const [stats, setStats] = useState<KBStats | null>(null)
  const [tagDoc, setTagDoc] = useState<Doc | null>(null)
  const [errDoc, setErrDoc] = useState<Doc | null>(null)
  const [tagInput, setTagInput] = useState<string>('')
  const [connector, setConnector] = useState<ConnectorInfo | null>(null)
  const [connTestLoading, setConnTestLoading] = useState(false)
  const [connTestResult, setConnTestResult] = useState<{ count: number; items: any[] } | null>(null)
  const [connQuery, setConnQuery] = useState('测试')
  const [syncSt, setSyncSt] = useState<{ enabled: boolean; last_at: number | null; last_status: string | null; last_count: number | null; last_error: string | null; seed_queries: string[]; limit: number; synced_doc_count: number } | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [syncCfgOpen, setSyncCfgOpen] = useState(false)
  const [syncCfgForm] = Form.useForm()
  const [embModels, setEmbModels] = useState<{ id: number; display_name: string }[]>([])
  const [verDoc, setVerDoc] = useState<Doc | null>(null)
  const [verList, setVerList] = useState<{ id: number; version: number; title: string | null; char_count: number; chunk_count: number; reason: string; created_at: string | null; current: boolean }[]>([])
  const [verLoading, setVerLoading] = useState(false)
  const nav = useNavigate()
  const timer = useRef<any>(null)

  const openVersions = async (doc: Doc) => {
    setVerDoc(doc); setVerList([]); setVerLoading(true)
    try { setVerList(await docApi.listVersions(doc.id)) }
    catch (e) { message.error(errMsg(e)) }
    finally { setVerLoading(false) }
  }

  const rollbackVersion = async (v: number) => {
    if (!verDoc) return
    try {
      await docApi.rollbackVersion(verDoc.id, v)
      message.success(`已回滚到 v${v}`)
      setVerDoc(null); loadDocs(); loadStats()
    } catch (e) { message.error(errMsg(e)) }
  }

  const loadEmbModels = async () => {
    try {
      const cfgs = await providerApi.configs()
      setEmbModels(cfgs.filter((c) => c.purpose === 'embedding').map((c) => ({ id: c.id, display_name: c.display_name })))
    } catch { /* 无权或未配置 */ }
  }

  const setKbEmbedding = async (modelId: number | null) => {
    try {
      const r = await kbApi.update(kbId, { embedding_model_id: modelId })
      setKb(r)
      message.success(modelId ? '已切换向量模型，旧文档需「重新处理」才会用新模型重嵌入' : '已恢复默认向量模型')
    } catch (e) { message.error(errMsg(e)) }
  }

  const isExternal = (kb?.source_type || 'local') === 'external'
  const isEntry = (kb?.source_type || 'local') === 'entry'
  // 有效能力：owner/manager/editor → 可写；manager/owner → 可管成员
  const canWrite = !!kb && ['owner', 'manager', 'editor'].includes(kb.my_perm || '')
  const canManage = !!kb && ['owner', 'manager'].includes(kb.my_perm || '')

  const loadConnector = async () => {
    try { setConnector(await kbApi.getConnector(kbId)) } catch { /* 忽略 */ }
  }

  const loadSyncStatus = async () => {
    try { setSyncSt(await kbApi.syncStatus(kbId)) } catch { /* 忽略 */ }
  }

  const doSync = async () => {
    setSyncing(true)
    try {
      const r = await kbApi.sync(kbId, syncSt?.limit || 500)
      message.success(`同步完成：拉取 ${r.fetched} 条，新增 ${r.created} 篇，跳过重复 ${r.skipped} 篇`)
      loadSyncStatus()
    } catch (e) { message.error(errMsg(e)) }
    finally { setSyncing(false) }
  }

  const openSyncConfig = () => {
    syncCfgForm.setFieldsValue({
      enabled: syncSt?.enabled ?? false,
      limit: syncSt?.limit ?? 500,
      seed_queries: (syncSt?.seed_queries || []).join('\n'),
    })
    setSyncCfgOpen(true)
  }

  const saveSyncConfig = async () => {
    const v = await syncCfgForm.validateFields().catch(() => null)
    if (!v) return
    try {
      await kbApi.syncConfig(kbId, {
        enabled: v.enabled,
        limit: Number(v.limit) || 500,
        seed_queries: (v.seed_queries || '').split('\n').map((s: string) => s.trim()).filter(Boolean),
      })
      message.success('已保存同步配置'); setSyncCfgOpen(false); loadSyncStatus()
    } catch (e) { message.error(errMsg(e)) }
  }

  const testConnector = async () => {
    setConnTestLoading(true)
    setConnTestResult(null)
    try {
      const r = await kbApi.testConnector(kbId, connQuery, 3)
      setConnTestResult({ count: r.count, items: r.items })
      message.success(`连接成功，返回 ${r.count} 条`)
    } catch (e) { message.error(errMsg(e)) }
    finally { setConnTestLoading(false) }
  }

  // 扁平化部门树 → 选项
  const deptOptions = useMemo(() => {
    const out: { value: number; label: string }[] = []
    const walk = (nodes: any[], prefix: string) => {
      for (const n of nodes || []) {
        out.push({ value: n.id, label: `${prefix}${n.name}` })
        if (n.children?.length) walk(n.children, `${prefix}— `)
      }
    }
    walk(depts, '')
    return out
  }, [depts])

  const objectOptions = useMemo(() => {
    if (aclType === 'user') return users.map((u) => ({ value: u.id, label: u.display_name || u.username }))
    if (aclType === 'role') return roles.map((r) => ({ value: r.id, label: r.name }))
    if (aclType === 'group') return groups.map((g) => ({ value: g.id, label: g.name }))
    return deptOptions
  }, [aclType, users, roles, groups, deptOptions])

  const openAcl = async (d: Doc) => {
    setAclDoc(d)
    try { const r = await docApi.acl(d.id); setAclList(r.items || []) }
    catch (e) { message.error(errMsg(e)) }
  }
  const addAcl = async () => {
    if (!aclDoc || aclPid == null) { message.warning('请选择对象'); return }
    try {
      await docApi.addAcl(aclDoc.id, { principal_type: aclType, principal_id: aclPid, effect: aclEffect })
      message.success('已添加授权')
      const r = await docApi.acl(aclDoc.id); setAclList(r.items || [])
      loadDocs()
    } catch (e) { message.error(errMsg(e)) }
  }
  const delAcl = async (aclId: number) => {
    if (!aclDoc) return
    try {
      await docApi.removeAcl(aclDoc.id, aclId)
      message.success('已移除')
      const r = await docApi.acl(aclDoc.id); setAclList(r.items || [])
    } catch (e) { message.error(errMsg(e)) }
  }

  const removeFolder = async (folderId: number) => {
    try { await docApi.removeFolder(folderId); message.success('已删除文件夹'); loadFolders(); loadDocs() }
    catch (e) { message.error(errMsg(e)) }
  }

  const loadFolders = async () => {
    try { setFolders(await docApi.listFolders(kbId)) } catch (e) { message.error(errMsg(e)) }
  }

  const addFolder = async () => {
    let name = ''
    Modal.confirm({
      title: '新建文件夹',
      icon: null,
      content: (
        <Input autoFocus placeholder="文件夹名称" onChange={(e) => { name = e.target.value }} />
      ),
      onOk: async () => {
        if (!name.trim()) { message.warning('请输入名称'); throw new Error('empty') }
        await docApi.createFolder(kbId, name.trim())
        message.success('已创建'); loadFolders()
      },
    })
  }

  const renameFolder = async (folderId: number, oldName: string) => {
    let name = oldName
    Modal.confirm({
      title: '重命名文件夹',
      icon: null,
      content: (
        <Input autoFocus defaultValue={oldName} onChange={(e) => { name = e.target.value }} />
      ),
      onOk: async () => {
        if (!name.trim()) { message.warning('请输入名称'); throw new Error('empty') }
        if (name.trim() === oldName) return
        await docApi.updateFolder(folderId, { name: name.trim() })
        message.success('已重命名'); loadFolders()
      },
    })
  }

  const moveFolderOrder = async (folderId: number, dir: -1 | 1) => {
    const ids = folders.map((f) => f.id)
    const i = ids.indexOf(folderId)
    const j = i + dir
    if (i < 0 || j < 0 || j >= ids.length) return
    ;[ids[i], ids[j]] = [ids[j], ids[i]]
    try { await docApi.reorderFolders(kbId, ids); loadFolders() }
    catch (e) { message.error(errMsg(e)) }
  }

  const batchDelete = async () => {
    if (!selectedDocIds.length) return
    try {
      const r = await docApi.batchDelete(selectedDocIds)
      message.success(r.message || '已删除')
      setSelectedDocIds([]); loadDocs(); loadStats()
    } catch (e) { message.error(errMsg(e)) }
  }

  const mergeExport = async (fmt: 'docx' | 'pdf' | 'md' | 'txt') => {
    if (!selectedDocIds.length) return
    try {
      const token = localStorage.getItem('access_token') || ''
      const resp = await fetch(docApi.mergeExportUrl(fmt), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ ids: selectedDocIds }),
      })
      if (!resp.ok) throw new Error('导出失败')
      const blob = await resp.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = `合并导出-${selectedDocIds.length}篇.${fmt}`
      a.click(); URL.revokeObjectURL(url)
    } catch (e) { message.error(errMsg(e)) }
  }

  const batchMove = async (folderId: number | null) => {
    if (!selectedDocIds.length) return
    try {
      const r = await docApi.batchMove(selectedDocIds, folderId)
      message.success(r.message || '已移动'); setSelectedDocIds([]); loadDocs()
    } catch (e) { message.error(errMsg(e)) }
  }

  const batchVisibility = async (visibility: string) => {
    if (!selectedDocIds.length) return
    try {
      const r = await docApi.batchVisibility(selectedDocIds, visibility)
      message.success(r.message || '已更新'); setSelectedDocIds([]); loadDocs()
    } catch (e) { message.error(errMsg(e)) }
  }

  const batchReprocess = async () => {
    if (!selectedDocIds.length) return
    try {
      const r = await docApi.batchReprocess(selectedDocIds)
      message.success(r.message || '已提交'); setSelectedDocIds([]); loadDocs()
    } catch (e) { message.error(errMsg(e)) }
  }

  const moveDoc = async (docId: number, folderId: number | null) => {
    try { await docApi.moveDoc(docId, folderId); message.success('已移动'); loadDocs() }
    catch (e) { message.error(errMsg(e)) }
  }

  const openPreview = (d: Doc) => setPreview(d)

  const openChunks = async (d: Doc) => {
    try {
      const r = await docApi.chunks(d.id)
      setChunks({ doc: d, total: r.total, items: r.items })
    } catch (e) { message.error(errMsg(e)) }
  }

  const reloadChunks = async () => {
    if (!chunks) return
    const r = await docApi.chunks(chunks.doc.id)
    setChunks({ doc: chunks.doc, total: r.total, items: r.items })
    loadDocs()
  }

  const saveChunk = async () => {
    if (!chunks || !chunkEdit) return
    try {
      await docApi.updateChunk(chunks.doc.id, chunkEdit.id, chunkEdit.text)
      message.success('已保存并重算向量'); setChunkEdit(null); reloadChunks()
    } catch (e) { message.error(errMsg(e)) }
  }

  const delChunk = async (chunkId: number) => {
    if (!chunks) return
    try { await docApi.deleteChunk(chunks.doc.id, chunkId); message.success('已删除'); reloadChunks() }
    catch (e) { message.error(errMsg(e)) }
  }

  const splitChunk = async (chunkId: number, content: string) => {
    if (!chunks) return
    const mid = Math.floor(content.length / 2)
    const off = window.prompt('在该分块内的第几个字符处切分？', String(mid))
    if (off == null) return
    const n = Number(off)
    if (!Number.isFinite(n)) return
    try { await docApi.splitChunk(chunks.doc.id, chunkId, n); message.success('已拆分'); reloadChunks() }
    catch (e) { message.error(errMsg(e)) }
  }

  const setVisibility = async (d: Doc, v: string) => {
    try { await docApi.setVisibility(d.id, v); message.success('已更新可见性'); loadDocs() }
    catch (e) { message.error(errMsg(e)) }
  }

  const saveTags = async () => {
    if (!tagDoc) return
    const tags = tagInput.split(/[,，\s]+/).map((t) => t.trim()).filter(Boolean)
    try { await docApi.setTags(tagDoc.id, tags); message.success('已保存标签'); setTagDoc(null); loadDocs() }
    catch (e) { message.error(errMsg(e)) }
  }

  const loadDocs = async () => {
    try {
      const list = await docApi.list(kbId)
      setDocs(list)
      const pending = list.some((d) => !['ready', 'failed'].includes(d.status))
      if (pending && !timer.current) timer.current = setInterval(loadDocs, 1500)
      else if (!pending && timer.current) { clearInterval(timer.current); timer.current = null }
    } catch (e) { message.error(errMsg(e)) }
  }

  const loadMembers = async () => {
    try { setMembers(await kbApi.members(kbId)) } catch (e) { message.error(errMsg(e)) }
  }

  const loadStats = async () => {
    try { setStats(await kbApi.stats(kbId)) } catch { /* 无权或暂无 */ }
  }

  useEffect(() => {
    (async () => {
      setLoading(true)
      try {
        const found = await kbApi.get(kbId).catch(() => null)
        setKb(found)
        if (found?.source_type === 'external') {
          await loadConnector()
          loadSyncStatus()
        } else {
          await loadDocs()
          await loadFolders()
          loadStats()
          loadEmbModels()
        }
        await loadMembers()
        const r = await rbacApi.users(1, 100)
        setUsers(r.items)
        rbacApi.roles().then(setRoles).catch(() => {})
        rbacApi.groups().then(setGroups).catch(() => {})
        rbacApi.deptTree().then(setDepts).catch(() => {})
      } finally { setLoading(false) }
    })()
    return () => { if (timer.current) clearInterval(timer.current) }
  }, [kbId])

  const beforeUpload = async (file: File) => {
    try {
      const r = await docApi.upload(kbId, file)
      // 去重命中：后端返回已有文档（相同 content_hash）
      const existed = docs.some((d) => d.id === r.id)
      message.success(existed ? `${file.name} 内容与已有文档重复，已复用` : `${file.name} 已上传，正在处理`)
      loadDocs()
    } catch (e) { message.error(errMsg(e)) }
    return false
  }

  const addMember = async () => {
    const v = await memberForm.validateFields()
    try {
      await kbApi.addMember(kbId, v.principal_type, v.principal_id, v.perm_level)
      message.success('已保存成员'); setMemberOpen(false); memberForm.resetFields(); loadMembers()
    } catch (e) { message.error(errMsg(e)) }
  }

  const openEntry = (d?: Doc) => {
    setEntryEdit(d || null)
    setEntryTitle(d?.title || '')
    setEntryContent(d?.content || '')
    setEntryFiles([])
    setEntryOpen(true)
  }
  const saveEntry = async () => {
    if (!entryTitle.trim() || !entryContent.trim()) { message.warning('标题和正文都要填'); return }
    setEntryBusy(true)
    try {
      if (entryEdit) {
        await docApi.updateEntry(entryEdit.id, { title: entryTitle.trim(), content: entryContent.trim() })
        if (entryFiles.length) await docApi.addEntryAttachments(entryEdit.id, entryFiles)
      } else {
        await docApi.createEntry(kbId, entryTitle.trim(), entryContent.trim(), entryFiles)
      }
      message.success('已保存，正在入库'); setEntryOpen(false); loadDocs()
    } catch (e) { message.error(errMsg(e)) } finally { setEntryBusy(false) }
  }

  const filteredDocs = docs.filter((d: any) =>
    folderFilter === 'all' ? true : folderFilter === 'root' ? !d.folder_id : d.folder_id === folderFilter)

  const statsPie = (data: Record<string, number>, nameMap?: Record<string, string>) => ({
    tooltip: { trigger: 'item' },
    legend: { orient: 'vertical', left: 'left', type: 'scroll' },
    series: [{
      type: 'pie', radius: ['40%', '68%'], center: ['62%', '50%'],
      data: Object.entries(data).map(([k, v]) => ({ name: nameMap?.[k] || k, value: v })),
    }],
  })

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => nav('/kb')}>返回</Button>
        <Typography.Title level={4} style={{ margin: 0 }}>{kb?.name || '知识库'}</Typography.Title>
        {kb?.source_type === 'entry' && <Tag color="cyan">图文知识库</Tag>}
        {kb?.source_type === 'external' && <Tag color="purple">外部知识库</Tag>}
      </Space>

      {kb && (
        <Card style={{ marginBottom: 16 }} size="small">
          {isExternal ? (
            <Descriptions column={4} size="small">
              <Descriptions.Item label="来源">外部知识库</Descriptions.Item>
              <Descriptions.Item label="连接器">{kb.connector_kind}</Descriptions.Item>
              <Descriptions.Item label="可见性">{kb.visibility}</Descriptions.Item>
              <Descriptions.Item label="检索方式">实时联邦检索</Descriptions.Item>
            </Descriptions>
          ) : (
            <Descriptions column={5} size="small">
              <Descriptions.Item label="可见性">{kb.visibility}</Descriptions.Item>
              <Descriptions.Item label="向量模型">
                {canManage ? (
                  <Select
                    size="small" style={{ minWidth: 160 }} value={kb.embedding_model_id ?? 0}
                    onChange={(v) => setKbEmbedding(v === 0 ? null : v)}
                    options={[
                      { value: 0, label: '租户默认' },
                      ...embModels.map((m) => ({ value: m.id, label: m.display_name })),
                    ]}
                  />
                ) : (
                  kb.embedding_model_id
                    ? (embModels.find((m) => m.id === kb.embedding_model_id)?.display_name || `#${kb.embedding_model_id}`)
                    : '默认'
                )}
              </Descriptions.Item>
              <Descriptions.Item label="分块策略">{kb.chunk_strategy?.type || 'parent_child'}</Descriptions.Item>
              <Descriptions.Item label="文档数">{kb.doc_count}</Descriptions.Item>
              <Descriptions.Item label="分块数">{kb.chunk_count}</Descriptions.Item>
            </Descriptions>
          )}
          {kb.description && <Typography.Paragraph type="secondary" style={{ margin: '8px 0 0', fontSize: 12 }}>{kb.description}</Typography.Paragraph>}
        </Card>
      )}

      <Tabs
        items={[
          ...(isExternal ? [{
            key: 'connector', label: <Space><ApiOutlined />连接信息</Space>,
            children: (
              <Card title="外部知识库连接" extra={<Button onClick={loadConnector}>刷新</Button>}>
                <Descriptions column={2} size="small" bordered style={{ marginBottom: 16 }}>
                  <Descriptions.Item label="连接器类型">{connector?.connector_kind || kb?.connector_kind}</Descriptions.Item>
                  <Descriptions.Item label="API Key">
                    {connector?.config?.api_key_set ? '已配置' : '未配置'}
                  </Descriptions.Item>
                  {Object.entries(connector?.config || {}).filter(([k]) => k !== 'api_key' && k !== 'api_key_set').map(([k, v]) => (
                    <Descriptions.Item key={k} label={k}>
                      <Typography.Text style={{ fontSize: 12 }} ellipsis>
                        {typeof v === 'object' ? JSON.stringify(v) : String(v)}
                      </Typography.Text>
                    </Descriptions.Item>
                  ))}
                </Descriptions>
                <Space style={{ marginBottom: 12 }}>
                  <Input value={connQuery} onChange={(e) => setConnQuery(e.target.value)}
                    placeholder="测试查询词" style={{ width: 240 }} />
                  <Button type="primary" loading={connTestLoading} onClick={testConnector}>测试检索</Button>
                </Space>
                {connTestResult && (
                  <List
                    size="small" bordered dataSource={connTestResult.items}
                    locale={{ emptyText: '连接成功但无返回，请检查响应映射配置' }}
                    renderItem={(it: any) => (
                      <List.Item>
                        <div style={{ width: '100%' }}>
                          <Space size={4}>
                            <Tag color="green">{it.title || '（无标题）'}</Tag>
                            {it.score > 0 && <Tag>score {it.score}</Tag>}
                            {it.source_uri && <a href={it.source_uri} target="_blank" rel="noreferrer">原文</a>}
                          </Space>
                          <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 4, marginBottom: 0 }}>
                            {it.content}
                          </Typography.Paragraph>
                        </div>
                      </List.Item>
                    )}
                  />
                )}
                <Alert type="info" showIcon style={{ marginTop: 12 }}
                  message="该知识库在检索时实时调用外部系统，结果与本地库一起排序融合；修改连接配置请在「编辑知识库」中进行。" />

                <Divider orientation="left" style={{ marginTop: 20 }}>导入同步</Divider>
                <Alert type="warning" showIcon style={{ marginBottom: 12 }}
                  message="实时检索依赖远端可用与响应速度；「导入同步」把远端内容一次性拉取并落本地索引，之后检索走本地、更快更稳，且可与本地内容一起重排。重复同步按来源去重，不会产生重复文档。" />
                {syncSt ? (
                  <Descriptions column={3} size="small" style={{ marginBottom: 12 }}>
                    <Descriptions.Item label="已同步文档">{syncSt.synced_doc_count}</Descriptions.Item>
                    <Descriptions.Item label="上次同步">
                      {syncSt.last_at ? new Date(syncSt.last_at).toLocaleString('zh-CN') : '从未'}
                    </Descriptions.Item>
                    <Descriptions.Item label="上次状态">
                      {syncSt.last_status === 'success'
                        ? <Tag color="green">成功（新增 {syncSt.last_count ?? 0}）</Tag>
                        : syncSt.last_status === 'failed'
                          ? <Tag color="red">失败</Tag>
                          : <Tag>未同步</Tag>}
                    </Descriptions.Item>
                    {syncSt.last_error && (
                      <Descriptions.Item label="错误" span={3}><Typography.Text type="danger" style={{ fontSize: 12 }}>{syncSt.last_error}</Typography.Text></Descriptions.Item>
                    )}
                  </Descriptions>
                ) : null}
                <Space wrap style={{ marginBottom: 8 }}>
                  <Button type="primary" icon={<SyncOutlined />} loading={syncing} disabled={!canManage} onClick={doSync}>
                    立即同步
                  </Button>
                  <Button icon={<SettingOutlined />} disabled={!canManage} onClick={openSyncConfig}>同步配置</Button>
                </Space>
              </Card>
            ),
          }] : [{
            key: 'docs', label: isEntry ? '图文条目' : '文档管理',
            children: (
              <Card
                title={
                  <Space wrap>
                    {!isEntry && (
                      <>
                        <Select size="small" value={folderFilter} style={{ width: 160 }}
                          onChange={(v) => setFolderFilter(v)}
                          options={[
                            { value: 'all', label: '全部文档' },
                            { value: 'root', label: '未分类' },
                            ...folders.map((f) => ({ value: f.id, label: `📁 ${f.name}` })),
                          ]} />
                        <Button size="small" icon={<FolderAddOutlined />} onClick={addFolder} disabled={!canWrite}>新建文件夹</Button>
                        {typeof folderFilter === 'number' && canWrite && (
                          <>
                            <Button size="small" icon={<EditOutlined />}
                              onClick={() => {
                                const f = folders.find((x) => x.id === folderFilter)
                                if (f) renameFolder(f.id, f.name)
                              }}>重命名</Button>
                            <Button size="small" icon={<ArrowUpOutlined />} title="上移"
                              onClick={() => moveFolderOrder(folderFilter as number, -1)} />
                            <Button size="small" icon={<ArrowDownOutlined />} title="下移"
                              onClick={() => moveFolderOrder(folderFilter as number, 1)} />
                            <Popconfirm title="删除该文件夹？文档会移回未分类" onConfirm={() => removeFolder(folderFilter as number)}>
                              <Button size="small" danger icon={<DeleteOutlined />}>删除文件夹</Button>
                            </Popconfirm>
                          </>
                        )}
                      </>
                    )}
                    {selectedDocIds.length > 0 && canWrite && (
                      <>
                        <Popconfirm title={`删除选中的 ${selectedDocIds.length} 个文档？`} onConfirm={batchDelete}>
                          <Button size="small" danger>批量删除（{selectedDocIds.length}）</Button>
                        </Popconfirm>
                        <Select size="small" placeholder="批量移到" style={{ width: 130 }}
                          onChange={(v: number) => batchMove(v === 0 ? null : v)} value={null as any}
                          options={[{ value: 0, label: '未分类' }, ...folders.map((f) => ({ value: f.id, label: f.name }))]} />
                        <Select size="small" placeholder="批量可见性" style={{ width: 130 }}
                          onChange={(v: string) => batchVisibility(v)} value={null as any}
                          options={[
                            { value: 'inherit', label: '继承知识库' },
                            { value: 'public', label: '公开' },
                            { value: 'restricted', label: '受限' },
                          ]} />
                        <Popconfirm title={`重新处理选中的 ${selectedDocIds.length} 个文档？`} onConfirm={batchReprocess}>
                          <Button size="small" icon={<ReloadOutlined />}>批量重灌</Button>
                        </Popconfirm>
                      </>
                    )}
                    {selectedDocIds.length > 0 && (
                      <Dropdown trigger={['click']} menu={{
                        items: [
                          { key: 'docx', label: '合并导出 Word' },
                          { key: 'pdf', label: '合并导出 PDF' },
                          { key: 'md', label: '合并导出 Markdown' },
                          { key: 'txt', label: '合并导出 TXT' },
                        ],
                        onClick: ({ key }) => mergeExport(key as any),
                      }}>
                        <Button size="small" icon={<DownloadOutlined />}>合并导出（{selectedDocIds.length}）</Button>
                      </Dropdown>
                    )}
                  </Space>
                }
                extra={
                  canWrite && !isExternal ? (
                    <Space>
                      {isEntry && <Button type="primary" icon={<FileTextOutlined />} onClick={() => openEntry()}>添加图文条目</Button>}
                      {!isEntry && (
                        <Upload beforeUpload={beforeUpload} showUploadList={false} multiple>
                          <Button type="primary" icon={<UploadOutlined />}>上传文档</Button>
                        </Upload>
                      )}
                    </Space>
                  ) : null
                }
              >
                <Table
                  rowKey="id" loading={loading}
                  dataSource={filteredDocs}
                  pagination={false}
                  rowSelection={{ selectedRowKeys: selectedDocIds, onChange: (ks) => setSelectedDocIds(ks as number[]) }}
                  columns={[
                    { title: '标题', dataIndex: 'title', ellipsis: true,
                      render: (v: string, r: Doc) => (
                        <Space size={4}>
                          {r.kind === 'entry' && <Tag color="cyan">图文条目</Tag>}
                          <span>{v}</span>
                        </Space>
                      ) },
                    { title: '类型', dataIndex: 'file_ext', width: 70,
                      render: (v, r: Doc) => r.kind === 'entry'
                        ? <Tag color="cyan">条目</Tag> : <Tag>{v || '-'}</Tag> },
                    {
                      title: '状态', dataIndex: 'status', width: 170,
                      render: (s: string, r: Doc) => (
                        <Space direction="vertical" size={0} style={{ width: 140 }}>
                          <Tag color={statusColor[s]}>{statusLabel[s] || s}</Tag>
                          {!['ready', 'failed'].includes(s) && <Progress percent={r.progress} size="small" />}
                          {(r.error_msg || r.error_detail) && (
                            <Typography.Link style={{ fontSize: 11 }}
                              onClick={() => setErrDoc(r)}>
                              查看详情
                            </Typography.Link>
                          )}
                        </Space>
                      ),
                    },
                    {
                      title: '标签', dataIndex: 'tags', width: 160,
                      render: (tags: string[] | null, r: Doc) => (
                        <Space size={2} wrap style={{ cursor: 'pointer' }}
                          onClick={() => { setTagDoc(r); setTagInput((r.tags || []).join(', ')) }}>
                          {(tags || []).length === 0
                            ? <Typography.Text type="secondary" style={{ fontSize: 12 }}><TagOutlined /> 添加</Typography.Text>
                            : (tags || []).map((t) => <Tag key={t} color="blue" style={{ marginRight: 0 }}>{t}</Tag>)}
                        </Space>
                      ),
                    },
                    ...(!isEntry ? [{
                      title: '可见性', dataIndex: 'visibility', width: 130,
                      render: (v: string, r: Doc) => (
                        <Select size="small" value={v || 'inherit'} style={{ width: 110 }}
                          onChange={(nv) => setVisibility(r, nv)}
                          options={[
                            { value: 'inherit', label: '继承知识库' },
                            { value: 'public', label: '公开' },
                            { value: 'restricted', label: '受限' },
                          ]} />
                      ),
                    },
                    { title: '分块', dataIndex: 'chunk_count', width: 60 },
                    {
                      title: '文件夹', width: 130,
                      render: (_: any, r: any) => (
                        <Select size="small" style={{ width: 116 }} placeholder="未分类"
                          value={r.folder_id || 0} onChange={(v) => moveDoc(r.id, v === 0 ? null : v)}
                          options={[{ value: 0, label: '未分类' }, ...folders.map((f) => ({ value: f.id, label: f.name }))]} />
                      ),
                    }] : []),
                    {
                      title: '操作', width: 300,
                      render: (_: any, r: Doc) => (
                        <Space>
                          {isEntry ? (
                            <>
                              <Tooltip title="编辑条目/附件">
                                <Button size="small" icon={<EditOutlined />} onClick={() => openEntry(r)} />
                              </Tooltip>
                              {canWrite && (
                                <Popconfirm title="删除该条目？" onConfirm={async () => {
                                  await docApi.remove(r.id); message.success('已删除'); loadDocs()
                                }}>
                                  <Button size="small" danger icon={<DeleteOutlined />} />
                                </Popconfirm>
                              )}
                            </>
                          ) : (
                            <>
                              <Tooltip title="在线预览"><Button size="small" icon={<EyeOutlined />} onClick={() => openPreview(r)} /></Tooltip>
                              <Tooltip title="分块管理"><Button size="small" icon={<AppstoreOutlined />} onClick={() => openChunks(r)} /></Tooltip>
                              <Tooltip title="版本历史"><Button size="small" icon={<HistoryOutlined />} onClick={() => openVersions(r)} /></Tooltip>
                              {canWrite && (
                                <>
                                  <Tooltip title="文档权限"><Button size="small" icon={<LockOutlined />} onClick={() => openAcl(r)} /></Tooltip>
                                  <Tooltip title="重新处理"><Button size="small" icon={<ReloadOutlined />} onClick={async () => {
                                    await docApi.reprocess(r.id); message.info('已重新提交处理'); loadDocs()
                                  }} /></Tooltip>
                                  <Popconfirm title="删除该文档？" onConfirm={async () => {
                                    await docApi.remove(r.id); message.success('已删除'); loadDocs()
                                  }}>
                                    <Button size="small" danger icon={<DeleteOutlined />} />
                                  </Popconfirm>
                                </>
                              )}
                            </>
                          )}
                        </Space>
                      ),
                    },
                  ]}
                />
              </Card>
            ),
          },
          {
            key: 'stats', label: <Space><PieChartOutlined />统计</Space>,
            children: (
              <Card>
                {!stats ? <Empty description="暂无统计数据" /> : (
                  <div>
                    <Descriptions column={5} size="small" style={{ marginBottom: 16 }}>
                      <Descriptions.Item label="文档数">{stats.doc_count}</Descriptions.Item>
                      <Descriptions.Item label="分块数">{stats.chunk_count}</Descriptions.Item>
                      <Descriptions.Item label="已向量化">{stats.embedded_chunks}</Descriptions.Item>
                      <Descriptions.Item label="向量覆盖率">{Math.round((stats.embedded_ratio || 0) * 100)}%</Descriptions.Item>
                      <Descriptions.Item label="存储占用">{humanSize(stats.total_size)}</Descriptions.Item>
                    </Descriptions>
                    <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                      <Card title="状态分布" size="small" style={{ flex: '1 1 360px' }}>
                        {Object.keys(stats.by_status).length
                          ? <ReactECharts option={statsPie(stats.by_status, statusLabel)} style={{ height: 280 }} />
                          : <Empty description="无数据" />}
                      </Card>
                      <Card title="文件类型分布" size="small" style={{ flex: '1 1 360px' }}>
                        {Object.keys(stats.by_ext).length
                          ? <ReactECharts option={statsPie(stats.by_ext)} style={{ height: 280 }} />
                          : <Empty description="无数据" />}
                      </Card>
                    </div>
                  </div>
                )}
              </Card>
            ),
          }]),
          {
            key: 'audit', label: <Space><SafetyCertificateOutlined />内容巡检</Space>,
            children: (
              <Space direction="vertical" style={{ width: '100%' }} size={16}>
              <Card
                title="内容巡检" extra={<Button size="small" icon={<ReloadOutlined />} loading={auditLoading} onClick={loadAudit}>扫描</Button>}
              >
                {!audit ? <Empty description="点击「扫描」检查内容质量" /> : (
                  <Space direction="vertical" style={{ width: '100%' }} size={12}>
                    <Space wrap>
                      <Tag color="red">失败 {audit.counts?.failed || 0}</Tag>
                      <Tag color="orange">空文档 {audit.counts?.empty || 0}</Tag>
                      <Tag color="gold">无分块 {audit.counts?.no_chunk || 0}</Tag>
                      <Tag color="default">未标签 {audit.counts?.untagged || 0}</Tag>
                      <Tag color="blue">陈旧 {audit.counts?.stale || 0}</Tag>
                    </Space>
                    {[
                      ['失败（需修复）', audit.failed, 'red'],
                      ['空文档（无正文）', audit.empty, 'orange'],
                      ['已就绪但无分块', audit.no_chunk, 'gold'],
                      ['陈旧（超 180 天未更新）', audit.stale, 'blue'],
                    ].map(([label, list, color]: any) => (list && list.length) ? (
                      <div key={label}>
                        <Typography.Text strong>{label}（{list.length}）</Typography.Text>
                        <div style={{ marginTop: 6 }}>
                          {list.slice(0, 20).map((d: any) => (
                            <Tag key={d.id} color={color} style={{ marginBottom: 4 }}>{d.title}（#{d.id}）</Tag>
                          ))}
                        </div>
                      </div>
                    ) : null)}
                    {!Object.values(audit.counts || {}).some((n: any) => n > 0) && (
                      <Alert type="success" showIcon message="未发现问题，内容质量良好" />
                    )}
                  </Space>
                )}
              </Card>
              <Card
                title="未命中查询（近 30 天）"
                extra={<Button size="small" icon={<ReloadOutlined />} loading={missLoading} onClick={loadMisses}>加载</Button>}
              >
                <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
                  这些提问在知识库中检索不到内容——按频次排序，是最值得补的内容缺口。
                </Typography.Paragraph>
                {!misses ? <Empty description="点击「加载」查看未命中查询" /> : misses.length === 0 ? (
                  <Alert type="success" showIcon message="近 30 天没有未命中记录" />
                ) : (
                  <Table
                    rowKey="query" size="small" dataSource={misses} pagination={{ pageSize: 10 }}
                    columns={[
                      { title: '查询', dataIndex: 'query' },
                      { title: '次数', dataIndex: 'count', width: 90,
                        render: (n: number) => <Tag color={n >= 5 ? 'red' : n >= 2 ? 'orange' : 'default'}>{n}</Tag> },
                    ]}
                  />
                )}
              </Card>
              </Space>
            ),
          },
          ...(canManage ? [{
            key: 'members', label: '成员管理',
            children: (
              <Card
                extra={canManage ? <Button type="primary" icon={<UserAddOutlined />} onClick={() => setMemberOpen(true)}>添加成员</Button> : undefined}
              >
                <Table
                  rowKey="id" dataSource={members} pagination={false}
                  columns={[
                    {
                      title: '授权对象', render: (_: any, m: KBMember) => (
                        <Space>
                          <Tag color={{ user: 'blue', department: 'cyan', role: 'purple', group: 'gold' }[m.principal_type] || 'default'}>
                            {{ user: '用户', department: '部门', role: '角色', group: '用户组' }[m.principal_type] || m.principal_type}
                          </Tag>
                          {m.display_name}
                        </Space>
                      ),
                    },
                    { title: '权限', dataIndex: 'perm_level', width: 140,
                      render: (v: string) => <Tag color={v === 'manager' ? 'red' : v === 'editor' ? 'blue' : 'default'}>
                        {v === 'manager' ? '管理' : v === 'editor' ? '编辑' : '查看'}</Tag> },
                    ...(canManage ? [{
                      title: '操作', width: 90,
                      render: (_: any, m: KBMember) => (
                        <Popconfirm title="移除该成员？" onConfirm={async () => {
                          await kbApi.removeMember(kbId, m.id); message.success('已移除'); loadMembers()
                        }}>
                          <Button size="small" danger icon={<DeleteOutlined />} />
                        </Popconfirm>
                      ),
                    }] : []),
                  ]}
                />
                <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 12 }}>
                  说明：知识库可见性为「私有」时仅创建者与下列成员可访问；「公开/内部」则本租户全员可见。可按用户 / 部门 / 角色 / 用户组授权。
                </Typography.Paragraph>
              </Card>
            ),
          }] : []),
        ]}
      />

      {/* 原文在线预览 */}
      <Drawer title={preview ? `预览：${preview.title}` : '文档预览'} width="72%" open={!!preview} onClose={() => setPreview(null)} destroyOnClose>
        {preview && <DocPreviewBody doc={preview} />}
      </Drawer>

      {/* 版本历史 */}
      <Drawer title={verDoc ? `版本历史：${verDoc.title}` : '版本历史'} width="62%" open={!!verDoc} onClose={() => setVerDoc(null)} destroyOnClose>        <Alert type="info" showIcon style={{ marginBottom: 12 }}
          message="文档每次「重新处理 / 覆盖上传」都会归档上一版。回滚会把分块与正文还原到所选版本（回滚前会先归档当前版本，操作可逆）。" />
        <Table
          rowKey="id" dataSource={verList} loading={verLoading} pagination={false} size="small"
          locale={{ emptyText: <Empty description="暂无历史版本（首次入库不产生版本记录）" /> }}
          columns={[
            { title: '版本', dataIndex: 'version', width: 90,
              render: (v: number, r) => <Space><Tag color={r.current ? 'green' : 'default'}>v{v}</Tag>{r.current && <Tag color="blue">当前</Tag>}</Space> },
            { title: '分块数', dataIndex: 'chunk_count', width: 80 },
            { title: '字符数', dataIndex: 'char_count', width: 90 },
            { title: '归档原因', dataIndex: 'reason', width: 100,
              render: (v: string) => <Tag>{v === 'reprocess' ? '重新处理' : v === 'reupload' ? '覆盖上传' : '手动'}</Tag> },
            { title: '归档时间', dataIndex: 'created_at', width: 180,
              render: (v: string | null) => v ? new Date(v).toLocaleString('zh-CN') : '-' },
            { title: '操作', width: 120,
              render: (_: any, r) => r.current ? <Typography.Text type="secondary">—</Typography.Text> : (
                canWrite ? (
                  <Popconfirm title={`回滚到 v${r.version}？当前版本会先被归档`} onConfirm={() => rollbackVersion(r.version)}>
                    <Button size="small" icon={<HistoryOutlined />}>回滚</Button>
                  </Popconfirm>
                ) : <Typography.Text type="secondary">—</Typography.Text>
              ) },
          ]}
        />
      </Drawer>

      {/* 导入同步配置 */}
      <Modal title="导入同步配置" open={syncCfgOpen} onOk={saveSyncConfig} onCancel={() => setSyncCfgOpen(false)} destroyOnClose>
        <Form form={syncCfgForm} layout="vertical">
          <Form.Item name="enabled" label="启用定时同步" valuePropName="checked"
            extra="开启后可由定时任务按计划触发；也可随时手动「立即同步」">
            <Switch />
          </Form.Item>
          <Form.Item name="limit" label="单次同步上限" extra="一次最多从远端拉取的条数">
            <Input type="number" placeholder="500" />
          </Form.Item>
          <Form.Item name="seed_queries" label="种子查询（每行一条）"
            extra="连接器无「批量列举」能力时，用这些查询词去远端检索并导入；具备批量列举能力的连接器会忽略此配置">
            <Input.TextArea rows={4} placeholder={'例如：\n产品手册\n常见问题'} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 分块查看 + 编辑 */}
      <Drawer title={`分块：${chunks?.doc.title || ''}（共 ${chunks?.total || 0}）`} width="70%"
        open={!!chunks} onClose={() => setChunks(null)}>
        <List
          dataSource={chunks?.items || []}
          locale={{ emptyText: '暂无分块' }}
          renderItem={(c: any) => (
            <List.Item>
              <div style={{ width: '100%' }}>
                <Space size={4} wrap style={{ marginBottom: 4 }}>
                  <Tag color="blue">#{c.ordinal}</Tag>
                  {c.chunk_type === 'parent' ? <Tag color="purple">父块</Tag> : <Tag>子块</Tag>}
                  {c.page && <Tag>第{c.page}页</Tag>}
                  <Tag>{c.token_count} 字</Tag>
                  {c.has_embedding ? <Tag color="green">已向量化</Tag> : <Tag color="orange">无向量</Tag>}
                  <Tag color={c.vis_scope === 2 ? 'red' : 'default'}>{VIS_LABEL[({ 0: 'inherit', 1: 'public', 2: 'restricted' } as Record<number, string>)[c.vis_scope as number]] || '继承'}</Tag>
                  {canWrite && (
                    <>
                      <Button size="small" type="link" icon={<EditOutlined />}
                        onClick={() => setChunkEdit({ id: c.id, text: c.content })}>编辑</Button>
                      <Button size="small" type="link" icon={<ScissorOutlined />}
                        onClick={() => splitChunk(c.id, c.content)}>拆分</Button>
                      <Popconfirm title="删除该分块？" onConfirm={() => delChunk(c.id)}>
                        <Button size="small" type="link" danger>删除</Button>
                      </Popconfirm>
                    </>
                  )}
                </Space>
                <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginTop: 2, fontSize: 13 }}>
                  {c.content}
                </Typography.Paragraph>
              </div>
            </List.Item>
          )}
        />
      </Drawer>

      {/* 分块编辑 */}
      <Modal title="编辑分块（保存后自动重算向量）" open={!!chunkEdit} onOk={saveChunk} onCancel={() => setChunkEdit(null)}
        width={720} destroyOnClose>
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          修改分块内容会重新生成向量并刷新关键词索引，检索结果随之更新。
        </Typography.Paragraph>
        <textarea
          value={chunkEdit?.text || ''}
          onChange={(e) => setChunkEdit((c) => (c ? { ...c, text: e.target.value } : c))}
          rows={14}
          style={{ width: '100%', fontFamily: 'ui-monospace, Consolas, monospace', fontSize: 13, padding: 8, borderRadius: 6, border: '1px solid #d9d9d9' }}
        />
      </Modal>

      {/* 文档级权限（ACL） */}
      <Drawer title={`文档权限：${aclDoc?.title || ''}`} width={600}
        open={!!aclDoc} onClose={() => setAclDoc(null)}>
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          说明：添加授权会将该文档设为「受限」，只有命中 allow 且未命中 deny 的主体可检索到。
        </Typography.Paragraph>
        <Space style={{ marginBottom: 12 }} wrap>
          <Select style={{ width: 120 }} value={aclType} onChange={(v) => { setAclType(v); setAclPid(undefined) }}
            options={[{ value: 'user', label: '用户' }, { value: 'department', label: '部门' }, { value: 'role', label: '角色' }, { value: 'group', label: '用户组' }]} />
          <Select style={{ width: 220 }} showSearch optionFilterProp="label" placeholder="选择授权对象"
            value={aclPid} onChange={setAclPid} options={objectOptions} />
          <Select style={{ width: 100 }} value={aclEffect} onChange={setAclEffect}
            options={[{ value: 'allow', label: '允许' }, { value: 'deny', label: '拒绝' }]} />
          <Button type="primary" onClick={addAcl}>添加</Button>
        </Space>
        <List
          size="small" bordered dataSource={aclList}
          locale={{ emptyText: '暂无授权（文档默认继承知识库可见性）' }}
          renderItem={(a) => (
            <List.Item actions={[
              <Popconfirm key="d" title="移除该授权？" onConfirm={() => delAcl(a.id)}>
                <Button size="small" danger icon={<DeleteOutlined />} />
              </Popconfirm>,
            ]}>
              <Space>
                <Tag color={a.effect === 'allow' ? 'green' : 'red'}>{a.effect === 'allow' ? '允许' : '拒绝'}</Tag>
                <span style={{ fontFamily: 'monospace', fontSize: 12 }}>principal #{a.principal_id}</span>
              </Space>
            </List.Item>
          )}
        />
      </Drawer>

      {/* 标签编辑 */}
      <Modal title={`编辑标签：${tagDoc?.title || ''}`} open={!!tagDoc} onOk={saveTags} onCancel={() => setTagDoc(null)} destroyOnClose>
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>多个标签用逗号或空格分隔，最多 20 个。</Typography.Paragraph>
        <Select mode="tags" style={{ width: '100%' }} placeholder="输入标签后回车"
          value={tagInput.split(/[,，\s]+/).filter(Boolean)}
          onChange={(vals) => setTagInput((vals as string[]).join(', '))} />
      </Modal>

      {/* 文档失败详情 */}
      <DocErrorDrawer
        doc={errDoc}
        onClose={() => setErrDoc(null)}
        onReprocess={async (d) => { await docApi.reprocess(d.id); message.info('已重新提交处理'); loadDocs() }}
      />

      {/* 添加成员 */}
      <Modal title="添加成员" open={memberOpen} onOk={addMember} onCancel={() => setMemberOpen(false)} destroyOnClose>
        <Form form={memberForm} layout="vertical" initialValues={{ perm_level: 'viewer', principal_type: 'user' }}>
          <Form.Item name="principal_type" label="授权对象类型">
            <Segmented block options={[
              { value: 'user', label: '用户' },
              { value: 'department', label: '部门' },
              { value: 'role', label: '角色' },
              { value: 'group', label: '用户组' },
            ]} />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(p, c) => p.principal_type !== c.principal_type}>
            {() => {
              const t = memberForm.getFieldValue('principal_type')
              const opts = t === 'user' ? users.map((u) => ({ value: u.id, label: `${u.display_name || u.username}（${u.username}）` }))
                : t === 'department' ? deptOptions
                : t === 'role' ? roles.map((r) => ({ value: r.id, label: r.name }))
                : groups.map((g) => ({ value: g.id, label: g.name }))
              return (
                <Form.Item name="principal_id" label="授权对象" rules={[{ required: true, message: '请选择对象' }]}>
                  <Select showSearch optionFilterProp="label" options={opts} />
                </Form.Item>
              )
            }}
          </Form.Item>
          <Form.Item name="perm_level" label="权限">
            <Select options={[
              { value: 'viewer', label: '查看' },
              { value: 'editor', label: '编辑（上传/删除文档）' },
              { value: 'manager', label: '管理（含成员管理）' },
            ]} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={entryEdit ? '编辑图文条目' : '添加图文条目'}
        open={entryOpen} onOk={saveEntry} onCancel={() => setEntryOpen(false)}
        confirmLoading={entryBusy} destroyOnClose width={640}
      >
        <Alert type="info" showIcon style={{ marginBottom: 12 }}
          message="录入一段文字并配图片/附件；当有人问到与这段文字相关的问题、被检索命中时，配套图片/附件会自动发送给提问者（渠道用户）。" />
        <Form layout="vertical">
          <Form.Item label="标题" required>
            <Input value={entryTitle} onChange={(e) => setEntryTitle(e.target.value)} placeholder="如：如何重置密码" />
          </Form.Item>
          <Form.Item label="正文（用于检索匹配）" required>
            <Input.TextArea rows={6} value={entryContent} onChange={(e) => setEntryContent(e.target.value)}
              placeholder="用自然语言描述这个条目要说明的内容，客户问相关问题时能匹配上。" />
          </Form.Item>
          <Form.Item label="配套图片/附件（命中后自动发送）">
            <Upload multiple beforeUpload={(f) => { setEntryFiles((arr) => [...arr, f]); return false }} fileList={[]}>
              <Button icon={<PaperClipOutlined />}>选择图片/附件</Button>
            </Upload>
            {entryEdit && (entryEdit.attachments || []).length > 0 && (
              <div style={{ marginTop: 8 }}>
                {(entryEdit.attachments || []).map((a, i) => (
                  <Tag key={`old-${i}`} color="geekblue" closable
                    onClose={async () => {
                      try {
                        const updated = await docApi.removeEntryAttachment(entryEdit.id, i)
                        setEntryEdit({ ...entryEdit, attachments: updated.attachments })
                        message.success('已删除附件')
                      } catch (e) { message.error(errMsg(e)) }
                    }}>
                    已有：{a.name}
                  </Tag>
                ))}
              </div>
            )}
            {entryFiles.length > 0 && (
              <div style={{ marginTop: 8 }}>
                {entryFiles.map((f, i) => (
                  <Tag key={i} color="green" closable onClose={() => setEntryFiles((arr) => arr.filter((_, j) => j !== i))}>
                    新增：{f.name}
                  </Tag>
                ))}
              </div>
            )}
          </Form.Item>
          {entryEdit && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              保存正文改动后，新增附件会自动追加到该条目。删除已有附件即时生效。
            </Typography.Text>
          )}
        </Form>
      </Modal>
    </div>
  )
}
