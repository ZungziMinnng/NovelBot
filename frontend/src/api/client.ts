import axios from 'axios'
import { useDevLogStore } from '@/store/devLogStore'

export const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// ── Dev log interceptors ────────────────────────────────────────────────────

api.interceptors.request.use((config) => {
  useDevLogStore.getState().addEntry({
    type: 'request',
    method: config.method?.toUpperCase(),
    url: (config.baseURL || '') + (config.url || ''),
    reqBody: config.data ? JSON.parse(JSON.stringify(config.data)) : undefined,
  })
  return config
})

api.interceptors.response.use(
  (response) => {
    useDevLogStore.getState().addEntry({
      type: 'response',
      method: response.config.method?.toUpperCase(),
      url: (response.config.baseURL || '') + (response.config.url || ''),
      status: response.status,
      resData: response.data,
    })
    return response
  },
  (error) => {
    useDevLogStore.getState().addEntry({
      type: 'response',
      method: error.config?.method?.toUpperCase(),
      url: (error.config?.baseURL || '') + (error.config?.url || ''),
      status: error.response?.status ?? 0,
      resData: error.response?.data ?? String(error),
    })
    return Promise.reject(error)
  },
)

// ── Types ──────────────────────────────────────────────────────────────────

export interface Novel {
  id: number
  title: string
  genre: string
  premise: string
  writing_style: string
  target_length: string
  core_setting: string
  current_volume: number
  current_chapter: number
  book_summary: string
  writer_model: string
  fast_model: string
  writer_system_prompt: string
  enable_critic: boolean
  writer_temperature: number
  writer_max_tokens: number
  rolling_summary_count: number
  rag_top_k: number
  chat_context_rounds: number
  enable_thinking: boolean
  thinking_level: string
  created_at: string
  updated_at: string
}

export interface Chapter {
  id: number
  novel_id: number
  volume: number
  number: number
  title: string
  content: string
  summary: string
  instruction?: string
  status: string
  word_count: number
  created_at: string
  updated_at: string
}

