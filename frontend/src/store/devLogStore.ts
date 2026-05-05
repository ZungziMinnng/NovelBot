import { create } from 'zustand'

export type DevLogType = 'request' | 'response' | 'sse' | 'llm_call'

export interface DevLogEntry {
  id: string
  ts: number
  type: DevLogType
  // HTTP fields
  method?: string
  url?: string
  reqBody?: unknown
  status?: number
  resData?: unknown
  // SSE fields
  event?: string
  eventData?: unknown
  // LLM Call fields
  agent?: string
  model?: string
  llmStatus?: 'ok' | 'truncated' | 'error'
  inputTokens?: number
  outputTokens?: number
  durationMs?: number
  payload?: Record<string, unknown>
}

interface DevLogState {
  entries: DevLogEntry[]
  addEntry: (entry: Omit<DevLogEntry, 'id' | 'ts'>) => void
  clear: () => void
}

let _seq = 0

export const useDevLogStore = create<DevLogState>()((set) => ({
  entries: [],

  addEntry: (entry) =>
    set((s) => ({
      entries: [
        ...s.entries.slice(-299),
        { ...entry, id: String(_seq++), ts: Date.now() },
      ],
    })),

  clear: () => set({ entries: [] }),
}))
