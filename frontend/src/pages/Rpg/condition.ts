import type { RpgAction, RpgCondition, RpgLocation, RpgModule, RpgNpc, RpgSession } from '@/api/client'

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

  const byId = new Map(locations.map(loc => [loc.id, loc]))
  let parentId = here.parent_id
  while (parentId != null) {
    if (out.has(parentId)) break
    out.add(parentId)
    parentId = byId.get(parentId)?.parent_id ?? null
  }
  return out
}

/**
 * 这个人此刻在哪儿：剧情挪过她就听剧情的，然后「跟着你」那一层，再是作息表
 * → 常驻地点。
 *
 * 后端 `rpg_context.npc_place` 的镜像，两边必须一样——不一样的那一次就是
 * 「面板上他站在你面前，提示词里却没有这个人」。
 *
 * places 传这一局的 `sess.npc_places`：玩家说了句「你过来」，结算把她的新位置
 * 写在里面，下一轮这一格就显示「就在你面前」。读不到会话的场合（模组编辑页）
 * 不传，行为和不传一样。
 *
 * followers / here 一起传：`here` 是**玩家此刻在哪**，跟着你的人就解析成它。
 * 只传 followers 不传 here 是空操作（后端那一层同样要求 here 非空）。
 */
export const npcPlace = (
  npc: RpgNpc, slot: string, places?: Record<string, string>,
  followers?: number[], here?: string,
) => {
  const over = ((places || {})[String(npc.id)] || '').trim()
  if (over) return over
  // 跟着你的那一层：解析出来就是**你此刻的位置**，所以关键随你走、零同步。
  // `here` 必须传玩家当前所在地（sess.location），**不能传要比较的那个地名**
  // ——那样跟随者在每一个地点都算「在」
  const at = (here || '').trim()
  if (at && (followers || []).includes(npc.id)) return at
  const now = (slot || '').trim()
  return (now ? ((npc.slot_locations || {})[now] || '').trim() : '') || (npc.location || '')
}

/** 他此刻是不是和玩家在同一个地点 */
export const onstage = (npc: RpgNpc, sess: RpgSession) =>
  !!sess.location
  && norm(npcPlace(npc, sess.slot, sess.npc_places, sess.npc_followers, sess.location))
    === norm(sess.location)

/** 他是不是跟着你走（在 `sess.npc_followers` 名单里）。
 *  **这不是第二个在场判据**——在场仍然只有 `onstage` 那一个定义。这个只用来
 *  画侧栏那个「跟着你」小块和打发她走的叉 */
export const following = (npc: RpgNpc, sess: RpgSession) =>
  (sess.npc_followers || []).includes(npc.id)

/**
 * 玩家已经知道存在的人：见过面的，加上此刻就在同一个地点的。
 *
 * 只认 met 会漏掉开局：met 要等他真的进过一轮上下文才置位，
 * 而开局时站在你起始地点的那个人，画面里明明就在眼前。
 * 主角模板不登场，永远排除。
 *
 * **模拟器给全量**：老板手里本来就有一份员工名册，开局就该全员在册。
 * 藏到见面才登记在这档里反而怪——「招募秘书」要能看见还没见过的人，
 * 手机也得能打给还没见过的人。
 *
 * 这一份和**后端那个 met 不是一回事**：后端管的是外貌要不要注入，
 * 这里管的是名单给谁看。别为了省事去建局时把 met 预置成 true——
 * 那样模型从此再也不知道任何人长什么样。
 */
export const knownNpcs = (npcs: RpgNpc[], sess: RpgSession, module?: RpgModule) =>
  npcs.filter(n => n.role !== 'protagonist'
    && (module?.play_style === 'sim'
      || sess.npc_states?.[String(n.id)]?.met || onstage(n, sess)))

/** 名字里的间隔号。只在人名比对时去掉，也不进 `norm`——背包那边「铁-钥匙」
 *  和「铁钥匙」是不是一件东西是另一个问题。同后端 `rpg_state._NAME_SEPS` */
const NAME_SEPS = /[·•・.\-_、,，]/g

/** 半个名字最少要这么长才敢认。一个字的「李」能撞上一整屋人（同 `_MIN_PARTIAL`） */
const MIN_PARTIAL = 2

/**
 * 关系条件里「不指定是谁」的写法。后端 `rpg_state.ANY_NPC` 的同名镜像，
 * 两边必须一样——不一样的那一次就是「按钮亮着，点下去后端说没人达标」。
 */
