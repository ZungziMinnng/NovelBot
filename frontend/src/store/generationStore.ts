import { create } from 'zustand'
import type { AgentLogEntry } from '@/components/AgentLog/AgentLog'

interface GenerationState {
  isGenerating: boolean
  novelId: number | null
  novelTitle: string
  chapterNum: number
  agentStage: string
  streamingText: string
  agentLogEntries: AgentLogEntry[]
  totalInputTokens: number
  totalOutputTokens: number
  abortController: AbortController | null

  startGeneration: (novelId: number, novelTitle: string, chapterNum: number) => void
  setAbortController: (ctrl: AbortController) => void
  setAgentStage: (stage: string) => void
  appendToken: (token: string) => void
  addLogEntry: (entry: AgentLogEntry) => void
  updateLogEntry: (id: string, updates: Partial<AgentLogEntry>) => void
  setTotalTokens: (input: number, output: number) => void
  finishGeneration: () => void
}

export const useGenerationStore = create<GenerationState>()((set) => ({
  isGenerating: false,
  novelId: null,
  novelTitle: '',
  chapterNum: 1,
  agentStage: '',
  streamingText: '',
  agentLogEntries: [],
  totalInputTokens: 0,
  totalOutputTokens: 0,
  abortController: null,

  startGeneration: (novelId, novelTitle, chapterNum) =>
    set({
      isGenerating: true,
      novelId,
      novelTitle,
      chapterNum,
      agentStage: 'building_context',
      streamingText: '',
      agentLogEntries: [],
      totalInputTokens: 0,
      totalOutputTokens: 0,
      abortController: null,
    }),

  setAbortController: (ctrl) => set({ abortController: ctrl }),

  setAgentStage: (stage) => set({ agentStage: stage }),

  appendToken: (token) => set((s) => ({ streamingText: s.streamingText + token })),

  addLogEntry: (entry) => set((s) => ({ agentLogEntries: [...s.agentLogEntries, entry] })),

  updateLogEntry: (id, updates) =>
    set((s) => ({
      agentLogEntries: s.agentLogEntries.map((e) => (e.id === id ? { ...e, ...updates } : e)),
    })),

  setTotalTokens: (input, output) =>
    set({ totalInputTokens: input, totalOutputTokens: output }),

  finishGeneration: () =>
    set({ isGenerating: false, agentStage: 'done', abortController: null }),
}))
