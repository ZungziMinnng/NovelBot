import { rpgApi, type RpgModule } from '@/api/client'
import type { WizardPicked } from './WizardApplyModal'

function newNamed<T extends { name: string }>(existing: { name: string }[], incoming: T[]): T[] {
  const names = new Set(existing.map(row => row.name.trim()))
  return incoming.filter(row => {
    const name = row.name.trim()
    if (!name || names.has(name)) return false
    names.add(name)
    return true
  })
}

export function mergeWizardFields(current: RpgModule, picked: WizardPicked): RpgModule {
  const next = { ...current }
  for (const key of ['genre', 'worldview', 'opening_scene', 'system_instruction', 'narration_sample', 'default_location'] as const) {
    const value = picked[key]
    if (typeof value === 'string' && value) next[key] = value
  }
  if (picked.time_slots?.length) {
    const slots = new Set((current.time_slots || []).map(slot => slot.trim()))
    const added = picked.time_slots.filter(slot => {
      const name = slot.trim()
      if (!name || slots.has(name)) return false
      slots.add(name)
      return true
    })
    next.time_slots = [...(current.time_slots || []), ...added]
  }
  for (const key of ['stat_defs', 'relation_stat_defs'] as const) {
    if (picked[key]?.length) {
      const existing = current[key] || []
      next[key] = [...existing, ...newNamed(existing, picked[key])]
    }
  }
  return next
}

export async function applyWizardEntities(moduleId: number, picked: WizardPicked): Promise<void> {
  const [locations, npcs, items, actions] = await Promise.all([
    picked.locations?.length || picked.npcs?.length ? rpgApi.locations.list(moduleId) : Promise.resolve([]),
    picked.npcs?.length ? rpgApi.npcs.list(moduleId) : Promise.resolve([]),
    picked.items?.length ? rpgApi.items.list(moduleId) : Promise.resolve([]),
    picked.actions?.length ? rpgApi.actions.list(moduleId) : Promise.resolve([]),
  ])
  const pendingLocations = newNamed(locations, picked.locations || [])
  const locationIds = new Map(locations.map(location => [location.name.trim(), location.id]))
  const locationNames = new Map([...locations, ...pendingLocations].map(location => [location.name.trim(), location.name]))
  const resolveLocation = (name: string) => locationNames.get(name.trim()) || name

  while (pendingLocations.length) {
    const ready = pendingLocations.filter(location => !location.parent_name || locationIds.has(location.parent_name.trim()))
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
      pendingLocations.splice(pendingLocations.indexOf(location), 1)
    }
  }
  for (const npc of newNamed(npcs, picked.npcs || [])) {
    await rpgApi.npcs.create(moduleId, {
      name: npc.name, persona: npc.persona, appearance: npc.appearance,
      description: npc.description, profile_sections: npc.profile_sections || {},
      location: resolveLocation(npc.location || ''), initial_state: npc.initial_state,
      relation_enabled: Object.keys(npc.initial_state || {}).length > 0,
    })
  }
  for (const item of newNamed(items, picked.items || [])) {
    await rpgApi.items.create(moduleId, {
      name: item.name, description: item.description, category: item.category,
      consumable: item.consumable, start_with: item.start_with, effects: item.effects,
    })
  }
  for (const action of newNamed(actions, picked.actions || [])) {
    await rpgApi.actions.create(moduleId, {
      name: action.name, prompt_hint: action.prompt_hint, needs_target: action.needs_target,
      effects: action.effects, relation_effects: action.relation_effects,
      group: action.group || '',
    })
  }
}
