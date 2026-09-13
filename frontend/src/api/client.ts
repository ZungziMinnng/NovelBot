import axios from 'axios'
import { useAuthStore, type AuthUser } from '@/store/authStore'

export const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// 裸 fetch（SSE 流式）调用点使用；axios 走下面的拦截器
export function authHeaders(): Record<string, string> {
  const token = useAuthStore.getState().token
  return token ? { Authorization: `Bearer ${token}` } : {}
}

function handleUnauthorized() {
  useAuthStore.getState().clear()
  if (!window.location.pathname.startsWith('/login')) {
    window.location.href = '/login'
  }
}

api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      handleUnauthorized()
    }
    return Promise.reject(error)
  }
)

// ── Auth APIs ──────────────────────────────────────────────────────────────

export interface AuthResponse {
  token: string
  user: AuthUser
}

export const authApi = {
  register: (username: string, password: string) =>
    api.post<AuthResponse>('/auth/register', { username, password }).then(r => r.data),
  login: (username: string, password: string) =>
    api.post<AuthResponse>('/auth/login', { username, password }).then(r => r.data),
  logout: () => api.post('/auth/logout').then(r => r.data),
  me: () => api.get<AuthUser>('/auth/me').then(r => r.data),
  updateMe: (data: { username?: string; default_writer_model?: string; default_fast_model?: string; hidden_novel_ids?: number[]; hidden_preset_ids?: number[]; old_password?: string; new_password?: string }) =>
    api.patch<AuthUser>('/auth/me', data).then(r => r.data),
}

export type ContextConfigValue = boolean | number

// ── Types ──────────────────────────────────────────────────────────────────

export interface GenreCard {
  name: string
  body: string
  /** 市面上的别称，写进题材栏也能匹配到这张卡 */
  aliases: string[]
}

export interface GenreCardList {
  /** genre_card 存这个值表示本书不用题材卡 */
  off_value: string
  cards: GenreCard[]
}

export interface Novel {
  id: number
  title: string
  genre: string
  /** 题材腔调卡：'' = 按 genre 自动匹配，'none' = 不用卡，其他 = 指定卡名 */
  genre_card: string
  premise: string
  plot_design: string
  /** 结局一句话：主角最后走到哪、跟谁、什么状态 */
  ending: string
  /** 主角起点→终点 */
  protagonist_arc: string
  writing_style: string
  target_length: string
  core_setting: string
  world_rules_seed: string
  current_volume: number
  current_chapter: number
  book_summary: string
  writer_model: string
  fast_model: string
  embedding_model: string
  writer_system_prompt: string
  writer_examples: ExampleTurn[]
  enable_critic: boolean
  critic_model: string
  enable_detail_review: boolean
  detail_review_model: string
  writer_temperature: number
  writer_use_custom_temperature: boolean
  writer_max_tokens: number
  rolling_summary_count: number
  rag_top_k: number
  chat_context_rounds: number
  deepseek_thinking_level: string
  gemini_thinking_level: string
  gemini_stream: boolean
  enable_full_text_context: boolean
  full_text_chapters: number
  context_config: Record<string, ContextConfigValue>
  // null = 从未配置（后端走内置规则默认）；[] = 用户显式全关。不要 `|| []` 把 null 塌成 []
  enabled_rule_ids: number[] | null
  tags: Record<string, string[]>
  // 投稿元数据：番茄/起点开书必填的作品简介与平台标签
  blurb: string
  submission_tags: string[]
  estimated_chapters: number
  enable_volume_split: boolean
  skip_outline: boolean
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
  model_used: string
  created_at: string
  updated_at: string
}

export interface CharacterSecret {
  fact: string
  known_by: string[]
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
  function: string
  properties: Record<string, unknown>
  current_state: Record<string, unknown>
  importance: number
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
  importance: number
  created_at: string
  updated_at: string
}

export interface Outline {
  chapter_number: number
  start_chapter?: number
  end_chapter?: number
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
  in_context: boolean
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
  // 执行计划，仅章级有意义。空串/0 = 未规划
  chapter_role: string
  emotion_tone: string
  emotion_intensity: number
  hook_type: string
  hook_strength: number
  created_at: string
  updated_at: string
}

export interface ModelEntry {
  id: number
  display_name: string
  model_id: string
  provider: string
  api_format: string
  model_type: string
  provider_id: number | null
  context_window: number
  input_price: number
  output_price: number
  price_currency: string
  currency_to_cny_rate: number
  created_at: string
}

// 模型下拉框统一用 ModelEntry.id 作 value（消歧同名 model_id 跨供应商）。
// stored 可能是 id 字符串（新）或旧的 model_id 字符串，都解析到对应条目。
export const findModelEntry = (
  models: ModelEntry[],
  stored: string,
): ModelEntry | undefined =>
  models.find((m) => String(m.id) === stored) ||
  models.find((m) => m.model_id === stored)

// 受控 <select> 的 value：把存储值归一化为 id 字符串，旧值找不到则空串
export const modelSelectValue = (models: ModelEntry[], stored: string): string => {
  const entry = findModelEntry(models, stored)
  return entry ? String(entry.id) : ''
}

export interface ApiProvider {
  id: number
  name: string
  base_url: string
  api_key_set: boolean
  api_key_masked: string
  api_format: string
  use_proxy: boolean
  created_at: string
}

export interface ExampleTurn {
  user: string
  assistant: string
}

export interface WriterPreset {
  id: number
  name: string
  prompt: string
  examples: ExampleTurn[]
  created_at: string
  updated_at: string
}

// 规则广场条目。与 WriterPreset 不同：预设是快照拷贝，规则是活链接，
// 改内容立刻对所有勾选它的小说生效
export interface PromptRule {
  id: number
  name: string
  content: string
  category: string
  enabled: boolean
  is_builtin: boolean
  builtin_key: string
  sort_order: number
  created_at: string
  updated_at: string
}

export interface NovelNote {
  id: number
  novel_id: number
  title: string
  content: string
  importance: number
  created_at: string
  updated_at: string
}

export interface GlossaryEntry {
  id: number
  novel_id: number
  term: string
  category: string
  forbidden_variants: string
  notes: string
  importance: number
  created_at: string
  updated_at: string
}

export const GLOSSARY_CATEGORIES = ['描写用词', '人名', '地名', '功法', '丹药', '武器', '常用词', '禁忌词', '自定义']

export interface WorldRule {
  id: number
  novel_id: number
  kind: 'rule' | 'element'
  title: string
  content: string
  importance: number
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface WorldviewChange {
  id: number
  novel_id: number
  fact: string
  supersedes: string
  effective_chapter: number
  status: string
  source: string
  created_at: string
}

export type StoryThreadKind = 'foreshadowing' | 'secret'
/** expired = 埋太久过期失效，仍算欠着的账，不注入写作上下文 */
export type StoryThreadStatus = 'active' | 'resolved' | 'abandoned' | 'expired'

export interface StoryThread {
  id: number
  novel_id: number
  kind: StoryThreadKind
  title: string
  content: string
  status: StoryThreadStatus
  source_chapter: number
  due_chapter: number
  resolved_chapter: number
  resolution: string
  known_by: string[]
  related_entities: string[]
  importance: number
  source: string
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
  importance: number
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
  importance: number
  created_at: string
  updated_at: string
}

export interface Volume {
  id: number
  novel_id: number
  number: number
  title: string
  description: string
  // 卷级库存，一行一条，不注入写作上下文，只用于体检
  endgame_cards: string
  power_tiers: string
  tier_count: number
  words_per_tier: number
  spent_payoffs: string
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
  labels: Array<{ from: string; desc: string; type?: 'base' | 'initial' | 'current' }>
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

export interface NewFactionsData {
  candidates: Array<{ name: string; type: string; description: string }>
}

export interface NewThreadsData {
  threads: Array<{
    kind: 'foreshadowing' | 'secret'
    title: string
    content: string
    importance: number
    known_by?: string[]
    related_entities?: string[]
    source_chapter?: number
  }>
}

export interface ThreadResolution {
  thread_id: number
  kind: 'foreshadowing' | 'secret'
  title: string
  content: string
  action: 'resolve' | 'reveal'
  resolution?: string
  newly_known_by?: string[]
  known_by?: string[]
  source_chapter: number
}

export interface ThreadResolutionsData {
  resolutions: ThreadResolution[]
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

export interface CriticIssuesData {
  issues_text: string
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
  { name: 'OpenAI',        base_url: 'https://api.openai.com/v1',                api_format: 'openai',    use_proxy: false },
  { name: 'DeepSeek',      base_url: 'https://api.deepseek.com',                 api_format: 'openai',    use_proxy: false },
  { name: 'AiHubMix',      base_url: 'https://aihubmix.com/v1',                  api_format: 'openai',    use_proxy: true },
  { name: 'Google Gemini',  base_url: 'https://generativelanguage.googleapis.com', api_format: 'gemini',    use_proxy: false },
  { name: 'Anthropic',     base_url: 'https://api.anthropic.com',                api_format: 'anthropic', use_proxy: false },
] as const

// ── Novel APIs ─────────────────────────────────────────────────────────────

export interface DashboardStats {
  total_novels: number
  total_words: number
  total_entities: number
  novel_words: Record<string, number>
}

export interface NovelOverview {
  volume_count: number
  chapter_count: number
  total_words: number
  characters: { name: string; role: string }[]
}

export const novelsApi = {
  dashboard: () => api.get<DashboardStats>('/novels/dashboard').then(r => r.data),
  genreCards: () => api.get<GenreCardList>('/novels/genre-cards').then(r => r.data),
  list: () => api.get<Novel[]>('/novels/').then(r => r.data),
  get: (id: number) => api.get<Novel>(`/novels/${id}`).then(r => r.data),
  overview: (id: number) => api.get<NovelOverview>(`/novels/${id}/overview`).then(r => r.data),
  create: (data: Partial<Novel>) => api.post<Novel>('/novels/', data).then(r => r.data),
  update: (id: number, data: Partial<Novel>) => api.patch<Novel>(`/novels/${id}`, data).then(r => r.data),
  delete: (id: number) => api.delete(`/novels/${id}`).then(r => r.data),
  duplicate: (id: number, mode: 'full' | 'settings') =>
    api.post<Novel>(`/novels/${id}/duplicate`, { mode }, { timeout: 120000 }).then(r => r.data),
  optimizeWorld: (novelId: number, coreSetting: string, section?: string) =>
    api.post<{ core_setting: string }>(`/novels/${novelId}/optimize-world`, { core_setting: coreSetting, section }).then(r => r.data),
  refreshBookSummary: (novelId: number) =>
    api.post<{ book_summary: string }>(`/novels/${novelId}/book-summary`).then(r => r.data),
  wizardCharacters: (novelId: number, characters: object[]) =>
    api.post('/novels/wizard/characters', { novel_id: novelId, characters }, { timeout: 120000 }).then(r => r.data),
  contextPreview: (novelId: number, chapterNumber?: number, instruction?: string, targetWords?: number) =>
    api.get<ContextPreview>(`/novels/${novelId}/context-preview`, {
      params: { chapter_number: chapterNumber, instruction, target_words: targetWords },
    }).then(r => r.data),
  reindexTimeline: (novelId: number) =>
    api.post<{ updated: number; results: Array<{ chapter: number; old: string; new: string }> }>(`/novels/${novelId}/reindex-timeline`).then(r => r.data),
  reindexEntities: (novelId: number) =>
    api.post<Record<string, number>>(`/novels/${novelId}/reindex-entities`).then(r => r.data),
  rebuildVectors: (novelId: number) =>
    api.post<{ ok: boolean }>(`/novels/${novelId}/rebuild-vectors`, undefined, { timeout: 300000 }).then(r => r.data),
  search: (novelId: number, query: string) =>
    api.get<SearchResult>(`/novels/${novelId}/search`, { params: { q: query } }).then(r => r.data),
  streamBuild: (
    novelId: number,
    nsfw_mode: boolean,
    onMessage: (msg: BuildSSEMessage) => void,
    onClose: () => void,
  ): AbortController => {
    const controller = new AbortController()
    fetch(`/api/novels/${novelId}/build`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ nsfw_mode }),
      signal: controller.signal,
    }).then(async (response) => {
      await readSseStream<BuildSSEMessage>(response, onMessage)
      onClose()
    }).catch((err) => {
      if (err.name !== 'AbortError') {
        onMessage({ event: 'error', data: String(err) })
      }
      onClose()
    })
    return controller
  },
}

