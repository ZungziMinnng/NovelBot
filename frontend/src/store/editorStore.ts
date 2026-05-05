import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface EditorDraft {
  instruction: string
  targetWords: number
  plotSuggestions: string[]
}

interface EditorStore {
  drafts: Record<number, EditorDraft>
  chapterSuggestions: Record<string, string[]>
  getDraft: (novelId: number) => EditorDraft
  setInstruction: (novelId: number, instruction: string) => void
  setTargetWords: (novelId: number, targetWords: number) => void
  setPlotSuggestions: (novelId: number, suggestions: string[]) => void
  getChapterSuggestions: (novelId: number, chapterNum: number) => string[]
  setChapterSuggestions: (novelId: number, chapterNum: number, suggestions: string[]) => void
}

const DEFAULT_DRAFT: EditorDraft = { instruction: '', targetWords: 800, plotSuggestions: [] }
const EMPTY_SUGGESTIONS: string[] = []

export const useEditorStore = create<EditorStore>()(
  persist(
    (set, get) => ({
      drafts: {},
      chapterSuggestions: {},

      getDraft: (novelId) => get().drafts[novelId] ?? DEFAULT_DRAFT,

      setInstruction: (novelId, instruction) =>
        set((s) => ({
          drafts: { ...s.drafts, [novelId]: { ...(s.drafts[novelId] ?? DEFAULT_DRAFT), instruction } },
        })),

      setTargetWords: (novelId, targetWords) =>
        set((s) => ({
          drafts: { ...s.drafts, [novelId]: { ...(s.drafts[novelId] ?? DEFAULT_DRAFT), targetWords } },
        })),

      setPlotSuggestions: (novelId, suggestions) =>
        set((s) => ({
          drafts: { ...s.drafts, [novelId]: { ...(s.drafts[novelId] ?? DEFAULT_DRAFT), plotSuggestions: suggestions } },
        })),

      getChapterSuggestions: (novelId, chapterNum) =>
        get().chapterSuggestions[`${novelId}_${chapterNum}`] ?? EMPTY_SUGGESTIONS,

      setChapterSuggestions: (novelId, chapterNum, suggestions) =>
        set((s) => ({
          chapterSuggestions: { ...s.chapterSuggestions, [`${novelId}_${chapterNum}`]: suggestions },
        })),
    }),
    { name: 'novelbot-editor' }
  )
)
