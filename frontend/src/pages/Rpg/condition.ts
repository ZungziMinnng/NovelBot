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
  // 按 norm 配，不按字面：地图上的线是 edgePairs 按 norm 画的，这里按字面配的话，
  // 连接名多一个空格（从别处粘进来的）会变成「线画着，点却还是灰的」
  || (here.connections || []).some(n => norm(n) === norm(loc.name))
  || (loc.connections || []).some(n => norm(n) === norm(location))

/**
 * 有路通到它的地点 id。判据和 mapLayout.edgePairs 完全一致：按 norm 配名字，
 * 悬空的名字（作者改名之后留下的）不算——画不出线的连接不能拿来散迷雾。
 */
function wiredIds(locations: RpgLocation[]): Set<number> {
  const byName = new Map(locations.map(l => [norm(l.name), l]))
  const out = new Set<number>()
  for (const a of locations) {
    for (const name of a.connections || []) {
      const b = byName.get(norm(name))
      if (!b || b.id === a.id) continue
      out.add(a.id)
      out.add(b.id)
    }
  }
  return out
}

/**
 * 地图上看得见的地点 id。去过的、当前站着的，加上它们的邻居；其余是迷雾。
 *
 * 同 knownNpcs 的道理：没探到的地方连名字都不该露出来。逃生口和 linked 一致
 * ——当前地点不在表里时全部可见，否则玩家会看到一张全黑的地图却什么都能去。
 *
 * **一条路都没连的地点始终可见。** 迷雾是顺着连接散的，不在图里的点没有任何
 * 路径能照亮它：玩家看不见就点不了，点不了就永远走不到，于是它永远是个灰点。
 * 作者在画布上双击建一个地点、还没来得及连线，就正好是这种情况——加完之后
 * 进游戏发现它不在，只会以为是没存上。要藏东西该用进入条件，那个至少会
 * 告诉玩家差在哪。
 */
export function visibleLocations(locations: RpgLocation[], sess: RpgSession): Set<number> {
  const at = sess.location || ''
  const here = locations.find(l => norm(l.name) === norm(at))
  if (!at || !here) return new Set(locations.map(l => l.id))

  const lit = new Set([norm(here.name), ...(sess.visited || []).map(norm)])
  const wired = wiredIds(locations)
  const out = new Set<number>()
  for (const loc of locations) {
    const near = !wired.has(loc.id)
      || lit.has(norm(loc.name))
      || locations.some(p => lit.has(norm(p.name)) && linked(loc, p, p.name))
    if (near) out.add(loc.id)
  }
  return out
}

/**
 * 这个人此刻在哪儿：剧情挪过她就听剧情的，否则作息表 → 常驻地点。
 *
 * 后端 `rpg_context.npc_place` 的镜像，两边必须一样——不一样的那一次就是
 * 「面板上他站在你面前，提示词里却没有这个人」。
 *
 * places 传这一局的 `sess.npc_places`：玩家说了句「你过来」，结算把她的新位置
 * 写在里面，下一轮这一格就显示「就在你面前」。读不到会话的场合（模组编辑页）
 * 不传，行为和不传一样。
 */
export const npcPlace = (npc: RpgNpc, slot: string, places?: Record<string, string>) => {
  const over = ((places || {})[String(npc.id)] || '').trim()
  if (over) return over
  const now = (slot || '').trim()
  const at = now ? ((npc.slot_locations || {})[now] || '').trim() : ''
  return at || (npc.location || '')
}

/** 他此刻是不是和玩家在同一个地点 */
export const onstage = (npc: RpgNpc, sess: RpgSession) =>
  !!sess.location && norm(npcPlace(npc, sess.slot, sess.npc_places)) === norm(sess.location)

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

/** 名字里的间隔号。只在人名比对时去掉，也不进 `norm`——背包那边「铁-钥匙」
 *  和「铁钥匙」是不是一件东西是另一个问题。同后端 `rpg_state._NAME_SEPS` */
const NAME_SEPS = /[·•・.\-_、,，]/g

/** 半个名字最少要这么长才敢认。一个字的「李」能撞上一整屋人（同 `_MIN_PARTIAL`） */
const MIN_PARTIAL = 2

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