export interface WriterMessage {
  role: string
  content: string
}

export interface ContextPreview {
  chapter_number: number
  meta: Array<{ key: string; label: string; detail: string; source: string; items: string[]; content: string }>
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
  system_source: string
  token_estimate: Record<string, number>
  context_config: Record<string, ContextConfigValue>
  dynamic_budget: {
    target_words: number
    context_window: number
    output_reserve: number
    thinking_reserve: number
    safety_reserve: number
    input_budget: number
    allocations: Record<string, number>
  }
  pricing: {
    model_entry_id: number | null
    model_name: string
    currency: string
    currency_to_cny_rate: number
    input_price_per_million: number
    output_price_per_million: number
    input_price_cny_per_million: number
    output_price_cny_per_million: number
    configured: boolean
    input_tokens: number
    expected_output_tokens: number
    input_cost_cny: number
    output_cost_cny: number
    total_cost_cny: number
    budget_input_cost_cny: number
  }
}

// ── Chapter APIs ───────────────────────────────────────────────────────────

/** 正文机械体检的一条结论。和 Critic 打回用的是同一套规则 */
export interface ProseFinding {
  severity: 'blocking' | 'advisory'
  category: string
  label: string
  evidence: string
}

export interface ProseLintResult {
  findings: ProseFinding[]
  blocking_count: number
}

export const chaptersApi = {
  list: (novelId: number) => api.get<Chapter[]>(`/chapters/novel/${novelId}`).then(r => r.data),
  update: (id: number, data: Partial<Chapter>) => api.patch<Chapter>(`/chapters/${id}`, data).then(r => r.data),
  confirm: (chapterId: number) => api.post('/chapters/confirm', { chapter_id: chapterId }, { timeout: 120000 }).then(r => r.data),
  delete: (id: number) => api.delete(`/chapters/${id}`).then(r => r.data),
  batchDelete: (chapterIds: number[]) =>
    api.post<{ ok: boolean; deleted: number }>('/chapters/batch-delete', { chapter_ids: chapterIds }).then(r => r.data),
  batchVolume: (chapterIds: number[], volume: number) =>
    api.post('/chapters/batch-volume', { chapter_ids: chapterIds, volume }).then(r => r.data),
  discover: (chapterId: number) =>
    api.post<{
      characters: Array<{ name: string; role: string; description: string }>
      entities: Array<{ name: string; type: string; description: string }>
      locations: Array<{ name: string; type: string; description: string; parent_name: string }>
      techniques: Array<{ name: string; type: string; description: string }>
      factions: Array<{ name: string; type: string; description: string }>
    }>(`/chapters/${chapterId}/discover`, {}, { timeout: 60000 }).then(r => r.data),
  lint: (text: string) =>
    api.post<ProseLintResult>('/chapters/lint', { text }).then(r => r.data),
  backfillSummaries: (novelId: number, mode: 'missing' | 'all' = 'missing') =>
    api.post<{
      total: number
      done: number[]
      failed: Array<{ number: number; error: string }>
    }>(`/chapters/novel/${novelId}/backfill-summaries`, { mode }, { timeout: 1800000 }).then(r => r.data),
}

// ── Submission APIs ────────────────────────────────────────────────────────

export interface SensitiveCategory {
  key: string
  label: string
  hint: string
  word_count: number
}

export interface SensitiveHit {
  word: string
  category: string
  position: number
  excerpt: string
}

export interface SensitiveScanResult {
  scanned_chapters: number
  total_hits: number
  word_count: number
  chapters: Array<{
    chapter_id: number
    number: number
    title: string
    hits: SensitiveHit[]
  }>
}

