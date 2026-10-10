import { API_BASE, http } from './http'

export { API_BASE }

// ---- 类型 ----
export interface RoleBrief {
  id: number
  code: string
  name: string
}

export interface User {
  id: number
  tenant_id: number
  username: string
  display_name: string
  email?: string
  is_admin: boolean
  department_id?: number
  department_name?: string
  roles?: RoleBrief[]
  permissions?: string[]
}

export interface KB {
  id: number
  name: string
  description?: string
  icon?: string
  visibility: 'public' | 'internal' | 'private'
  source_type?: 'local' | 'external' | 'entry'
  index_mode?: 'vector' | 'keyword'
  connector_kind?: string | null
  embedding_model_id?: number
  chunk_strategy?: Record<string, any>
  settings?: Record<string, any>
  doc_count: number
  chunk_count: number
  owner_id?: number
  my_perm?: string
  created_at: string
}

export interface ConnectorInfo {
  source_type: string
  connector_kind: string | null
  config: Record<string, any> | null
}

export interface KBMember {
  id: number
  principal_id: number
  principal_type: 'user' | 'department' | 'role' | 'group'
  principal_ref_id: number
  user_id: number | null
  display_name: string
  perm_level: string
}

export interface KBStats {
  doc_count: number
  chunk_count: number
  embedded_chunks: number
  embedded_ratio: number
  total_size: number
  by_status: Record<string, number>
  by_ext: Record<string, number>
}

export interface Doc {
  id: number
  kb_id: number
  title: string
  kind?: string
  file_name?: string
  file_ext?: string
  file_size: number
  content?: string | null
  attachments?: { file_key: string; name: string; mime: string; size: number }[] | null
  status: string
  visibility: string
  progress: number
  error_msg?: string
  error_detail?: Record<string, any> | null
  page_count: number
  char_count: number
  chunk_count: number
  tags?: string[] | null
  created_at: string
}

export interface RetrievedChunk {
  chunk_id: number
  doc_id: number
  kb_id: number
  content: string
  score: number
  page?: number
  doc_title?: string
  source: string
}

export interface Citation {
  chunk_id: number
  doc_id: number
  doc_title?: string
  page?: number
  score: number
  snippet: string
  source_uri?: string | null
  attachments?: { file_key: string; name: string; mime: string; size: number }[] | null
}

export interface Provider {
  id: number
  name: string
  kind: string
  base_url: string
  api_key_set: boolean
  status: string
  health_status?: string
  last_check_at?: number | null
  timeout?: number
  extra_headers?: Record<string, any> | null
}

export interface ModelConfig {
  id: number
  provider_id: number
  purpose: string
  model_name: string
  display_name: string
  embedding_dim?: number
  is_default: boolean
  priority: number
  status: string
}

export interface Conversation {
  id: number
  title: string
  kb_ids?: number[]
  model_config_id?: number | null
  message_count: number
  created_at: string
  summary?: string | null
}

export interface UsageTotals {
  calls: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cached_tokens: number
}

export interface Attachment {
  type: 'image' | 'document' | 'video'
  file_key: string
  name: string
  mime?: string
  size?: number
  url: string
  doc_id?: number
}
export interface ArtifactRef {
  artifact_id: number
  file_key: string
  name: string
  mime?: string
  size?: number
  url?: string
}

export interface Message {
  id: number
  conversation_id: number
  role: string
  content: string
  citations?: Citation[]
  attachments?: Attachment[]
  artifacts?: ArtifactRef[]
  usage?: Record<string, number>
  model?: string
  feedback?: number | null
  created_at: number
}

// ---- Auth ----
export const authApi = {
  login: (username: string, password: string) =>
    http.post('/auth/login', { username, password }).then((r) => r.data),
  me: () => http.get<User>('/auth/me').then((r) => r.data),
  updateProfile: (data: { display_name?: string; email?: string; avatar?: string }) =>
    http.patch<User>('/auth/profile', data).then((r) => r.data),
  register: (data: { username: string; password: string; display_name?: string; email?: string; department_id?: number; reason?: string }) =>
    http.post<{ message: string; pending: boolean }>('/auth/register', data).then((r) => r.data),
  registerDepartments: () =>
    http.get<{ id: number; name: string; parent_id: number | null; depth: number }[]>(
      '/auth/register/departments').then((r) => r.data),
  changePassword: (oldPassword: string, newPassword: string) =>
    http.post('/auth/password', { old_password: oldPassword, new_password: newPassword }).then((r) => r.data),
}

// ---- KB ----
export const kbApi = {
  list: () => http.get<KB[]>('/kbs').then((r) => r.data),
  create: (data: Partial<KB>) => http.post<KB>('/kbs', data).then((r) => r.data),
  get: (id: number) => http.get<KB>(`/kbs/${id}`).then((r) => r.data),
  update: (id: number, data: Partial<KB>) => http.patch<KB>(`/kbs/${id}`, data).then((r) => r.data),
  remove: (id: number) => http.delete(`/kbs/${id}`).then((r) => r.data),
  stats: (id: number) => http.get<KBStats>(`/kbs/${id}/stats`).then((r) => r.data),
  addMember: (id: number, principalType: string, principalId: number, perm: string) =>
    http.post(`/kbs/${id}/members`, { principal_type: principalType, principal_id: principalId, perm_level: perm }).then((r) => r.data),
  members: (id: number) =>
    http.get<KBMember[]>(`/kbs/${id}/members`).then((r) => r.data),
  removeMember: (id: number, memberId: number) =>
    http.delete(`/kbs/${id}/members/${memberId}`).then((r) => r.data),
  testConnectorConfig: (connector_kind: string, connector_config: Record<string, any>, query = '测试', top_k = 3) =>
    http.post<{ ok: boolean; count: number; items: any[] }>('/kbs/connector/test',
      { connector_kind, connector_config, query, top_k }).then((r) => r.data),
  getConnector: (id: number) => http.get<ConnectorInfo>(`/kbs/${id}/connector`).then((r) => r.data),
  testConnector: (id: number, query = '测试', top_k = 3) =>
    http.post<{ ok: boolean; count: number; items: any[] }>(`/kbs/${id}/connector/test`, { query, top_k }).then((r) => r.data),
  syncStatus: (id: number) =>
    http.get<{ enabled: boolean; last_at: number | null; last_status: string | null; last_count: number | null;
               last_error: string | null; seed_queries: string[]; limit: number; synced_doc_count: number }>(
      `/kbs/${id}/sync/status`).then((r) => r.data),
  sync: (id: number, limit = 500) =>
    http.post<{ kb_id: number; fetched: number; created: number; skipped: number; document_ids: number[] }>(
      `/kbs/${id}/sync`, { limit }).then((r) => r.data),
  syncConfig: (id: number, data: { enabled?: boolean; seed_queries?: string[]; limit?: number }) =>
    http.put(`/kbs/${id}/sync/config`, data).then((r) => r.data),
  audit: (id: number, staleDays = 180) =>
    http.get<{ total: number; counts: Record<string, number>; empty: any[]; failed: any[];
               no_chunk: any[]; untagged: any[]; stale: any[] }>(
      `/kbs/${id}/audit`, { params: { stale_days: staleDays } }).then((r) => r.data),
  missedQueries: (days = 30, limit = 20) =>
    http.get<{ query: string; count: number }[]>('/retrieval/missed-queries', { params: { days, limit } }).then((r) => r.data),
}

