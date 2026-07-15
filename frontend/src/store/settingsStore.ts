import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface SettingsStore {
  theme: string
  streamingMode: boolean
  nsfwMode: boolean
  hiddenNovelIds: number[]
  setTheme: (id: string) => void
  toggleStreamingMode: () => void
  toggleNsfwMode: () => void
  toggleNovelHidden: (id: number) => void
}

export const useSettingsStore = create<SettingsStore>()(
  persist(
    (set) => ({
      theme: 'dark',
      streamingMode: true,
      nsfwMode: false,
      hiddenNovelIds: [],
      setTheme: (id) => set({ theme: id }),
      toggleStreamingMode: () => set((s) => ({ streamingMode: !s.streamingMode })),
      toggleNsfwMode: () => set((s) => ({ nsfwMode: !s.nsfwMode })),
      toggleNovelHidden: (id) =>
        set((s) => ({
          hiddenNovelIds: s.hiddenNovelIds.includes(id)
            ? s.hiddenNovelIds.filter((x) => x !== id)
            : [...s.hiddenNovelIds, id],
        })),
    }),
    {
      name: 'novelbot-settings',
      partialize: (state) => ({
        theme: state.theme,
        streamingMode: state.streamingMode,
        hiddenNovelIds: state.hiddenNovelIds,
      }),
    }
  )
)