export const submissionApi = {
  /** 触发浏览器下载。导出可能是几十万字，交给 blob 而不是新窗口打开。 */
  export: async (novelId: number, scope: 'confirmed' | 'all', split: 'single' | 'per_chapter') => {
    const res = await api.get(`/submission/novel/${novelId}/export`, {
      params: { scope, split },
      responseType: 'blob',
      timeout: 300000,
    })
    const disposition = String(res.headers['content-disposition'] || '')
    const match = disposition.match(/filename\*=UTF-8''([^;]+)/)
    const filename = match ? decodeURIComponent(match[1]) : `novel.${split === 'per_chapter' ? 'zip' : 'txt'}`
    const url = URL.createObjectURL(res.data as Blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    link.click()
    URL.revokeObjectURL(url)
  },
  sensitiveWords: () =>
    api.get<{ categories: SensitiveCategory[]; custom: Array<{ id: number; word: string; note: string }> }>(
      '/submission/sensitive-words',
    ).then(r => r.data),
  addSensitiveWords: (text: string, note = '') =>
    api.post<{ added: number }>('/submission/sensitive-words', { text, note }).then(r => r.data),
  deleteSensitiveWord: (id: number) =>
    api.delete(`/submission/sensitive-words/${id}`).then(r => r.data),
  scan: (novelId: number, categories: string[], scope: 'confirmed' | 'all', includeCustom: boolean) =>
    api.post<SensitiveScanResult>(`/submission/novel/${novelId}/sensitive-scan`, {
      categories, scope, include_custom: includeCustom,
    }, { timeout: 300000 }).then(r => r.data),
}

// ── Character APIs ─────────────────────────────────────────────────────────

export const charactersApi = {
  list: (novelId: number) => api.get<Character[]>(`/characters/novel/${novelId}`).then(r => r.data),
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
  generateImagePrompt: (characterId: number, style: 'sd_tags' | 'natural_zh') =>
    api.post<{ prompt: string }>(`/characters/${characterId}/generate-image-prompt`, { style }, { timeout: 60000 }).then(r => r.data),
  generateSheet: (characterId: number) =>
    api.post<Character>(`/characters/${characterId}/generate-sheet`, {}, { timeout: 120000 }).then(r => r.data),
}

// ── World Entity APIs ─────────────────────────────────────────────────────

export const worldEntitiesApi = {
  list: (novelId: number, type?: string) =>
    api.get<WorldEntity[]>(`/world-entities/novel/${novelId}`, { params: type ? { type } : {} }).then(r => r.data),
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
  create: (data: Partial<Location>) => api.post<Location>('/locations/', data).then(r => r.data),
  update: (id: number, data: Partial<Location>) => api.patch<Location>(`/locations/${id}`, data).then(r => r.data),
  delete: (id: number) => api.delete(`/locations/${id}`).then(r => r.data),
}

// ── Admin APIs ────────────────────────────────────────────────────────────

export const adminApi = {
  listMemories: (novelId: number) => api.get<Memory[]>(`/admin/novel/${novelId}/memories`).then(r => r.data),
  updateMemory: (id: number, data: { content?: string; in_context?: boolean }) => api.patch<Memory>(`/admin/memories/${id}`, data).then(r => r.data),
  deleteMemory: (id: number) => api.delete(`/admin/memories/${id}`).then(r => r.data),
  listOutlines: (novelId: number) => api.get<OutlineEntry[]>(`/admin/novel/${novelId}/outlines`).then(r => r.data),
  updateOutline: (id: number, data: { title?: string; content?: string }) => api.patch<OutlineEntry>(`/admin/outlines/${id}`, data).then(r => r.data),
  backfillMilestones: (novelId: number, startChapter: number, endChapter: number) =>
    api.post<{ processed: number; extracted: number; failed: number[] }>(
      `/admin/novel/${novelId}/backfill-milestones`,
      { start_chapter: startChapter, end_chapter: endChapter },
      { timeout: 600000 },
    ).then(r => r.data),
}

// ── Corrections APIs（统一搜索 + 修正）─────────────────────────────────────

export type CorrectionSource = 'character' | 'location' | 'chapter' | 'memory' | 'outline'

export interface CorrectionHit {
  source: CorrectionSource
  id: number
  field: string
  title: string
  context: string
  value: string
  match: 'keyword' | 'semantic'
  score: number | null
}

export const correctionsApi = {
  search: (novelId: number, q: string) =>
    api.get<CorrectionHit[]>(`/corrections/novel/${novelId}/search`, { params: { q } }).then(r => r.data),
  apply: (novelId: number, body: { source: CorrectionSource; id: number; field: string; value: string }) =>
    api.post<{ source: string; id: number; field: string; value: string; ok: boolean }>(
      `/corrections/novel/${novelId}/apply`, body,
    ).then(r => r.data),
}

// ── Settings APIs ──────────────────────────────────────────────────────────

export interface ProxyStatus {
  enabled: boolean
  proxy: string
  host: string
  port: number
  reachable: boolean | null
  detail: string
}

export const settingsApi = {
  get: () => api.get('/settings/').then(r => r.data),
  update: (data: object) => api.patch('/settings/', data).then(r => r.data),
  test: (model?: string) => api.post('/settings/test', { model: model ?? '' }).then(r => r.data),
  proxyStatus: () => api.get<ProxyStatus>('/settings/proxy-status').then(r => r.data),
}

// ── Provider APIs ────────────────────────────────────────────────────────────

export const providersApi = {
  list: () => api.get<ApiProvider[]>('/providers/').then(r => r.data),
  create: (data: { name: string; base_url: string; api_key: string; api_format: string; use_proxy?: boolean }) =>
    api.post<ApiProvider>('/providers/', data).then(r => r.data),
  update: (id: number, data: { name?: string; base_url?: string; api_key?: string; api_format?: string; use_proxy?: boolean }) =>
    api.patch<ApiProvider>(`/providers/${id}`, data).then(r => r.data),
  delete: (id: number) => api.delete(`/providers/${id}`).then(r => r.data),
}

// ── Model Library APIs ──────────────────────────────────────────────────────

export const modelLibraryApi = {
  list: () => api.get<ModelEntry[]>('/models/').then(r => r.data),
  create: (data: { display_name: string; model_id: string; provider_id: number; provider?: string; api_format?: string; model_type?: string; context_window?: number; input_price?: number; output_price?: number; price_currency?: string; currency_to_cny_rate?: number }) =>
    api.post<ModelEntry>('/models/', data).then(r => r.data),
  update: (id: number, data: { display_name?: string; model_id?: string; provider_id?: number; model_type?: string; context_window?: number; input_price?: number; output_price?: number; price_currency?: string; currency_to_cny_rate?: number }) =>
    api.patch<ModelEntry>(`/models/${id}`, data).then(r => r.data),
  delete: (id: number) => api.delete(`/models/${id}`).then(r => r.data),
}

// ── Writer Preset APIs ─────────────────────────────────────────────────────

export const writerPresetsApi = {
  list: () => api.get<WriterPreset[]>('/writer-presets/').then(r => r.data),
  create: (data: { name: string; prompt?: string; examples?: ExampleTurn[] }) => api.post<WriterPreset>('/writer-presets/', data).then(r => r.data),
  update: (id: number, data: { name?: string; prompt?: string; examples?: ExampleTurn[] }) => api.patch<WriterPreset>(`/writer-presets/${id}`, data).then(r => r.data),
  delete: (id: number) => api.delete(`/writer-presets/${id}`).then(r => r.data),
}

// ── Prompt Rules APIs ──────────────────────────────────────────────────────

export const promptRulesApi = {
  list: () => api.get<PromptRule[]>('/prompt-rules/').then(r => r.data),
  create: (data: { name: string; content?: string; category?: string; enabled?: boolean; sort_order?: number }) =>
    api.post<PromptRule>('/prompt-rules/', data).then(r => r.data),
  update: (id: number, data: { name?: string; content?: string; category?: string; enabled?: boolean; sort_order?: number }) =>
    api.patch<PromptRule>(`/prompt-rules/${id}`, data).then(r => r.data),
  delete: (id: number) => api.delete(`/prompt-rules/${id}`).then(r => r.data),
}

// ── Tavern APIs（酒馆模式：与小说侧完全独立）─────────────────────────────────

/** 支持 AI 生成/优化的角色卡栏位，与后端 tavern_card_agent 对齐 */
export type TavernAssistField =
  'personality' | 'description' | 'opening_scene' | 'creator_note'

export interface TavernCard {
  id: number
  name: string
  /** 除自己的世界书外，还要一起匹配的角色卡 id */
  linked_book_card_ids: number[]
  /** 角色卡介绍：只给创作者看，后端永不注入 prompt */
  creator_note: string
  personality: string
  opening_scene: string
  system_instruction: string
  description: string
  profile_sections: { appearance?: string; background?: string; abilities?: string; relationships?: string }
  /** 对话示例：作为真实 few-shot 消息轮注入，定腔调最有效的字段 */
  dialogue_examples: ExampleTurn[]
  /** 勾选的酒馆规则 id（不是规则广场）。默认 [] = 不注入，没有小说侧那套 null 三态语义 */
  enabled_rule_ids: number[]
  avatar_url: string
  /** 期望回复字数，0 = 不作要求。写进提示词的软约束，不是 max_tokens 那种硬截断 */
  reply_length: number
  /** 世界书关键词往回扫几条消息，1 = 只看玩家刚发的这句 */
  scan_depth: number
  context_turns: number
  temperature: number
  max_tokens: number
  model_ref: string
  summary_model_ref: string
  session_count: number
  created_at: string
  updated_at: string
}

export interface TavernWorldEntry {
  id: number
  card_id: number
  keywords: string
  content: string
  enabled: boolean
  sort_order: number
  /** 常驻：不看关键词，每轮都注入 */
  constant: boolean
  /** 0 = 拼进 system；n>0 = 并进倒数第 n 条消息开头，离当前对话越近模型越难忽略 */
  depth: number
  created_at: string
  updated_at: string
}

export interface TavernSessionCardRef {
  id: number
  name: string
  avatar_url: string
}

export interface TavernSession {
  id: number
  /** 主卡：权限和会话级操作（摘要、帮我想想）都认它 */
  card_id: number
  /** 参与角色，按发言顺序。长度 > 1 即群聊 */
  cards: TavernSessionCardRef[]
  title: string
  persona_name: string
  persona_desc: string
  summary: string
  summarized_upto_id: number
  message_count: number
  created_at: string
  updated_at: string
}

/** 酒馆写作规则：与规则广场（PromptRule）分开两张表，那批是按写小说正文调的 */
export interface TavernRule {
  id: number
  name: string
  content: string
  enabled: boolean
  sort_order: number
  created_at: string
  updated_at: string
}

/** 常用系统指令：建卡时可直接取用，与小说侧 writer_presets 各存一份 */
export interface TavernInstructionPreset {
  id: number
  name: string
  content: string
  created_at: string
  updated_at: string
}

export interface TavernMessage {
  id: number
  session_id: number
  role: string
  /** 说话人。null = 玩家消息，或群聊之前的老数据（回落到主卡） */
  card_id: number | null
  content: string
  input_tokens: number
  output_tokens: number
  created_at: string
}

export const tavernApi = {
  cards: {
    list: () => api.get<TavernCard[]>('/tavern/cards/').then(r => r.data),
    get: (id: number) => api.get<TavernCard>(`/tavern/cards/${id}`).then(r => r.data),
    create: (data: Partial<TavernCard> & { name: string }) =>
      api.post<TavernCard>('/tavern/cards/', data).then(r => r.data),
    update: (id: number, data: Partial<TavernCard>) =>
      api.patch<TavernCard>(`/tavern/cards/${id}`, data).then(r => r.data),
    delete: (id: number) => api.delete(`/tavern/cards/${id}`).then(r => r.data),
    uploadAvatar: (id: number, file: File) => {
      const form = new FormData()
      form.append('file', file)
      return api.post<TavernCard>(`/tavern/cards/${id}/avatar`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      }).then(r => r.data)
    },
    deleteAvatar: (id: number) =>
      api.delete<TavernCard>(`/tavern/cards/${id}/avatar`).then(r => r.data),
    // 传当前表单文本而不是 card_id：新卡还没保存时也要能用
    assist: (data: {
      field: TavernAssistField
      name?: string
      personality?: string
      description?: string
      profile_sections?: TavernCard['profile_sections']
      opening_scene?: string
    }) => api.post<{ text: string }>('/tavern/cards/assist', data, { timeout: 180000 })
      .then(r => r.data),
  },
  worldEntries: {
    list: (cardId: number) =>
      api.get<TavernWorldEntry[]>(`/tavern/cards/${cardId}/world-entries`).then(r => r.data),
    create: (cardId: number, data: Partial<Omit<TavernWorldEntry, 'id' | 'card_id' | 'created_at' | 'updated_at'>>) =>
      api.post<TavernWorldEntry>(`/tavern/cards/${cardId}/world-entries`, data).then(r => r.data),
    update: (id: number, data: Partial<Omit<TavernWorldEntry, 'id' | 'card_id' | 'created_at' | 'updated_at'>>) =>
      api.patch<TavernWorldEntry>(`/tavern/world-entries/${id}`, data).then(r => r.data),
    delete: (id: number) => api.delete(`/tavern/world-entries/${id}`).then(r => r.data),
  },
  sessions: {
    list: (cardId: number) =>
      api.get<TavernSession[]>(`/tavern/cards/${cardId}/sessions`).then(r => r.data),
    get: (id: number) => api.get<TavernSession>(`/tavern/sessions/${id}`).then(r => r.data),
    create: (cardId: number, data: { title?: string; persona_name?: string; persona_desc?: string }) =>
      api.post<TavernSession>(`/tavern/cards/${cardId}/sessions`, data).then(r => r.data),
    // 群聊：card_ids 首个为主卡
    createGroup: (cardIds: number[], data: { title?: string; persona_name?: string; persona_desc?: string }) =>
      api.post<TavernSession>('/tavern/sessions', { ...data, card_ids: cardIds }).then(r => r.data),
    update: (id: number, data: { title?: string; persona_name?: string; persona_desc?: string }) =>
      api.patch<TavernSession>(`/tavern/sessions/${id}`, data).then(r => r.data),
    delete: (id: number) => api.delete(`/tavern/sessions/${id}`).then(r => r.data),
  },
  rules: {
    list: () => api.get<TavernRule[]>('/tavern/rules/').then(r => r.data),
    create: (data: { name: string; content?: string; enabled?: boolean; sort_order?: number }) =>
      api.post<TavernRule>('/tavern/rules/', data).then(r => r.data),
    update: (id: number, data: { name?: string; content?: string; enabled?: boolean; sort_order?: number }) =>
      api.patch<TavernRule>(`/tavern/rules/${id}`, data).then(r => r.data),
    delete: (id: number) => api.delete(`/tavern/rules/${id}`).then(r => r.data),
  },
  instructionPresets: {
    list: () =>
      api.get<TavernInstructionPreset[]>('/tavern/instruction-presets/').then(r => r.data),
    create: (data: { name: string; content: string }) =>
      api.post<TavernInstructionPreset>('/tavern/instruction-presets/', data).then(r => r.data),
    update: (id: number, data: { name?: string; content?: string }) =>
      api.patch<TavernInstructionPreset>(`/tavern/instruction-presets/${id}`, data).then(r => r.data),
    delete: (id: number) => api.delete(`/tavern/instruction-presets/${id}`).then(r => r.data),
  },
  messages: {
    list: (sessionId: number) =>
      api.get<TavernMessage[]>(`/tavern/sessions/${sessionId}/messages`).then(r => r.data),
    update: (id: number, content: string) =>
      api.patch<TavernMessage>(`/tavern/messages/${id}`, { content }).then(r => r.data),
    delete: (id: number) => api.delete(`/tavern/messages/${id}`).then(r => r.data),
  },
  suggest: (sessionId: number) =>
    api.post<{ suggestions: string[] }>(
      `/tavern/sessions/${sessionId}/suggest`, {}, { timeout: 120000 },
    ).then(r => r.data),
}

