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
  /** 构思/设定生成的温度（世界观、大纲、角色卡、自动构建）。负数 = 整个参数不发 */
  build_temperature: number
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

// 按供应商分组，给 <optgroup> 用。同一个 model_id 在几家都有的时候，光看
// 模型名分不出这一条是哪家的（编辑器和酒馆的模型下拉就是这么排的）
export function groupModelsByProvider(models: ModelEntry[]) {
  const groups = new Map<string, ModelEntry[]>()
  for (const m of models.filter(m => m.model_type !== 'embedding')) {
    const key = m.provider || '未分组'
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(m)
  }
  return [...groups.entries()]
    .sort(([a], [b]) => a.localeCompare(b, 'zh-Hans-CN'))
    .map(([provider, items]) => ({
      provider,
      items: items.sort((a, b) =>
        (a.display_name || a.model_id).localeCompare(b.display_name || b.model_id, 'zh-Hans-CN'),
      ),
    }))
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

export interface ComfyStatus {
  reachable: boolean
  base_url: string
  detail: string
}

export const settingsApi = {
  get: () => api.get('/settings/').then(r => r.data),
  update: (data: object) => api.patch('/settings/', data).then(r => r.data),
  test: (model?: string) => api.post('/settings/test', { model: model ?? '' }).then(r => r.data),
  proxyStatus: () => api.get<ProxyStatus>('/settings/proxy-status').then(r => r.data),
  comfyStatus: () => api.get<ComfyStatus>('/settings/comfyui-status').then(r => r.data),
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
  /** 填满时。无 / 标记——立一条「{名字}满」的 flag，这项就成了进度时钟。
   *  只在有上限的项上有意义：没上限的永远填不满 */
  on_full?: string
  /** 条 / 数字 / 隐藏 */
  display?: string
  /** 跨天恢复（抬到 max 的七成，只往上抬不往下压）。只在有上限的项上有意义 */
  reset_daily?: boolean
  /** AI 每轮最多让这一项动几点。留空 = 不限；写 0 = AI 一点都不许动 */
  step_max?: number | null
  /** 这个数值影响什么。每轮发给模型一句，作者不写就没有 */
  effect?: string
  /** 分档。空数组和没写是一回事 */
  tiers?: RpgStatTier[]
}

/** 统一条件格式。世界书触发、动作按钮可用性、地点进入条件共用 */
export interface RpgCondition {
  stats?: Record<string, { op: string; value: number }>
  /** npc 写 "*" 表示不指定是谁：任意一个角色达标就算成立。放在动作的可用条件上
   *  时，后端只把这一轮选中的对象喂给条件求值，于是它自动是「你选的那个人」 */
  relations?: { npc: string; stat: string; op: string; value: number }[]
  /** 「!xxx」表示这条 flag 不能立着 */
  flags?: string[]
  items?: string[]
  /** 当前时段必须是其中之一，「!晚」表示不能在晚上。模组没设时段时一律不成立 */
  slots?: string[]
  /** 天数门槛，形状同 stats */
  day?: { op: string; value: number }
  /** 「某件事之后 N 天」。day 是绝对天数（第 10 天），这条是相对的——
   *  AI 推进的剧情没有写死的时间线，能锚的只有那件事发生的那天。
   *  没记过日期的 flag（加 flag_days 之前的老局）判不成立 */
  after_days?: { flag: string; days: number }[]
}

/** 玩法类别。和 genre 是两根正交的轴：genre 说「世界长什么样」，
 *  这个说「这局怎么玩」。同一个魔法学院可以是模拟养成也可以是探索冒险 */
export type RpgPlayStyle = 'sim' | 'rpg' | 'slg'

/** 支持 AI 生成/优化的模组栏位，与后端 agents/rpg_assist.py 的 FIELD_SPECS 对齐。
 *  两边是手工对齐的：这里多写一个，后端会回 400 */
export type RpgAssistField =
  | 'worldview' | 'opening_scene' | 'system_instruction' | 'narration_sample'
  | 'npc_persona' | 'npc_appearance' | 'npc_description'
  | 'location_description' | 'item_description' | 'skill_description'
  | 'task_description'

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
  opening_npc_ids: number[]
  opening_npc_locations: Record<string, string>
  /** 默认时段表，如 ["早","中","晚"]。空 = 这个模组不用时段 */
  time_slots: string[]
  /** 主角的名字和出身由模组定死，玩家在建局界面改不动。**只在有主角模板卡时
   *  生效**：后端建局那一步也会照卡覆写，所以界面只读不是唯一的防线 */
  lock_protagonist: boolean
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
  fast_model_ref: string
  settlement_model_ref: string
  adjudication_model_ref: string
  suggestion_model_ref: string
  activity_model_ref: string
  offscreen_model_ref: string
  discovery_model_ref: string
  /** 压缩旧剧情用。空 = 跟着 fast_model_ref 走 */
  summary_model_ref: string
  /** 立绘 tag 转换用。空 = 跟着 fast_model_ref 走 */
  image_model_ref: string
  /** 推时段时写一句「别处此刻在发生什么」进大事记。**默认关**：
   *  开了之后「结束这个时段」就不再是零模型调用了 */
  offscreen_brief: boolean
  /** 一个时段最多几格**行动**（点动作/道具/技能/移动，纯对话不算）。
   *  攒满自动推一格。0 = 关，老模组一格都不会自己走 */
  slot_budget: number
  /** 纯对话攒到几条就把「结束这个时段」点亮。**只提醒，不推时间**。0 = 关 */
  chat_nudge: number
  /** 自由打字收尾时吃掉一格行动。**不是每条都吃**：只有结算判定「这一幕收尾了」
   *  那一轮才算一格，闲聊三句不收尾就是 0 格。默认关 */
  free_costs_slot: boolean
  /** NPC 立绘的出图设置。老模组是 {}，三项都要判空 */
  image_config: RpgImageConfig
  /** 构思向导上次回填写进来的东西。老模组是 {}，回填时按「没有台账」处理 */
  wizard_state: RpgWizardState
  session_count: number
  npc_count: number
  entry_count: number
  created_at: string
  updated_at: string
}

