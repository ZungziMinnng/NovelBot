import type { RpgCondition, RpgLocation, RpgNpc, RpgSession } from '@/api/client'

export const norm = (s: string) => (s || '').trim().toLowerCase()

/**
 * `loc` 是不是挨着 `location`。连接是双向的：作者在 A 里写了 B，B 也算挨着 A。
 *
 * **只给迷雾用**，不是关卡：移动不看连接（后端 _move 也不看），
 * 连接只决定地图上画不画那条线、以及去过之后能顺带照亮谁。
 * `location` 空、或者当前地点不在地点表里（模型能把你「移动」到任何一个
 * 它现编的地名上）时一律算挨着——那种局面下不该把整张地图都藏起来。
 */
const linked = (loc: RpgLocation, here: RpgLocation | undefined, location: string) =>
  !location || !here
  || (here.connections || []).includes(loc.name)
  || (loc.connections || []).includes(location)

/**
 * 地图上看得见的地点 id。去过的、当前站着的，加上它们的邻居；其余是迷雾。
 *
 * 同 knownNpcs 的道理：没探到的地方连名字都不该露出来。逃生口和 linked 一致
 * ——当前地点不在表里时全部可见，否则玩家会看到一张全黑的地图却什么都能去。
 */
export function visibleLocations(locations: RpgLocation[], sess: RpgSession): Set<number> {
  const at = sess.location || ''
  const here = locations.find(l => norm(l.name) === norm(at))
  if (!at || !here) return new Set(locations.map(l => l.id))

  const lit = new Set([norm(here.name), ...(sess.visited || []).map(norm)])
  const out = new Set<number>()
  for (const loc of locations) {
    const near = lit.has(norm(loc.name))
      || locations.some(p => lit.has(norm(p.name)) && linked(loc, p, p.name))
    if (near) out.add(loc.id)
  }
  return out
}

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

  // 时段：和后端一样，没设时段时判不成立而不是放行——
  // 放行会让「只有晚上开」的门永远开着
  const slots = cond.slots || []
  if (slots.length > 0) {
    const now = (sess.slot || '').trim()
    if (!now) return [false, '这个模组没有设定时段']
    const allow = slots.filter(s => !s.startsWith('!')).map(s => s.trim())
    const deny = slots.filter(s => s.startsWith('!')).map(s => s.slice(1).trim())
    if (deny.includes(now)) return [false, `${now}不能做这件事`]
    if (allow.length > 0 && !allow.includes(now)) {
      return [false, `只有${allow.join('、')}能做这件事（现在是${now}）`]
    }
  }

  if (cond.day) {
    const op = OPS[cond.day.op || '>=']
    const day = Number(sess.day || 1)
    if (op && !op(day, Number(cond.day.value ?? 1))) {
      return [false, `第 ${day} 天不满足（需要 ${cond.day.op} ${cond.day.value}）`]
    }
  }

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
