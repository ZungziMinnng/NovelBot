import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface SettingsStore {
  theme: string
  streamingMode: boolean
  nsfwMode: boolean
  setTheme: (id: string) => void
  toggleStreamingMode: () => void
  toggleNsfwMode: () => void
}

export const useSettingsStore = create<SettingsStore>()(
  persist(
    (set) => ({
      theme: 'dark',
      streamingMode: true,
      nsfwMode: false,
      setTheme: (id) => set({ theme: id }),
      toggleStreamingMode: () => set((s) => ({ streamingMode: !s.streamingMode })),
      toggleNsfwMode: () => set((s) => ({ nsfwMode: !s.nsfwMode })),
    }),
    {
      name: 'novelbot-settings',
      partialize: (state) => ({
        theme: state.theme,
        streamingMode: state.streamingMode,
      }),
    }
  )
)
