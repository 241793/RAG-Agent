/** 附件/产物签名 URL：短期 URL 换取 + 内存缓存 + 过期自动重签。
 *
 * <img>/<video>/<a> 等原生标签无法携带 Authorization 头，故附件端点支持
 * ?t=<签名token>。此模块负责按需签名并缓存，避免重复请求。
 */
import { chatApi, fileApi } from './index'

interface Cached { url: string; exp: number }
const cache = new Map<string, Cached>()

const TTL_SKEW = 10_000 // 提前 10s 视为过期，留出加载余量

function get(key: string): string | undefined {
  const c = cache.get(key)
  if (c && c.exp > Date.now()) return c.url
  return undefined
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

/** 批量预热附件 URL（一屏消息一次请求）。 */
export async function prewarmAttachments(fileKeys: string[]): Promise<void> {
  const miss = fileKeys.filter((k) => !get('a:' + k))
  if (miss.length === 0) return
  try {
    const r = await chatApi.signAttachmentsBatch(miss)
    const exp = Date.now() + r.expires_in * 1000 - TTL_SKEW
    for (const [k, url] of Object.entries(r.urls)) cache.set('a:' + k, { url, exp })
  } catch {
    /* 预热失败不影响单条渲染 */
  }
}

export function fileExt(name: string): string {
  const i = name.lastIndexOf('.')
  return i >= 0 ? name.slice(i + 1).toLowerCase() : ''
}

const TEXT_EXTS = new Set(['txt', 'md', 'markdown', 'csv', 'log', 'json', 'xml', 'yml', 'yaml', 'html', 'htm', 'js', 'css', 'py'])

export function renderKind(name: string, type?: string): 'image' | 'video' | 'pdf' | 'text' | 'office' | 'other' {
  const ext = fileExt(name)
  if (type === 'image') return 'image'
  if (type === 'video') return 'video'
  if (ext === 'pdf') return 'pdf'
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg'].includes(ext)) return 'image'
  if (['mp4', 'webm', 'mov', 'avi', 'mkv', 'mp3', 'wav', 'm4a'].includes(ext)) return 'video'
  if (TEXT_EXTS.has(ext)) return 'text'
  if (['docx', 'doc', 'xlsx', 'xls', 'pptx', 'ppt'].includes(ext)) return 'office'
  return 'other'
}
