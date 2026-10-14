import { api } from '@/api/client'

export type LoreKind = 'item' | 'skill' | 'rule'
export type LoreOrigin = 'lore' | 'novel' | 'rpg' | 'tavern'

export interface LoreSourceItem {
  origin: LoreOrigin
  kind: LoreKind
  id: number
  name: string
  group: string
  brief: string
}

export interface LoreSourceRef {
  origin: LoreOrigin
  kind: LoreKind
  id: number
  weight: number
  instruction: string
}

export interface LoreSavedSource extends LoreSourceRef {
  name: string
}

export interface LoreDraft {
  name: string
  category: string
  level: string
  description: string
  detail: string
}

export interface LoreEntry extends LoreDraft {
  id: number
  kind: LoreKind
  sources: Partial<LoreSavedSource>[]
  created_at: string
  updated_at: string
}

export type LoreExportTarget = 'novel' | 'tavern' | 'rpg'

export interface LoreExportParams {
  target: LoreExportTarget
  novel_id?: number
  module_id?: number
  card_id?: number
}

export interface LoreExportResult {
  target: string
  id: number
}

export interface LoreNamedOption {
  id: number
  name?: string
  title?: string
}

export interface LoreCardOption {
  id: number
  name: string
}

export interface LoreFuseParams {
  sources: LoreSourceRef[]
  goal: string
  model_ref: string
}

export const EMPTY_DRAFT: LoreDraft = {
  name: '',
  category: '',
  level: '',
  description: '',
  detail: '',
}

export const LORE_KIND_LABEL: Record<LoreKind, string> = {
  item: '道具',
  skill: '技能',
  rule: '规则',
}

export const loreApi = {
  sources: (kind: LoreKind) =>
    api.get<LoreSourceItem[]>('/lore/sources', { params: { kind } }).then(r => r.data),

  fuse: (data: LoreFuseParams) =>
    api.post<LoreDraft>('/lore/fuse', data, { timeout: 180000 }).then(r => r.data),

  list: (kind?: LoreKind) =>
    api.get<LoreEntry[]>('/lore/entries', { params: { kind } }).then(r => r.data),

  create: (data: LoreDraft & { kind: LoreKind; sources: LoreSavedSource[] }) =>
    api.post<LoreEntry>('/lore/entries', data).then(r => r.data),

  update: (id: number, data: Partial<LoreDraft>) =>
    api.patch<LoreEntry>(`/lore/entries/${id}`, data).then(r => r.data),

  remove: (id: number) => api.delete(`/lore/entries/${id}`).then(r => r.data),

  export: (id: number, data: LoreExportParams) =>
    api.post<LoreExportResult>(`/lore/entries/${id}/export`, data).then(r => r.data),

  modules: () => api.get<LoreNamedOption[]>('/rpg/modules/').then(r => r.data),

  novels: () => api.get<LoreNamedOption[]>('/novels/').then(r => r.data),

  cards: () => api.get<LoreCardOption[]>('/tavern/cards/').then(r => r.data),
}