// ── RPG APIs ───────────────────────────────────────────────────────────────

/** 判定难度档位。模型只能从这五档里挑，成功率由模组的 rate_table 定 */
export type RpgBand = 'trivial' | 'easy' | 'medium' | 'hard' | 'extreme'

/** 数值的一档。只写下界 `at`，不写区间——见 rpg_state.tier_list */
export interface RpgStatTier {
  /** 到多少算这一档（含）。生效的是 at <= 值 里最大的那个。
   *  没填的行会被后端跳过，所以这里允许缺省——作者刚点「添加一档」就是这状态 */
  at?: number
  /** 短标签，画在数字后面给玩家看。如「亲近」 */
  label?: string
  /** 这一档什么表现。只给模型看，不进玩家侧 */
  note?: string
}

/** 一项数值的定义。玩家数值和关系数值共用这个形状 */
export interface RpgStatDef {
  name: string
  initial: number
  min: number
  /** null = 无上限（钱、声望这种） */
  max: number | null
  /** 能不能拿来判定。资金不行，敏捷可以 */
  for_check?: boolean
  /** 无 / 死亡 / 标记 */
  on_zero?: string
  /** 条 / 数字 / 隐藏 */
  display?: string
  /** 跨天回满（回到 max）。只在有上限的项上有意义 */
  reset_daily?: boolean
  /** 这个数值影响什么。每轮发给模型一句，作者不写就没有 */
  effect?: string
  /** 分档。空数组和没写是一回事 */
  tiers?: RpgStatTier[]
}

/** 统一条件格式。世界书触发、动作按钮可用性、地点进入条件共用 */
export interface RpgCondition {
  stats?: Record<string, { op: string; value: number }>
  relations?: { npc: string; stat: string; op: string; value: number }[]
  /** 「!xxx」表示这条 flag 不能立着 */
  flags?: string[]
  items?: string[]
  /** 当前时段必须是其中之一，「!晚」表示不能在晚上。模组没设时段时一律不成立 */
  slots?: string[]
  /** 天数门槛，形状同 stats */
  day?: { op: string; value: number }
}

/** 玩法类别。和 genre 是两根正交的轴：genre 说「世界长什么样」，
 *  这个说「这局怎么玩」。同一个魔法学院可以是模拟养成也可以是探索冒险 */
export type RpgPlayStyle = 'sim' | 'rpg' | 'slg'

/** 支持 AI 生成/优化的模组栏位，与后端 agents/rpg_assist.py 的 FIELD_SPECS 对齐。
 *  两边是手工对齐的：这里多写一个，后端会回 400 */
export type RpgAssistField =
  | 'worldview' | 'opening_scene' | 'system_instruction' | 'narration_sample'
  | 'npc_persona' | 'npc_appearance' | 'npc_description'
  | 'location_description' | 'item_description'

/** 模组（剧本）：一份可反复开局的世界设定，对应酒馆的角色卡 */
export interface RpgModule {
  id: number
  name: string
  /** 只给作者看，后端永不注入 prompt */
  creator_note: string
  /** 题材（都市 / 魔法学院 / 互动养成…），进 GM 提示词 */
  genre: string
  /** 玩法类别。老模组读出来是 'rpg'；后端对未知值一律按 'rpg' 算 */
  play_style: RpgPlayStyle
  worldview: string
  /** 开局旁白，建局时落成首条 assistant 消息 */
  opening_scene: string
  system_instruction: string
  /** 勾选的写作规则 id（rpg_rules）。默认 [] = 不注入 */
  enabled_rule_ids: number[]
  /** 叙事腔调样例，作为文字引用进 system，不做真实 few-shot 轮 */
  narration_sample: string
  cover_url: string
  /** 玩家数值定义 */
  stat_defs: RpgStatDef[]
  /** 关系数值定义。定义一次，每个角色各持一份 */
  relation_stat_defs: RpgStatDef[]
  default_inventory: RpgInvItem[]
  default_location: string
  /** 默认时段表，如 ["早","中","晚"]。空 = 这个模组不用时段 */
  time_slots: string[]
  /** 档位 → 成功率(%)。绝对难度由模组作者锁定，模型只管相对档位 */
  rate_table: Record<RpgBand, number>
  /** 整体难度旋钮，加到成功率上。-10 轻松 / +10 手软 */
  difficulty_bias: number
  /** never = 纯叙事（默认）/ smart = AI 判断要不要判 / always = 每轮都判 */
  check_mode: 'smart' | 'always' | 'never'
  /** 开了判定之后，掷不掷随机数。关掉则同一存档重玩结果一样 */
  random_check: boolean
  scan_depth: number
  context_turns: number
  temperature: number
  max_tokens: number
  reply_length: number
  model_ref: string
  /** 裁决 / 结算 / 建议共用的便宜模型 */
  fast_model_ref: string
  /** 压缩旧剧情用。空 = 跟着 fast_model_ref 走 */
  summary_model_ref: string
  /** 推时段时写一句「别处此刻在发生什么」进大事记。**默认关**：
   *  开了之后「结束这个时段」就不再是零模型调用了 */
  offscreen_brief: boolean
  session_count: number
  npc_count: number
  entry_count: number
  created_at: string
  updated_at: string
}

/** RPG 写作规则。独立规则库，不复用酒馆 / 小说侧那两张表 */
export interface RpgRule {
  id: number
  name: string
  content: string
  enabled: boolean
  sort_order: number
  created_at: string
  updated_at: string
}

/** 背包里的一行。和模组的道具定义 RpgItem 是两回事 */
export interface RpgInvItem {
  name: string
  qty: number
  note?: string
}

/** 模组定义的道具。「使用」时由引擎按 effects 精确增减，AI 碰不到 */
export interface RpgItem {
  id: number
  module_id: number
  name: string
  description: string
  category: string
  usable: boolean
  consumable: boolean
  /** 开局就带在身上。和模组的「开局背包」default_inventory 不是一回事：
   *  那是这一局开场凭空多出来的一件东西，这是这件道具本身就该在玩家身上。
   *  建局时两边合并，同名的算一件 */
  start_with: boolean
  /** 数值增减 {"精力": 20, "资金": -50} */
  effects: Record<string, number>
  sort_order: number
  created_at: string
  updated_at: string
}

/** 地点。connections 存名字不存 id——NPC.location 本来就是字符串 */
export interface RpgLocation {
  id: number
  module_id: number
  name: string
  description: string
  connections: string[]
  enter_requires: RpgCondition
  sort_order: number
  /** 地图上的位置，百分比 0..100。两个都是 0 = 作者还没摆过，落兜底网格 */
  x: number
  y: number
  created_at: string
  updated_at: string
}

