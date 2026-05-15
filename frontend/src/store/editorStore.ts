import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface EditorDraft {
  instruction: string
  targetWords: number
}

export interface Annotation {
  id: string
  paragraph?: number
  text: string
}

interface EditorStore {
  drafts: Record<number, EditorDraft>
  lastChapter: Record<number, number>
  annotations: Record<string, Annotation[]>
  getDraft: (novelId: number) => EditorDraft
  setInstruction: (novelId: number, instruction: string) => void
  setTargetWords: (novelId: number, targetWords: number) => void
  getLastChapter: (novelId: number) => number
  setLastChapter: (novelId: number, chapterNum: number) => void
  getAnnotations: (novelId: number, chapterNum: number) => Annotation[]
  addAnnotation: (novelId: number, chapterNum: number, annotation: Annotation) => void
  removeAnnotation: (novelId: number, chapterNum: number, annotationId: string) => void
  clearAnnotations: (novelId: number, chapterNum: number) => void
}

const DEFAULT_DRAFT: EditorDraft = { instruction: '', targetWords: 800 }
const EMPTY_ANNOTATIONS: Annotation[] = []

export const useEditorStore = create<EditorStore>()(
  persist(
    (set, get) => ({
      drafts: {},
      lastChapter: {},
      annotations: {},

      getDraft: (novelId) => get().drafts[novelId] ?? DEFAULT_DRAFT,

      setInstruction: (novelId, instruction) =>
        set((s) => ({
          drafts: { ...s.drafts, [novelId]: { ...(s.drafts[novelId] ?? DEFAULT_DRAFT), instruction } },
        })),

      setTargetWords: (novelId, targetWords) =>
        set((s) => ({
          drafts: { ...s.drafts, [novelId]: { ...(s.drafts[novelId] ?? DEFAULT_DRAFT), targetWords } },
        })),

      getLastChapter: (novelId) => get().lastChapter[novelId] ?? 1,

      setLastChapter: (novelId, chapterNum) =>
        set((s) => ({
          lastChapter: { ...s.lastChapter, [novelId]: chapterNum },
        })),

      getAnnotations: (novelId, chapterNum) =>
        get().annotations[`${novelId}_${chapterNum}`] ?? EMPTY_ANNOTATIONS,

      addAnnotation: (novelId, chapterNum, annotation) =>
        set((s) => {
          const key = `${novelId}_${chapterNum}`
          return { annotations: { ...s.annotations, [key]: [...(s.annotations[key] ?? []), annotation] } }
        }),

      removeAnnotation: (novelId, chapterNum, annotationId) =>
        set((s) => {
          const key = `${novelId}_${chapterNum}`
          return { annotations: { ...s.annotations, [key]: (s.annotations[key] ?? []).filter(a => a.id !== annotationId) } }
        }),

      clearAnnotations: (novelId, chapterNum) =>
        set((s) => {
          const key = `${novelId}_${chapterNum}`
          return { annotations: { ...s.annotations, [key]: [] } }
        }),
    }),
    { name: 'novelbot-editor' }
  )
)
