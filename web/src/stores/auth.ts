import { create } from 'zustand'
import { authApi, type User } from '../api'

interface AuthState {
  user: User | null
  loading: boolean
  hasPermission: (code: string) => boolean
  setUser: (u: User | null) => void
  fetchMe: () => Promise<void>
  logout: () => void
}

export const useAuth = create<AuthState>((set, get) => ({
  user: null,
  loading: true,
  hasPermission: (code) => {
    const u = get().user
    if (!u) return false
    if (u.is_admin) return true
    const p = u.permissions || []
    return p.includes('*') || p.includes(code)
  },
  setUser: (u) => set({ user: u }),
  fetchMe: async () => {
    set({ loading: true })
    try {
      const u = await authApi.me()
      set({ user: u, loading: false })
    } catch {
      set({ user: null, loading: false })
    }
  },
  logout: () => {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    set({ user: null })
  },
}))
