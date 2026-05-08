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
  enable_critic: boolean
  writer_temperature: number
  writer_max_tokens: number
  rolling_summary_count: number
  rag_top_k: number
  chat_context_rounds: number
  enable_thinking: boolean
  thinking_level: string
  gemini_stream: boolean
  context_config: Record<string, boolean>
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
  avatar_url: string
  created_at: string
  updated_at: string
}

export interface WorldEntity {
  id: number
  novel_id: number
  type: 'item' | 'system'
  name: string
  description: string
  properties: Record<string, unknown>
  current_state: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface Location {
  id: number
  novel_id: number
  name: string
  type: string  // continent/region/city/building/landmark/other
  description: string
  parent_id: number | null
  properties: Record<string, unknown>
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
  start_chapter: number
  end_chapter: number
  title: string
  content: string
  created_at: string
  updated_at: string
}

export interface ModelEntry {
  id: number
  display_name: string
  model_id: string
  provider: string
  api_format: string
  provider_id: number | null
  created_at: string
}

export interface ApiProvider {
  id: number
  name: string
  base_url: string
  api_key_set: boolean
  api_key_masked: string
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

export interface NovelNote {
  id: number
  novel_id: number
  title: string
  content: string
  created_at: string
  updated_at: string
}

export interface Faction {
  id: number
  novel_id: number
  name: string
  type: string
  power_level: string
  alignment: string
  leader: string
  headquarters: string
  location_id: number | null
  member_count: string
  color: string
  description: string
  goals: string
  traits: string
  history: string
  created_at: string
  updated_at: string
}

export interface Technique {
  id: number
  novel_id: number
  name: string
  type: string
  description: string
  practitioners: string
  power_level: string
  created_at: string
  updated_at: string
}

export interface Volume {
  id: number
  novel_id: number
  number: number
  title: string
  description: string
  created_at: string
  updated_at: string
}

export interface RelationshipNode {
  id: number
  name: string
  role: string
}

export interface RelationshipEdge {
  source: number
  target: number
  labels: Array<{ from: string; desc: string; type?: 'initial' | 'current' }>
}

export interface ContextStepData {
  key: string
  label: string
  detail: string
  source: string
  items: string[]
  content?: string
}

export interface NewLocationsData {
  candidates: Array<{ name: string; type: string; description: string; parent_name: string }>
}

export interface ReviewIssue {
  type: string
  severity: string
  description: string
  chapters: number[]
}

export interface ReviewResult {
  issues: ReviewIssue[]
  input_tokens: number
  output_tokens: number
  model: string
  chapter_count: number
  word_count: number
}

export interface SearchResult {
  chapters: Array<{ chapter_number: number; summary: string; score: number }>
  characters: Array<{ id: number; name: string; role: string; description: string }>
  items: Array<{ id: number; name: string; type: string; description: string }>
  systems: Array<{ id: number; name: string; type: string; description: string }>
  locations: Array<{ id: number; name: string; type: string; description: string }>
  factions: Array<{ id: number; name: string; type: string; description: string }>
  techniques: Array<{ id: number; name: string; type: string; description: string }>
  notes: Array<{ id?: number; title: string; content: string; score?: number }>
}

export const PROVIDER_PRESETS = [
  { name: 'OpenAI',        base_url: 'https://api.openai.com/v1',                api_format: 'openai' },
  { name: 'DeepSeek',      base_url: 'https://api.deepseek.com',                 api_format: 'openai' },
  { name: 'AiHubMix',      base_url: 'https://aihubmix.com/v1',                  api_format: 'openai' },
  { name: 'Google Gemini',  base_url: 'https://generativelanguage.googleapis.com', api_format: 'gemini' },
  { name: 'Anthropic',     base_url: 'https://api.anthropic.com',                api_format: 'anthropic' },
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
  contextPreview: (novelId: number, chapterNumber?: number, instruction?: string, targetWords?: number) =>
    api.get<ContextPreview>(`/novels/${novelId}/context-preview`, {
      params: { chapter_number: chapterNumber, instruction, target_words: targetWords },
    }).then(r => r.data),
  reindexTimeline: (novelId: number) =>
    api.post<{ updated: number; results: Array<{ chapter: number; old: string; new: string }> }>(`/novels/${novelId}/reindex-timeline`).then(r => r.data),
  reindexEntities: (novelId: number) =>
    api.post<Record<string, number>>(`/novels/${novelId}/reindex-entities`).then(r => r.data),
  search: (novelId: number, query: string) =>
    api.get<SearchResult>(`/novels/${novelId}/search`, { params: { q: query } }).then(r => r.data),
}

export interface WriterMessage {
  role: string
  content: string
}

export interface ContextPreview {
  chapter_number: number
  context: {
    core_setting: string
    book_summary: string
    arc_summary: string
    chapter_outline: string
    rolling_summary: string
    rag_context: string
    recent_text: string
    characters_count: number
    entities_count: number
    locations_count: number
    notes_context: string
  }
  writer_messages: WriterMessage[]
  writer_model: string
  token_estimate: Record<string, number>
  context_config: Record<string, boolean>
}

// ── Chapter APIs ───────────────────────────────────────────────────────────

export const chaptersApi = {
  list: (novelId: number) => api.get<Chapter[]>(`/chapters/novel/${novelId}`).then(r => r.data),
  get: (id: number) => api.get<Chapter>(`/chapters/${id}`).then(r => r.data),
  create: (data: Partial<Chapter>) => api.post<Chapter>('/chapters/', data).then(r => r.data),
  update: (id: number, data: Partial<Chapter>) => api.patch<Chapter>(`/chapters/${id}`, data).then(r => r.data),
  confirm: (chapterId: number) => api.post('/chapters/confirm', { chapter_id: chapterId }, { timeout: 120000 }).then(r => r.data),
  delete: (id: number) => api.delete(`/chapters/${id}`).then(r => r.data),
  batchVolume: (chapterIds: number[], volume: number) =>
    api.post('/chapters/batch-volume', { chapter_ids: chapterIds, volume }).then(r => r.data),
  discover: (chapterId: number) =>
    api.post<{
      characters: Array<{ name: string; role: string; description: string }>
      entities: Array<{ name: string; type: string; description: string }>
      locations: Array<{ name: string; type: string; description: string; parent_name: string }>
      techniques: Array<{ name: string; type: string; description: string }>
    }>(`/chapters/${chapterId}/discover`, {}, { timeout: 60000 }).then(r => r.data),
}

// ── Character APIs ─────────────────────────────────────────────────────────

export const charactersApi = {
  list: (novelId: number) => api.get<Character[]>(`/characters/novel/${novelId}`).then(r => r.data),
  get: (id: number) => api.get<Character>(`/characters/${id}`).then(r => r.data),
  create: (data: Partial<Character>) => api.post<Character>('/characters/', data).then(r => r.data),
  update: (id: number, data: Partial<Character>) => api.patch<Character>(`/characters/${id}`, data).then(r => r.data),
  delete: (id: number) => api.delete(`/characters/${id}`).then(r => r.data),
  uploadAvatar: (characterId: number, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.post<Character>(`/characters/${characterId}/avatar`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then(r => r.data)
  },
  deleteAvatar: (characterId: number) =>
    api.delete<Character>(`/characters/${characterId}/avatar`).then(r => r.data),
  refreshAppearance: (characterId: number) =>
    api.post<Character>(`/characters/${characterId}/refresh-appearance`).then(r => r.data),
  enhance: (characterId: number, data: { prompt: string; scope: string[] }) =>
    api.post<Character>(`/characters/${characterId}/enhance`, data).then(r => r.data),
  relationshipGraph: (novelId: number) =>
    api.get<{ nodes: RelationshipNode[]; edges: RelationshipEdge[] }>(`/characters/novel/${novelId}/relationship-graph`).then(r => r.data),
  generateHistory: (characterId: number) =>
    api.post<Character>(`/characters/${characterId}/generate-history`, {}, { timeout: 300000 }).then(r => r.data),
}

// ── World Entity APIs ─────────────────────────────────────────────────────

export const worldEntitiesApi = {
  list: (novelId: number, type?: string) =>
    api.get<WorldEntity[]>(`/world-entities/novel/${novelId}`, { params: type ? { type } : {} }).then(r => r.data),
  get: (id: number) => api.get<WorldEntity>(`/world-entities/${id}`).then(r => r.data),
  create: (data: Partial<WorldEntity>) => api.post<WorldEntity>('/world-entities/', data).then(r => r.data),
  update: (id: number, data: Partial<WorldEntity>) => api.patch<WorldEntity>(`/world-entities/${id}`, data).then(r => r.data),
  delete: (id: number) => api.delete(`/world-entities/${id}`).then(r => r.data),
  convertToTechnique: (entityId: number) =>
    api.post<Technique>(`/world-entities/${entityId}/convert-to-technique`).then(r => r.data),
}

// ── Location APIs ────────────────────────────────────────────────────────────

export const locationsApi = {
  list: (novelId: number, type?: string) =>
    api.get<Location[]>(`/locations/novel/${novelId}`, { params: type ? { type } : {} }).then(r => r.data),
  get: (id: number) => api.get<Location>(`/locations/${id}`).then(r => r.data),
  create: (data: Partial<Location>) => api.post<Location>('/locations/', data).then(r => r.data),
  update: (id: number, data: Partial<Location>) => api.patch<Location>(`/locations/${id}`, data).then(r => r.data),
  delete: (id: number) => api.delete(`/locations/${id}`).then(r => r.data),
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

// ── Provider APIs ────────────────────────────────────────────────────────────

export const providersApi = {
  list: () => api.get<ApiProvider[]>('/providers/').then(r => r.data),
  create: (data: { name: string; base_url: string; api_key: string; api_format: string }) =>
    api.post<ApiProvider>('/providers/', data).then(r => r.data),
  update: (id: number, data: { name?: string; base_url?: string; api_key?: string; api_format?: string }) =>
    api.patch<ApiProvider>(`/providers/${id}`, data).then(r => r.data),
  delete: (id: number) => api.delete(`/providers/${id}`).then(r => r.data),
}

// ── Model Library APIs ──────────────────────────────────────────────────────

export const modelLibraryApi = {
  list: () => api.get<ModelEntry[]>('/models/').then(r => r.data),
  create: (data: { display_name: string; model_id: string; provider_id: number; provider?: string; api_format?: string }) =>
    api.post<ModelEntry>('/models/', data).then(r => r.data),
  update: (id: number, data: { display_name?: string; model_id?: string; provider_id?: number }) =>
    api.patch<ModelEntry>(`/models/${id}`, data).then(r => r.data),
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
  review: (novelId: number) =>
    api.post<ReviewResult>('/generation/review', { novel_id: novelId }, { timeout: 300000 }).then(r => r.data),
}

// ── Novel Notes APIs ──────────────────────────────────────────────────────

export const novelNotesApi = {
  list: (novelId: number) =>
    api.get<NovelNote[]>(`/notes/novel/${novelId}`).then(r => r.data),
  create: (data: { novel_id: number; title: string; content?: string }) =>
    api.post<NovelNote>('/notes/', data).then(r => r.data),
  update: (id: number, data: { title?: string; content?: string }) =>
    api.patch<NovelNote>(`/notes/${id}`, data).then(r => r.data),
  delete: (id: number) =>
    api.delete(`/notes/${id}`).then(r => r.data),
}

// ── Faction APIs ──────────────────────────────────────────────────────────

export const factionsApi = {
  list: (novelId: number) =>
    api.get<Faction[]>(`/factions/novel/${novelId}`).then(r => r.data),
  create: (data: Partial<Faction> & { novel_id: number }) =>
    api.post<Faction>('/factions/', data).then(r => r.data),
  update: (id: number, data: Partial<Faction>) =>
    api.patch<Faction>(`/factions/${id}`, data).then(r => r.data),
  delete: (id: number) =>
    api.delete(`/factions/${id}`).then(r => r.data),
}

// ── Technique APIs ────────────────────────────────────────────────────────

export const techniquesApi = {
  list: (novelId: number) =>
    api.get<Technique[]>(`/techniques/novel/${novelId}`).then(r => r.data),
  create: (data: Partial<Technique> & { novel_id: number }) =>
    api.post<Technique>('/techniques/', data).then(r => r.data),
  update: (id: number, data: Partial<Technique>) =>
    api.patch<Technique>(`/techniques/${id}`, data).then(r => r.data),
  delete: (id: number) =>
    api.delete(`/techniques/${id}`).then(r => r.data),
  convertToEntity: (id: number, type: 'item' | 'system') =>
    api.post<WorldEntity>(`/techniques/${id}/convert-to-entity`, { type }).then(r => r.data),
}

// ── Volume APIs ───────────────────────────────────────────────────────────

export const volumesApi = {
  list: (novelId: number) =>
    api.get<Volume[]>(`/volumes/novel/${novelId}`).then(r => r.data),
  create: (data: { novel_id: number; number: number; title: string; description?: string }) =>
    api.post<Volume>('/volumes/', data).then(r => r.data),
  update: (id: number, data: { title?: string; description?: string }) =>
    api.patch<Volume>(`/volumes/${id}`, data).then(r => r.data),
  delete: (id: number) =>
    api.delete(`/volumes/${id}`).then(r => r.data),
}

// ── Outline APIs ──────────────────────────────────────────────────────────

export const outlinesApi = {
  list: (novelId: number) =>
    api.get<OutlineEntry[]>(`/outlines/novel/${novelId}`).then(r => r.data),
  create: (data: { novel_id: number; start_chapter: number; end_chapter: number; title?: string; content: string; volume?: number }) =>
    api.post<OutlineEntry>('/outlines/', data).then(r => r.data),
  update: (id: number, data: { start_chapter?: number; end_chapter?: number; title?: string; content?: string }) =>
    api.patch<OutlineEntry>(`/outlines/${id}`, data).then(r => r.data),
  delete: (id: number) =>
    api.delete(`/outlines/${id}`).then(r => r.data),
  expand: (id: number) =>
    api.post<OutlineEntry[]>(`/outlines/${id}/expand`).then(r => r.data),
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

export interface NewEntitiesData {
  candidates: Array<{ name: string; type: string; description: string }>
}

export interface NewTechniquesData {
  candidates: Array<{ name: string; type: string; description: string }>
}

export interface PlotSuggestionsData {
  suggestions: string[]
}

export interface LlmCallData {
  agent: string
  model: string
  status: 'ok' | 'truncated' | 'error'
  input_tokens: number
  output_tokens: number
  duration_ms: number
  payload?: Record<string, unknown>
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
  | { event: 'new_entities'; data: NewEntitiesData }
  | { event: 'plot_suggestions'; data: PlotSuggestionsData }
  | { event: 'llm_request'; data: Record<string, unknown> }
  | { event: 'llm_call'; data: LlmCallData }
  | { event: 'new_locations'; data: NewLocationsData }
  | { event: 'new_techniques'; data: NewTechniquesData }
  | { event: 'context_step'; data: ContextStepData }

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
    system_prompt?: string
    temperature?: number
    max_tokens?: number
    context_rounds?: number
  },
  onMessage: (msg: ChatSSEMessage) => void,
  onClose: () => void,
): AbortController {
  const controller = new AbortController()

  fetch('/api/chat/stream', {
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
            const msg = JSON.parse(line.slice(6)) as ChatSSEMessage
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