// ---- Document ----
export const docApi = {
  list: (kbId: number) => http.get<Doc[]>('/documents', { params: { kb_id: kbId } }).then((r) => r.data),
  get: (id: number) => http.get<Doc>(`/documents/${id}`).then((r) => r.data),
  upload: (kbId: number, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return http.post<Doc>(`/documents/upload?kb_id=${kbId}`, fd).then((r) => r.data)
  },
  createEntry: (kbId: number, title: string, content: string, files: File[]) => {
    const fd = new FormData()
    fd.append('title', title)
    fd.append('content', content)
    files.forEach((f) => fd.append('files', f))
    return http.post<Doc>(`/documents/kbs/${kbId}/entries`, fd).then((r) => r.data)
  },
  updateEntry: (id: number, data: { title?: string; content?: string }) =>
    http.patch<Doc>(`/documents/${id}/entry`, data).then((r) => r.data),
  addEntryAttachments: (id: number, files: File[]) => {
    const fd = new FormData()
    files.forEach((f) => fd.append('files', f))
    return http.post<Doc>(`/documents/${id}/attachments`, fd).then((r) => r.data)
  },
  removeEntryAttachment: (id: number, idx: number) =>
    http.delete(`/documents/${id}/attachments/${idx}`).then((r) => r.data),
  entryAttachmentUrl: (docId: number, idx: number) => `/api/v1/documents/${docId}/attachments/${idx}/download`,
  remove: (id: number) => http.delete(`/documents/${id}`).then((r) => r.data),
  reprocess: (id: number) => http.post<Doc>(`/documents/${id}/reprocess`).then((r) => r.data),
  rawUrl: (id: number) => `/api/v1/documents/${id}/raw`,
  content: (id: number) =>
    http.get<{ id: number; title: string; content: string; source: string; page_count: number }>(`/documents/${id}/content`).then((r) => r.data),
  chunks: (id: number, page = 1, pageSize = 50) =>
    http.get<{ total: number; items: any[] }>(`/documents/${id}/chunks`, { params: { page, page_size: pageSize } }).then((r) => r.data),
  updateChunk: (docId: number, chunkId: number, content: string) =>
    http.put(`/documents/${docId}/chunks/${chunkId}`, { content }).then((r) => r.data),
  deleteChunk: (docId: number, chunkId: number) =>
    http.delete(`/documents/${docId}/chunks/${chunkId}`).then((r) => r.data),
  splitChunk: (docId: number, chunkId: number, offset: number) =>
    http.post(`/documents/${docId}/chunks/${chunkId}/split`, { offset }).then((r) => r.data),
  batchDelete: (ids: number[]) => http.post('/documents/batch-delete', { ids }).then((r) => r.data),
  batchMove: (ids: number[], folderId: number | null) =>
    http.post('/documents/batch-move', { ids, folder_id: folderId }).then((r) => r.data),
  batchVisibility: (ids: number[], visibility: string) =>
    http.post('/documents/batch-visibility', { ids, visibility }).then((r) => r.data),
  batchReprocess: (ids: number[]) => http.post('/documents/batch-reprocess', { ids }).then((r) => r.data),
  mergeExportUrl: (fmt: 'docx' | 'pdf' | 'md' | 'txt' = 'docx') =>
    `${API_BASE}/documents/batch-merge-export?fmt=${fmt}`,
  setTags: (id: number, tags: string[]) => http.put<Doc>(`/documents/${id}/tags`, { tags }).then((r) => r.data),
  setVisibility: (id: number, visibility: string) =>
    http.patch<Doc>(`/documents/${id}/visibility`, { visibility }).then((r) => r.data),
  acl: (id: number) =>
    http.get<{ visibility: string; items: { id: number; principal_id: number; effect: string; principal_name?: string | null }[] }>(
      `/documents/${id}/acl`).then((r) => r.data),
  addAcl: (id: number, data: { principal_type: string; principal_id: number; effect: string }) =>
    http.post(`/documents/${id}/acl`, data).then((r) => r.data),
  removeAcl: (id: number, aclId: number) =>
    http.delete(`/documents/${id}/acl/${aclId}`).then((r) => r.data),
  listVersions: (docId: number) =>
    http.get<{ id: number; version: number; title: string | null; char_count: number; chunk_count: number; reason: string; created_at: string | null; current: boolean }[]>(
      `/documents/${docId}/versions`).then((r) => r.data),
  getVersion: (docId: number, version: number) =>
    http.get<{ id: number; version: number; title: string | null; content: string | null; char_count: number; chunk_count: number; chunk_snapshot: any[] | null; reason: string; created_at: string | null }>(
      `/documents/${docId}/versions/${version}`).then((r) => r.data),
  rollbackVersion: (docId: number, version: number) =>
    http.post<Doc>(`/documents/${docId}/versions/${version}/rollback`).then((r) => r.data),
  listFolders: (kbId: number) =>
    http.get<{ id: number; name: string; parent_id: number | null; sort?: number }[]>('/documents/folders/list', { params: { kb_id: kbId } }).then((r) => r.data),
  createFolder: (kbId: number, name: string, parentId?: number, sort?: number) =>
    http.post('/documents/folders', { name, parent_id: parentId, sort }, { params: { kb_id: kbId } }).then((r) => r.data),
  updateFolder: (folderId: number, data: { name?: string; sort?: number; parent_id?: number | null }) =>
    http.patch(`/documents/folders/${folderId}`, data).then((r) => r.data),
  reorderFolders: (kbId: number, orderedIds: number[]) =>
    http.put('/documents/folders/order', { ordered_ids: orderedIds }, { params: { kb_id: kbId } }).then((r) => r.data),
  removeFolder: (folderId: number) => http.delete(`/documents/folders/${folderId}`).then((r) => r.data),
  moveDoc: (docId: number, folderId: number | null) =>
    http.patch(`/documents/${docId}/folder`, { folder_id: folderId }).then((r) => r.data),
}

// ---- Retrieval ----
export const retrievalApi = {
  query: (query: string, kbIds: number[], opts: { topK?: number; useHybrid?: boolean; scoreThreshold?: number } = {}) =>
    http
      .post('/retrieval/query', {
        query,
        kb_ids: kbIds,
        top_k: opts.topK ?? 5,
        use_hybrid: opts.useHybrid ?? true,
        score_threshold: opts.scoreThreshold ?? 0,
      })
      .then((r) => r.data as { query: string; chunks: RetrievedChunk[]; timing_ms: number }),
}

// ---- Provider ----
export const providerApi = {
  list: () => http.get<Provider[]>('/providers').then((r) => r.data),
  create: (data: Partial<Provider> & { kind: string; base_url: string }) =>
    http.post<Provider>('/providers', data).then((r) => r.data),
  update: (id: number, data: Partial<Provider>) =>
    http.patch<Provider>(`/providers/${id}`, data).then((r) => r.data),
  remove: (id: number) => http.delete(`/providers/${id}`).then((r) => r.data),
  test: (id: number, purpose: string, modelName?: string) =>
    http.post(`/providers/${id}/test`, { purpose, model_name: modelName }).then((r) => r.data),
  health: (id: number, purpose = 'chat') =>
    http.post<{ ok: boolean; message: string; latency_ms: number; health_status: string; last_check_at: number }>(
      `/providers/${id}/health`, null, { params: { purpose } }).then((r) => r.data),
  listModels: (id: number) =>
    http.get<{ ok: boolean; models: { id: string; owned_by?: string }[]; message?: string }>(
      `/providers/${id}/models`,
    ).then((r) => r.data),
  configs: () => http.get<ModelConfig[]>('/providers/configs/all').then((r) => r.data),
  createConfig: (data: Partial<ModelConfig>) =>
    http.post<ModelConfig>('/providers/configs', data).then((r) => r.data),
  updateConfig: (id: number, data: Partial<ModelConfig>) =>
    http.patch<ModelConfig>(`/providers/configs/${id}`, data).then((r) => r.data),
  removeConfig: (id: number) => http.delete(`/providers/configs/${id}`).then((r) => r.data),
}

// ---- Chat ----
export const chatApi = {
  conversations: () => http.get<Conversation[]>('/chat/conversations').then((r) => r.data),
  createConversation: (kbIds: number[], title?: string) =>
    http.post<Conversation>('/chat/conversations', { kb_ids: kbIds, title }).then((r) => r.data),
  messages: (convId: number) => http.get<Message[]>(`/chat/conversations/${convId}/messages`).then((r) => r.data),
  rename: (convId: number, title: string) =>
    http.patch(`/chat/conversations/${convId}`, { title }).then((r) => r.data),
  setModel: (convId: number, modelConfigId: number | null) =>
    http.patch(`/chat/conversations/${convId}`, { model_config_id: modelConfigId }).then((r) => r.data),
  remove: (convId: number) => http.delete(`/chat/conversations/${convId}`).then((r) => r.data),
  usage: (convId: number) => http.get<UsageTotals>(`/chat/conversations/${convId}/usage`).then((r) => r.data),
  adminConversations: (userId?: number) =>
    http.get<(Conversation & { owner_id: number; owner_name: string })[]>('/chat/admin/conversations', { params: { user_id: userId } }).then((r) => r.data),
  adminChatUsers: () =>
    http.get<{ user_id: number; name: string; conversation_count: number }[]>('/chat/admin/users').then((r) => r.data),
  uploadAttachment: (file: File, opts: { kind?: string; kbId?: number } = {}) => {
    const fd = new FormData()
    fd.append('file', file)
    const q = new URLSearchParams()
    if (opts.kind) q.set('kind', opts.kind)
    if (opts.kbId) q.set('kb_id', String(opts.kbId))
    return http.post<Attachment>(`/chat/attachments?${q.toString()}`, fd).then((r) => r.data)
  },
  feedback: (messageId: number, feedback: number) =>
    http.patch(`/chat/messages/${messageId}/feedback`, { feedback }).then((r) => r.data),
  regenerateUrl: (convId: number) => `${API_BASE}/chat/conversations/${convId}/regenerate`,
  signAttachment: (fileKey: string) =>
    http.post<{ url: string; expires_in: number }>(`/chat/attachments/${fileKey}/sign`).then((r) => r.data),
  signAttachmentsBatch: (fileKeys: string[]) =>
    http.post<{ urls: Record<string, string>; expires_in: number }>('/chat/attachments/sign', { file_keys: fileKeys }).then((r) => r.data),
  exportUrl: (convId: number, fmt: 'md' | 'pdf' | 'docx' = 'md') =>
    `${API_BASE}/chat/conversations/${convId}/export?fmt=${fmt}`,
  share: (convId: number) =>
    http.post<{ url: string; download_url: string; expires_in: number }>(`/chat/conversations/${convId}/share`).then((r) => r.data),
}

