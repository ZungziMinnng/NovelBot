import { rpgApi, type RpgLocation, type RpgModule, type RpgWizardExtract, type RpgWizardState } from '@/api/client'
import type { WizardPicked } from './WizardApplyModal'

export type WizardStatGroup = 'stat_defs' | 'relation_stat_defs'

export function moveWizardStat(draft: RpgWizardExtract, from: WizardStatGroup, index: number): RpgWizardExtract {
  const source = draft[from] || []
  const stat = source[index]
  if (!stat) throw new Error('这项数值已不存在，请重新打开预览')
  const to: WizardStatGroup = from === 'stat_defs' ? 'relation_stat_defs' : 'stat_defs'
  const target = draft[to] || []
  if (target.some(item => item.name.trim() === stat.name.trim())) {
    throw new Error(`另一组已有「${stat.name}」，请先核对两项数值，避免覆盖`)
  }
  return { ...draft, [from]: source.filter((_, position) => position !== index), [to]: [...target, stat] }
}

export function mergeWizardStage(base: RpgWizardExtract, step: RpgWizardExtract, stageId: string): RpgWizardExtract {
  const merged = { ...base }
  for (const [key, value] of Object.entries(step)) {
    if (key === 'dropped') continue
    if ((typeof value === 'string' && value) || (Array.isArray(value) && value.length)) {
      Object.assign(merged, { [key]: value })
    }
  }
  if (stageId === 'stats') {
    merged.stat_defs = step.stat_defs || []
    merged.relation_stat_defs = step.relation_stat_defs || []
  }
  merged.dropped = Array.from(new Set([...(base.dropped || []), ...(step.dropped || [])]))
  return merged
}

/** 按名字去重：trim 后为空、或已经在 seen 里的丢掉。收下的记进 seen */
function dedupeNamed<T extends { name: string }>(incoming: T[], seen: Set<string>): T[] {
  return incoming.filter(row => {
    const name = row.name.trim()
    if (!name || seen.has(name)) return false
    seen.add(name)
    return true
  })
}

function dedupeSlots(incoming: string[], seen: Set<string>): string[] {
  return incoming.filter(raw => {
    const name = raw.trim()
    if (!name || seen.has(name)) return false
    seen.add(name)
    return true
  })
}

function newNamed<T extends { name: string }>(existing: { name: string }[], incoming: T[]): T[] {
  return dedupeNamed(incoming, new Set(existing.map(row => row.name.trim())))
}

function trimmed(list: string[]): string[] {
  return list.map(item => item.trim()).filter(Boolean)
}

function names(rows: { name: string }[]): string[] {
  return trimmed(rows.map(row => row.name))
}

/**
 * 把向导的结果合进模组主表。
 *
 * 文本栏一律覆盖。时段/数值是「先摘掉上次向导写的那几个，再写这一轮的」：
 * 没有台账时（老模组，或从没回填过）跟加台账之前一样是纯追加；有台账时
 * 「重新生成 → 再回填」不会叠出两套。作者自己手打的那几条不在台账里，一直留着。
 *
 * 没勾的栏目一律不动——勾选列表就是「这一轮要写哪些栏」的意思，
 * 不勾的栏目既不清空也不追加。
 */
export function mergeWizardFields(
  current: RpgModule, picked: WizardPicked, prev: RpgWizardState,
): RpgModule {
  const next = { ...current }
  for (const key of ['genre', 'worldview', 'opening_scene', 'system_instruction', 'narration_sample', 'default_location'] as const) {
    const value = picked[key]
    if (typeof value === 'string' && value) next[key] = value
  }

  if (picked.time_slots?.length) {
    const written = new Set(prev.slots || [])
    const kept = (current.time_slots || []).filter(slot => !written.has(slot.trim()))
    next.time_slots = [...kept, ...dedupeSlots(picked.time_slots, new Set(kept.map(s => s.trim())))]
  }
  for (const key of ['stat_defs', 'relation_stat_defs'] as const) {
    if (picked[key]?.length) {
      const written = new Set((key === 'stat_defs' ? prev.stats : prev.relation_stats) || [])
      const kept = (current[key] || []).filter(def => !written.has(def.name.trim()))
      next[key] = [...kept, ...dedupeNamed(picked[key], new Set(kept.map(d => d.name.trim())))]
    }
  }
  return next
}

/** 已经不在的那些（作者手删过）当成功，保证「回填失败重试」不会卡在这儿 */
function isMissing(err: unknown): boolean {
  return (err as { response?: { status?: number } })?.response?.status === 404
}

