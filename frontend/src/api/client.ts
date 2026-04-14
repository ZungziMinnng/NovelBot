import axios from 'axios'

export const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

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

// ── Novel APIs ─────────────────────────────────────────────────────────────

export const novelsApi = {
  list: () => api.get<Novel[]>('/novels/').then(r => r.data),
  get: (id: number) => api.get<Novel>(`/novels/${id}`).then(r => r.data),
  create: (data: Partial<Novel>) => api.post<Novel>('/novels/', data).then(r => r.data),
  update: (id: number, data: Partial<Novel>) => api.patch<Novel>(`/novels/${id}`, data).then(r => r.data),
  delete: (id: number) => api.delete(`/novels/${id}`).then(r => r.data),
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

// ── Settings APIs ──────────────────────────────────────────────────────────

export const settingsApi = {
  get: () => api.get('/settings/').then(r => r.data),
  update: (data: object) => api.patch('/settings/', data).then(r => r.data),
  test: () => api.post('/settings/test').then(r => r.data),
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

export type SSEMessage =
  | { event: 'stage'; data: string }
  | { event: 'token'; data: string }
  | { event: 'done'; data: string }
  | { event: 'error'; data: string }
  | { event: 'agent_start'; data: AgentStartData }
  | { event: 'agent_done'; data: AgentDoneData }
  | { event: 'total_usage'; data: TotalUsageData }

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

  fetch('/api/generation/chapter', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal: controller.signal,
  }).then(async (response) => {
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
          } catch {}
        }
      }
    }
    onClose()
  }).catch((err) => {
    if (err.name !== 'AbortError') {
      onMessage({ event: 'error', data: String(err) })
    }
    onClose()
  })

  return controller
}