// SSE 流式对话
export interface ToolCallEvt {
  id: string
  name: string
  arguments: string
  turn?: number
}
export interface ToolResultEvt {
  id: string
  name: string
  content: string
  is_error: boolean
  data?: any
  turn?: number
}
export interface PendingActionEvt {
  action_id: number
  tool_name: string
  arguments: any
  summary: string
  expires_at?: number
}
export interface StreamHandlers {
  onMeta?: (data: { conversation_id: number }) => void
  onDelta?: (text: string) => void
  onCitations?: (citations: Citation[]) => void
  onUsage?: (usage: Record<string, number>, latency: number) => void
  onDone?: (messageId: number) => void
  onError?: (msg: string) => void
  onCitationCheck?: (evt: { warning: string; has_fake_cite: boolean }) => void
  onReasoning?: (text: string) => void
  onToolCall?: (evt: ToolCallEvt) => void
  onToolResult?: (evt: ToolResultEvt) => void
  onPendingAction?: (evt: PendingActionEvt) => void
  onActionResolved?: (evt: { action_id: number; decision: string; ok: boolean; error?: string }) => void
}

export async function streamChat(
  body: {
    conversation_id?: number
    kb_ids: number[]
    message: string
    top_k?: number
    model_config_id?: number
    mode_id?: number
    temperature?: number
    attachments?: any[]
  },
  handlers: StreamHandlers,
  signal?: AbortSignal,
  url?: string,
) {
  const token = localStorage.getItem('access_token')
  const resp = await fetch(url || `${API_BASE}/chat/completions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ ...body, stream: true }),
    signal,
  })
  if (!resp.body) throw new Error('无响应流')
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let event = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''
    for (const line of lines) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) {
        const raw = line.slice(5).trim()
        if (!raw) continue
        let data: any
        try {
          data = JSON.parse(raw)
        } catch {
          continue
        }
        if (event === 'meta') handlers.onMeta?.(data)
        else if (event === 'delta') handlers.onDelta?.(data.text || '')
        else if (event === 'reasoning') handlers.onReasoning?.(data.text || '')
        else if (event === 'citations') handlers.onCitations?.(data.citations || [])
        else if (event === 'usage') handlers.onUsage?.(data.usage || {}, data.latency_ms || 0)
        else if (event === 'done') handlers.onDone?.(data.message_id)
        else if (event === 'error') handlers.onError?.(data.message)
        else if (event === 'tool_call') handlers.onToolCall?.(data)
        else if (event === 'tool_result') handlers.onToolResult?.(data)
        else if (event === 'citation_check') handlers.onCitationCheck?.(data)
        else if (event === 'pending_action') handlers.onPendingAction?.(data)
        else if (event === 'action_resolved') handlers.onActionResolved?.(data)
      }
    }
  }
}

// ---- 企业聊天室 ----
export interface ChatRoomBrief {
  id: number; name: string; kind: 'group' | 'direct'; is_default: boolean
  announcement?: string | null; owner_id: number; my_role: string
  peer_user_id?: number | null; last_message_at?: number | null
  last_preview?: string; message_count?: number; unread?: number
}
export interface ChatMsgItem {
  id: number; room_id: number; sender_id: number | null; sender_type: 'user' | 'agent' | 'system'
  sender_name: string; sender_is_agent?: boolean; content: string; content_type?: string
  attachments?: any[] | null; mentions?: number[] | null; reply_to_id?: number | null
  pinned: boolean; revoked: boolean; revoked_by?: number | null; created_at: number
}
export const chatRoomApi = {
  list: () => http.get<ChatRoomBrief[]>('/chat/rooms').then((r) => r.data),
  create: (data: { name: string; announcement?: string; member_ids?: number[] }) =>
    http.post('/chat/rooms', data).then((r) => r.data),
  direct: (userId: number) => http.post<{ id: number; kind: string }>('/chat/rooms/direct', { user_id: userId }).then((r) => r.data),
  detail: (roomId: number) => http.get<{
    id: number; name: string; kind: string; is_default: boolean; announcement?: string | null
    owner_id: number; my_role: string; peer_user_id?: number | null
    members: { id: number; user_id: number | null; agent_id?: number | null; role: string; name: string; username?: string | null; is_admin?: boolean; is_agent?: boolean; muted_until?: number | null }[]
    bots: { member_id: number; agent_id: number; name: string }[]
    announcements?: { id: number; content: string; pinned: boolean; created_by?: number | null; created_by_name?: string; created_at?: number | null }[]
    pinned: ChatMsgItem[]
  }>(`/chat/rooms/${roomId}`).then((r) => r.data),
  messages: (roomId: number, beforeId?: number, limit = 30) =>
    http.get<{ items: ChatMsgItem[]; has_more: boolean }>(`/chat/rooms/${roomId}/messages`,
      { params: { before_id: beforeId, limit } }).then((r) => r.data),
  send: (roomId: number, data: { content?: string; attachments?: any[]; mentions?: number[]; reply_to_id?: number | null }) =>
    http.post<ChatMsgItem>(`/chat/rooms/${roomId}/messages`, data).then((r) => r.data),
  revoke: (roomId: number, msgId: number) =>
    http.post(`/chat/rooms/${roomId}/messages/${msgId}/revoke`).then((r) => r.data),
  pin: (roomId: number, msgId: number, pinned = true) =>
    http.post(`/chat/rooms/${roomId}/messages/${msgId}/pin`, { pinned }).then((r) => r.data),
  read: (roomId: number) => http.post(`/chat/rooms/${roomId}/read`).then((r) => r.data),
  addMembers: (roomId: number, userIds: number[]) =>
    http.post(`/chat/rooms/${roomId}/members`, { user_ids: userIds }).then((r) => r.data),
  setRole: (roomId: number, userId: number, role: string) =>
    http.post(`/chat/rooms/${roomId}/members/${userId}/role`, { role }).then((r) => r.data),
  removeMember: (roomId: number, userId: number) =>
    http.delete(`/chat/rooms/${roomId}/members/${userId}`).then((r) => r.data),
  mute: (roomId: number, userId: number, minutes: number) =>
    http.post(`/chat/rooms/${roomId}/members/${userId}/mute`, { minutes }).then((r) => r.data),
  setAnnouncement: (roomId: number, announcement: string, pinned = false) =>
    http.post(`/chat/rooms/${roomId}/announcement`, { announcement, pinned }).then((r) => r.data),
  announcements: (roomId: number) =>
    http.get(`/chat/rooms/${roomId}/announcements`).then((r) => r.data),
  updateAnnouncement: (roomId: number, annId: number, data: { content?: string; pinned?: boolean }) =>
    http.patch(`/chat/rooms/${roomId}/announcements/${annId}`, data).then((r) => r.data),
  deleteAnnouncement: (roomId: number, annId: number) =>
    http.delete(`/chat/rooms/${roomId}/announcements/${annId}`).then((r) => r.data),
  setBotRole: (roomId: number, agentId: number, role: string) =>
    http.post(`/chat/rooms/${roomId}/bots/${agentId}/role`, { role }).then((r) => r.data),
  updateRoom: (roomId: number, data: { name?: string; avatar?: string; announcement?: string }) =>
    http.patch(`/chat/rooms/${roomId}`, data).then((r) => r.data),
  transferOwner: (roomId: number, userId: number) =>
    http.post(`/chat/rooms/${roomId}/transfer`, { user_id: userId }).then((r) => r.data),
  leaveRoom: (roomId: number) => http.post(`/chat/rooms/${roomId}/leave`).then((r) => r.data),
  clearMessages: (roomId: number) => http.post(`/chat/rooms/${roomId}/clear`).then((r) => r.data),
  dissolveRoom: (roomId: number) => http.post(`/chat/rooms/${roomId}/dissolve`).then((r) => r.data),
  files: (roomId: number, kind?: string) =>
    http.get(`/chat/rooms/${roomId}/files`, { params: kind ? { kind } : {} }).then((r) => r.data),
  addBot: (roomId: number, agentId: number) =>
    http.post(`/chat/rooms/${roomId}/bots`, { agent_id: agentId }).then((r) => r.data),
  removeBot: (roomId: number, agentId: number) =>
    http.delete(`/chat/rooms/${roomId}/bots/${agentId}`).then((r) => r.data),
  wsUrl: () => {
    const token = localStorage.getItem('access_token') || ''
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    return `${proto}://${location.host}/api/v1/chat/rooms/ws?token=${encodeURIComponent(token)}`
  },
}

