import axios from 'axios'

// 统一入口：默认走相对路径 /api/v1（dev 由 Vite 代理到 :6677，生产由后端同端口托管）
export const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'

export const http = axios.create({ baseURL: API_BASE, timeout: 120000 })

http.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

http.interceptors.response.use(
  (resp) => resp,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('access_token')
      if (location.pathname !== '/login') location.href = '/login'
    }
    return Promise.reject(err)
  },
)

export function errMsg(e: unknown): string {
  const anyE = e as any
  return (
    anyE?.response?.data?.message ||
    anyE?.response?.data?.detail ||
    anyE?.message ||
    '请求失败'
  )
}

/** 把 token 拼到下载 URL 上（浏览器直接打开需带鉴权） */
export function withToken(url: string): string {
  const token = localStorage.getItem('access_token')
  if (!token) return url
  return url + (url.includes('?') ? '&' : '?') + 't=' + encodeURIComponent(token)
}
