import type { RpgNpc } from '@/api/client'

/**
 * 主角模板卡：`role = 'protagonist'` 的那一张，没有就是 null。
 *
 * 主角不是一个新字段。同一张卡编辑器管 NPC 和主角两种角色，主角那张不登场
 * （`world_npcs` / `knownNpcs` / `OpeningCast` 都把它过滤掉），只用来定「玩家
 * 扮演谁」。「主角」面板改的就是这张卡，所以两处不会各存一份主角设定。
 */
export const protagonistCard = (npcs: RpgNpc[]): RpgNpc | null =>
  npcs.find(n => n.role === 'protagonist') || null

/**
 * 卡上的两栏拼成建局要用的那一段「出身与动机」。
 *
 * 卡上是分开的（一句话简介 + 性格），而这一局只有 `char_desc` 一栏。后端锁定
 * 主角时是同一个拼法（services/rpg_state.protagonist_identity）——两边拼得不一样，
 * 玩家在弹窗里看到的就不是真正存进去的那一份。
 */
export const protagonistDesc = (npc: RpgNpc): string =>
  [npc.description, npc.persona].map(s => (s || '').trim()).filter(Boolean).join('\n\n')
