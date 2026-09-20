import type { RpgAction, RpgModule, RpgSession, RpgStatDef } from '@/api/client'

export function actionTimeHint(action: RpgAction, session: RpgSession, module?: RpgModule): string {
  const slots = (session.time_slots?.length ? session.time_slots : module?.time_slots || [])
    .map(slot => slot.trim()).filter(Boolean)
  if (!slots.length) return '不推进时间'
  const budget = module?.slot_budget || 0
  const advances = action.cost_slot || (budget > 0 && (session.slot_actions || 0) + 1 >= budget)
  const cost = action.cost_slot ? '推进 1 个时段' : budget > 0 ? '消耗 1 次行动' : '不自动推进时间'
  if (!advances) return cost
  const nextIndex = slots.indexOf((session.slot || '').trim()) + 1
  const nextDay = Math.max(1, session.day || 1) + (nextIndex >= slots.length ? 1 : 0)
  return `${cost} · 本次结束于第 ${nextDay} 天 · ${slots[nextIndex % slots.length]}`
}

export function effectPreview(
  name: string, amount: number, definitions?: RpgStatDef[], values?: Record<string, number>,
): string {
  const key = name.trim()
  const definition = definitions?.find(row => row.name.trim() === key)
  if (definitions && !definition) return `${key}未生效（未定义）`
  if (!definition || !values) return `${key}${amount > 0 ? '+' : ''}${amount}（基础效果）`
  const before = Math.trunc(values[key] ?? 0)
  const lower = Math.max(definition.min ?? 0, before + Math.trunc(amount))
  const after = definition.max == null ? lower : Math.min(definition.max, lower)
  const actual = after - before
  return `${key}${actual ? `${actual > 0 ? '+' : ''}${actual}` : '不变'}`
}
