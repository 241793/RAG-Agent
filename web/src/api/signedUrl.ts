/**
 * 附件 / 产物签名 URL：短期 URL 换取 + 内存缓存 + 过期自动重签。
 *
 * <img>/<video>/<a> 等原生标签无法携带 Authorization 头，故附件端点支持 ?t=<签名token>。
 * 本模块按需签名并缓存，避免重复请求（与 React 版行为一致）。
 */
import { API_BASE, chatApi, fileApi } from './index'

interface Cached {
  url: string
  exp: number
}
const cache = new Map<string, Cached>()
const TTL_SKEW = 10_000 // 提前 10s 视为过期，留出加载余量

function get(key: string): string | undefined {
  const c = cache.get(key)
  if (c && c.exp > Date.now()) return c.url
  return undefined
}

/** 相对路径 → 绝对（签名 URL 可能以 /api/v1 开头） */
export function absUrl(u: string): string {
  return u.startsWith('http') ? u : `${API_BASE.replace('/api/v1', '')}${u}`
}

export async function getAttachmentUrl(fileKey: string): Promise<string> {
  const key = 'a:' + fileKey
  const hit = get(key)
  if (hit) return hit
  const r = await chatApi.signAttachment(fileKey)
  cache.set(key, { url: r.url, exp: Date.now() + r.expires_in * 1000 - TTL_SKEW })
  return r.url
}

export async function getArtifactUrl(artifactId: number, download = false): Promise<string> {
  const key = (download ? 'd:' : 'f:') + artifactId
  const hit = get(key)
  if (hit) return hit
  const r = await fileApi.signUrl(artifactId)
  const url = download ? r.download_url : r.url
  cache.set(key, { url, exp: Date.now() + r.expires_in * 1000 - TTL_SKEW })
  return url
}

export function fileExt(name: string): string {
  const i = name.lastIndexOf('.')
  return i >= 0 ? name.slice(i + 1).toLowerCase() : ''
}

const TEXT_EXTS = new Set([
  'txt', 'md', 'markdown', 'csv', 'log', 'json', 'xml', 'yml', 'yaml', 'html', 'htm', 'js', 'css', 'py',
])

export function renderKind(
  name: string,
  type?: string,
): 'image' | 'video' | 'pdf' | 'html' | 'text' | 'office' | 'other' {
  const ext = fileExt(name)
  if (type === 'image') return 'image'
  if (type === 'video') return 'video'
  if (ext === 'pdf') return 'pdf'
  if (ext === 'html' || ext === 'htm') return 'html'
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg'].includes(ext)) return 'image'
  if (['mp4', 'webm', 'mov', 'avi', 'mkv', 'mp3', 'wav', 'm4a'].includes(ext)) return 'video'
  if (TEXT_EXTS.has(ext)) return 'text'
  if (['docx', 'doc', 'xlsx', 'xls', 'pptx', 'ppt'].includes(ext)) return 'office'
  return 'other'
}

export function fmtSize(n?: number): string {
  if (!n) return ''
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(2)} MB`
}
