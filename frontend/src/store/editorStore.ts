import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface EditorDraft {
  instruction: string
  targetWords: number
}

interface EditorStore {
  drafts: Record<number, EditorDraft>
  chapterSuggestions: Record<string, string[]>
  lastChapter: Record<number, number>
  getDraft: (novelId: number) => EditorDraft
  setInstruction: (novelId: number, instruction: string) => void
  setTargetWords: (novelId: number, targetWords: number) => void
  getChapterSuggestions: (novelId: number, chapterNum: number) => string[]
  setChapterSuggestions: (novelId: number, chapterNum: number, suggestions: string[]) => void
  getLastChapter: (novelId: number) => number
  setLastChapter: (novelId: number, chapterNum: number) => void
}

const DEFAULT_DRAFT: EditorDraft = { instruction: '', targetWords: 800 }
const EMPTY_SUGGESTIONS: string[] = []

export const useEditorStore = create<EditorStore>()(
  persist(
    (set, get) => ({
      drafts: {},
      chapterSuggestions: {},
      lastChapter: {},

      getDraft: (novelId) => get().drafts[novelId] ?? DEFAULT_DRAFT,

      setInstruction: (novelId, instruction) =>
        set((s) => ({
          drafts: { ...s.drafts, [novelId]: { ...(s.drafts[novelId] ?? DEFAULT_DRAFT), instruction } },
        })),

      setTargetWords: (novelId, targetWords) =>
        set((s) => ({
          drafts: { ...s.drafts, [novelId]: { ...(s.drafts[novelId] ?? DEFAULT_DRAFT), targetWords } },
        })),

      getChapterSuggestions: (novelId, chapterNum) =>
        get().chapterSuggestions[`${novelId}_${chapterNum}`] ?? EMPTY_SUGGESTIONS,

      setChapterSuggestions: (novelId, chapterNum, suggestions) =>
        set((s) => ({
          chapterSuggestions: { ...s.chapterSuggestions, [`${novelId}_${chapterNum}`]: suggestions },
        })),

      getLastChapter: (novelId) => get().lastChapter[novelId] ?? 1,

      setLastChapter: (novelId, chapterNum) =>
        set((s) => ({
          lastChapter: { ...s.lastChapter, [novelId]: chapterNum },
        })),
    }),
    { name: 'novelbot-editor' }
  )
)
