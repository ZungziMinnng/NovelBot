import type { RpgModule, RpgPlayStyle } from '@/api/client'

/**
 * 玩法类别在界面上的那一份。
 *
 * 类别管「这局怎么玩」，题材（genre）管「什么世界」——同一个魔法学院可以是
 * 模拟养成也可以是探索冒险，所以两根轴分开。真正让模型改行为的是后端
 * services/rpg_play_style.py 注入的那段玩法规则，这个文件只负责三件事：
 * 建模组时带的默认开关、右栏的板块顺序、示例词。全是文案和取舍，不碰数据。
 *
 * 标签要和后端 STYLE_LABELS 一致，不然页头写着一套、模型收到另一套。
 */
export const PLAY_STYLES: Array<{
  key: RpgPlayStyle
  label: string
  /** 选的时候看的一句话 */
  hint: string
}> = [
  { key: 'sim', label: '模拟', hint: '过日子：数值和好感慢慢变，按时段推进，基本不打架。' },
  { key: 'rpg', label: '探索冒险', hint: '闯地方：地图、道具、判定是主角，有输有赢。' },
  { key: 'slg', label: '经营策略', hint: '算账本：资源有限，每回合权衡取舍，看长期结果。' },
]

export const styleLabel = (key: string) =>
  PLAY_STYLES.find(s => s.key === key)?.label ?? '探索冒险'

/**
 * 建新模组时按类别带的默认开关。只是起点，作者随时能改。
 *
 * 三个都是 check_mode='never'：判定默认全关是这个模式的既定设计（推动游戏的是
 * 数值在动，骰子只是冒险题材的调味）。类别改的是随机数和时段表——模拟和经营
 * 要一个可复现的账本，冒险不需要时钟。
 */
export const STYLE_DEFAULTS: Record<RpgPlayStyle, Partial<RpgModule>> = {
  sim: { check_mode: 'never', random_check: false, time_slots: ['早', '中', '晚'] },
  rpg: { check_mode: 'never', random_check: true, time_slots: [] },
  slg: { check_mode: 'never', random_check: false, time_slots: ['上半月', '下半月'] },
}

/** 编辑页右栏的板块。名字对应 RpgModule.tsx 里那张「块名 → JSX」的表 */
export type BlockName =
  | 'stats' | 'slots' | 'actions' | 'items' | 'locations'
  | 'inventory' | 'worldbook' | 'rules' | 'npcs' | 'difficulty'

/**
 * 右栏按类别排序。数值和时段永远在最前（整个模组的地基），判定永远在最后
 * （默认关着的东西不该占视线）；中间那几块谁在前，看这局主要在玩什么。
 */
export const STYLE_BLOCKS: Record<RpgPlayStyle, BlockName[]> = {
  // 探索冒险 = 现状，写作规则紧跟世界书（都是「怎么讲这个世界」）
  rpg: ['stats', 'slots', 'actions', 'items', 'locations', 'inventory', 'worldbook', 'rules', 'npcs', 'difficulty'],
  // 模拟的重心是人：角色卡提到动作前面
  sim: ['stats', 'slots', 'npcs', 'actions', 'items', 'locations', 'inventory', 'worldbook', 'rules', 'difficulty'],
  // 经营的重心是地盘：地点提到动作前面
  slg: ['stats', 'slots', 'locations', 'actions', 'items', 'inventory', 'worldbook', 'rules', 'npcs', 'difficulty'],
}

/** 几个输入框里的示例词。空表单最劝退，举的例子对不对路差别很大 */
export const STYLE_EXAMPLES: Record<RpgPlayStyle, { stat: string; action: string; location: string }> = {
  sim: { stat: '精力', action: '一起吃饭', location: '出租屋' },
  rpg: { stat: '体力', action: '搜刮', location: '地窖' },
  slg: { stat: '粮草', action: '征兵', location: '主城' },
}