async function drop(del: () => Promise<unknown>): Promise<void> {
  try {
    await del()
  } catch (err) {
    if (!isMissing(err)) throw err
  }
}

/**
 * 删台账里记着的那几个地点。**子必须先于父**：parent_id 是硬外键，
 * 父地点还带着孩子时删不掉。建的那边也是同一个理由按层建。
 */
async function dropWrittenLocations(written: RpgLocation[]): Promise<void> {
  const left = new Set(written.map(loc => loc.id))
  const children = new Map<number, number[]>()
  for (const loc of written) {
    if (loc.parent_id != null && left.has(loc.parent_id)) {
      children.set(loc.parent_id, [...(children.get(loc.parent_id) || []), loc.id])
    }
  }
  while (left.size) {
    const leaves = [...left].filter(id => !(children.get(id) || []).some(child => left.has(child)))
    // 环形引用不该出现，真出现了也别死循环：剩下的按原顺序删，让外键去报错
    for (const id of leaves.length ? leaves : [...left]) {
      left.delete(id)
      await drop(() => rpgApi.locations.delete(id))
    }
  }
}

/**
 * 把地点/角色/道具/技能/任务/动作写进模组，返回这一轮写进去的台账。
 *
 * 每一栏先删掉上一轮向导建的行、再建这一轮的——同名跳过仍然管用，但只对
 * **留下来的**（作者手写的）同名行生效。没勾的栏一律不碰，旧行和台账都留着。
 */
