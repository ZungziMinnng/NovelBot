import type { RpgModule, RpgPlayStyle } from '@/api/client'

/** 玩法决定这局怎么玩，题材（genre）决定世界是什么。 */
export const PLAY_STYLES: Array<{
  key: RpgPlayStyle
  label: string
  hint: string
}> = [
  { key: 'sim', label: '模拟器', hint: '模拟一个身份、职业或系统，管理日程、权限、资源和环境变化。' },
  { key: 'rpg', label: '探索冒险', hint: '闯地方：地图、道具、判定是主角，有输有赢。' },
  { key: 'slg', label: '角色养成', hint: '安排角色的每日行动，推进属性、关系、阶段事件和结局。' },
]

export const styleLabel = (key: string) =>
  PLAY_STYLES.find(s => s.key === key)?.label ?? '探索冒险'

/** 建新模组时带入的起点，作者进入编辑页后仍可调整。 */
export const STYLE_DEFAULTS: Record<RpgPlayStyle, Partial<RpgModule>> = {
  sim: { check_mode: 'never', random_check: false, time_slots: ['早晨', '白天', '夜晚'] },
  rpg: { check_mode: 'never', random_check: true, time_slots: [] },
  slg: { check_mode: 'never', random_check: false, time_slots: ['早晨', '白天', '夜晚'] },
}

export type BlockName =
  | 'stats' | 'slots' | 'actions' | 'items' | 'skills' | 'tasks' | 'locations'
  // 开局背包并进了 protagonist，不再单独占一格
  | 'protagonist' | 'worldbook' | 'npcs' | 'difficulty'
  // 这两个不是「一摊数据」而是整页的头和尾，但既然这张表就是面板顺序的唯一来源，
  // 它们也得在里面——漏一个的表达方式是「这一档不显示它」，那不是我们要的
  | 'world' | 'narration' | 'generation'

/** 面板顺序。类型只改变编辑重点和默认顺序，不隐藏或删除其它能力。
 *
 *  sim 把「功能」提到数值后面、地点前面：那一档的功能按钮就是玩家的主界面
 *  （见 SimHome），地点退成主页上的一栏，编辑时的注意力顺序也该跟着换。
 *
 *  三档都把 protagonist 排在 world 后头：「这个世界是什么」定完，紧接着就是
 *  「玩家在这个世界里是谁」，而开局背包是那个人身上带着的东西，所以它从原来
 *  的倒数第几格搬进了那一块（见 BLOCK_TITLES 上的注释）。
 *
 *  **slots 三档都要有。** 它原先只排在 sim 里，于是 rpg 模组根本找不到填时段
 *  的地方——而作息表、跨天恢复、带时段门槛的世界书/地点/动作、每时段行动上限
 *  全都是后端一视同仁支持的能力，唯独入口被这张表藏掉了。这和上面那句「不隐藏
 *  或删除其它能力」直接矛盾。rpg/slg 里排在地点后面（时段和作息表是一对），
 *  sim 保持原位。默认时段表仍按 STYLE_DEFAULTS 各行其是，rpg 依旧是空的——
 *  这里只管「找不找得到」，不管「默认开不开」。 */
export const STYLE_BLOCKS: Record<RpgPlayStyle, BlockName[]> = {
  rpg: ['world', 'protagonist', 'npcs', 'locations', 'slots', 'stats', 'actions', 'skills', 'items', 'tasks', 'narration', 'generation', 'worldbook', 'difficulty'],
  sim: ['world', 'protagonist', 'stats', 'actions', 'npcs', 'locations', 'slots', 'skills', 'items', 'tasks', 'narration', 'generation', 'worldbook', 'difficulty'],
  slg: ['world', 'protagonist', 'npcs', 'locations', 'slots', 'stats', 'actions', 'skills', 'items', 'tasks', 'narration', 'generation', 'worldbook', 'difficulty'],
}

/** 面板标题。sim 那一档「动作按钮」改叫「功能」：在那边它不是聊天框旁边的
 *  快捷路，而是玩家的主界面本身 */
export const BLOCK_TITLES: Record<BlockName, string> = {
  world: '世界观',
  npcs: '角色',
  locations: '地点',
  stats: '数值系统',
  actions: '动作按钮',
  skills: '技能',
  items: '道具',
  tasks: '任务',
  slots: '时段',
  // 「开局时的背包」原先是自己一格，现在是这一块里的一栏：它是主角开局身上
  // 带着的东西，摆在别处的话作者要在两个面板之间来回对
  protagonist: '主角',
  narration: '叙事风格',
  generation: '生成参数',
  worldbook: '世界书',
  difficulty: '判定',
}

export const blockTitle = (name: BlockName, playStyle: RpgPlayStyle): string =>
  name === 'actions' && playStyle === 'sim' ? '功能' : BLOCK_TITLES[name]

export const STYLE_EXAMPLES: Record<RpgPlayStyle, { stat: string; action: string; location: string }> = {
  sim: { stat: '权限', action: '安排日程', location: '办公室' },
  rpg: { stat: '体力', action: '搜刮', location: '地窖' },
  slg: { stat: '服从', action: '安排训练', location: '房间' },
}
