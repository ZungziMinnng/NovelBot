import type { RpgActionSeed, RpgStatDef } from '@/api/client'
import { GENRE_PRESETS } from './genrePresets'

/**
 * 套装库的公共数据和纯函数。套装页和模组编辑页两边都从这儿取，
 * 免得「什么算缺属性」「补建用什么默认值」两边各写一份、迟早不一致。
 *
 * 套用的语义是**拷贝一次就断开**：套完之后库和模组各过各的。
 */

/** 一套数值。用户存的那份多一个 id，内置的那三套没有 */
export interface StatPack {
  id?: number
  /** 内置套装的稳定标识（就是题材模板的 key），用户套装没有 */
  key?: string
  name: string
  note: string
  stat_defs: RpgStatDef[]
  relation_stat_defs: RpgStatDef[]
}

/** 一套动作。同上 */
export interface ActionPack {
  id?: number
  key?: string
  name: string
  note: string
  actions: RpgActionSeed[]
}

/** 内置套装 = 三套题材模板拆出来的只读视图。
 *
 *  刻意是 map 出来的而不是另写一份数据：复制一份，以后改模板得记得改两个地方，
 *  而第一次漂移谁也看不出来。
 *
 *  内置套装不落库，所以也不需要写作规则那套 is_builtin / 开新号补种的逻辑——
 *  它就是代码，用户要改就「另存为」变成自己那一份。 */
export const BUILTIN_STAT_PACKS: StatPack[] = GENRE_PRESETS.map(p => ({
  key: p.key,
  name: p.label,
  note: p.desc,
  stat_defs: p.stat_defs,
  relation_stat_defs: p.relation_stat_defs,
}))

export const BUILTIN_ACTION_PACKS: ActionPack[] = GENRE_PRESETS.map(p => ({
  key: p.key,
  name: `${p.label}的动作`,
  note: `配「${p.label}」那套数值用`,
  // 题材模板里的动作不带分栏、时间开销和远程指定：这三套是按探索冒险写的，那边
  // 动作本来就平铺一排、不吃时间、对象都在跟前。补上默认值而不是回头给模板逐条
  // 加字段——补了也全是空的
  actions: p.actions.map(a => ({
    ...a, group: '', cost_slot: false, target_anywhere: false, summons_target: false,
  })),
}))

/**
 * 这些动作用到了、而模组还没定义的数值名。
 *
 * 只看 effects / relation_effects 的键：这两处的键是后端 apply_stats /
 * apply_relations 唯一认的东西，定义表里没有的键会被直接丢掉、只留一条 warning。
 * 表现就是「玩家点了按钮，数字一动不动，而且不报错」——最难查的那种。
 *
 * requires 不用看：套装里根本不存它（见 RpgActionPreset 的注释）。
 */
export function missingStats(
  actions: RpgActionSeed[], statDefs: RpgStatDef[], relationDefs: RpgStatDef[],
): { stats: string[]; relations: string[] } {
  const have = new Set((statDefs || []).map(d => d.name))
  const haveRel = new Set((relationDefs || []).map(d => d.name))
  const stats = new Set<string>()
  const relations = new Set<string>()
  for (const a of actions) {
    for (const k of Object.keys(a.effects || {})) if (k && !have.has(k)) stats.add(k)
    for (const k of Object.keys(a.relation_effects || {})) if (k && !haveRel.has(k)) relations.add(k)
  }
  return { stats: [...stats], relations: [...relations] }
}

/**
 * 喂给 EffectEditor 的可选数值名。
 *
 * 前半截是参考套装里的定义，后半截是这些动作已经填过的键——后半截必须有：
 * EffectEditor 的 <select value={名字}> 找不到对应 option 时会渲染成一个空白行，
 * 作者会以为这一项丢了。
 */
export function defsForKeys(base: RpgStatDef[], usedKeys: string[]): RpgStatDef[] {
  const out = [...(base || [])]
  const have = new Set(out.map(d => d.name))
  for (const k of usedKeys) {
    if (!k || have.has(k)) continue
    have.add(k)
    out.push({ name: k, initial: 0, min: 0, max: 100, display: '条' })
  }
  return out
}

/** 一个套装里所有动作用到的数值名，去重。传给 defsForKeys 用 */
export function usedKeys(actions: RpgActionSeed[], relation = false): string[] {
  const keys = new Set<string>()
  for (const a of actions) {
    for (const k of Object.keys((relation ? a.relation_effects : a.effects) || {})) {
      if (k) keys.add(k)
    }
  }
  return [...keys]
}

/** 一个干净的空动作。库里的动作没有 requires 和 at_location */
export const emptySeed = (): RpgActionSeed => ({
  name: '', prompt_hint: '', effects: {}, relation_effects: {}, needs_target: false,
  target_anywhere: false, summons_target: false, group: '', cost_slot: false,
})