/**
 * 构思向导的回填台账：上一次回填往模组里写了什么。
 *
 * 只用来「下次回填先把这些摘掉」。没有它就只能一律追加，于是
 * 「重新生成 → 再回填」会在模组里叠出两套数值/时段/角色。
 *
 * 全可选：老模组这一列是 {}，那时按「没有台账」处理，退回只追加。
 * 名字一律按 trim 后比对，和 wizardApply.ts 的 newNamed 同一套口径。
 */
export interface RpgWizardState {
  slots?: string[]
  stats?: string[]
  relation_stats?: string[]
  location_ids?: number[]
  npc_ids?: number[]
  item_ids?: number[]
  skill_ids?: number[]
  task_ids?: number[]
  action_ids?: number[]
}

/**
 * 模组的出图设置。全可选——老模组这一列是 {}。
 *
 * 题材**不在这里**：module.genre 已经是主字段，出图时现读，两处存会不同步。
 */
export interface RpgImageConfig {
  /** comfy_workflows/ 下的文件名（不带 .json）。空 = 后端默认 npc_portrait */
  workflow?: string
  /** 展开后的英文画风 tag 串，不是 imageStyles 里的 key */
  style?: string
  /**
   * 展开后的中文姿势 tag。三态，取值一律用 `?? DEFAULT_POSE` 不能用 `||`：
   * undefined = 没设过（走默认站姿全身像），'' = 明确「不指定」（什么都不加）
   */
  pose?: string
  /** 用户自己补的词：hentai、质量词、画师串之类 */
  extra?: string
  /**
   * 提示词发出去时是什么形态。undefined = 中文自然语言（老模组的行为，逐字不变）。
   *
   * `'sd_tags'` 是给光辉（Illustrious）这类 SDXL 系工作流用的：它们走 CLIP-L，
   * **只认英文 Danbooru tag**，喂中文散文基本等于喂噪声。Z-Image 相反，
   * 它的文本编码器是 Qwen-3-4B，中文才是它的主场。
   *
   * 为什么是显式选而不是嗅探工作流里的模型名：文件名是用户自己命的，
   * 改个名或换个加载器判断就失效，而失效的表现是「图悄悄变差」，没有报错。
   */
  prompt_form?: 'natural_zh' | 'sd_tags'
  /**
   * 出图画幅，存的是 imageFrames.ts 里的 **key**（不是展开值）。
   * 和 style / pose 存展开值的做法故意不一样——画幅还带着两个数字，不是纯 tag。
   */
  frame?: string
  /**
   * LoRA 开关与权重的覆写，**按工作流名分组**：`{工作流名: {LoRA 文件名: {...}}}`。
   * 只存调过的那几条，没动过的不落库——这样用户在 ComfyUI 里改了工作流默认值，
   * 没调过的那些会跟着变。
   */
  loras?: Record<string, Record<string, RpgLoraOverride>>
  /**
   * 底模覆写，同样**按工作流名分组**：`{工作流名: checkpoint 文件名}`。
   *
   * 只在 `prompt_form === 'sd_tags'`（光辉那类 SDXL 工作流）下生效——后端出图时
   * 会再判一次这个条件，中文自然语言那套不吃 checkpoint，配了也不发出去。
   * 覆盖的是工作流里写死的底模，而且**一处不落**：光辉那份工作流里三个加载器
   * 各写一遍 `ckpt_name`、高清修复脚本里还有一个 `hires_ckpt_name`，只改一处
   * 就是「主模型换了、高清还在用旧的」。
   */
  checkpoints?: Record<string, string>
}

/** 工作流文件里一条 LoRA 的原始状态。lora 是带目录的文件名，当 key 用 */
export interface RpgLoraSlot {
  lora: string
  on: boolean
  strength: number
}

export interface RpgLoraOverride {
  on: boolean
  strength: number
}

/** 工作流文件里一处写死的底模。空 slots = 这份工作流不认底模，别画控件 */
export interface RpgCkptSlot {
  /** 节点 id，只用来在提示里数「覆盖后这 N 处会统一」 */
  node: string
  class: string
  /** ckpt_name 或 hires_ckpt_name */
  key: string
  name: string
}