// ---- RBAC ----
export interface Role {
  id: number
  code: string
  name: string
  scope: string
  is_system: boolean
  description?: string
  permission_count?: number
  user_count?: number
}
export interface PermissionItem {
  id: number
  code: string
  name: string
  resource: string
  action: string
}
export interface UserListItem {
  id: number
  username: string
  display_name: string
  email?: string
  status: string
  approval_status?: 'pending' | 'approved' | 'rejected'
  is_admin: boolean
  department_id?: number
  created_at: string
}
export interface UserRoleItem {
  id: number
  user_id: number
  role_id: number
  role_code?: string
  role_name?: string
  scope_type: string
  scope_id: number
  expires_at?: string
}
export interface DeptNode {
  id: number
  name: string
  parent_id?: number
  code?: string
  path: string
  depth: number
  sort: number
  member_count?: number
  children: DeptNode[]
}

export const rbacApi = {
  // 角色
  roles: () => http.get<Role[]>('/admin/roles').then((r) => r.data),
  createRole: (data: Partial<Role>) => http.post<Role>('/admin/roles', data).then((r) => r.data),
  updateRole: (id: number, data: Partial<Role>) =>
    http.patch<Role>(`/admin/roles/${id}`, data).then((r) => r.data),
  removeRole: (id: number) => http.delete(`/admin/roles/${id}`).then((r) => r.data),
  permissions: () => http.get<PermissionItem[]>('/admin/permissions').then((r) => r.data),
  rolePermissions: (id: number) => http.get<number[]>(`/admin/roles/${id}/permissions`).then((r) => r.data),
  setRolePermissions: (id: number, permissionIds: number[]) =>
    http.put(`/admin/roles/${id}/permissions`, { permission_ids: permissionIds }).then((r) => r.data),
  // 用户
  users: (page = 1, pageSize = 20, search?: string, status?: string) =>
    http
      .get('/admin/users', { params: { page, page_size: pageSize, search, status } })
      .then((r) => r.data as { items: UserListItem[]; total: number }),
  pendingUsers: () =>
    http.get<{ id: number; username: string; display_name: string; email: string | null; reason: string | null; registered_at: string | null }[]>(
      '/admin/users/pending').then((r) => r.data),
  approveUser: (id: number) => http.post(`/admin/users/${id}/approve`).then((r) => r.data),
  rejectUser: (id: number) => http.post(`/admin/users/${id}/reject`).then((r) => r.data),
  createUser: (data: Record<string, any>) =>
    http.post<UserListItem>('/admin/users', data).then((r) => r.data),
  updateUser: (id: number, data: Record<string, any>) =>
    http.patch<UserListItem>(`/admin/users/${id}`, data).then((r) => r.data),
  removeUser: (id: number) => http.delete(`/admin/users/${id}`).then((r) => r.data),
  resetUserPassword: (id: number, password: string) =>
    http.patch<UserListItem>(`/admin/users/${id}`, { password }).then((r) => r.data),
  userRoles: (id: number) => http.get<UserRoleItem[]>(`/admin/users/${id}/roles`).then((r) => r.data),
  grantRole: (id: number, data: Record<string, any>) =>
    http.post<UserRoleItem>(`/admin/users/${id}/roles`, data).then((r) => r.data),
  revokeRole: (userId: number, urId: number) =>
    http.delete(`/admin/users/${userId}/roles/${urId}`).then((r) => r.data),
  // 部门
  deptTree: () => http.get<DeptNode[]>('/admin/departments/tree').then((r) => r.data),
  createDept: (data: Record<string, any>) =>
    http.post('/admin/departments', data).then((r) => r.data),
  updateDept: (id: number, data: Record<string, any>) =>
    http.patch(`/admin/departments/${id}`, data).then((r) => r.data),
  removeDept: (id: number) => http.delete(`/admin/departments/${id}`).then((r) => r.data),
  // 用户组
  groups: () => http.get('/admin/groups').then((r) => r.data),
  createGroup: (data: Record<string, any>) => http.post('/admin/groups', data).then((r) => r.data),
  updateGroup: (id: number, data: Record<string, any>) =>
    http.patch(`/admin/groups/${id}`, data).then((r) => r.data),
  removeGroup: (id: number) => http.delete(`/admin/groups/${id}`).then((r) => r.data),
  groupMembers: (id: number) => http.get<number[]>(`/admin/groups/${id}/members`).then((r) => r.data),
  setGroupMembers: (id: number, userIds: number[]) =>
    http.put(`/admin/groups/${id}/members`, { user_ids: userIds }).then((r) => r.data),
}

// ---- Agent 平台 ----
export interface Agent {
  id: number
  name: string
  slug: string
  description?: string
  icon?: string
  type: string
  system_prompt: string
  model_config_id?: number
  kb_ids?: number[]
  skill_ids?: number[]
  tool_config?: Record<string, any>
  config?: Record<string, any>
  default_mode_id?: number
  status: string
  visibility: string
  owner_id?: number
  created_at: string
}
export interface AgentMode {
  id: number
  agent_id: number
  name: string
  description?: string
  system_prompt: string
  skill_ids?: number[]
  tool_config?: Record<string, any>
  kb_ids?: number[]
  params?: Record<string, any>
  is_default: boolean
  sort: number
}
export interface Skill {
  id: number
  name: string
  slug: string
  description?: string
  icon?: string
  kind: string
  prompt_template?: string
  params_schema?: Record<string, any>
  tool_ids?: number[]
  kb_ids?: number[]
  model_config_id?: number
  tool_def?: Record<string, any>
  source?: string
  body_md?: string
  package_id?: number
  parent_id?: number | null
  collection_subpath?: string | null
  status: string
}
export interface ToolItem {
  id: number
  name: string
  display_name: string
  description: string
  kind: string
  parameters?: Record<string, any>
  source?: Record<string, any>
  enabled: boolean
  status: string
  builtin: boolean
}

export const agentApi = {
  list: () => http.get<Agent[]>('/agents').then((r) => r.data),
  get: (id: number) => http.get<Agent>(`/agents/${id}`).then((r) => r.data),
  create: (data: Partial<Agent>) => http.post<Agent>('/agents', data).then((r) => r.data),
  update: (id: number, data: Partial<Agent>) => http.patch<Agent>(`/agents/${id}`, data).then((r) => r.data),
  remove: (id: number) => http.delete(`/agents/${id}`).then((r) => r.data),
  publish: (id: number) => http.post<Agent>(`/agents/${id}/publish`).then((r) => r.data),
  clone: (id: number) => http.post<Agent>(`/agents/${id}/clone`).then((r) => r.data),
  versions: (id: number) => http.get<{ id: number; version: number; note?: string; created_at: string }[]>(`/agents/${id}/versions`).then((r) => r.data),
  snapshot: (id: number, note?: string) => http.post(`/agents/${id}/versions`, { note }).then((r) => r.data),
  rollback: (id: number, versionId: number) => http.post<Agent>(`/agents/${id}/versions/${versionId}/rollback`).then((r) => r.data),
  modes: (id: number) => http.get<AgentMode[]>(`/agents/${id}/modes`).then((r) => r.data),
  createMode: (id: number, data: Partial<AgentMode>) =>    http.post<AgentMode>(`/agents/${id}/modes`, data).then((r) => r.data),
  updateMode: (id: number, modeId: number, data: Partial<AgentMode>) =>
    http.patch<AgentMode>(`/agents/${id}/modes/${modeId}`, data).then((r) => r.data),
  removeMode: (id: number, modeId: number) =>
    http.delete(`/agents/${id}/modes/${modeId}`).then((r) => r.data),
  confirmToolUrl: (id: number) => `${API_BASE}/agents/${id}/tool-confirm`,
}

export interface SkillPackageInfo {
  id: number
  name: string
  source_type: string
  source_uri?: string
  version?: string
  files?: { path: string; size: number }[]
  entry_scripts?: { name: string; path: string; description?: string }[]
  scripts_enabled: boolean
  manifest?: Record<string, any>
}

export interface SkillImportResult {
  duplicate?: boolean
  multi_skill?: boolean
  collection?: boolean
  skill_id?: number
  package_id?: number
  name?: string
  files?: number
  count?: number
  children?: { id: number; name: string; subpath: string }[]
  sub_skills?: string[]
  existing_skill_id?: number
  existing_skill_name?: string
}