/** 动作按钮。点一次数值由引擎算死，AI 只负责写成画面 */
export interface RpgAction {
  id: number
  module_id: number
  name: string
  /** 点了等于玩家说了这句话 */
  prompt_hint: string
  effects: Record<string, number>
  /** 对目标角色的关系数值增减 */
  relation_effects: Record<string, number>
  requires: RpgCondition
  /** 要不要先选一个在场角色 */
  needs_target: boolean
  sort_order: number
  created_at: string
  updated_at: string
}

export interface RpgWorldEntry {
  id: number
  module_id: number
  keywords: string
  content: string
  enabled: boolean
  sort_order: number
  /** 常驻：不看关键词，每轮都注入 */
  constant: boolean
  /** 0 = 拼进 system；n>0 = 并进倒数第 n 条消息开头 */
  depth: number
  /** 附加条件。空 = 无条件。常驻 + 条件 = 跨过某条线就解锁 */
  trigger_condition: RpgCondition
  created_at: string
  updated_at: string
}

export interface RpgNpc {
  id: number
  module_id: number
  name: string
  /** protagonist = 主角模板，开局时预填玩家角色 */
  role: 'npc' | 'protagonist'
  avatar_url: string
  description: string
  persona: string
  /** 只在首次见面时注入，之后省掉这段 token */
  appearance: string
  /** 常驻地点。等于当前局的 location 即视为在场 */
  location: string
  /** 作息表：{"早": "大礼堂", "晚": "寝室"}。当前时段在这张表里有值就用它，
   *  没有就落回 location。后端的 rpg_context.npc_place 是同一套算法 */
  slot_locations: Record<string, string>
  /** 额外触发词：人不在场但被提到也注入 */
  keywords: string
  /** 勾上之后，这一轮没提到她时她自己过日子：模型写一句「最近在做什么」，
   *  记在这一局的 npc_activities 里，下回见面时注入。默认关 */
  ai_scheduled: boolean
  /** 分栏档案，照抄酒馆卡：外貌身材 / 背景故事 / … */
  profile_sections: Record<string, string>
  dialogue_examples: { user: string; assistant: string }[]
  /** 覆盖这个角色的关系数值起点（青梅竹马开局好感就该更高） */
  initial_state: Record<string, number | boolean>
  sort_order: number
  created_at: string
  updated_at: string
}

/** 一局存档。世界的权威状态（数值/背包/地点）就在这上面 */
export interface RpgSession {
  id: number
  module_id: number
  title: string
  /** 数值按 on_zero=死亡 归零后端置 dead，前端据此拦输入 */
  status: 'alive' | 'dead' | 'ended'
  char_name: string
  char_desc: string
  /** 玩家数值，键由模组的 stat_defs 决定 */
  stats: Record<string, number>
  inventory: RpgInvItem[]
  location: string
  /** 这一局自己的时段表，建局时从模组拷来。空 = 不用时段 */
  time_slots: string[]
  /** 当前时段，存的是名字。空 = 没有时钟 */
  slot: string
  day: number
  flags: Record<string, string | number | boolean | null>
  /** {"3": {"好感": 62, "met": true}}，键是 npc_id 的字符串 */
  npc_states: Record<string, Record<string, number | boolean>>
  /** GM 这一局边玩边记下的 NPC 近况。{"3": {"伤势": "左肩中刀"}}，值一律是字符串。
   *  和 npc_states 分开存：那边的值是关系数字，合在一起会被字符串盖掉 */
  npc_notes: Record<string, Record<string, string>>
  /** AI 调度给不在场的人记的那一句「最近在做什么」。{"3": "在图书馆翻旧报纸"}。
   *  和 npc_notes 分开存，后端的 rpg_state.apply_npc_activity 是同一个意思 */
  npc_activities: Record<string, string>
  /** 剧情把谁挪到哪儿了：{"3": "校长办公室"}。你在对话框里说「你过来」，
   *  结算从刚写出的正文里读出她的新位置写在这——它优先于作息表，推时段清空。
   *  取值口径见 condition.npcPlace（后端 rpg_context.npc_place 的镜像） */
  npc_places: Record<string, string>
  /** 大事记：已经「传开」的事，跨对话线共享。注入时排在【外场】 */
  chronicle: string[]
  /** 去过的地点名。地图的迷雾按它散开 */
  visited: string[]
  summary: string
  summarized_upto_id: number
  turn_count: number
  created_at: string
  updated_at: string
}

/** 一张存档。存的是「这一回合发生之前」的干净状态 */
export interface RpgSave {
  id: number
  session_id: number
  /** auto 每回合自动拍、只留最近 30 张；manual 永不自动清 */
  kind: 'auto' | 'manual'
  label: string
  turn_index: number
  before_message_id: number
  created_at: string
}

/** 本回合判定，只挂在 user 行上。null = 这轮没判定 */
export interface RpgRoll {
  need_check: boolean
  attr: string
  band: RpgBand
  intent: string
  reason: string
  /** 成功率(%)。玩家看得懂这个，看不懂「D20+2 对抗 16」 */
  rate?: number
  /** 掷点 1~100，越低越好。0 = 关了随机，前端只显示成功率 */
  dice?: number
  outcome?: RpgOutcome
}

/** 五档结果。narrow = 险胜：做成了但付出看得见的代价 */
export type RpgOutcome = 'crit_success' | 'success' | 'narrow' | 'fail' | 'crit_fail'

export interface RpgMessage {
  id: number
  session_id: number
  role: 'user' | 'assistant'
  content: string
  /** 这条消息发生在哪个地点。统一时间线之后一屏里会混着几个地方的戏，
   *  前端靠它在换地方的地方插一条分隔 */
  location: string
  /** 当时在场的 NPC id。看某个人的视角就按它筛——他参与过的群戏也在里面。
   *  null = 不知道（迁移过来的老消息），当所有人可见：不知道不等于没有 */
  present: number[] | null
  roll: RpgRoll | null
  state_delta: Record<string, unknown> | null
  suggestions: string[] | null
  /** 叙事那次调用的消耗 */
  input_tokens: number
  output_tokens: number
  /** 裁决 + 结算 + 建议的合计，和叙事分开显示 */
  aux_input_tokens: number
  aux_output_tokens: number
  created_at: string
}

type RpgEntryInput = Partial<Omit<RpgWorldEntry, 'id' | 'module_id' | 'created_at' | 'updated_at'>>
type RpgNpcInput = Partial<Omit<RpgNpc, 'id' | 'module_id' | 'created_at' | 'updated_at'>>
type RpgItemInput = Partial<Omit<RpgItem, 'id' | 'module_id' | 'created_at' | 'updated_at'>>
type RpgLocationInput = Partial<Omit<RpgLocation, 'id' | 'module_id' | 'created_at' | 'updated_at'>>
type RpgActionInput = Partial<Omit<RpgAction, 'id' | 'module_id' | 'created_at' | 'updated_at'>>

/** 道具 / 地点 / 动作三套 CRUD 形状完全一样，和后端的路由工厂一一对应 */
function moduleChild<T, I>(prefix: string) {
  return {
    list: (moduleId: number) =>
      api.get<T[]>(`/rpg/modules/${moduleId}/${prefix}/`).then(r => r.data),
    create: (moduleId: number, data: I & { name: string }) =>
      api.post<T>(`/rpg/modules/${moduleId}/${prefix}/`, data).then(r => r.data),
    update: (id: number, data: I) =>
      api.patch<T>(`/rpg/${prefix}/${id}`, data).then(r => r.data),
    delete: (id: number) => api.delete(`/rpg/${prefix}/${id}`).then(r => r.data),
  }
}

/** 构思向导抽取时喂给后端的白名单：前面几步已经定过的名字。
 *  后端用它过滤角色/道具/动作引用的数值名和地点名 */
/** 单摊一键生成支持的类别，同后端 rpg_wizard.KINDS */
export type RpgGenerateKind = 'location' | 'npc' | 'item' | 'action'

export interface RpgWizardKnown {
  stat_names?: string[]
  relation_names?: string[]
  location_names?: string[]
}

/** 一步抽取的结果。字段全 Optional：一次只返回当前这步那一摊。
 *  dropped 是被白名单过滤掉的引用的说明，必须显示给作者看 */
export interface RpgWizardExtract {
  genre?: string
  worldview?: string
  opening_scene?: string
  system_instruction?: string
  narration_sample?: string
  stat_defs?: RpgStatDef[]
  relation_stat_defs?: RpgStatDef[]
  locations?: Array<{ name: string; description: string; connections: string[] }>
  default_location?: string
  npcs?: Array<{
    name: string; persona: string; appearance: string; description: string
    location: string; initial_state: Record<string, number>
  }>
  items?: Array<{
    name: string; description: string; category: string
    consumable: boolean; start_with: boolean; effects: Record<string, number>
  }>
  actions?: Array<{
    name: string; prompt_hint: string; needs_target: boolean
    effects: Record<string, number>; relation_effects: Record<string, number>
  }>
  dropped: string[]
}

