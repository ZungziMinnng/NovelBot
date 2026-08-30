import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface SettingsStore {
  theme: string
  streamingMode: boolean
  nsfwMode: boolean
  /** 隐藏名单已迁到服务端 users 表；这两个字段只为把老数据搬上去，搬完清空 */
  hiddenNovelIds: number[]
  hiddenPresetIds: number[]
  setTheme: (id: string) => void
  toggleStreamingMode: () => void
  toggleNsfwMode: () => void
  clearLegacyHidden: () => void
}

export const useSettingsStore = create<SettingsStore>()(
  persist(
    (set) => ({
      theme: 'dark',
      streamingMode: true,
      nsfwMode: false,
      hiddenNovelIds: [],
      hiddenPresetIds: [],
      setTheme: (id) => set({ theme: id }),
      toggleStreamingMode: () => set((s) => ({ streamingMode: !s.streamingMode })),
      toggleNsfwMode: () => set((s) => ({ nsfwMode: !s.nsfwMode })),
      clearLegacyHidden: () => set({ hiddenNovelIds: [], hiddenPresetIds: [] }),
    }),
    {
      name: 'novelbot-settings',
      partialize: (state) => ({
        theme: state.theme,
        streamingMode: state.streamingMode,
        hiddenNovelIds: state.hiddenNovelIds,
        hiddenPresetIds: state.hiddenPresetIds,
      }),
    }
  )
)
