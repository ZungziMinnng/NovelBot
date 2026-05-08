import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface SettingsStore {
  theme: 'dark' | 'light'
  streamingMode: boolean
  toggleTheme: () => void
  toggleStreamingMode: () => void
}

export const useSettingsStore = create<SettingsStore>()(
  persist(
    (set) => ({
      theme: 'dark',
      streamingMode: true,
      toggleTheme: () => set((s) => ({ theme: s.theme === 'dark' ? 'light' : 'dark' })),
      toggleStreamingMode: () => set((s) => ({ streamingMode: !s.streamingMode })),
    }),
    { name: 'novelbot-settings' }
  )
)