export const rpgApi = {
  modules: {
    list: () => api.get<RpgModule[]>('/rpg/modules/').then(r => r.data),
    get: (id: number) => api.get<RpgModule>(`/rpg/modules/${id}`).then(r => r.data),
    create: (data: Partial<RpgModule> & { name: string }) =>
      api.post<RpgModule>('/rpg/modules/', data).then(r => r.data),
    update: (id: number, data: Partial<RpgModule>) =>
      api.patch<RpgModule>(`/rpg/modules/${id}`, data).then(r => r.data),
    delete: (id: number) => api.delete(`/rpg/modules/${id}`).then(r => r.data),
    uploadCover: (id: number, file: File) => {
      const form = new FormData()
      form.append('file', file)
      return api.post<RpgModule>(`/rpg/modules/${id}/cover`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      }).then(r => r.data)
    },
    deleteCover: (id: number) =>
      api.delete<RpgModule>(`/rpg/modules/${id}/cover`).then(r => r.data),
    /** 帮作者写某一栏。不落库，返回的文字由作者决定要不要用。
     *  超时放宽到 3 分钟：这是一次完整的创作生成，不是补全 */
    assist: (
      moduleId: number,
      data: { field: RpgAssistField; content?: string; context?: Record<string, string> },
    ) =>
      api.post<{ text: string }>(`/rpg/modules/${moduleId}/assist`, data, {
        timeout: 180000,
      }).then(r => r.data),
    /** 构思向导：抽当前这一步聊定的结论。known 带前面已定的名字白名单，
     *  后端按它过滤角色/道具引用的数值名和地点名，对不上的进 dropped */
    wizardExtract: (
      moduleId: number,
      data: { stage: string; messages: ChatMessage[]; known?: RpgWizardKnown; model?: string },
    ) =>
      api.post<RpgWizardExtract>(`/rpg/modules/${moduleId}/wizard/extract`, data, {
        timeout: 180000,
      }).then(r => r.data),
    /** 在某一摊（地点/角色/道具/动作）点「AI 生成」。白名单由后端查库，不用前端传。
     *  返回结构同 wizardExtract，只会含 kind 对应那一摊的列表 */
    generate: (
      moduleId: number,
      kind: RpgGenerateKind,
      data: { instruction?: string; count?: number; nsfw?: boolean; model?: string },
    ) =>
      api.post<RpgWizardExtract>(`/rpg/modules/${moduleId}/generate/${kind}`, data, {
        timeout: 180000,
      }).then(r => r.data),
  },
  worldEntries: {
    list: (moduleId: number) =>
      api.get<RpgWorldEntry[]>(`/rpg/modules/${moduleId}/entries/`).then(r => r.data),
    create: (moduleId: number, data: RpgEntryInput) =>
      api.post<RpgWorldEntry>(`/rpg/modules/${moduleId}/entries/`, data).then(r => r.data),
    update: (id: number, data: RpgEntryInput) =>
      api.patch<RpgWorldEntry>(`/rpg/entries/${id}`, data).then(r => r.data),
    delete: (id: number) => api.delete(`/rpg/entries/${id}`).then(r => r.data),
  },
  npcs: {
    list: (moduleId: number) =>
      api.get<RpgNpc[]>(`/rpg/modules/${moduleId}/npcs/`).then(r => r.data),
    create: (moduleId: number, data: RpgNpcInput & { name: string }) =>
      api.post<RpgNpc>(`/rpg/modules/${moduleId}/npcs/`, data).then(r => r.data),
    update: (id: number, data: RpgNpcInput) =>
      api.patch<RpgNpc>(`/rpg/npcs/${id}`, data).then(r => r.data),
    delete: (id: number) => api.delete(`/rpg/npcs/${id}`).then(r => r.data),
    uploadAvatar: (id: number, file: File) => {
      const form = new FormData()
      form.append('file', file)
      return api.post<RpgNpc>(`/rpg/npcs/${id}/avatar`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      }).then(r => r.data)
    },
    deleteAvatar: (id: number) =>
      api.delete<RpgNpc>(`/rpg/npcs/${id}/avatar`).then(r => r.data),
  },
  items: moduleChild<RpgItem, RpgItemInput>('items'),
  locations: moduleChild<RpgLocation, RpgLocationInput>('locations'),
  actions: moduleChild<RpgAction, RpgActionInput>('actions'),
  rules: {
    list: () => api.get<RpgRule[]>('/rpg/rules/').then(r => r.data),
    create: (data: { name: string; content?: string; enabled?: boolean; sort_order?: number }) =>
      api.post<RpgRule>('/rpg/rules/', data).then(r => r.data),
    update: (id: number, data: { name?: string; content?: string; enabled?: boolean; sort_order?: number }) =>
      api.patch<RpgRule>(`/rpg/rules/${id}`, data).then(r => r.data),
    delete: (id: number) => api.delete(`/rpg/rules/${id}`).then(r => r.data),
  },
  sessions: {
    list: (moduleId: number) =>
      api.get<RpgSession[]>(`/rpg/modules/${moduleId}/sessions/`).then(r => r.data),
    get: (id: number) => api.get<RpgSession>(`/rpg/sessions/${id}`).then(r => r.data),
    create: (moduleId: number, data: { char_name: string; char_desc?: string; title?: string; stats?: Record<string, number>; location?: string; time_slots?: string[] }) =>
      api.post<RpgSession>(`/rpg/modules/${moduleId}/sessions/`, data).then(r => r.data),
    /** 结束当前时段。纯引擎，不调模型，所以是普通请求不是 SSE */
    advance: (id: number) =>
      api.post<{ session: RpgSession; facts: string[] }>(
        `/rpg/sessions/${id}/advance`,
      ).then(r => r.data),
    /** 瞬移：从地点总览点一个地方就直接过去。同样零 LLM 调用 */
    move: (id: number, target: string) =>
      api.post<{ session: RpgSession; message: string }>(
        `/rpg/sessions/${id}/move`, { target },
      ).then(r => r.data),
    update: (id: number, data: { title?: string }) =>
      api.patch<RpgSession>(`/rpg/sessions/${id}`, data).then(r => r.data),
    /** 划掉 GM 记错的一条 NPC 近况。没有这个口子，记错了只能读档 */
    deleteNpcNote: (id: number, npcId: number, key: string) =>
      api.patch<RpgSession>(`/rpg/sessions/${id}/npc-notes/${npcId}`, { key }).then(r => r.data),
    /** 划掉 AI 调度给这个人记的那句「最近在做什么」。只清这一句，
     *  「AI 调度」开关是模组作者的决定，改它要回模组页 */
    deleteNpcActivity: (id: number, npcId: number) =>
      api.delete<RpgSession>(`/rpg/sessions/${id}/npc-activity/${npcId}`).then(r => r.data),
    delete: (id: number) => api.delete(`/rpg/sessions/${id}`).then(r => r.data),
  },
  messages: {
    list: (sessionId: number) =>
      api.get<RpgMessage[]>(`/rpg/sessions/${sessionId}/messages/`).then(r => r.data),
    delete: (id: number) => api.delete(`/rpg/messages/${id}`).then(r => r.data),
  },
  saves: {
    list: (sessionId: number) =>
      api.get<RpgSave[]>(`/rpg/sessions/${sessionId}/saves/`).then(r => r.data),
    create: (sessionId: number, label: string) =>
      api.post<RpgSave>(`/rpg/sessions/${sessionId}/saves/`, { label }).then(r => r.data),
    /** 读档：返回回溯之后的局。比这张更晚的存档会一并作废 */
    restore: (id: number) =>
      api.post<RpgSession>(`/rpg/saves/${id}/restore`).then(r => r.data),
    delete: (id: number) => api.delete(`/rpg/saves/${id}`).then(r => r.data),
  },
  /** 「帮我想想」看的是整条时间线：全场只有一条历史，隔壁刚聊的那几句
   *  就是你的前情 */
  suggest: (sessionId: number, focusNpcId?: number | null) =>
    api.post<{ suggestions: string[] }>(
      `/rpg/sessions/${sessionId}/suggest`,
      focusNpcId ? { focus_npc_id: focusNpcId } : {},
      { timeout: 120000 },
    ).then(r => r.data),
}

// ── Glossary APIs ──────────────────────────────────────────────────────────

export const glossaryApi = {
  list: (novelId: number) =>
    api.get<GlossaryEntry[]>(`/glossary/novel/${novelId}`).then(r => r.data),
  create: (data: { novel_id: number; term: string; category?: string; forbidden_variants?: string; notes?: string; importance?: number }) =>
    api.post<GlossaryEntry>('/glossary/', data).then(r => r.data),
  update: (id: number, data: { term?: string; category?: string; forbidden_variants?: string; notes?: string; importance?: number }) =>
    api.patch<GlossaryEntry>(`/glossary/${id}`, data).then(r => r.data),
  delete: (id: number) =>
    api.delete(`/glossary/${id}`).then(r => r.data),
}

// ── Text Replace APIs（全书批量替换）────────────────────────────────────────

export type ReplaceScope = 'content' | 'summary' | 'outline' | 'memory'

export interface ReplaceRow {
  table: string
  row_id: number
  field: string
  label: string
  count: number
  snippets: string[]
}

export interface ReplacePreview {
  find: string
  scope: ReplaceScope[]
  total_occurrences: number
  affected_rows: number
  rows: ReplaceRow[]
  truncated: boolean
}

export interface ReplaceBackup {
  id: number
  find_text: string
  replace_text: string
  scope: ReplaceScope[]
  affected_rows: number
  total_occurrences: number
  created_at: string
  undone_at: string | null
}

export const textReplaceApi = {
  preview: (novelId: number, find: string, scope: ReplaceScope[]) =>
    api.get<ReplacePreview>(`/text-replace/novel/${novelId}/preview`, {
      params: { find, scope },
      // axios 默认把数组序列化成 scope[]=a，FastAPI 要 scope=a&scope=b
      paramsSerializer: { indexes: null },
    }).then(r => r.data),
  apply: (novelId: number, find: string, replace: string, scope: ReplaceScope[]) =>
    api.post<{ ok: boolean; backup_id: number; affected_rows: number; total_occurrences: number }>(
      `/text-replace/novel/${novelId}/apply`,
      { find, replace, scope },
      { timeout: 300000 },
    ).then(r => r.data),
  undo: (novelId: number, backupId: number) =>
    api.post<{ ok: boolean; restored_rows: number; missing_rows: number }>(
      `/text-replace/novel/${novelId}/undo/${backupId}`,
      {},
      { timeout: 300000 },
    ).then(r => r.data),
  backups: (novelId: number) =>
    api.get<ReplaceBackup[]>(`/text-replace/novel/${novelId}/backups`).then(r => r.data),
}