export const skillApi = {
  list: () => http.get<Skill[]>('/skills').then((r) => r.data),
  create: (data: Partial<Skill>) => http.post<Skill>('/skills', data).then((r) => r.data),
  update: (id: number, data: Partial<Skill>) => http.patch<Skill>(`/skills/${id}`, data).then((r) => r.data),
  remove: (id: number) => http.delete(`/skills/${id}`).then((r) => r.data),
  importUpload: (file: File, subpath?: string) => {
    const fd = new FormData()
    fd.append('file', file)
    const q = subpath ? `?subpath=${encodeURIComponent(subpath)}` : ''
    return http.post<SkillImportResult>(`/skills/import/upload${q}`, fd).then((r) => r.data)
  },
  importUrl: (url: string, subpath?: string) =>
    http.post<SkillImportResult>('/skills/import/url', { url, subpath }).then((r) => r.data),
  importCollection: (url: string) =>
    http.post<SkillImportResult>('/skills/import/collection', { url }).then((r) => r.data),
  importCollectionUpload: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return http.post<SkillImportResult>('/skills/import/collection/upload', fd).then((r) => r.data)
  },
  importMarkdown: (text: string, filename?: string) =>
    http.post<SkillImportResult>('/skills/import/markdown', { text, filename }).then((r) => r.data),
  parseMarkdown: (text: string) =>
    http.post<{
      name: string; description: string; has_frontmatter: boolean
      meta: Record<string, any>; body_preview: string
    }>('/skills/parse/markdown', { text }).then((r) => r.data),
  upgradeUpload: (skillId: number, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return http.post<{ skill_id: number; version?: string; files: number }>(
      `/skills/${skillId}/upgrade/upload`, fd,
    ).then((r) => r.data)
  },
  upgradeUrl: (skillId: number, url: string) =>
    http.post<{ skill_id: number; version?: string; files: number }>(
      `/skills/${skillId}/upgrade`, { url },
    ).then((r) => r.data),
  runScript: (skillId: number, script: string, args: Record<string, any>) =>
    http.post<{ ok: boolean; content: string; is_error: boolean }>(
      `/skills/${skillId}/scripts/run`, { script, args },
    ).then((r) => r.data),
  getPackage: (skillId: number) =>
    http.get<SkillPackageInfo>(`/skills/${skillId}/package`).then((r) => r.data),
  readPackageFile: (skillId: number, path: string) =>
    http
      .get<{ path: string; binary: boolean; size: number; content: string | null }>(
        `/skills/${skillId}/package/file`,
        { params: { path } },
      )
      .then((r) => r.data),
  writePackageFile: (skillId: number, path: string, content: string) =>
    http.put(`/skills/${skillId}/package/file`, { path, content }).then((r) => r.data),
  toggleScripts: (skillId: number, enabled: boolean) =>
    http.post(`/skills/${skillId}/package/scripts?enabled=${enabled}`).then((r) => r.data),
}

export const toolApi = {
  list: () => http.get<ToolItem[]>('/tools').then((r) => r.data),
  adminList: () => http.get<{ name: string; description: string; permission: string; kind: string }[]>('/tools/admin-list').then((r) => r.data),
  create: (data: Partial<ToolItem>) => http.post<ToolItem>('/tools', data).then((r) => r.data),
  remove: (id: number) => http.delete(`/tools/${id}`).then((r) => r.data),
  test: (id: number, args: Record<string, any>) =>
    http.post(`/tools/${id}/test`, { args }).then((r) => r.data),
}

// ---- MCP ----
export interface McpServerItem {
  id: number
  name: string
  transport: 'http' | 'sse' | 'stdio'
  url?: string
  command?: string
  args?: string[]
  env?: Record<string, string>
  headers?: Record<string, string>
  auth_token_set: boolean
  enabled: boolean
  status: string
  last_error?: string
  tools_count: number
  last_synced_at?: number
  timeout?: number
}

export interface McpToolItem {
  name: string
  description?: string
  inputSchema: Record<string, any>
}

export const mcpApi = {
  list: () => http.get<McpServerItem[]>('/mcp/servers').then((r) => r.data),
  create: (data: Record<string, any>) => http.post<McpServerItem>('/mcp/servers', data).then((r) => r.data),
  update: (id: number, data: Record<string, any>) =>
    http.patch<McpServerItem>(`/mcp/servers/${id}`, data).then((r) => r.data),
  remove: (id: number) => http.delete(`/mcp/servers/${id}`).then((r) => r.data),
  test: (id: number) => http.post(`/mcp/servers/${id}/test`).then((r) => r.data),
  sync: (id: number) => http.post(`/mcp/servers/${id}/sync`).then((r) => r.data),
  tools: (id: number) => http.get<McpToolItem[]>(`/mcp/servers/${id}/tools`).then((r) => r.data),
  call: (id: number, toolName: string, args: Record<string, any>) =>
    http.post(`/mcp/servers/${id}/tools/${toolName}/call`, { args }).then((r) => r.data),
}

// ---- Workflow ----
export interface WorkflowGraph {
  nodes: any[]
  edges: any[]
}
export interface WorkflowData {
  id: number
  graph: WorkflowGraph
  version: number
  status: string
}
export const workflowApi = {
  get: (agentId: number) => http.get<WorkflowData>(`/agents/${agentId}/workflow`).then((r) => r.data),
  save: (agentId: number, graph: WorkflowGraph) =>
    http.put(`/agents/${agentId}/workflow`, { graph }).then((r) => r.data),
  publish: (agentId: number) => http.post(`/agents/${agentId}/workflow/publish`).then((r) => r.data),
  run: (agentId: number, inputs: Record<string, any>) =>
    http.post(`/agents/${agentId}/workflow/run`, { inputs }).then((r) => r.data),
  getRun: (runId: number) => http.get(`/workflow-runs/${runId}`).then((r) => r.data),
  listRuns: (agentId: number, limit = 20) =>
    http.get<{ runs: any[] }>(`/agents/${agentId}/workflow/runs`, { params: { limit } }).then((r) => r.data),
  approveUrl: (runId: number) => `${API_BASE}/workflow-runs/${runId}/approve`,
  pendingApprovals: () =>
    http.get<{ run_id: number; agent_id: number; agent_name: string; pending_node_id?: string | null;
               input?: any; created_at?: string }[]>('/approvals/pending').then((r) => r.data),
}

// ---- 待办 / 日程 / 提醒 ----
export interface ReminderItem {
  id: number
  title: string
  content?: string | null
  due_at?: number | null
  status: string
  assignee_id?: number | null
  creator_id?: number | null
  source: string
  repeat_cron?: string | null
  remind_before_minutes: number
  notify_on_due: boolean
  notified_at?: number | null
  done_at?: number | null
  created_at?: string
}
export const reminderApi = {
  list: (params: { assignee_id?: number; status?: string } = {}) =>
    http.get<ReminderItem[]>('/reminders', { params }).then((r) => r.data),
  create: (data: Partial<ReminderItem>) => http.post<ReminderItem>('/reminders', data).then((r) => r.data),
  update: (id: number, data: Partial<ReminderItem>) =>
    http.patch<ReminderItem>(`/reminders/${id}`, data).then((r) => r.data),
  done: (id: number) => http.post<ReminderItem>(`/reminders/${id}/done`).then((r) => r.data),
  remove: (id: number) => http.delete(`/reminders/${id}`).then((r) => r.data),
}

// 工作流运行 SSE
export async function streamWorkflowRun(
  agentId: number,
  inputs: Record<string, any>,
  handlers: {
    onNodeStarted?: (d: any) => void
    onNodeFinished?: (d: any) => void
    onFinished?: (d: any) => void
    onApprovalRequired?: (d: any) => void
  },
) {
  const token = localStorage.getItem('access_token')
  const resp = await fetch(`${API_BASE}/agents/${agentId}/workflow/run`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ inputs }),
  })
  if (!resp.body) throw new Error('无响应流')
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let event = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''
    for (const line of lines) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) {
        const raw = line.slice(5).trim()
        if (!raw) continue
        let data: any
        try { data = JSON.parse(raw) } catch { continue }
        if (event === 'node_started') handlers.onNodeStarted?.(data)
        else if (event === 'node_finished') handlers.onNodeFinished?.(data)
        else if (event === 'approval_required') handlers.onApprovalRequired?.(data)
        else if (event === 'run_finished') handlers.onFinished?.(data)
      }
    }
  }
}

// ---- 审计日志 ----
export interface AuditLogItem {
  id: number
  actor_id?: number
  actor_type: string
  actor_name?: string
  action: string
  resource_type?: string
  resource_id?: string
  before?: Record<string, any>
  after?: Record<string, any>
  result: string
  error?: string
  ip?: string
  user_agent?: string
  request_id?: string
  created_at: number
}

export const auditApi = {
  list: (params: Record<string, any> = {}) =>
    http.get('/audit-logs', { params }).then((r) => r.data as { items: AuditLogItem[]; total: number }),
}

// ---- API Key ----
export interface ApiKeyItem {
  id: number
  name: string
  key_prefix: string
  user_id?: number
  scopes?: string[]
  kb_ids?: number[]
  rate_limit: number
  status: string
  expires_at?: string
  last_used_at?: string
}

export const apiKeyApi = {
  list: () => http.get<ApiKeyItem[]>('/api-keys').then((r) => r.data),
  create: (data: Record<string, any>) =>
    http.post<{ id: number; name: string; key: string; key_prefix: string }>('/api-keys', data).then((r) => r.data),
  revoke: (id: number) => http.delete(`/api-keys/${id}`).then((r) => r.data),
}

