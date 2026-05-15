import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface SettingsStore {
  theme: string
  streamingMode: boolean
  setTheme: (id: string) => void
  toggleStreamingMode: () => void
}

export const useSettingsStore = create<SettingsStore>()(
  persist(
    (set) => ({
      theme: 'dark',
      streamingMode: true,
      setTheme: (id) => set({ theme: id }),
      toggleStreamingMode: () => set((s) => ({ streamingMode: !s.streamingMode })),
    }),
    { name: 'novelbot-settings' }
  )
)