// ── World Rules APIs（核心规则/特殊元素）─────────────────────────────────────

export const worldRulesApi = {
  list: (novelId: number, kind?: 'rule' | 'element') =>
    api.get<WorldRule[]>(`/world-rules/novel/${novelId}`, { params: kind ? { kind } : undefined }).then(r => r.data),
  create: (data: { novel_id: number; kind: 'rule' | 'element'; title?: string; content?: string; importance?: number; enabled?: boolean }) =>
    api.post<WorldRule>('/world-rules/', data).then(r => r.data),
  update: (id: number, data: { title?: string; content?: string; importance?: number; enabled?: boolean }) =>
    api.patch<WorldRule>(`/world-rules/${id}`, data).then(r => r.data),
  delete: (id: number) =>
    api.delete(`/world-rules/${id}`).then(r => r.data),
}

// ── Generation APIs ─────────────────────────────────────────────────────────

export const generationApi = {
  review: (novelId: number) =>
    api.post<ReviewResult>('/generation/review', { novel_id: novelId }, { timeout: 300000 }).then(r => r.data),
}

// ── Novel Notes APIs ──────────────────────────────────────────────────────

export const novelNotesApi = {
  list: (novelId: number) =>
    api.get<NovelNote[]>(`/notes/novel/${novelId}`).then(r => r.data),
  create: (data: { novel_id: number; title: string; content?: string; importance?: number }) =>
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

// ── Worldview Change APIs ─────────────────────────────────────────────────

export const worldviewChangesApi = {
  list: (novelId: number) =>
    api.get<WorldviewChange[]>(`/worldview-changes/novel/${novelId}`).then(r => r.data),
  create: (data: Partial<WorldviewChange> & { novel_id: number; fact: string }) =>
    api.post<WorldviewChange>('/worldview-changes/', data).then(r => r.data),
  update: (id: number, data: Partial<WorldviewChange>) =>
    api.patch<WorldviewChange>(`/worldview-changes/${id}`, data).then(r => r.data),
  delete: (id: number) =>
    api.delete(`/worldview-changes/${id}`).then(r => r.data),
  scan: (novelId: number) =>
    api.post<{ detected: number; added: number }>(`/worldview-changes/novel/${novelId}/scan`, {}, { timeout: 300000 }).then(r => r.data),
}

// ── Durable Foreshadowing / Secret APIs ───────────────────────────────────

export interface StaleThreadReport {
  current_chapter: number
  active_count: number
  expired_count: number
  stale_after: number
  /** 在场条数偏多/偏少的提示，正常时为空串 */
  density_hint: string
  stale: Array<Pick<StoryThread, 'id' | 'kind' | 'title' | 'content' | 'source_chapter' | 'due_chapter' | 'importance'> & { reason: string }>
}

export const storyThreadsApi = {
  list: (novelId: number, kind?: StoryThreadKind, status?: StoryThreadStatus) =>
    api.get<StoryThread[]>(`/story-threads/novel/${novelId}`, {
      params: { ...(kind ? { kind } : {}), ...(status ? { status } : {}) },
    }).then(r => r.data),
  create: (data: Partial<StoryThread> & { novel_id: number; kind: StoryThreadKind; content: string }) =>
    api.post<StoryThread>('/story-threads/', data).then(r => r.data),
  update: (id: number, data: Partial<StoryThread>) =>
    api.patch<StoryThread>(`/story-threads/${id}`, data).then(r => r.data),
  delete: (id: number) =>
    api.delete(`/story-threads/${id}`).then(r => r.data),
  stale: (novelId: number) =>
    api.get<StaleThreadReport>(`/story-threads/novel/${novelId}/stale`).then(r => r.data),
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

// ── Prompt APIs ──────────────────────────────────────────────────────────

export interface PromptInfo {
  name: string
  category: string
  label: string
  description: string
}

export interface PromptContent {
  name: string
  content: string
}

export const promptsApi = {
  list: () => api.get<PromptInfo[]>('/prompts/').then(r => r.data),
  get: (name: string) => api.get<PromptContent>(`/prompts/${encodeURIComponent(name)}`).then(r => r.data),
  update: (name: string, content: string) => api.put<PromptContent>(`/prompts/${encodeURIComponent(name)}`, { content }).then(r => r.data),
}

// ── Volume APIs ───────────────────────────────────────────────────────────

export const volumesApi = {
  list: (novelId: number) =>
    api.get<Volume[]>(`/volumes/novel/${novelId}`).then(r => r.data),
  create: (data: { novel_id: number; number: number; title: string; description?: string }
    & Partial<Pick<Volume, 'endgame_cards' | 'power_tiers' | 'tier_count' | 'words_per_tier'>>) =>
    api.post<Volume>('/volumes/', data).then(r => r.data),
  update: (id: number, data: Partial<Pick<Volume, 'title' | 'description' | 'endgame_cards' | 'power_tiers' | 'tier_count' | 'words_per_tier' | 'spent_payoffs'>>) =>
    api.patch<Volume>(`/volumes/${id}`, data).then(r => r.data),
  delete: (id: number) =>
    api.delete(`/volumes/${id}`).then(r => r.data),
}

// ── Outline APIs ──────────────────────────────────────────────────────────

export interface HealthFinding {
  level: 'warn' | 'info'
  label: string
  detail: string
}

export interface PlanOptions {
  chapter_roles: string[]
  emotion_tones: string[]
  hook_types: string[]
}

export interface OutlineHealth {
  chapter_count: number
  total_target_words: number
  chapters: HealthFinding[]
  volumes: Array<{ number: number; title: string; findings: HealthFinding[] }>
}

/** 执行计划字段，创建与修改共用 */
export type OutlinePlanFields = Partial<
  Pick<OutlineEntry, 'chapter_role' | 'emotion_tone' | 'emotion_intensity' | 'hook_type' | 'hook_strength'>
>

export const outlinesApi = {
  list: (novelId: number) =>
    api.get<OutlineEntry[]>(`/outlines/novel/${novelId}`).then(r => r.data),
  create: (data: OutlinePlanFields & { novel_id: number; start_chapter: number; end_chapter: number; title?: string; content: string; volume?: number }) =>
    api.post<OutlineEntry>('/outlines/', data).then(r => r.data),
  update: (id: number, data: OutlinePlanFields & { start_chapter?: number; end_chapter?: number; title?: string; content?: string }) =>
    api.patch<OutlineEntry>(`/outlines/${id}`, data).then(r => r.data),
  delete: (id: number) =>
    api.delete(`/outlines/${id}`).then(r => r.data),
  expand: (id: number) =>
    api.post<OutlineEntry[]>(`/outlines/${id}/expand`).then(r => r.data),
  health: (novelId: number) =>
    api.get<OutlineHealth>(`/outlines/novel/${novelId}/health`).then(r => r.data),
  planOptions: () =>
    api.get<PlanOptions>('/outlines/plan-options').then(r => r.data),
  /** 给单独一章补细纲：写正文前发现这章没纲时用 */
  draftChapter: (novelId: number, chapterNumber: number) =>
    api.post<OutlineEntry>(
      `/outlines/novel/${novelId}/chapter/${chapterNumber}/draft`, {}, { timeout: 120000 },
    ).then(r => r.data),
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
  | { event: 'review_result'; data: ReviewResult }
  | { event: 'llm_request'; data: Record<string, unknown> }
  | { event: 'llm_call'; data: LlmCallData }
  | { event: 'new_locations'; data: NewLocationsData }
  | { event: 'new_factions'; data: NewFactionsData }
  | { event: 'new_techniques'; data: NewTechniquesData }
  | { event: 'new_threads'; data: NewThreadsData }
  | { event: 'thread_resolutions'; data: ThreadResolutionsData }
  | { event: 'context_step'; data: ContextStepData }
  | { event: 'critic_issues'; data: CriticIssuesData }

// ── SSE Build ──────────────────────────────────────────────────────────────

export interface BuildStepData {
  step: number
  key: string
  label: string
  status: 'running' | 'done' | 'skipped'
}

export type BuildSSEMessage =
  | { event: 'build_step'; data: BuildStepData }
  | { event: 'build_token'; data: string }
  | { event: 'build_progress'; data: { percent: number; input_tokens: number; output_tokens: number } }
  | { event: 'build_done'; data: { novel_id: number } }
  | { event: 'error'; data: string }

// ── SSE Chat ───────────────────────────────────────────────────────────────

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export type ChatSSEMessage =
  | { event: 'token'; data: string }
  | { event: 'done'; data: { input_tokens: number; output_tokens: number } }
  | { event: 'warning'; data: string }
  | { event: 'error'; data: string }

async function readSseStream<T>(
  response: Response,
  onMessage: (msg: T) => void,
) {
  if (response.status === 401) {
    handleUnauthorized()
    throw new Error('未登录或登录已过期')
  }
  if (!response.ok) {
    const text = await response.text().catch(() => '')
    throw new Error(text || `HTTP ${response.status} ${response.statusText}`)
  }
  if (!response.body) {
    throw new Error('服务器未返回流式响应')
  }

  const reader = response.body.getReader()
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
          onMessage(JSON.parse(line.slice(6)) as T)
        } catch {}
      }
    }
  }
  if (buffer.startsWith('data: ')) {
    try {
      onMessage(JSON.parse(buffer.slice(6)) as T)
    } catch {}
  }
}

