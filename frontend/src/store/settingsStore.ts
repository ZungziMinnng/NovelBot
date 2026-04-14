import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface SettingsStore {
  apiKeySet: boolean
  baseUrl: string
  writerModel: string
  fastModel: string
  theme: 'dark' | 'light'
  setApiKeySet: (v: boolean) => void
  setModels: (writer: string, fast: string) => void
  toggleTheme: () => void
}

export const useSettingsStore = create<SettingsStore>()(
  persist(
    (set) => ({
      apiKeySet: false,
      baseUrl: 'https://aihubmix.com/v1',
      writerModel: 'gpt-4o',
      fastModel: 'gpt-4o-mini',
      theme: 'dark',
      setApiKeySet: (v) => set({ apiKeySet: v }),
      setModels: (writer, fast) => set({ writerModel: writer, fastModel: fast }),
      toggleTheme: () => set((s) => ({ theme: s.theme === 'dark' ? 'light' : 'dark' })),
    }),
    { name: 'novelbot-settings' }
  )
)
