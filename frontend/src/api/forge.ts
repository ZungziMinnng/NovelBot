import { api, type ExampleTurn } from '@/api/client'

export type ForgeKind = 'tavern' | 'npc' | 'novel'
export type ForgeExportTarget = ForgeKind

export interface ForgeSourceItem {
  kind: ForgeKind
  id: number
  name: string
  group: string
  avatar_url: string
  brief: string
}

export interface ForgeSourceRef {
  kind: ForgeKind
  id: number
  weight: number
  instruction: string
}

export interface ForgeSavedSource extends ForgeSourceRef {
  name: string
}

export interface ForgeDraft {
  name: string
  age: string
  description: string
  personality: string
  speech_style: string
  appearance: string
  background: string
  abilities: string
  relationships: string
  dialogue_examples: ExampleTurn[]
}

export interface ForgeCharacter extends ForgeDraft {
  id: number
  sources: Partial<ForgeSavedSource>[]
  created_at: string
  updated_at: string
}

export interface ForgeModuleOption {
  id: number
  name: string
}

export interface ForgeNovelOption {
  id: number
  title: string
}

export interface ForgeFuseParams {
  sources: ForgeSourceRef[]
  goal: string
  model_ref: string
}

export interface ForgeExportParams {
  target: ForgeExportTarget
  module_id?: number
  novel_id?: number
}

export interface ForgeExportResult {
  target: string
  id: number
}

export const EMPTY_DRAFT: ForgeDraft = {
  name: '',
  age: '',
  description: '',
  personality: '',
  speech_style: '',
  appearance: '',
  background: '',
  abilities: '',
  relationships: '',
  dialogue_examples: [],
}

export const forgeApi = {
  sources: () => api.get<ForgeSourceItem[]>('/forge/sources').then(r => r.data),

  fuse: (data: ForgeFuseParams) =>
    api.post<ForgeDraft>('/forge/fuse', data, { timeout: 180000 }).then(r => r.data),

  list: () => api.get<ForgeCharacter[]>('/forge/characters').then(r => r.data),

  create: (data: ForgeDraft & { sources: ForgeSavedSource[] }) =>
    api.post<ForgeCharacter>('/forge/characters', data).then(r => r.data),

  update: (id: number, data: Partial<ForgeDraft>) =>
    api.patch<ForgeCharacter>(`/forge/characters/${id}`, data).then(r => r.data),

  remove: (id: number) => api.delete(`/forge/characters/${id}`).then(r => r.data),

  export: (id: number, data: ForgeExportParams) =>
    api.post<ForgeExportResult>(`/forge/characters/${id}/export`, data).then(r => r.data),

  modules: () => api.get<ForgeModuleOption[]>('/rpg/modules/').then(r => r.data),

  novels: () => api.get<ForgeNovelOption[]>('/novels/').then(r => r.data),
}