export function streamChat(
  payload: {
    novel_id: number
    messages: ChatMessage[]
    model?: string
    system_prompt?: string
    temperature?: number
    max_tokens?: number
    context_rounds?: number
    chapter_number?: number
    web_search?: boolean
  },
  onMessage: (msg: ChatSSEMessage) => void,
  onClose: () => void,
): AbortController {
  const controller = new AbortController()

  fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(payload),
    signal: controller.signal,
  }).then(async (response) => {
    await readSseStream<ChatSSEMessage>(response, onMessage)
    onClose()
  }).catch((err) => {
    if (err.name !== 'AbortError') {
      onMessage({ event: 'error', data: String(err) })
    }
    onClose()
  })

  return controller
}

/** 构思对话里聊定的结论。空串/空数组 = 没聊到，前端不覆盖对应栏位 */
export interface BrainstormExtract {
  title: string
  genre: string
  writing_style: string
  premise: string
  plot_design: string
  core_setting: string
  world_rules_seed: string
  ending: string
  protagonist_arc: string
  endgame_cards: Array<{ volume: number; text: string }>
  characters: Array<{ name: string; role: string; age: string; description: string }>
}

export const brainstormApi = {
  extract: (messages: ChatMessage[], model = '') =>
    api.post<BrainstormExtract>('/chat/brainstorm/extract', { messages, model }, { timeout: 180000 })
      .then(r => r.data),
}

/** 新建小说页的构思对话：还没有 novel，也不读表单（对话单向影响表单） */
export function streamBrainstorm(
  payload: {
    messages: ChatMessage[]
    model?: string
    temperature?: number
    max_tokens?: number
    context_rounds?: number
    nsfw?: boolean
    web_search?: boolean
    /** 构思目标：market = 投稿向，indulge = 自娱自乐。决定后端用哪套提示词 */
    purpose?: string
    /** 向导阶段 id，留空走自由聊天 */
    stage?: string
    /** 向导前几步已敲定的结论，防止早期结论被轮次截断后 AI 重复提问 */
    confirmed?: string
  },
  onMessage: (msg: ChatSSEMessage) => void,
  onClose: () => void,
): AbortController {
  const controller = new AbortController()

  fetch('/api/chat/brainstorm', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(payload),
    signal: controller.signal,
  }).then(async (response) => {
    await readSseStream<ChatSSEMessage>(response, onMessage)
    onClose()
  }).catch((err) => {
    if (err.name !== 'AbortError') {
      onMessage({ event: 'error', data: String(err) })
    }
    onClose()
  })

  return controller
}

/** 模组构思向导的对话轮。事件同 brainstorm：token / warning / done / error */
export function streamRpgWizard(
  moduleId: number,
  payload: {
    messages: ChatMessage[]
    model?: string
    nsfw?: boolean
    /** 向导阶段 id（world/stats/places/cast/things），留空走自由聊天 */
    stage?: string
    /** 前几步已敲定的结论，防止早期结论被轮次截断后 AI 重复提问 */
    confirmed?: string
    /** 玩法类别，决定往哪个方向聊 */
    play_style?: string
  },
  onMessage: (msg: ChatSSEMessage) => void,
  onClose: () => void,
): AbortController {
  const controller = new AbortController()

  fetch(`/api/rpg/modules/${moduleId}/wizard`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(payload),
    signal: controller.signal,
  }).then(async (response) => {
    await readSseStream<ChatSSEMessage>(response, onMessage)
    onClose()
  }).catch((err) => {
    if (err.name !== 'AbortError') {
      onMessage({ event: 'error', data: String(err) })
    }
    onClose()
  })

  return controller
}

// ── SSE Tavern ────────────────────────────────────────────────────────────

export interface TavernTurnMeta {
  system_tokens: number
  history_count: number
  triggered: { id: number; keywords: string; constant: boolean; depth: number }[]
  rules_used: number
  examples_used: number
  speaker?: { card_id: number; name: string }
  /** 刚落库的那条用户消息，前端要靠它才能马上编辑这句。只在本轮第一个发言人的 meta 里带 */
  user_message_id?: number
}

/** 群聊时每个角色开口前发一次，token 归属最近的这个 speaker */
export interface TavernSpeaker {
  card_id: number
  name: string
  avatar_url: string
}

export type TavernSSEMessage =
  | { event: 'speaker'; data: TavernSpeaker }
  | { event: 'meta'; data: TavernTurnMeta }
  | { event: 'token'; data: string }
  | { event: 'warning'; data: string }
  | { event: 'summarized'; data: { upto_id: number } }
  | { event: 'done'; data: { input_tokens: number; output_tokens: number; message_id: number } }
  | { event: 'error'; data: string }

export function streamTavernTurn(
  sessionId: number,
  payload: { content: string },
  onMessage: (msg: TavernSSEMessage) => void,
  onClose: () => void,
): AbortController {
  const controller = new AbortController()

  fetch(`/api/tavern/sessions/${sessionId}/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(payload),
    signal: controller.signal,
  }).then(async (response) => {
    await readSseStream<TavernSSEMessage>(response, onMessage)
    onClose()
  }).catch((err) => {
    if (err.name !== 'AbortError') {
      onMessage({ event: 'error', data: String(err) })
    }
    onClose()
  })

  return controller
}

// ── SSE RPG ───────────────────────────────────────────────────────────────

/** 后端发两次 meta：第一次只带 user_message_id（模型没配好时也要送出去），
 *  上下文拼完再补发一次带诊断的。前端必须合并而不是覆盖 */
export interface RpgTurnMeta {
  user_message_id?: number
  system_tokens?: number
  state_tokens?: number
  npc_tokens?: number
  /** 【外场】那一块占了多少 token */
  chronicle_tokens?: number
  /** 【场面】那一块占了多少 token：地点描述加在场名单，每轮都在 */
  scene_tokens?: number
  history_count?: number
  triggered?: { id: number; keywords: string; constant: boolean; depth: number }[]
  npcs_onstage?: { id: number; name: string }[]
  /** 真的和玩家站在同一个地点的那些人。诊断行的「在场」读这一份——
   *  npcs_onstage 还含「只是被提到」的人，那是给提示词注入用的宽名单 */
  npcs_here?: { id: number; name: string }[]
  slot?: string
  day?: number
  /** 裁决归一化出来的意图，它也参与了世界书关键词扫描 */
  intent_used?: string
}

/** 引擎/AI 结算完的权威状态，直接替换前端那份 */
export interface RpgStatePatch {
  stats: Record<string, number>
  inventory: RpgInvItem[]
  flags: Record<string, string | number | boolean | null>
  location: string
  npc_states: Record<string, Record<string, number | boolean>>
  npc_notes: Record<string, Record<string, string>>
  npc_activities: Record<string, string>
  npc_places: Record<string, string>
  status: 'alive' | 'dead' | 'ended'
  /** 时钟也跟着走，否则按完「结束这个时段」要等整页重拉才动 */
  time_slots: string[]
  slot: string
  day: number
}

export type RpgSSEMessage =
  | { event: 'meta'; data: RpgTurnMeta }
  | { event: 'adjudicate'; data: { need_check: boolean; attr: string; band: RpgBand; intent: string; reason: string } }
  | { event: 'roll'; data: { rate: number; dice: number; outcome: RpgOutcome; attr: string } }
  | { event: 'token'; data: string }
  /** 后端当前处在哪一步：adjudicating（裁决）/ building（组织线索）/ settling（结算）。
   *  只在这些静默阶段发，叙述开始后靠 token 表示「在写」 */
  | { event: 'stage'; data: string }
  | { event: 'warning'; data: string }
  | { event: 'state'; data: RpgStatePatch }
  | { event: 'suggestions'; data: string[] }
  | { event: 'done'; data: { message_id: number; input_tokens: number; output_tokens: number; aux_input_tokens: number; aux_output_tokens: number } }
  | { event: 'error'; data: string }

export function streamRpgTurn(
  sessionId: number,
  payload: {
    content: string
    attr?: string
    /** 「点出来的」行动。给了任意一个就走引擎，数字由模组定义算死 */
    action_id?: number | null
    item_name?: string
    move_to?: string
    /** 当前查看的 NPC，用于选择该角色可见的历史与摘要 */
    focus_npc_id?: number | null
    /** 动作用在谁身上（好感加给他）。和「这段叙事归谁看」无关——
     *  那个由消息上的 present 快照决定，不由请求参数决定 */
    target_npc?: string
  },
  onMessage: (msg: RpgSSEMessage) => void,
  onClose: () => void,
): AbortController {
  const controller = new AbortController()

  fetch(`/api/rpg/sessions/${sessionId}/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(payload),
    signal: controller.signal,
  }).then(async (response) => {
    await readSseStream<RpgSSEMessage>(response, onMessage)
    onClose()
  }).catch((err) => {
    if (err.name !== 'AbortError') {
      onMessage({ event: 'error', data: String(err) })
    }
    onClose()
  })

  return controller
}

// ── SSE Rewrite ───────────────────────────────────────────────────────────

export interface AnnotationItem {
  paragraph?: number
  text: string
}

export function streamChapterRewrite(
  payload: {
    novel_id: number
    chapter_number: number
    annotations: AnnotationItem[]
    target_words: number
    rewrite_model?: string
  },
  onMessage: (msg: SSEMessage) => void,
  onClose: () => void,
): AbortController {
  const controller = new AbortController()

  fetch('/api/generation/rewrite-chapter', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(payload),
    signal: controller.signal,
  }).then(async (response) => {
    await readSseStream<SSEMessage>(response, onMessage)
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
    pov?: string
  },
  onMessage: (msg: SSEMessage) => void,
  onClose: () => void,
): AbortController {
  const controller = new AbortController()

  fetch('/api/generation/chapter', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(payload),
    signal: controller.signal,
  }).then(async (response) => {
    await readSseStream<SSEMessage>(response, onMessage)
    onClose()
  }).catch((err) => {
    if (err.name !== 'AbortError') {
      onMessage({ event: 'error', data: String(err) })
    }
    onClose()
  })

  return controller
}