export interface Character {
  id: number
  novel_id: number
  name: string
  role: string
  age: string
  description: string
  full_sheet: Record<string, unknown>
  current_state: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface Outline {
  chapter_number: number
  title: string
  content: string
}

export interface Memory {
  id: number
  novel_id: number
  chapter_id: number | null
  memory_type: string
  content: string
  volume: number
  chapter_number: number
  created_at: string
}

export interface OutlineEntry {
  id: number
  novel_id: number
  level: string
  volume: number
  chapter_number: number
  title: string
  content: string
  updated_at: string
}

export interface ModelEntry {
  id: number
  display_name: string
  model_id: string
  provider: string
  api_format: string
  created_at: string
}

export interface WriterPreset {
  id: number
  name: string
  prompt: string
  created_at: string
  updated_at: string
}

export const PROVIDERS = [
  { label: 'OpenAI', api_format: 'openai' },
  { label: 'Google / Gemini', api_format: 'gemini' },
  { label: 'Anthropic / Claude', api_format: 'anthropic' },
  { label: '其他（OpenAI 兼容）', api_format: 'openai' },
] as const

// ── Novel APIs ─────────────────────────────────────────────────────────────

export const novelsApi = {
  list: () => api.get<Novel[]>('/novels/').then(r => r.data),
  get: (id: number) => api.get<Novel>(`/novels/${id}`).then(r => r.data),
  create: (data: Partial<Novel>) => api.post<Novel>('/novels/', data).then(r => r.data),
  update: (id: number, data: Partial<Novel>) => api.patch<Novel>(`/novels/${id}`, data).then(r => r.data),
  delete: (id: number) => api.delete(`/novels/${id}`).then(r => r.data),
  optimizeWorld: (novelId: number, coreSetting: string) =>
    api.post<{ core_setting: string }>(`/novels/${novelId}/optimize-world`, { core_setting: coreSetting }).then(r => r.data),
  refreshBookSummary: (novelId: number) =>
    api.post<{ book_summary: string }>(`/novels/${novelId}/book-summary`).then(r => r.data),
  wizardWorld: (novelId: number, rawSetting: string, rawRules: string) =>
    api.post('/novels/wizard/world', { novel_id: novelId, raw_world_setting: rawSetting, raw_world_rules: rawRules }).then(r => r.data),
  wizardCharacters: (novelId: number, characters: object[]) =>
    api.post('/novels/wizard/characters', { novel_id: novelId, characters }).then(r => r.data),
  wizardOutline: (novelId: number) =>
    api.post('/novels/wizard/outline', { novel_id: novelId }).then(r => r.data),
}

// ── Chapter APIs ───────────────────────────────────────────────────────────

export const chaptersApi = {
  list: (novelId: number) => api.get<Chapter[]>(`/chapters/novel/${novelId}`).then(r => r.data),
  get: (id: number) => api.get<Chapter>(`/chapters/${id}`).then(r => r.data),
  create: (data: Partial<Chapter>) => api.post<Chapter>('/chapters/', data).then(r => r.data),
  update: (id: number, data: Partial<Chapter>) => api.patch<Chapter>(`/chapters/${id}`, data).then(r => r.data),
  confirm: (chapterId: number) => api.post('/chapters/confirm', { chapter_id: chapterId }).then(r => r.data),
  delete: (id: number) => api.delete(`/chapters/${id}`).then(r => r.data),
}

// ── Character APIs ─────────────────────────────────────────────────────────

export const charactersApi = {
  list: (novelId: number) => api.get<Character[]>(`/characters/novel/${novelId}`).then(r => r.data),
  get: (id: number) => api.get<Character>(`/characters/${id}`).then(r => r.data),
  create: (data: Partial<Character>) => api.post<Character>('/characters/', data).then(r => r.data),
  update: (id: number, data: Partial<Character>) => api.patch<Character>(`/characters/${id}`, data).then(r => r.data),
  delete: (id: number) => api.delete(`/characters/${id}`).then(r => r.data),
}

// ── Admin APIs ────────────────────────────────────────────────────────────

export const adminApi = {
  listMemories: (novelId: number) => api.get<Memory[]>(`/admin/novel/${novelId}/memories`).then(r => r.data),
  updateMemory: (id: number, data: { content: string }) => api.patch<Memory>(`/admin/memories/${id}`, data).then(r => r.data),
  deleteMemory: (id: number) => api.delete(`/admin/memories/${id}`).then(r => r.data),
  listOutlines: (novelId: number) => api.get<OutlineEntry[]>(`/admin/novel/${novelId}/outlines`).then(r => r.data),
  updateOutline: (id: number, data: { title?: string; content?: string }) => api.patch<OutlineEntry>(`/admin/outlines/${id}`, data).then(r => r.data),
}

// ── Settings APIs ──────────────────────────────────────────────────────────

export const settingsApi = {
  get: () => api.get('/settings/').then(r => r.data),
  update: (data: object) => api.patch('/settings/', data).then(r => r.data),
  test: (model?: string) => api.post('/settings/test', { model: model ?? '' }).then(r => r.data),
}

// ── Model Library APIs ──────────────────────────────────────────────────────

export const modelLibraryApi = {
  list: () => api.get<ModelEntry[]>('/models/').then(r => r.data),
  create: (data: Omit<ModelEntry, 'id' | 'created_at'>) => api.post<ModelEntry>('/models/', data).then(r => r.data),
  update: (id: number, data: Partial<Omit<ModelEntry, 'id' | 'created_at'>>) => api.patch<ModelEntry>(`/models/${id}`, data).then(r => r.data),
  delete: (id: number) => api.delete(`/models/${id}`).then(r => r.data),
}

// ── Writer Preset APIs ─────────────────────────────────────────────────────

export const writerPresetsApi = {
  list: () => api.get<WriterPreset[]>('/writer-presets/').then(r => r.data),
  create: (data: { name: string; prompt?: string }) => api.post<WriterPreset>('/writer-presets/', data).then(r => r.data),
  update: (id: number, data: { name?: string; prompt?: string }) => api.patch<WriterPreset>(`/writer-presets/${id}`, data).then(r => r.data),
  delete: (id: number) => api.delete(`/writer-presets/${id}`).then(r => r.data),
}

// ── Generation APIs ─────────────────────────────────────────────────────────

export const generationApi = {
  plotSuggestions: (novelId: number, chapterNumber: number, volume = 1) =>
    api.post<{ suggestions: string[] }>('/generation/plot-suggestions', {
      novel_id: novelId,
      chapter_number: chapterNumber,
      volume,
    }).then(r => r.data.suggestions),
}

// ── SSE Generation ─────────────────────────────────────────────────────────

export interface AgentStartData {
  agent: string
  label: string
}

export interface AgentDoneData {
  agent: string
  label: string
  input_tokens: number
  output_tokens: number
  passed: boolean
}

export interface TotalUsageData {
  input_tokens: number
  output_tokens: number
}

export interface OriginalDraftData {
  text: string
}

export interface NewCharactersData {
  candidates: Array<{ name: string; role: string; description: string }>
}

export type SSEMessage =
  | { event: 'stage'; data: string }
  | { event: 'token'; data: string }
  | { event: 'done'; data: string }
  | { event: 'error'; data: string }
  | { event: 'warning'; data: string }
  | { event: 'agent_start'; data: AgentStartData }
  | { event: 'agent_done'; data: AgentDoneData }
  | { event: 'total_usage'; data: TotalUsageData }
  | { event: 'original_draft'; data: OriginalDraftData }
  | { event: 'new_characters'; data: NewCharactersData }
  | { event: 'llm_request'; data: Record<string, unknown> }

// ── SSE Chat ───────────────────────────────────────────────────────────────

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export type ChatSSEMessage =
  | { event: 'token'; data: string }
  | { event: 'done'; data: { input_tokens: number; output_tokens: number } }
  | { event: 'error'; data: string }

export function streamChat(
  payload: {
    novel_id: number
    messages: ChatMessage[]
    model?: string
  },
  onMessage: (msg: ChatSSEMessage) => void,
  onClose: () => void,
): AbortController {
  const controller = new AbortController()
  const devLog = useDevLogStore.getState()

  devLog.addEntry({ type: 'request', method: 'POST', url: '/api/chat/stream', reqBody: payload })

  fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal: controller.signal,
  }).then(async (response) => {
    devLog.addEntry({ type: 'response', method: 'POST', url: '/api/chat/stream', status: response.status })
    const reader = response.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const msg = JSON.parse(line.slice(6)) as ChatSSEMessage
            onMessage(msg)
            if (msg.event !== 'token') {
              devLog.addEntry({ type: 'sse', event: msg.event, eventData: msg.data })
            }
          } catch {}
        }
      }
    }
    onClose()
  }).catch((err) => {
    if (err.name !== 'AbortError') {
      onMessage({ event: 'error', data: String(err) })
      devLog.addEntry({ type: 'sse', event: 'error', eventData: String(err) })
    }
    onClose()
  })

  return controller
}

// ── SSE Generation ─────────────────────────────────────────────────────────

export function streamChapterGeneration(
  payload: {
    novel_id: number
    chapter_number: number
    volume: number
    instruction: string
    target_words: number
  },
  onMessage: (msg: SSEMessage) => void,
  onClose: () => void,
): AbortController {
  const controller = new AbortController()
  const devLog = useDevLogStore.getState()

  devLog.addEntry({ type: 'request', method: 'POST', url: '/api/generation/chapter', reqBody: payload })

  fetch('/api/generation/chapter', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal: controller.signal,
  }).then(async (response) => {
    devLog.addEntry({ type: 'response', method: 'POST', url: '/api/generation/chapter', status: response.status })
    const reader = response.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const msg = JSON.parse(line.slice(6)) as SSEMessage
            onMessage(msg)
            if (msg.event !== 'token') {
              devLog.addEntry({ type: 'sse', event: msg.event, eventData: msg.data })
            }
          } catch {}
        }
      }
    }
    onClose()
  }).catch((err) => {
    if (err.name !== 'AbortError') {
      onMessage({ event: 'error', data: String(err) })
      devLog.addEntry({ type: 'sse', event: 'error', eventData: String(err) })
    }
    onClose()
  })

  return controller
}
