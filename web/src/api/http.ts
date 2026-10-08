import axios from 'axios'

// 统一入口：默认走相对路径 /api/v1（由后端同端口托管或 Vite 代理转发）
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
  return anyE?.response?.data?.message || anyE?.response?.data?.detail || anyE?.message || '请求失败'
}