export interface RpgCkptInfo {
  /** 本机 ComfyUI 里可选的 checkpoint，来自它的 /object_info */
  available: string[]
  slots: RpgCkptSlot[]
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

/** 常用 GM 指令。取用是拷贝文本，模组不存 id */
export interface RpgInstructionPreset {
  id: number
  name: string
  content: string
  created_at: string
  updated_at: string
}

/** 数值套装：攒在用户名下的一整套数值定义，新模组一键套用。
 *  套用是拷贝一次就断开——套完这份和模组里那份再无关系 */
export interface RpgStatPreset {
  id: number
  name: string
  /** 「适合什么局」，只给自己在列表里认人用，永不进 prompt */
  note: string
  stat_defs: RpgStatDef[]
  relation_stat_defs: RpgStatDef[]
  sort_order: number
  created_at: string
  updated_at: string
}

/** 动作套装。存的是 RpgAction 去掉 requires——可用条件引用的是某个模组自己的
 *  标记和角色名，搬过去只会变成永远灰着的死按钮 */
export interface RpgActionPreset {
  id: number
  name: string
  note: string
  actions: RpgActionSeed[]
  sort_order: number
  created_at: string
  updated_at: string
}

/** 库里存的一个动作。= RpgAction 去掉 id/module_id/requires/at_location/sort_order。
 *  at_location 和 requires 一起被排除，理由逐字相同：它绑的是某个模组自己的地点名，
 *  搬过去只会变成永远灰着的死按钮。
 *  group 和 cost_slot 留着：一个是纯文本，一个是布尔，都不引用模组里的任何名字。
 *  套进没配时段的模组时 cost_slot 自动没有效果（advance_slot 会空转），不会变成坏按钮 */
export type RpgActionSeed = Pick<
  RpgAction,
  'name' | 'prompt_hint' | 'effects' | 'relation_effects' | 'needs_target'
  | 'target_anywhere' | 'summons_target' | 'group' | 'cost_slot'
>

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

/** 技能栏里的一行。和模组的技能定义 RpgSkill 是两回事，同 RpgInvItem */
export interface RpgLearnedSkill {
  name: string
  /** 还要歇几个回合才能再用。0 = 现在就能使 */
  cooldown_left: number
}

/** 模组定义的技能。和道具同一条链：引擎按 effects 精确增减，AI 碰不到 */
export interface RpgSkill {
  id: number
  module_id: number
  name: string
  description: string
  /** 主动 / 被动。被动的不出「使用」按钮 */
  category: string
  usable: boolean
  /** 数值增减 {"精力": -10} */
  effects: Record<string, number>
  /** 使用条件，形状同 RpgAction.requires */
  requires: RpgCondition
  /** 用完要歇几个回合。0 = 随便用 */
  cooldown: number
  /** 开局就会 */
  start_with: boolean
  sort_order: number
  created_at: string
  updated_at: string
}

/** 任务栏里的一行。和模组的任务定义 RpgTask 是两回事，同 RpgInvItem */
export interface RpgSessionTask {
  name: string
  desc: string
  /** 「怎样才算办完」。接下这桩事的时候从定义拷过来，之后不跟着定义变 */
  goal: string
  /** 主线 / 支线 / 日常；旧存档可能没有此字段 */
  category?: string
  status: 'open' | 'done' | 'failed'
  /** 对应模组里那一行；剧情里冒出来的差事没有，也就没有奖励 */
  task_id: number | null
  source: string
  opened_turn: number
  closed_turn: number
}

/** 模型提议「这桩事看着办完了」，等玩家点头。改不改状态由玩家定 */
export interface RpgTaskProposal {
  id: string
  name: string
  action: 'done' | 'failed'
  /** 正文原话，是这条提议的全部依据 */
  reason: string
  message_id: number
}

/** 模组定义的任务。小说侧「伏笔」在 RPG 这边的对应物 */
export interface RpgTask {
  id: number
  module_id: number
  name: string
  description: string
  /** 做到什么才算办完。判定完成与否只看这一句 */
  objective: string
  /** 主线 / 支线 / 日常 */
  category: string
  /** 办成之后的数值奖励 */
  effects: Record<string, number>
  /** 开局就接下 */
  auto_start: boolean
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
  parent_id: number | null
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
  /** 目标可以是不在跟前的人（手机、传讯这类远程渠道） */
  target_anywhere: boolean
  /** 点了把目标叫到你身边 */
  summons_target: boolean
  /** 分栏用的自由文本，空 = 归到「其他」那一栏 */
  group: string
  /** 点一下推进一格时段 */
  cost_slot: boolean
  /** 限定只在这个地点可用，空 = 随处可用 */
  at_location: string
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
  /** 自由文本，不是数字：「十七八岁」「三百岁」都能写。每轮随长相一起注入 */
  age: string
  avatar_url: string
  /** 当前这张立绘用的随机种子，0 = 没记录（自己上传的、或还没生成过）。只读 */
  avatar_seed: number
  /**
   * 只给这个人的出图设置。形状和 `RpgModule.image_config` 一模一样，但**是稀疏的**：
   * 某个 key 不在 = 这一项跟随模组，在 = 只这个人覆写。`{}` 是常态。
   * 合并规则在 pages/Rpg/imageConfig.ts，后端同一套在 services/rpg_image.py
   */
  image_config: RpgImageConfig
  description: string
  persona: string
  /** 只在首次见面时注入，之后省掉这段 token */
  appearance: string
  /** 常驻地点。等于当前局的 location 即视为在场 */
  location: string
  /** 作息表：{"早": "大礼堂", "晚": "寝室"}。当前时段在这张表里有值就用它，
   *  没有就落回 location。后端的 rpg_context.npc_place 是同一套算法 */
  slot_locations: Record<string, string>
  /** 仅这些时段执行随机移动；空数组表示所有时段 */
  random_movement_slots: string[]
  /** 额外触发词：人不在场但被提到也注入 */
  keywords: string
  /** 勾上之后，这一轮没提到她时她自己过日子：模型写一句「最近在做什么」，
   *  记在这一局的 npc_activities 里，下回见面时注入。默认关 */
  ai_scheduled: boolean
  random_movement: boolean
  /** 分栏档案，照抄酒馆卡：外貌身材 / 背景故事 / … */
  profile_sections: Record<string, string>
  dialogue_examples: { user: string; assistant: string }[]
  /** 覆盖这个角色的关系数值起点（青梅竹马开局好感就该更高） */
  initial_state: Record<string, number | boolean>
  relation_enabled: boolean
  relation_stat_names: string[]
  sort_order: number
  created_at: string
  updated_at: string
}

/** 一局存档。世界的权威状态（数值/背包/地点）就在这上面 */
/** 结算认出来的、还没登记进模组的一个东西。只是待办，不是游戏状态 */
export interface RpgDiscovery {
  id: string
  kind: 'npc' | 'place' | 'item' | 'skill' | 'task'
  name: string
  /** 正文里能看出它是什么的那一句。后端校验过确实是原文，不是模型编的 */
  hint: string
  /** 哪一段剧情认出来的。补全时拿它回去取正文当依据 */
  message_id: number
}

/** 结算说「你拿到了这件东西」、还没认领的一条。同 RpgDiscovery 只是待办：
 *  认下来才进背包，划掉就什么都不留 */
export interface RpgItemClaim {
  id: string
  name: string
  qty: number
  /** 这件东西的来历或样子。认下来时会写进定义的描述里 */
  note: string
  /** 正文里提到它的那一句。可能是空串——名字往往只是个称呼，靠这句话认 */
  hint: string
  message_id: number
  /** 模组道具表里已经有的同名定义。非空 = 不必再问「一次性还是重复使用」 */
  known_item_id: number | null
}

/** 一个人这一局经历过的一件事。结算时模型写一句，引擎盖上日期时段 */
export interface RpgNpcHistoryEntry {
  day: number
  slot: string
  content: string
}

/** 一段关系拐弯的那一下。a / b 是两头，名册上的人写名册上的名字，玩家自己是「你」 */
export interface RpgMilestone {
  day: number
  slot: string
  /** 初见 / 动心 / 表白 / 决裂 / 和解 / 身份揭露 / 其他。后端白名单挡过，不会有别的 */
  type: string
  a: string
  b: string
  content: string
}

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
  /** 这一局会的技能和各自的冷却。形状同 inventory */
  skills: RpgLearnedSkill[]
  /** 这一局的待办清单，和等玩家点头的收线提议 */
  tasks: RpgSessionTask[]
  task_proposals: RpgTaskProposal[]
  location: string
  /** 这一局自己的时段表，建局时从模组拷来。空 = 不用时段 */
  time_slots: string[]
  /** 当前时段，存的是名字。空 = 没有时钟 */
  slot: string
  day: number
  /** 这一格已经用掉几格行动、聊了几条。advance_slot 归零。
   *  按钮的提醒读它们，配模组的 slot_budget / chat_nudge 看 */
  slot_actions: number
  slot_chats: number
  flags: Record<string, string | number | boolean | null>
  /** 每个 flag 第一次立起来是第几天。{"聊过电机": 4}。引擎单方面记，模型碰不到；
   *  after_days 条件靠它算「之后 N 天」。老局读出来是 {} */
  flag_days: Record<string, number>
  /** {"3": {"好感": 62, "met": true}}，键是 npc_id 的字符串 */
  npc_states: Record<string, Record<string, number | boolean>>
  /** GM 这一局边玩边记下的 NPC 近况。{"3": {"伤势": "左肩中刀"}}，值一律是字符串。
   *  和 npc_states 分开存：那边的值是关系数字，合在一起会被字符串盖掉 */
  npc_notes: Record<string, Record<string, string>>
  /** 这一局被**永久改写掉**的外貌。{"3": {"胸部": "服丰元玉乳散后长出"}}。
   *  和 npc_notes 分开存：那张表满了淘汰最久没更新的，而身体改造写一次就不刷新，
   *  永远排在淘汰队列最前面。注入时它紧贴作者写的 appearance 之后、并压过它 */
  npc_appearance: Record<string, Record<string, string>>
  /** AI 调度给不在场的人记的那一句「最近在做什么」。{"3": "在图书馆翻旧报纸"}。
   *  和 npc_notes 分开存，后端的 rpg_state.apply_npc_activity 是同一个意思 */
  npc_activities: Record<string, string>
  /** 每个人这一局的经历，{"3": [...]}，按发生顺序往后追加。和 npc_notes 分开存：
   *  那边同名键会被盖掉（她现在怎么样），这边只增不改（她经历过什么） */
  npc_history: Record<string, RpgNpcHistoryEntry[]>
  /** 关系的转折点，整局一条线不按人分——一条连着两个人 */
  npc_milestones: RpgMilestone[]
  /** 剧情把谁挪到哪儿了：{"3": "校长办公室"}。你在对话框里说「你过来」，
   *  结算从刚写出的正文里读出她的新位置写在这——它优先于作息表，推时段清空。
   *  取值口径见 condition.npcPlace（后端 rpg_context.npc_place 的镜像） */
  npc_places: Record<string, string>
  /** 跟着你走的人，装的是 npc id。**只装 id 不记位置**——她的位置就是你的位置，
   *  由 npcPlace 的取值链当场算出来。和 npc_places 分开存、而且推时段**不清空**：
   *  那一列防的是模型随手写一笔盖掉作者的作息表，这一列是**玩家**自己说的
   *  （打了句话，或点了侧栏那个叉），跨时段存活直到你打发她走 */
  npc_followers: number[]
  /** 这个地方现在什么样：{"地窖": "门被你踹坏了，合不上"}，键是**地名**。
   *  不是第四个记忆格，就是结算顺手记的一句，你走进去它才进上下文 */
  place_notes: Record<string, string>
  /** 大事记：已经「传开」的事，跨对话线共享。注入时排在【外场】 */
  chronicle: string[]
  /** 去过的地点名。地图的迷雾按它散开 */
  visited: string[]
  /** 结算顺带认出来、模组里还没登记的人/地方/东西，等作者勾选。侧栏「新发现」那一格读它 */
  discoveries: RpgDiscovery[]
  /** 结算说「你拿到了」、还没认领的道具。道具那一格最上面那块读它 */
  item_claims: RpgItemClaim[]
  /** 你亲身经历那条线的长期记忆。旧剧情溢出窗口时压成的一段话，每轮注入。
   *  空 = 还没溢出过，这一局的全部原文都还在窗口里 */
  summary: string
  summarized_upto_id: number
  /** 和每个角色各自的长期记忆，{"3": "她告诉你二十年前那桩事"}，键是 npc_id
   *  的字符串。和上面那条是**并列的格子**：那条是你自己记得的，这些是她记得的，
   *  只在她在跟前时注入。同样是溢出才有 */
  thread_summaries: Record<string, string>
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

export interface RpgSettlement {
  status: 'pending' | 'running' | 'done' | 'partial' | 'failed' | 'stale'
  revision?: string
  attempts?: number
  domains?: Record<string, { status: string; warnings: string[] }>
  changes?: string[]
  engine_facts?: string[]
  warnings?: string[]
  facts?: { kind: string; summary: string; quote: string; witnesses: number[]; visibility: string }[]
  applied?: Record<string, { before: unknown; after: unknown }>
  proposed?: Record<string, unknown>
  retryable?: boolean
}

/**
 * 一条建议。两条路（主动的「帮我想想」和每轮结算顺带产出的）都收成这个形状。
 *
 * `kind` 决定点下去走哪个入口：
 * - `free`  当成一句话发出去，`text` 就是那句话
 * - `skill` / `item` / `move` 分别带 `name` 走 useSkill / useItem / moveByTurn
 * - `action` 带 `action_id` 走引擎动作；要不要先挑人由那个动作自己的
 *   `needs_target` 说了算，数据里**不带** target
 */
export interface RpgSuggestion {
  text: string
  kind: string
  name: string
  action_id: number | null
}

export interface RpgMessage {
  id: number
  session_id: number
  role: 'user' | 'assistant'
  content: string
  turn_request?: {
    attr?: string
    action_id?: number | null
    item_name?: string
    item_qty?: number
    skill_name?: string
    move_to?: string
    target_npc?: string
    mode?: 'group' | 'private' | 'solo'
    private_with?: number | null
  } | null
  /** 这条消息发生在哪个地点。统一时间线之后一屏里会混着几个地方的戏，
   *  前端靠它在换地方的地方插一条分隔 */
  location: string
  /** 当时在场的 NPC id。看某个人的视角就按它筛——他参与过的群戏也在里面。
   *  null = 不知道（迁移过来的老消息），当所有人可见：不知道不等于没有 */
  present: number[] | null
  roll: RpgRoll | null
  state_delta: Record<string, unknown> | null
  settlement: RpgSettlement | null
  /** 建议条。**老行是 `string[]`**——这一列是 JSON，加结构化之前写进去的就是
   *  纯字符串，没有迁移。所以类型老实写成联合，逼所有消费点过
   *  `pages/Rpg/suggestion.ts` 的 normalizeSuggestions（唯一收口） */
  suggestions: (RpgSuggestion | string)[] | null
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
type RpgSkillInput = Partial<Omit<RpgSkill, 'id' | 'module_id' | 'created_at' | 'updated_at'>>
type RpgTaskInput = Partial<Omit<RpgTask, 'id' | 'module_id' | 'created_at' | 'updated_at'>>
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
export type RpgGenerateKind = 'location' | 'npc' | 'item' | 'skill' | 'task' | 'action'

export interface RpgWizardKnown {
  stat_names?: string[]
  relation_names?: string[]
  location_names?: string[]
  /** 时段名。角色那一步的作息表要同时对上它和 location_names，缺了就整摊丢掉 */
  slot_names?: string[]
}
export type RpgWorldScope = 'world' | 'region'

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
  locations?: Array<{ name: string; description: string; connections: string[]; parent_id?: number | null; parent_name?: string }>
  default_location?: string
  time_slots?: string[]
  npcs?: Array<{
    name: string; persona: string; appearance: string; description: string
    profile_sections?: Record<string, string>
    location: string; initial_state: Record<string, number>
    /** 作息表。键过时段白名单、值过地点白名单，两张表缺一个就是空对象 */
    slot_locations?: Record<string, string>
    dialogue_examples?: Array<{ user: string; assistant: string }>
  }>
  items?: Array<{
    name: string; description: string; category: string
    consumable: boolean; start_with: boolean; effects: Record<string, number>
  }>
  skills?: Array<{
    name: string; description: string; category: string
    cooldown: number; start_with: boolean; effects: Record<string, number>
    /** 解锁门槛。只有 stats / items 两个子形状进抽取，见 rpg_wizard._clean_requires */
    requires?: RpgCondition
  }>
  tasks?: Array<{
    name: string; description: string; objective: string; category: string
    auto_start: boolean; effects: Record<string, number>
  }>
  actions?: Array<{
    name: string; prompt_hint: string; needs_target: boolean
    effects: Record<string, number>; relation_effects: Record<string, number>
    /** 分栏名是纯文本，编错了只是分栏难看。cost_slot 是布尔，at_location 过地点
     *  白名单、对不上就留空并记 dropped（见 rpg_wizard._clean_things 里那条注释） */
    group?: string
    cost_slot?: boolean
    at_location?: string
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
      /** temperature 是抽取的**起始**温度；不传就按后端默认 0.3，0.1 那一档兜底始终保留 */
      data: {
        stage: string; messages: ChatMessage[]; known?: RpgWizardKnown
        model?: string; temperature?: number
      },
    ) =>
      api.post<RpgWizardExtract>(`/rpg/modules/${moduleId}/wizard/extract`, data, {
        timeout: 180000,
      }).then(r => r.data),
    wizardGenerate: (
      moduleId: number,
      data: {
        instruction: string; nsfw?: boolean; model?: string
        world_scope?: RpgWorldScope; temperature?: number
      },
    ) =>
      api.post<RpgWizardExtract>(`/rpg/modules/${moduleId}/wizard/generate`, data, {
        timeout: 180000,
      }).then(r => r.data),
    /** 在某一摊（地点/角色/道具/动作）点「AI 生成」。白名单由后端查库，不用前端传。
     *  返回结构同 wizardExtract，只会含 kind 对应那一摊的列表 */
    generate: (
      moduleId: number,
      kind: RpgGenerateKind,
      data: { instruction?: string; count?: number; nsfw?: boolean; model?: string; temperature?: number },
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
    /** 调本机 ComfyUI 出立绘。冷启动要把模型加载进显存，实测百秒级，
     *  所以超时给到 5 分钟——默认 30s 必被掐断 */
    generateAvatar: (id: number, prompt: string, seed?: number, width = 1024, height = 1536) =>
      api.post<RpgNpc>(
        `/rpg/npcs/${id}/avatar/generate`,
        // seed 不传 = 后端摇一个随机的；给了值就是复现同一张脸
        { prompt, seed, width, height },
        { timeout: 300000 },
      ).then(r => r.data),
    /** 中文源文转 Danbooru tag，给光辉这类 SDXL 工作流用。返回命中的 tag 和
     *  两趟都没转成功、原样交回来的词（dropped）——这些要显示给用户，不能偷偷扔。
     *  跑两趟 LLM + 查表，比出图快但也不是瞬时，超时放到 60s。 */
    promptAsTags: (id: number, source: string, nsfw = false, includeCharName = false) =>
      api.post<{ tags: string[]; dropped: string[] }>(
        `/rpg/npcs/${id}/prompt-as-tags`,
        { source, nsfw, include_char_name: includeCharName },
        { timeout: 60000 },
      ).then(r => r.data),
  },
  items: moduleChild<RpgItem, RpgItemInput>('items'),
  skills: moduleChild<RpgSkill, RpgSkillInput>('skills'),
  tasks: moduleChild<RpgTask, RpgTaskInput>('tasks'),
  locations: moduleChild<RpgLocation, RpgLocationInput>('locations'),
  actions: moduleChild<RpgAction, RpgActionInput>('actions'),
  /** data/comfy_workflows/ 下有哪些工作流，给出图设置的下拉用。空数组 = 还没放 */
  comfyWorkflows: () => api.get<string[]>('/rpg/comfy-workflows').then(r => r.data),
  /**
   * 某份工作流里有哪些 LoRA，返回的是**文件里的原始状态**。
   * 模组调过的值在 image_config.loras 里，要自己叠上去，别直接当当前值用。
   */
  comfyLoras: (workflow: string) =>
    api.get<RpgLoraSlot[]>('/rpg/comfy-loras', { params: { workflow } }).then(r => r.data),
  /**
   * 某份工作流认不认底模、现在写死的是哪个，外加本机有哪些可选。
   * slots 为空说明这份工作流走的是 UNETLoader 单文件，底模控件不该画出来。
   */
  comfyCheckpoints: (workflow: string) =>
    api.get<RpgCkptInfo>('/rpg/comfy-checkpoints', { params: { workflow } }).then(r => r.data),
  rules: {
    list: () => api.get<RpgRule[]>('/rpg/rules/').then(r => r.data),
    create: (data: { name: string; content?: string; enabled?: boolean; sort_order?: number }) =>
      api.post<RpgRule>('/rpg/rules/', data).then(r => r.data),
    update: (id: number, data: { name?: string; content?: string; enabled?: boolean; sort_order?: number }) =>
      api.patch<RpgRule>(`/rpg/rules/${id}`, data).then(r => r.data),
    delete: (id: number) => api.delete(`/rpg/rules/${id}`).then(r => r.data),
  },
  /** 常用 GM 指令。用户级，照酒馆 instructionPresets */
  instructionPresets: {
    list: () =>
      api.get<RpgInstructionPreset[]>('/rpg/instruction-presets/').then(r => r.data),
    create: (data: { name: string; content: string }) =>
      api.post<RpgInstructionPreset>('/rpg/instruction-presets/', data).then(r => r.data),
    update: (id: number, data: { name?: string; content?: string }) =>
      api.patch<RpgInstructionPreset>(`/rpg/instruction-presets/${id}`, data).then(r => r.data),
    delete: (id: number) => api.delete(`/rpg/instruction-presets/${id}`).then(r => r.data),
  },
  /** 数值套装库。用户级，不带 moduleId——所以套不上 moduleChild 那个工厂 */
  statPresets: {
    list: () => api.get<RpgStatPreset[]>('/rpg/stat-presets/').then(r => r.data),
    create: (data: {
      name: string; note?: string
      stat_defs?: RpgStatDef[]; relation_stat_defs?: RpgStatDef[]; sort_order?: number
    }) => api.post<RpgStatPreset>('/rpg/stat-presets/', data).then(r => r.data),
    update: (id: number, data: {
      name?: string; note?: string
      stat_defs?: RpgStatDef[]; relation_stat_defs?: RpgStatDef[]; sort_order?: number
    }) => api.patch<RpgStatPreset>(`/rpg/stat-presets/${id}`, data).then(r => r.data),
    delete: (id: number) => api.delete(`/rpg/stat-presets/${id}`).then(r => r.data),
  },
  actionPresets: {
    list: () => api.get<RpgActionPreset[]>('/rpg/action-presets/').then(r => r.data),
    create: (data: { name: string; note?: string; actions?: RpgActionSeed[]; sort_order?: number }) =>
      api.post<RpgActionPreset>('/rpg/action-presets/', data).then(r => r.data),
    update: (id: number, data: { name?: string; note?: string; actions?: RpgActionSeed[]; sort_order?: number }) =>
      api.patch<RpgActionPreset>(`/rpg/action-presets/${id}`, data).then(r => r.data),
    delete: (id: number) => api.delete(`/rpg/action-presets/${id}`).then(r => r.data),
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
    /** 让某人跟着你 / 别跟着了。和 move 同类：纯引擎、零 LLM、不产生消息。
     *  **不占行动位**——跟着走或散开不花这个时段的时间 */
    follow: (id: number, npcId: number, following = true) =>
      api.post<{ session: RpgSession; message: string }>(
        `/rpg/sessions/${id}/follow`, { npc_id: npcId, following },
      ).then(r => r.data),
    update: (id: number, data: { title?: string }) =>
      api.patch<RpgSession>(`/rpg/sessions/${id}`, data).then(r => r.data),
    /** 划掉 GM 记错的一条 NPC 近况。没有这个口子，记错了只能读档 */
    deleteNpcNote: (id: number, npcId: number, key: string) =>
      api.patch<RpgSession>(`/rpg/sessions/${id}/npc-notes/${npcId}`, { key }).then(r => r.data),
    /** 划掉模型给这个人改写的一处外貌。比 deleteNpcNote 更要紧：近况记错是卡上多
     *  一行字，外貌改写记错是这个人的长相被永久改掉，而且它压过作者原文 */
    deleteNpcAppearance: (id: number, npcId: number, key: string) =>
      api.patch<RpgSession>(`/rpg/sessions/${id}/npc-appearance/${npcId}`, { key }).then(r => r.data),
    /** 划掉 AI 调度给这个人记的那句「最近在做什么」。只清这一句，
     *  「AI 调度」开关是模组作者的决定，改它要回模组页 */
    deleteNpcActivity: (id: number, npcId: number) =>
      api.delete<RpgSession>(`/rpg/sessions/${id}/npc-activity/${npcId}`).then(r => r.data),
    /** 划掉 GM 给某个地方记错的那一句近况。理由同 deleteNpcNote：这一句每次你
     *  走进这个地方都会进上下文，记错了没有这个口子就只能读档 */
    deletePlaceNote: (id: number, place: string) =>
      api.patch<RpgSession>(`/rpg/sessions/${id}/place-note`, { key: place }).then(r => r.data),
    /** 改写某一格的长期记忆。slot 传 'player'（你亲身经历的那条）或角色 id 的
     *  字符串。空串 = 这段记忆不要了。**指针不动**，所以被压掉的原文不会回来，
     *  改完之后模型看到的就只有你写的这一版 */
    editSummary: (id: number, slot: string, text: string) =>
      api.patch<RpgSession>(`/rpg/sessions/${id}/summary`, { slot, text }).then(r => r.data),
    /** 把勾中的新发现补全成完整档案并建进模组。这是**第二次**模型调用——
     *  提取是结算那一次顺带的，不花钱；补属性、连地图才在这里花。
     *  超时同向导的 3 分钟：它是一次完整的设定生成 */
    applyDiscoveries: (id: number, data: { ids: string[]; model?: string; temperature?: number }) =>
      api.post<RpgDiscoveryApply>(`/rpg/sessions/${id}/discoveries/apply`, data, {
        timeout: 180000,
      }).then(r => r.data),
    /** 「不要这个」。只从待办里划掉，不影响剧情 */
    dismissDiscovery: (id: number, discoveryId: string) =>
      api.delete<RpgSession>(`/rpg/sessions/${id}/discoveries/${discoveryId}`).then(r => r.data),
    /** 认下一件新道具：进背包，并在模组道具表里落一条定义。
     *  consumable 只在模组里还没有同名定义时才用得上，有定义的按那一行走 */
    confirmItemClaim: (id: number, claimId: string, consumable: boolean) =>
      api.post<RpgSession>(`/rpg/sessions/${id}/item_claims/${claimId}/confirm`, { consumable })
        .then(r => r.data),
    /** 「这不是我拿到的东西」。只划掉这一条，背包不动 */
    dismissItemClaim: (id: number, claimId: string) =>
      api.delete<RpgSession>(`/rpg/sessions/${id}/item_claims/${claimId}`).then(r => r.data),
    /** 玩家在确认窗里勾完了。勾中的按提议改状态并发奖励，没勾的只是不再弹 */
    resolveTasks: (id: number, accepts: Array<{ id: string; accept: boolean }>) =>
      api.post<RpgSession>(`/rpg/sessions/${id}/tasks/resolve`, { accepts }).then(r => r.data),
    /** 玩家自己改一条待办：标完成/失败、改回进行中，status 给空串是划掉 */
    setTaskState: (id: number, name: string, status: '' | 'open' | 'done' | 'failed') =>
      api.patch<RpgSession>(`/rpg/sessions/${id}/tasks`, { name, status }).then(r => r.data),
    /** 修改器：玩家自己把这几摊掰成想要的样子。**传的是目标值**，差多少由后端算——
     *  「先夹到上下限、再算差值」那套规则只该有一份，前端再做一遍减法迟早对不上。
     *  各项都可选，只发真的动过的那几项；notes 是后端对某一项的批注
     *  （「被限制在 100」这类），前端逐条念给玩家听，不进剧情 */
    tweak: (id: number, body: {
      stats?: Record<string, number>
      relations?: Record<string, Record<string, number>>
      inventory?: { name: string; qty: number }[]
      flags?: Record<string, boolean | null>
      npc_places?: Record<string, string | null>
    }) => api.patch<{ session: RpgSession; notes: string[] }>(
      `/rpg/sessions/${id}/tweak`, body,
    ).then(r => r.data),
    delete: (id: number) => api.delete(`/rpg/sessions/${id}`).then(r => r.data),
  },
  messages: {
    list: (sessionId: number) =>
      api.get<RpgMessage[]>(`/rpg/sessions/${sessionId}/messages/`).then(r => r.data),
    /** 只改正文。地点、在场名单、判定结果都是写入时的快照，不跟着改 */
    update: (id: number, content: string) =>
      api.patch<RpgMessage>(`/rpg/messages/${id}`, { content }).then(r => r.data),
    settle: (id: number) =>
      api.post<RpgMessage>(`/rpg/messages/${id}/settle`, {}, { timeout: 300000 }).then(r => r.data),
    /** 回到这条消息之前：它和它之后的消息全删，数值/背包/时段一起回滚。
     *  改自己说过的话必须走这个，光删消息会留下「话没说过，代价还在」 */
    rewind: (id: number) =>
      api.post<RpgSession>(`/rpg/messages/${id}/rewind`).then(r => r.data),
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
  suggest: (sessionId: number) =>
    api.post<{ suggestions: RpgSuggestion[]; diag: Record<string, number> }>(
      `/rpg/sessions/${sessionId}/suggest`, {}, { timeout: 120000 },
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
    // FastAPI 的报错是 {"detail": "..."}。整串 JSON 甩到界面上，玩家看到的是
    // 一行大括号；detail 才是那句人话
    let detail = ''
    try { detail = JSON.parse(text)?.detail || '' } catch { /* 不是 JSON，原样用 */ }
    throw new Error(detail || text || `HTTP ${response.status} ${response.statusText}`)
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
    /** 世界规模：完整世界或单一区域故事 */
    world_scope?: RpgWorldScope
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
  /** 【道具与技能】那一块占了多少 token：模组定义过的东西的说明书，每轮都在 */
  catalog_tokens?: number
  npc_tokens?: number
  /** 【角色总表】那一块占了多少 token：全模组角色一人一行（名字 + 常驻地 +
   *  一句简介），完整设定仍归 npc_tokens；私聊时不注入，所以那一轮会是 0 */
  roster_tokens?: number
  /** 【外场】那一块占了多少 token */
  chronicle_tokens?: number
  /** 【关系的转折】那一块占了多少 token：整局攒下的关系里程碑，
   *  不按在场筛、每轮都在，所以它只增不减 */
  milestone_tokens?: number
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
  /** 技能和冷却。不带回来的话点完技能要等整页重拉才灰 */
  skills: RpgLearnedSkill[]
  /** 待办清单。同理，不带的话任务格要整页重拉才更新 */
  tasks: RpgSessionTask[]
  flags: Record<string, string | number | boolean | null>
  /** flag 的立起日期。同上，不带的话「某事之后 N 天」的按钮要整页重拉才解锁 */
  flag_days: Record<string, number>
  location: string
  npc_states: Record<string, Record<string, number | boolean>>
  npc_notes: Record<string, Record<string, string>>
  /** 被永久改写掉的外貌。同上，不带回来的话要整页重拉才看得见 */
  npc_appearance: Record<string, Record<string, string>>
  npc_activities: Record<string, string>
  npc_history: Record<string, RpgNpcHistoryEntry[]>
  npc_milestones: RpgMilestone[]
  npc_places: Record<string, string>
  place_notes: Record<string, string>
  status: 'alive' | 'dead' | 'ended'
  /** 时钟也跟着走，否则按完「结束这个时段」要等整页重拉才动 */
  time_slots: string[]
  slot: string
  day: number
  /** 这一格的两个计数器，同理：不带的话「还剩一格」要等整页重拉才显示 */
  slot_actions: number
  slot_chats: number
}

/** 勾选「加入模组」之后后端回的东西：建成了哪几行 + 哪些被拦下了。
 *  dropped 必须显示出来——白名单过滤和重名拦截都是静默的，不说等于骗作者 */
export interface RpgDiscoveryApply {
  npcs: RpgNpc[]
  locations: RpgLocation[]
  items: RpgItem[]
  /** 这一次**新建了定义**的技能和任务 */
  skills: RpgSkill[]
  tasks: RpgTask[]
  /** 这一局真的学会 / 接下的名字。和上面两项不是一回事：模组里早就有定义、
   *  这一次只补上「这一局也拿到」的那些只出现在这里。非空就得重拉会话 */
  learned: string[]
  opened: string[]
  dropped: string[]
  /** 处理完之后还剩的待确认项，直接拿来覆盖角标 */
  remaining: RpgDiscovery[]
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
  | { event: 'engine_result'; data: { facts: string[] } }
  | { event: 'settlement'; data: { message_id: number; report: RpgSettlement | null } }
  | { event: 'suggestions'; data: RpgSuggestion[] }
  /** 这一轮认出来的、模组里还没有的人/地方/东西。只挂角标，不打断 */
  | { event: 'discoveries'; data: RpgDiscovery[] }
  | { event: 'item_claims'; data: RpgItemClaim[] }
  /** 模型觉得这几桩事办完了。弹窗问玩家，点头才算 */
  | { event: 'task_proposals'; data: RpgTaskProposal[] }
  /** 模型觉得这一幕收尾了，可以推时段。**只点亮按钮，不推时间**——
   *  时钟仍然只有玩家能拨。data 是给玩家看的那句理由 */
  | { event: 'slot_hint'; data: string }
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
    item_qty?: number
    skill_name?: string
    move_to?: string
    /** 这一轮怎么说话：group 群聊 / private 私聊 / solo 独自行动。
     *  它决定这段戏记进谁的记忆，和「界面正在筛谁」是两件事 */
    mode?: 'group' | 'private' | 'solo'
    /** 私聊对象，只在 mode=private 时有意义。她必须此刻就在跟前 */
    private_with?: number | null
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
      // message 而不是 String(err)：后者带一个「Error: 」前缀
      onMessage({ event: 'error', data: err?.message || String(err) })
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
