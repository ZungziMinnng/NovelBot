import { create } from 'zustand'
import type { Novel, Chapter, Character } from '@/api/client'

interface NovelStore {
  novels: Novel[]
  currentNovel: Novel | null
  chapters: Chapter[]
  characters: Character[]
  currentChapter: Chapter | null

  setNovels: (novels: Novel[]) => void
  setCurrentNovel: (novel: Novel | null) => void
  setChapters: (chapters: Chapter[]) => void
  setCharacters: (characters: Character[]) => void
  setCurrentChapter: (chapter: Chapter | null) => void
  updateChapter: (chapter: Chapter) => void
  addChapter: (chapter: Chapter) => void
}

export const useNovelStore = create<NovelStore>((set) => ({
  novels: [],
  currentNovel: null,
  chapters: [],
  characters: [],
  currentChapter: null,

  setNovels: (novels) => set({ novels }),
  setCurrentNovel: (novel) => set({ currentNovel: novel }),
  setChapters: (chapters) => set({ chapters }),
  setCharacters: (characters) => set({ characters }),
  setCurrentChapter: (chapter) => set({ currentChapter: chapter }),
  updateChapter: (chapter) =>
    set((state) => ({
      chapters: state.chapters.map((c) => (c.id === chapter.id ? chapter : c)),
      currentChapter: state.currentChapter?.id === chapter.id ? chapter : state.currentChapter,
    })),
  addChapter: (chapter) =>
    set((state) => ({ chapters: [...state.chapters, chapter] })),
}))