// ---- SSO ----
export interface SsoProvider {
  provider: string
  name: string
}
export interface SsoConfigItem {
  id?: number
  provider: string
  name: string
  enabled: boolean
  client_id?: string
  authorize_url?: string
  token_url?: string
  userinfo_url?: string
  corp_id?: string
  agent_id?: string
  redirect_uri?: string
}

export const ssoApi = {
  providers: () => http.get<SsoProvider[]>('/auth/sso/providers').then((r) => r.data),
  configs: () => http.get<SsoConfigItem[]>('/auth/sso/configs/all').then((r) => r.data),
  saveConfig: (data: Record<string, any>) => http.post('/auth/sso/configs', data).then((r) => r.data),
  loginUrl: (provider: string) => `${API_BASE}/auth/sso/${provider}/login`,
}

// ---- 用量统计 ----
export interface UsageSummary {
  total: { calls: number; prompt_tokens: number; completion_tokens: number; avg_latency_ms: number }
  by_model: { model_config_id: number; name: string; calls: number; prompt_tokens: number; completion_tokens: number }[]
  by_user: { user_id: number; name: string; calls: number; prompt_tokens: number; completion_tokens: number }[]
  by_day: { date: string; calls: number; total_tokens?: number }[]
}
export interface ToolStat {
  tool: string
  calls: number
  success: number
  failure: number
  success_rate: number | null
  avg_latency_ms: number | null
}
export interface ToolStats {
  total: number
  success: number
  failure: number
  success_rate: number | null
  by_tool: ToolStat[]
  by_day: { date: string; calls: number }[]
}

export const usageApi = {
  summary: (days = 30) => http.get<UsageSummary>('/usage/summary', { params: { days } }).then((r) => r.data),
  meToday: () => http.get<UsageTotals>('/usage/me/today').then((r) => r.data),
  tools: (days = 30) => http.get<ToolStats>('/usage/tools', { params: { days } }).then((r) => r.data),
}

// ---- RAG 问答质量评估 ----
export interface EvalDataset {
  id: number
  name: string
  description?: string | null
  kb_ids?: number[] | null
  question_count?: number | null
}
export interface EvalQuestion {
  id: number
  dataset_id: number
  question: string
  expected_answer?: string | null
  expected_doc_ids?: number[] | null
  sort?: number
}
export interface EvalRun {
  id: number
  dataset_id: number
  status: string
  progress: number
  total: number
  summary?: Record<string, any> | null
  error?: string | null
  started_at?: number | null
  finished_at?: number | null
}
export interface EvalResult {
  id: number
  question: string
  answer?: string | null
  hit_expected?: boolean | null
  faithfulness?: number | null
  relevance?: number | null
  comment?: string | null
  latency_ms?: number | null
  error?: string | null
}

export const evalApi = {
  datasets: () => http.get<EvalDataset[]>('/eval/datasets').then((r) => r.data),
  createDataset: (data: Partial<EvalDataset>) => http.post<EvalDataset>('/eval/datasets', data).then((r) => r.data),
  updateDataset: (id: number, data: Partial<EvalDataset>) => http.patch<EvalDataset>(`/eval/datasets/${id}`, data).then((r) => r.data),
  removeDataset: (id: number) => http.delete(`/eval/datasets/${id}`).then((r) => r.data),
  questions: (dsId: number) => http.get<EvalQuestion[]>(`/eval/datasets/${dsId}/questions`).then((r) => r.data),
  addQuestion: (dsId: number, data: Partial<EvalQuestion>) =>
    http.post<EvalQuestion>(`/eval/datasets/${dsId}/questions`, data).then((r) => r.data),
  updateQuestion: (qId: number, data: Partial<EvalQuestion>) =>
    http.patch<EvalQuestion>(`/eval/questions/${qId}`, data).then((r) => r.data),
  removeQuestion: (qId: number) => http.delete(`/eval/questions/${qId}`).then((r) => r.data),
  run: (dsId: number, top_k = 5) => http.post<EvalRun>(`/eval/datasets/${dsId}/run`, { top_k }).then((r) => r.data),
  getRun: (runId: number) => http.get<EvalRun>(`/eval/runs/${runId}`).then((r) => r.data),
  runResults: (runId: number) => http.get<EvalResult[]>(`/eval/runs/${runId}/results`).then((r) => r.data),
  exportUrl: (runId: number) => `/api/v1/eval/runs/${runId}/export`,
}

// ---- 内容安全 ----
export interface GuardStatus {
  enabled: boolean
  block_threshold: number
  flag_threshold: number
  wrap_context: boolean
  sensitive_word_count: number
  engine: string
}
export interface GuardDetectResult {
  risk_score: number
  risk_level: string
  action: string
  summary: string
  hits: { category: string; rule: string; snippet: string }[]
}
export const securityApi = {
  status: () => http.get<GuardStatus>('/security/status').then((r) => r.data),
  detect: (text: string) => http.post<GuardDetectResult>('/security/detect', { text }).then((r) => r.data),
}

// ---- 文件管理 ----
export interface FileItem {
  id: number
  file_name: string
  file_ext?: string
  mime?: string
  size: number
  source: 'generated' | 'upload'
  user_id: number
  user_name?: string
  conversation_id?: number
  created_at: string
  expires_at?: number | null
}
export const fileApi = {
  list: (params: { page?: number; page_size?: number; source?: string; q?: string; user_id?: number; sort?: string; order?: string } = {}) =>
    http.get<{ total: number; items: FileItem[] }>('/files', { params }).then((r) => r.data),
  remove: (id: number) => http.delete(`/files/${id}`).then((r) => r.data),
  downloadUrl: (id: number) => `${API_BASE}/files/${id}/download`,
  signUrl: (id: number) => http.get<{ url: string; download_url: string; expires_in: number }>(`/files/${id}/url`).then((r) => r.data),
  cleanup: () => http.post('/files/cleanup').then((r) => r.data),
}

// ---- 定时任务 ----
export interface ScheduleValue {
  schedule_kind: 'cron' | 'interval' | 'once'
  cron_expr?: string
  interval_seconds?: number
  run_at?: number
}
export interface ScheduledTask {
  id: number
  name: string
  agent_id: number
  target_type: 'prompt' | 'workflow'
  prompt?: string | null
  inputs?: Record<string, any> | null
  schedule_kind: string
  cron_expr?: string | null
  interval_seconds?: number | null
  run_at?: number | null
  trigger_kind?: 'schedule' | 'event'
  event_name?: string | null
  notify_on?: 'always' | 'success' | 'fail' | 'never'
  max_retries?: number
  retry_count?: number
  retry_interval_seconds?: number
  timeout_seconds?: number | null
  enabled: boolean
  depends_on_task_id?: number | null
  next_run_at?: number | null
  last_run_at?: number | null
  last_status?: string | null
  last_result?: string | null
  run_count: number
}
export const scheduledApi = {
  list: () => http.get<ScheduledTask[]>('/scheduled-tasks').then((r) => r.data),
  create: (data: any) => http.post<ScheduledTask>('/scheduled-tasks', data).then((r) => r.data),
  update: (id: number, data: any) => http.patch<ScheduledTask>(`/scheduled-tasks/${id}`, data).then((r) => r.data),
  remove: (id: number) => http.delete(`/scheduled-tasks/${id}`).then((r) => r.data),
  enable: (id: number, enabled: boolean) => http.post(`/scheduled-tasks/${id}/enable`, { enabled }).then((r) => r.data),
  runNow: (id: number) => http.post(`/scheduled-tasks/${id}/run-now`).then((r) => r.data),
  runs: (id: number, page = 1, pageSize = 20) =>
    http.get<{ total: number; items: any[] }>(`/scheduled-tasks/${id}/runs`, { params: { page, page_size: pageSize } }).then((r) => r.data),
  createWebhook: (id: number, name = '默认') =>
    http.post<{ id: number; token: string; webhook_url: string }>(`/scheduled-tasks/${id}/webhook-token`, { name }).then((r) => r.data),
  webhookTokens: (id: number) =>
    http.get<{ id: number; name: string; enabled: boolean }[]>(`/scheduled-tasks/${id}/webhook-tokens`).then((r) => r.data),
  removeWebhook: (tokenId: number) => http.delete(`/webhook-tokens/${tokenId}`).then((r) => r.data),
}

// ---- 事件订阅（出站 Webhook：外部系统订阅平台事件）----
export interface EventSubItem {
  id: number
  name: string
  url: string
  events?: string | null
  secret_set: boolean
  enabled: boolean
}
export const eventSubApi = {
  list: () => http.get<EventSubItem[]>('/event-subscriptions').then((r) => r.data),
  events: () => http.get<string[]>('/event-subscriptions/events').then((r) => r.data),
  create: (data: Record<string, any>) => http.post<EventSubItem>('/event-subscriptions', data).then((r) => r.data),
  update: (id: number, data: Record<string, any>) =>
    http.patch<EventSubItem>(`/event-subscriptions/${id}`, data).then((r) => r.data),
  remove: (id: number) => http.delete(`/event-subscriptions/${id}`).then((r) => r.data),
  test: (id: number) => http.post<{ ok: boolean; message: string }>(`/event-subscriptions/${id}/test`).then((r) => r.data),
}

