import { create } from 'zustand'
import type { AgentLogEntry } from '@/components/AgentLog/AgentLog'

interface GenerationState {
  isGenerating: boolean
  novelId: number | null
  novelTitle: string
  chapterNum: number
  agentStage: string
  errorMessage: string
  warningMessage: string
  streamingText: string
  originalDraft: string   // 首次 Critic 失败前的初稿（有重写时才有值）
  agentLogEntries: AgentLogEntry[]
  totalInputTokens: number
  totalOutputTokens: number
  abortController: AbortController | null

  startGeneration: (novelId: number, novelTitle: string, chapterNum: number) => void
  setAbortController: (ctrl: AbortController) => void
  setAgentStage: (stage: string) => void
  setError: (message: string) => void
  setWarning: (message: string) => void
  appendToken: (token: string) => void
  setOriginalDraft: (text: string) => void
  addLogEntry: (entry: AgentLogEntry) => void
  updateLogEntry: (id: string, updates: Partial<AgentLogEntry>) => void
  setTotalTokens: (input: number, output: number) => void
  finishGeneration: () => void
  abortGeneration: () => void
}

// ── Token batching: accumulate tokens and flush at ~30fps ──────────────────
let _tokenBuffer = ''
let _rafId: number | null = null

function _flushTokens() {
  _rafId = null
  if (!_tokenBuffer) return
  const chunk = _tokenBuffer
  _tokenBuffer = ''
  useGenerationStore.setState((s) => ({ streamingText: s.streamingText + chunk }))
}

function _clearTokenBuffer() {
  _tokenBuffer = ''
  if (_rafId !== null) {
    cancelAnimationFrame(_rafId)
    _rafId = null
  }
}

export const useGenerationStore = create<GenerationState>()((set, get) => ({
  isGenerating: false,
  novelId: null,
  novelTitle: '',
  chapterNum: 1,
  agentStage: '',
  errorMessage: '',
  warningMessage: '',
  streamingText: '',
  originalDraft: '',
  agentLogEntries: [],
  totalInputTokens: 0,
  totalOutputTokens: 0,
  abortController: null,

  startGeneration: (novelId, novelTitle, chapterNum) => {
    _clearTokenBuffer()
    set({
      isGenerating: true,
      novelId,
      novelTitle,
      chapterNum,
      agentStage: 'building_context',
      errorMessage: '',
      warningMessage: '',
      streamingText: '',
      originalDraft: '',
      agentLogEntries: [],
      totalInputTokens: 0,
      totalOutputTokens: 0,
      abortController: null,
    })
  },

  setAbortController: (ctrl) => set({ abortController: ctrl }),

  setAgentStage: (stage) => set({ agentStage: stage }),

  setError: (message) => set({ agentStage: 'error', errorMessage: message }),

  setWarning: (message) => set({ warningMessage: message }),

  appendToken: (token) => {
    _tokenBuffer += token
    if (_rafId === null) {
      _rafId = requestAnimationFrame(_flushTokens)
    }
  },

  setOriginalDraft: (text) => set({ originalDraft: text }),

  addLogEntry: (entry) => set((s) => ({ agentLogEntries: [...s.agentLogEntries, entry] })),

  updateLogEntry: (id, updates) =>
    set((s) => ({
      agentLogEntries: s.agentLogEntries.map((e) => (e.id === id ? { ...e, ...updates } : e)),
    })),

  setTotalTokens: (input, output) =>
    set({ totalInputTokens: input, totalOutputTokens: output }),

  finishGeneration: () => {
    // Flush any pending tokens before finishing
    if (_rafId !== null) {
      cancelAnimationFrame(_rafId)
      _rafId = null
    }
    if (_tokenBuffer) {
      const chunk = _tokenBuffer
      _tokenBuffer = ''
      set((s) => ({ streamingText: s.streamingText + chunk }))
    }
    set((s) => ({
      isGenerating: false,
      agentStage: s.agentStage === 'error' ? 'error' : 'done',
      abortController: null,
    }))
  },

  abortGeneration: () => {
    get().abortController?.abort()
    set({ isGenerating: false, novelId: null, chapterNum: 1 })
  },
}))
