import type { RpgCondition, RpgNpc, RpgSession } from '@/api/client'

export const norm = (s: string) => (s || '').trim().toLowerCase()

/** 他此刻是不是和玩家在同一个地点 */
export const onstage = (npc: RpgNpc, sess: RpgSession) =>
  !!sess.location && norm(npc.location) === norm(sess.location)

/**
 * 玩家已经知道存在的人：见过面的，加上此刻就在同一个地点的。
 *
 * 只认 met 会漏掉开局：met 要等他真的进过一轮上下文才置位，
 * 而开局时站在你起始地点的那个人，画面里明明就在眼前。
 * 主角模板不登场，永远排除。
 */
export const knownNpcs = (npcs: RpgNpc[], sess: RpgSession) =>
  npcs.filter(n => n.role !== 'protagonist'
    && (sess.npc_states?.[String(n.id)]?.met || onstage(n, sess)))

const OPS: Record<string, (a: number, b: number) => boolean> = {
  '>=': (a, b) => a >= b,
  '>': (a, b) => a > b,
  '<=': (a, b) => a <= b,
  '<': (a, b) => a < b,
  '==': (a, b) => a === b,
  '!=': (a, b) => a !== b,
}

/**
 * 后端 rpg_state.check_condition 的镜像，只为了把不能点的按钮提前灰掉并写明原因。
 * 判定权仍然在后端：这里放行了后端照样会拦，反过来则不会。
 */
export function checkCondition(
  cond: RpgCondition | undefined, sess: RpgSession, npcs: RpgNpc[],
): [boolean, string] {
  if (!cond) return [true, '']

  const stats = sess.stats || {}
  for (const [name, rule] of Object.entries(cond.stats || {})) {
    const op = OPS[rule.op || '>=']
    if (!op) continue
    const have = Number(stats[name] || 0)
    if (!op(have, Number(rule.value || 0))) {
      return [false, `${name}不满足（当前 ${have}，需要 ${rule.op} ${rule.value}）`]
    }
  }

  const states = sess.npc_states || {}
  for (const rule of cond.relations || []) {
    const npc = npcs.find(n => norm(n.name) === norm(rule.npc))
    if (!npc) return [false, `找不到角色「${rule.npc}」`]
    const op = OPS[rule.op || '>=']
    if (!op) continue
    const have = Number(states[String(npc.id)]?.[rule.stat] || 0)
    if (!op(have, Number(rule.value || 0))) {
      return [false, `${rule.npc}的${rule.stat}不满足（当前 ${have}，需要 ${rule.op} ${rule.value}）`]
    }
  }

  const flags = sess.flags || {}
  for (const raw of cond.flags || []) {
    const key = (raw || '').trim()
    if (key.startsWith('!')) {
      if (flags[key.slice(1).trim()]) return [false, `「${key.slice(1).trim()}」已经发生了`]
    } else if (!flags[key]) {
      return [false, `还没有「${key}」`]
    }
  }

  const owned = new Set((sess.inventory || []).map(it => norm(it.name)))
  for (const want of cond.items || []) {
    if (!owned.has(norm(want))) return [false, `没有「${(want || '').trim()}」`]
  }

  return [true, '']
}