// ---- 站内消息通知 ----
export interface NotificationItem {
  id: number
  kind: string
  title: string
  body?: string | null
  level: string
  link?: string | null
  read: boolean
  ref_type?: string | null
  ref_id?: number | null
  created_at: number
}

export const notificationApi = {
  list: (page = 1, pageSize = 20, unreadOnly = false) =>
    http.get<{ total: number; unread: number; items: NotificationItem[] }>('/notifications',
      { params: { page, page_size: pageSize, unread_only: unreadOnly } }).then((r) => r.data),
  unreadCount: () => http.get<{ unread: number }>('/notifications/unread-count').then((r) => r.data),
  markRead: (ids: number[]) => http.post('/notifications/read', { ids }).then((r) => r.data),
  markAllRead: () => http.post('/notifications/read-all').then((r) => r.data),
  remove: (id: number) => http.delete(`/notifications/${id}`).then((r) => r.data),
}

// ---- 外部 IM 渠道 ----
export interface ChannelItem {
  id: number
  kind: 'qqbot' | 'wxclaw' | 'wework' | 'feishu'
  name: string
  config: Record<string, any>
  enabled: boolean
  connected: boolean
  last_error?: string | null
  default_tenant_id?: number | null
  default_kb_ids: number[]
  kb_mode?: 'auto' | 'custom' | 'off'
  service_mode?: 'qa' | 'support'
  default_lang?: string | null
  default_agent_id?: number | null
  reply_mode: 'rag' | 'agent'
  command_prefix: string
  greeting?: string | null
  callback_url: string
}

export interface ChannelUserItem {
  id: number
  external_id: string
  display_name?: string | null
  user_id: number
  agent_id?: number | null
  created_at: string
  bound_user_id?: number | null
  bound_user_name?: string | null
  bind_code?: string | null
}

export const channelApi = {
  list: () => http.get<ChannelItem[]>('/channels').then((r) => r.data),
  create: (data: any) => http.post<ChannelItem>('/channels', data).then((r) => r.data),
  update: (id: number, data: any) => http.patch<ChannelItem>(`/channels/${id}`, data).then((r) => r.data),
  remove: (id: number) => http.delete(`/channels/${id}`).then((r) => r.data),
  test: (id: number) => http.post<{ ok: boolean; message: string; latency_ms: number }>(`/channels/${id}/test`).then((r) => r.data),
  users: (id: number) => http.get<ChannelUserItem[]>(`/channels/${id}/users`).then((r) => r.data),
  bindUser: (channelId: number, cuId: number, data: { user_id?: number; bind_code?: string }) =>
    http.post<{ message: string; bound_user_id: number }>(
      `/channels/${channelId}/users/${cuId}/bind`, data).then((r) => r.data),
  unbindUser: (channelId: number, cuId: number) =>
    http.delete<{ message: string }>(`/channels/${channelId}/users/${cuId}/bind`).then((r) => r.data),
  wxScanLogin: (id: number) =>
    http.post<{ ok: boolean; logged_in: boolean; qr: string; qr_display: string; ticket: string; status: string }>(
      `/channels/${id}/wxclaw/scan-login`).then((r) => r.data),
  wxLoginStatus: (id: number) =>
    http.get<{ logged_in: boolean; status: string; qr_display: string; ticket: string; message?: string }>(
      `/channels/${id}/wxclaw/login-status`).then((r) => r.data),
  // 无渠道依赖的扫码（新建渠道表单用）
  wxScan: () =>
    http.post<{ session: string; logged_in: boolean; qr: string; qr_display: string; ticket: string; status: string }>(
      `/channels/wxclaw/scan`).then((r) => r.data),
  wxScanStatus: (session: string) =>
    http.get<{ logged_in: boolean; status: string; token: string; bot_id?: string; qr_display: string; message?: string }>(
      `/channels/wxclaw/scan-status`, { params: { session } }).then((r) => r.data),
}

// ---- 系统运行日志 ----
export const systemApi = {
  logs: (params: { lines?: number; level?: string; keyword?: string } = {}) =>
    http.get<{ lines: string[]; path: string; total: number }>('/system/logs', { params }).then((r) => r.data),
  downloadUrl: () => `/api/v1/system/logs/download`,
  logStats: () => http.get<{ path: string; total_bytes: number; file_count: number; max_bytes: number; backup_count: number; retention_days: number; cleanup_interval_hours: number }>('/system/logs/stats').then((r) => r.data),
  clearLogs: () => http.post<{ message: string; removed: number; freed_bytes: number }>('/system/logs/clear').then((r) => r.data),
}

// ---- 系统设置 ----
export interface SettingField {
  key: string
  label: string
  group: string
  kind: 'bool' | 'int' | 'float' | 'str' | 'csv' | 'secret' | 'json'
  restart: boolean
  help?: string
  is_set?: boolean | null
  value: any
}

export const settingsApi = {
  get: () => http.get<{ groups: { key: string; label: string }[]; fields: SettingField[] }>('/system/settings').then((r) => r.data),
  update: (updates: Record<string, any>) =>
    http.put<{ message: string; restart_required: boolean; changed: string[] }>('/system/settings', { updates }).then((r) => r.data),
  restart: () => http.post<{ message: string }>('/system/settings/restart').then((r) => r.data),
}

// ---- 数据库与运维 ----
export interface SystemInfo {
  db_kind: string
  db_url_masked: string
  db_file?: string | null
  db_file_size: number
  driver_required: string[]
  driver_ok: boolean
  vector_backend: string
  task_backend: string
  data_dir: string
  data_dir_size: number
  files_dir_size: number
  uptime_seconds: number
  table_count: number
  python: string
  platform: string
  frozen: boolean
}
export interface DbTestResult {
  ok: boolean
  kind?: string
  message: string
  driver_missing?: string[]
}
export const systemOpsApi = {
  info: () => http.get<SystemInfo>('/system/info').then((r) => r.data),
  drivers: () => http.get<Record<string, { packages: string[]; ok: boolean }>>('/system/db/drivers').then((r) => r.data),
  testDb: (database_url: string) => http.post<DbTestResult>('/system/db/test', { database_url }).then((r) => r.data),
  installDriver: (target: string) =>
    http.post<{ ok: boolean; message: string; log: string; packages?: string[] }>('/system/db/install-driver', { target }).then((r) => r.data),
  initDb: (database_url: string) =>
    http.post<{ ok: boolean; message: string; table_count?: number }>('/system/db/init', { database_url }).then((r) => r.data),
  saveRestart: (database_url: string) =>
    http.post<{ ok: boolean; message: string }>('/system/db/save-restart', { database_url }).then((r) => r.data),
  migrate: () => http.post<{ ok: boolean; message: string }>('/system/db/migrate').then((r) => r.data),
  reset: () => http.post<{ ok: boolean; message: string }>('/system/db/reset').then((r) => r.data),
  backupUrl: () => '/api/v1/system/db/backup',
  listBackups: () =>
    http.get<{ name: string; size: number; created_at: number }[]>('/system/db/backups').then((r) => r.data),
  createBackup: () =>
    http.post<{ ok: boolean; name: string; size: number; message: string }>('/system/db/backups').then((r) => r.data),
  backupDownloadUrl: (name: string) => `/api/v1/system/db/backups/${encodeURIComponent(name)}/download`,
  deleteBackup: (name: string) =>
    http.delete<{ ok: boolean; message: string }>(`/system/db/backups/${encodeURIComponent(name)}`).then((r) => r.data),
  restore: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return http.post<{ ok: boolean; message: string }>('/system/db/restore', fd).then((r) => r.data)
  },
  seed: () => http.post<{ ok: boolean; message: string }>('/system/seed').then((r) => r.data),
  resetAdminPassword: (username: string, new_password: string) =>
    http.post<{ ok: boolean; message: string }>('/system/reset-admin-password', { username, new_password }).then((r) => r.data),
  cleanup: (scope = 'all') =>
    http.post<{ ok: boolean; message: string; removed: number; freed_bytes: number }>('/system/cleanup', { scope }).then((r) => r.data),
}

// ---- 通知渠道 ----
export interface NotifyChannelItem {
  id: number
  kind: 'inapp' | 'webhook' | 'wecom' | 'dingtalk' | 'smtp' | 'external'
  name: string
  config?: Record<string, any> | null
  enabled: boolean
  events?: string | null
}

