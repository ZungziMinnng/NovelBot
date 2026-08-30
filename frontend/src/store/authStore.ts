import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export interface AuthUser {
  id: number
  username: string
  is_admin: boolean
  default_writer_model: string
  default_fast_model: string
  hidden_novel_ids: number[]
  hidden_preset_ids: number[]
}

interface AuthStore {
  token: string
  user: AuthUser | null
  setAuth: (token: string, user: AuthUser) => void
  setUser: (user: AuthUser) => void
  clear: () => void
}

export const useAuthStore = create<AuthStore>()(
  persist(
    (set) => ({
      token: '',
      user: null,
      setAuth: (token, user) => set({ token, user }),
      setUser: (user) => set({ user }),
      clear: () => set({ token: '', user: null }),
    }),
    { name: 'novelbot-auth' }
  )
)