export const ANY_NPC = '*'

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
  // 这个角色此刻的这项关系数值；没在追踪就是 null。同后端 `_relation_value`：
  // 「没追踪」和「值等于 0」是两回事，前者该说没有追踪
  const value = (npc: RpgNpc, stat: string): number | null => {
    if (npc.relation_enabled === false) return null
    const state = states[String(npc.id)] || {}
    return stat in state ? Number(state[stat] || 0) : null
  }
  for (const rule of cond.relations || []) {
    const op = OPS[rule.op || '>=']
    if (!op) continue
    const want = Number(rule.value || 0)
    // ANY_NPC = 不指定是谁，任意一个角色达标就算成立。同后端 check_condition
    if (rule.npc === ANY_NPC) {
      if (!npcs.some(n => {
        const have = value(n, rule.stat)
        return have !== null && op(have, want)
      })) {
        return [false, `没有角色的${rule.stat}满足（需要 ${rule.op} ${rule.value}）`]
      }
      continue
    }
    const npc = npcs.find(n => norm(n.name) === norm(rule.npc))
    if (!npc) return [false, `找不到角色「${rule.npc}」`]
    const have = value(npc, rule.stat)
    if (have === null) return [false, `${rule.npc}没有追踪关系数值「${rule.stat}」`]
    if (!op(have, want)) {
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

  // 「某件事之后 N 天」。同后端：flag 没立过、或立过但没记日期（老局）都判不成立
  const flagDays = sess.flag_days || {}
  for (const rule of cond.after_days || []) {
    const key = (rule.flag || '').trim()
    if (!key) continue
    if (!flags[key]) return [false, `还没有「${key}」`]
    const since = flagDays[key]
    if (since == null) return [false, `没记下「${key}」是哪天发生的`]
    const left = Number(since) + Number(rule.days || 0) - Number(sess.day || 1)
    if (left > 0) return [false, `「${key}」之后还要等 ${left} 天`]
  }

  const owned = new Set((sess.inventory || []).map(it => norm(it.name)))
  for (const want of cond.items || []) {
    if (!owned.has(norm(want))) return [false, `没有「${(want || '').trim()}」`]
  }

  return [true, '']
}

/**
 * 这个行动此刻能不能点。空串 = 能点，否则是给玩家看的那一句「差在哪」。
 *
 * 三条判据和后端 `_action_gate` 一一对应：requires → at_location → needs_target。
 * at_location 不在 RpgCondition 里，是 RpgAction 自己的一列，所以只能在这儿单独判。
 *
 * 收成一份是因为有两个调用方（对话页的快捷行动、模拟器主页），而两处各写一遍
 * 已经漂过一次：模拟器那份有 at_location，对话页那份漏了——「限客卧」的动作
 * 走到别处照样亮着，点下去后端才拦。判定权始终在后端（`_run_action` 会拦），
 * 这里只管别让玩家点到一个必然失败的按钮。
 */
export function actionBlocked(
  action: RpgAction, sess: RpgSession, npcs: RpgNpc[], target = '', module?: RpgModule,
): string {
  if (action.needs_target && action.target_anywhere && !target) {
    const candidates = knownNpcs(npcs, sess, module)
    return candidates.some(npc => !actionBlocked(action, sess, npcs, npc.name, module))
      ? '' : '没有满足条件的对象'
  }
  const picked = action.needs_target
    ? npcs.filter(n => norm(n.name) === norm(target))
    : npcs
  const [ok, why] = checkCondition(action.requires, sess, picked)
  if (!ok) return why
  const need = (action.at_location || '').trim()
  if (need && norm(need) !== norm(sess.location || '')) return `得在${need}才行`
  const cost = effectCostReason(action.effects, sess, module)
  if (cost) return cost
  // 远程动作不要求事先选好对象：它的顺序是反过来的——点了按钮才挑人
  // （RpgPlay 的 runAction 会弹名单）。这里按老规矩判的话，「发消息」在
  // 没预选对象时是灰的，而玩家根本没有预选它的入口
  if (action.needs_target && !action.target_anywhere && !target) return '先选一个对象'
  return ''
}

export function effectCostReason(
  effects: Record<string, number> | undefined, sess: RpgSession, module?: RpgModule,
): string {
  for (const [name, amount] of Object.entries(effects || {})) {
    const minimum = module?.stat_defs.find(spec => spec.name === name)?.min ?? 0
    if (amount < 0 && (sess.stats[name] ?? 0) + amount < minimum) {
      return `${name}不足，需要至少 ${minimum - amount}`
    }
  }
  return ''
}

/**
 * 这个动作能挑谁当对象。
 *
 * 远程动作（手机、传讯）挑名册上的人：不在跟前正是它存在的理由。名单本身
 * 仍然按 knownNpcs 那一份走——探索冒险档里见过面这条门槛要留着，对一个还没
 * 登场的人发消息等于把他从名单里抖出来；模拟器档名册本来就是全员。
 * 其余动作只能挑此刻站在跟前的人：「夸她」隔着三条街不成立。
 */
export const targetChoices = (
  action: RpgAction, npcs: RpgNpc[], sess: RpgSession, hereNpcs: RpgNpc[],
  module?: RpgModule,
) => (action.target_anywhere ? knownNpcs(npcs, sess, module) : hereNpcs)