export const notifyChannelApi = {
  list: () => http.get<NotifyChannelItem[]>('/notify-channels').then((r) => r.data),
  create: (data: Record<string, any>) => http.post<NotifyChannelItem>('/notify-channels', data).then((r) => r.data),
  update: (id: number, data: Record<string, any>) =>
    http.patch<NotifyChannelItem>(`/notify-channels/${id}`, data).then((r) => r.data),
  remove: (id: number) => http.delete(`/notify-channels/${id}`).then((r) => r.data),
  test: (id: number) => http.post<{ ok: boolean; message: string }>(`/notify-channels/${id}/test`).then((r) => r.data),
}

// ---- 邮件入库源 ----
export interface EmailSourceItem {
  id: number
  name: string
  imap_host: string
  imap_port: number
  use_ssl: boolean
  username: string
  password_set: boolean
  folder: string
  kb_id: number
  ingest_mode: 'both' | 'attach' | 'body'
  allow_from?: string | null
  subject_keywords?: string | null
  enabled: boolean
  status: string
  last_error?: string | null
  last_sync_at?: number | null
  ingested_count: number
}

export const emailSourceApi = {
  list: () => http.get<EmailSourceItem[]>('/email-sources').then((r) => r.data),
  create: (data: Record<string, any>) => http.post<EmailSourceItem>('/email-sources', data).then((r) => r.data),
  update: (id: number, data: Record<string, any>) =>
    http.patch<EmailSourceItem>(`/email-sources/${id}`, data).then((r) => r.data),
  remove: (id: number) => http.delete(`/email-sources/${id}`).then((r) => r.data),
  test: (id: number) => http.post<{ ok: boolean; message: string }>(`/email-sources/${id}/test`).then((r) => r.data),
  sync: (id: number) => http.post<{ ok: boolean; message: string; ingested: number }>(`/email-sources/${id}/sync`).then((r) => r.data),
}

// ---- 客服工单 ----
export interface ServiceTicketItem {
  id: number
  status: string
  priority: string
  subject: string
  category?: string | null
  tags?: string[] | null
  source?: string
  channel_id?: number | null
  channel_kind?: string | null
  external_user?: string | null
  conversation_id?: number | null
  assignee_id?: number | null
  messages?: { role: string; content: string; ts: number; agent_id?: number; attachments?: any[] }[] | null
  internal_notes?: { content: string; ts: number; agent_id?: number }[] | null
  last_message_at?: number | null
  closed_at?: number | null
  resolution?: string | null
  first_response_at?: number | null
  sla_due_at?: number | null
  sla_breached?: boolean
  satisfaction?: number | null
  customer_lang?: string | null
  watch?: boolean
}

export const serviceTicketApi = {
  list: (params: { status?: string; assignee_id?: number } = {}) =>
    http.get<ServiceTicketItem[]>('/service-tickets', { params }).then((r) => r.data),
  exportUrl: (status?: string) =>
    `${API_BASE}/service-tickets/export${status ? `?status=${encodeURIComponent(status)}` : ''}`,
  get: (id: number) => http.get<ServiceTicketItem>(`/service-tickets/${id}`).then((r) => r.data),
  create: (data: Record<string, any>) => http.post<ServiceTicketItem>('/service-tickets', data).then((r) => r.data),
  reply: (id: number, content: string) =>
    http.post<ServiceTicketItem>(`/service-tickets/${id}/reply`, { content }).then((r) => r.data),
  update: (id: number, data: Record<string, any>) =>
    http.patch<ServiceTicketItem>(`/service-tickets/${id}`, data).then((r) => r.data),
  addNote: (id: number, content: string) =>
    http.post<ServiceTicketItem>(`/service-tickets/${id}/notes`, { content }).then((r) => r.data),
  context: (id: number) =>
    http.get<{
      external_user: string | null; channel_kind: string | null
      ticket_total: number; ticket_open: number
      history: { id: number; subject: string; status: string; created_at: number }[]
      recent_messages: { role: string; content: string; ts: number }[]
    }>(`/service-tickets/${id}/context`).then((r) => r.data),
  channelConversations: (limit = 50) =>
    http.get<{
      id: number; title: string; channel: string; external_id: string | null
      message_count: number; last_message?: string; last_at?: number | null
      channel_user_id?: number | null; note?: string | null
    }[]>('/service-tickets/channel-conversations', { params: { limit } }).then((r) => r.data),
  setCustomerNote: (channelUserId: number, content: string) =>
    http.patch<{ ok: boolean; note: string | null }>(
      `/service-tickets/channel-customers/${channelUserId}/note`, { content }).then((r) => r.data),
  conversationMessages: (convId: number) =>
    http.get<{
      id: number; role: string; content: string
      attachments: any[]; artifacts: any[]; created_at: number; model?: string | null
    }[]>(`/service-tickets/conversations/${convId}/messages`).then((r) => r.data),
  replyInConversation: (convId: number, content: string) =>
    http.post<{ ok: boolean; sent_to_channel: boolean }>(
      `/service-tickets/conversations/${convId}/reply`, { content }).then((r) => r.data),
  conversationMeta: (convId: number) =>
    http.get<{ notes: { content: string; ts: number }[]; watch: boolean }>(
      `/service-tickets/conversations/${convId}/meta`).then((r) => r.data),
  addConversationNote: (convId: number, content: string) =>
    http.post<{ ok: boolean; notes: any[] }>(
      `/service-tickets/conversations/${convId}/notes`, { content }).then((r) => r.data),
  setConversationWatch: (convId: number, watch: boolean) =>
    http.patch<{ ok: boolean; watch: boolean }>(
      `/service-tickets/conversations/${convId}/watch`, null, { params: { watch } }).then((r) => r.data),
  sendConversationAttachment: (convId: number, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return http.post<{ ok: boolean; sent_to_channel: boolean; attachment: any }>(
      `/service-tickets/conversations/${convId}/attachment`, fd).then((r) => r.data)
  },
  // 批量操作 / 转派 / 标记已解决
  bulk: (ids: number[], action: string, value?: number | string | null) =>
    http.post<{ updated: number; skipped: number }>('/service-tickets/bulk', { ids, action, value }).then((r) => r.data),
  assign: (id: number, assignee_id: number | null) =>
    http.post<ServiceTicketItem>(`/service-tickets/${id}/assign`, { assignee_id }).then((r) => r.data),
  resolve: (id: number, content?: string) =>
    http.post<ServiceTicketItem>(`/service-tickets/${id}/resolve`, content ? { content } : null).then((r) => r.data),
  // 快捷回复（话术库）
  quickReplies: () => http.get<QuickReplyItem[]>('/service-tickets/quick-replies').then((r) => r.data),
  createQuickReply: (data: Partial<QuickReplyItem>) =>
    http.post<QuickReplyItem>('/service-tickets/quick-replies', data).then((r) => r.data),
  updateQuickReply: (id: number, data: Partial<QuickReplyItem>) =>
    http.patch<QuickReplyItem>(`/service-tickets/quick-replies/${id}`, data).then((r) => r.data),
  removeQuickReply: (id: number) => http.delete(`/service-tickets/quick-replies/${id}`).then((r) => r.data),
}

export interface QuickReplyItem {
  id: number
  title: string
  content: string
  category?: string | null
  scope: string
  enabled: boolean
  created_by?: number | null
}

// ---- 智能录单 ----
export interface RecordField {
  name: string
  label: string
  type?: string
  required?: boolean
  desc?: string
  options?: any[]
}

export interface RecordTemplateItem {
  id: number
  name: string
  description?: string | null
  fields?: RecordField[] | null
  instructions?: string | null
  enabled: boolean
}

export const recordApi = {
  listTemplates: () => http.get<RecordTemplateItem[]>('/record-templates').then((r) => r.data),
  createTemplate: (data: Record<string, any>) =>
    http.post<RecordTemplateItem>('/record-templates', data).then((r) => r.data),
  updateTemplate: (id: number, data: Record<string, any>) =>
    http.patch<RecordTemplateItem>(`/record-templates/${id}`, data).then((r) => r.data),
  removeTemplate: (id: number) => http.delete(`/record-templates/${id}`).then((r) => r.data),
  extract: (data: { template_id: number; text: string; save?: boolean; source_type?: string }) =>
    http.post<{ count: number; entries: any[] }>('/record-templates/extract', data).then((r) => r.data),
  entries: (templateId: number) =>
    http.get<{ id: number; data: Record<string, any>; source_type: string; status: string }[]>(
      `/record-templates/${templateId}/entries`).then((r) => r.data),
  updateEntry: (entryId: number, data: Record<string, any>, status?: string) =>
    http.patch(`/record-templates/entries/${entryId}`, { data, status }).then((r) => r.data),
  removeEntry: (entryId: number) => http.delete(`/record-templates/entries/${entryId}`).then((r) => r.data),
  exportUrl: (templateId: number, fmt: 'xlsx' | 'csv' | 'md' = 'xlsx') =>
    `${API_BASE}/record-templates/${templateId}/export?fmt=${fmt}`,
}


