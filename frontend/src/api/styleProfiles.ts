import { api, type ExampleTurn } from '@/api/client'

export interface StyleScene {
  summary?: string // 一句话场景概括；旧数据没有
  scene_type: string
  text: string
  speakers: string[]
  input?: string // 导入时反推的玩家输入，游戏叙事示例的「玩家」一侧；旧数据没有
}

export interface StyleCharacter {
  name: string
  role: string
}

export interface StyleStats {
  avg_sentence_len?: number
  dialogue_ratio?: number
  avg_para_len?: number
  person?: string
}

export interface StyleProfilePreview {
  name: string
  style_desc: string
  stats: StyleStats
  characters: StyleCharacter[]
  scenes: StyleScene[]
}

export interface StyleProfile extends StyleProfilePreview {
  id: number
  created_at: string
  updated_at: string
}

export type StyleAdaptMode = 'novel' | 'tavern' | 'rpg_narration' | 'rpg_npc'

export interface StyleAdaptResult {
  examples?: ExampleTurn[]
}

export interface StyleProfileUpdate {
  name?: string
  style_desc?: string
  characters?: StyleCharacter[]
  scenes?: StyleScene[]
}

export interface StyleAdaptParams {
  mode: StyleAdaptMode
  scene_indexes: number[]
  character?: string
  name_map?: Record<string, string> // 示例里的中性名 → 这边的真名
  model?: string // 空 = 默认快速模型
}

// 名字要和后端 style_extract.PRESET_CATEGORIES 一致，对不上的会被当成自定义类别
export const PRESET_CATEGORIES = ['对话', '外貌描写', '打斗', '环境描写', '心理描写', '日常']
export const DEFAULT_CATEGORIES = ['对话', '外貌描写', '打斗']

export const styleProfilesApi = {
  list: () => api.get<StyleProfile[]>('/style-profiles/').then(r => r.data),

  get: (id: number) => api.get<StyleProfile>(`/style-profiles/${id}`).then(r => r.data),

  importTxt: (file: File, categories: string[], model = '') => {
    const fd = new FormData()
    fd.append('file', file)
    for (const c of categories) fd.append('categories', c)
    fd.append('model', model)
    return api
      .post<StyleProfilePreview>('/style-profiles/import', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
        // 先全书粗筛，再每类调一次模型摘句，几分钟很正常
        timeout: 600000,
      })
      .then(r => r.data)
  },

  create: (data: StyleProfilePreview) =>
    api.post<StyleProfile>('/style-profiles/', data).then(r => r.data),

  update: (id: number, data: StyleProfileUpdate) =>
    api.patch<StyleProfile>(`/style-profiles/${id}`, data).then(r => r.data),

  delete: (id: number) => api.delete(`/style-profiles/${id}`).then(r => r.data),

  adapt: (id: number, params: StyleAdaptParams) =>
    api
      .post<StyleAdaptResult>(`/style-profiles/${id}/adapt`, params, { timeout: 180000 })
      .then(r => r.data),
}

const OTHER_TYPE = '其他'

/** 默认勾 3 段：先每种 scene_type 各取第一段（「其他」压最后），不够 3 段再按顺序补齐。 */
export function defaultPick(scenes: StyleScene[], indexes: number[]): number[] {
  if (indexes.length <= 3) return [...indexes]

  const firstOfType = new Map<string, number>()
  for (const i of indexes) {
    const type = scenes[i]?.scene_type || OTHER_TYPE
    if (!firstOfType.has(type)) firstOfType.set(type, i)
  }

  const picked: number[] = []
  const taken = new Set<number>()

  // sort 是稳定的：非「其他」保持出现顺序，只把「其他」挪到最后
  const types = [...firstOfType.keys()].sort((a, b) =>
    a === OTHER_TYPE ? 1 : b === OTHER_TYPE ? -1 : 0,
  )
  for (const type of types) {
    if (picked.length >= 3) break
    const i = firstOfType.get(type)!
    picked.push(i)
    taken.add(i)
  }

  for (const i of indexes) {
    if (picked.length >= 3) break
    if (!taken.has(i)) {
      picked.push(i)
      taken.add(i)
    }
  }

  return picked
}