export async function applyWizardEntities(
  moduleId: number, picked: WizardPicked, prev: RpgWizardState,
): Promise<RpgWizardState> {
  const writing = {
    locations: !!picked.locations?.length,
    npcs: !!picked.npcs?.length,
    items: !!picked.items?.length,
    skills: !!picked.skills?.length,
    tasks: !!picked.tasks?.length,
    actions: !!picked.actions?.length,
  }
  const [allLocations, allNpcs, allItems, allSkills, allTasks, allActions] = await Promise.all([
    writing.locations ? rpgApi.locations.list(moduleId) : Promise.resolve([] as RpgLocation[]),
    writing.npcs ? rpgApi.npcs.list(moduleId) : Promise.resolve([]),
    writing.items ? rpgApi.items.list(moduleId) : Promise.resolve([]),
    writing.skills ? rpgApi.skills.list(moduleId) : Promise.resolve([]),
    writing.tasks ? rpgApi.tasks.list(moduleId) : Promise.resolve([]),
    writing.actions ? rpgApi.actions.list(moduleId) : Promise.resolve([]),
  ])

  const gone = new Set(writing.locations ? prev.location_ids || [] : [])
  const goneNpcIds = new Set(writing.npcs ? prev.npc_ids || [] : [])
  const goneItemIds = new Set(writing.items ? prev.item_ids || [] : [])
  const goneSkillIds = new Set(writing.skills ? prev.skill_ids || [] : [])
  const goneTaskIds = new Set(writing.tasks ? prev.task_ids || [] : [])
  const goneActionIds = new Set(writing.actions ? prev.action_ids || [] : [])

  if (gone.size) await dropWrittenLocations(allLocations.filter(loc => gone.has(loc.id)))
  for (const id of goneNpcIds) await drop(() => rpgApi.npcs.delete(id))
  for (const id of goneItemIds) await drop(() => rpgApi.items.delete(id))
  for (const id of goneSkillIds) await drop(() => rpgApi.skills.delete(id))
  for (const id of goneTaskIds) await drop(() => rpgApi.tasks.delete(id))
  for (const id of goneActionIds) await drop(() => rpgApi.actions.delete(id))

  // 删完再建。留下来的列表里不能还剩刚删掉的那些行，否则同名的新条目会被
  // 「同名跳过」挡下来，等于白删
  const locations = allLocations.filter(loc => !gone.has(loc.id))
  const npcs = allNpcs.filter(npc => !goneNpcIds.has(npc.id))
  const items = allItems.filter(item => !goneItemIds.has(item.id))
  const skills = allSkills.filter(skill => !goneSkillIds.has(skill.id))
  const tasks = allTasks.filter(task => !goneTaskIds.has(task.id))
  const actions = allActions.filter(action => !goneActionIds.has(action.id))

  const pendingLocations = newNamed(locations, picked.locations || [])
  const locationIds = new Map(locations.map(loc => [loc.name.trim(), loc.id]))
  const locationNames = new Map([...locations, ...pendingLocations].map(loc => [loc.name.trim(), loc.name]))
  const resolveLocation = (name: string) => locationNames.get(name.trim()) || name
  const createdLocationIds: number[] = []
  while (pendingLocations.length) {
    const ready = pendingLocations.filter(loc => !loc.parent_name || locationIds.has(loc.parent_name.trim()))
    const batch = ready.length ? ready : [pendingLocations[0]]
    for (const location of batch) {
      const parentId = location.parent_name ? locationIds.get(location.parent_name.trim()) : undefined
      const created = await rpgApi.locations.create(moduleId, {
        name: location.name,
        description: location.description,
        connections: (location.connections || []).map(resolveLocation),
        ...(parentId !== undefined ? { parent_id: parentId } : {}),
      })
      locationIds.set(location.name.trim(), created.id)
      createdLocationIds.push(created.id)
      pendingLocations.splice(pendingLocations.indexOf(location), 1)
    }
  }

  const createdNpcIds: number[] = []
  for (const npc of newNamed(npcs, picked.npcs || [])) {
    // 作息表里的地点名也要过 resolveLocation：和 location 一样，模型写的名字
    // 可能和真正建出来的那行差一点，不归一化就是一条永远不生效的作息
    const slotLocations = Object.fromEntries(
      Object.entries(npc.slot_locations || {}).map(([slot, place]) => [slot, resolveLocation(place)]),
    )
    const created = await rpgApi.npcs.create(moduleId, {
      name: npc.name, persona: npc.persona, appearance: npc.appearance,
      description: npc.description, profile_sections: npc.profile_sections || {},
      location: resolveLocation(npc.location || ''), initial_state: npc.initial_state,
      relation_enabled: Object.keys(npc.initial_state || {}).length > 0,
      slot_locations: slotLocations, dialogue_examples: npc.dialogue_examples || [],
    })
    createdNpcIds.push(created.id)
  }
  const createdItemIds: number[] = []
  for (const item of newNamed(items, picked.items || [])) {
    const created = await rpgApi.items.create(moduleId, {
      name: item.name, description: item.description, category: item.category,
      consumable: item.consumable, start_with: item.start_with, effects: item.effects,
    })
    createdItemIds.push(created.id)
  }
  const createdSkillIds: number[] = []
  for (const skill of newNamed(skills, picked.skills || [])) {
    const created = await rpgApi.skills.create(moduleId, {
      name: skill.name, description: skill.description, category: skill.category,
      cooldown: skill.cooldown, start_with: skill.start_with, effects: skill.effects,
      requires: skill.requires || {},
    })
    createdSkillIds.push(created.id)
  }
  const createdTaskIds: number[] = []
  for (const task of newNamed(tasks, picked.tasks || [])) {
    const created = await rpgApi.tasks.create(moduleId, {
      name: task.name, description: task.description, objective: task.objective,
      category: task.category, auto_start: task.auto_start, effects: task.effects,
    })
    createdTaskIds.push(created.id)
  }
  const createdActionIds: number[] = []
  for (const action of newNamed(actions, picked.actions || [])) {
    const created = await rpgApi.actions.create(moduleId, {
      name: action.name, prompt_hint: action.prompt_hint, needs_target: action.needs_target,
      effects: action.effects, relation_effects: action.relation_effects,
      group: action.group || '',
      cost_slot: !!action.cost_slot, at_location: resolveLocation(action.at_location || ''),
    })
    createdActionIds.push(created.id)
  }

  // 台账 = 「现在这个模组里属于向导的那些」。没写的栏沿用上一轮的台账，
  // 因为那些行还留在模组里，下次回填仍然得认得出来
  return {
    slots: picked.time_slots?.length ? trimmed(picked.time_slots) : prev.slots || [],
    stats: picked.stat_defs?.length ? names(picked.stat_defs) : prev.stats || [],
    relation_stats: picked.relation_stat_defs?.length ? names(picked.relation_stat_defs) : prev.relation_stats || [],
    location_ids: writing.locations ? createdLocationIds : prev.location_ids || [],
    npc_ids: writing.npcs ? createdNpcIds : prev.npc_ids || [],
    item_ids: writing.items ? createdItemIds : prev.item_ids || [],
    skill_ids: writing.skills ? createdSkillIds : prev.skill_ids || [],
    task_ids: writing.tasks ? createdTaskIds : prev.task_ids || [],
    action_ids: writing.actions ? createdActionIds : prev.action_ids || [],
  }
}
