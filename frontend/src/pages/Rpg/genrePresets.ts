import type { RpgAction, RpgItem, RpgLocation, RpgStatDef } from '@/api/client'

export type ActionSeed = Pick<RpgAction, 'name' | 'prompt_hint' | 'effects' | 'relation_effects' | 'needs_target'>
type ItemSeed = Pick<
  RpgItem, 'name' | 'description' | 'category' | 'effects' | 'consumable' | 'start_with'
>
type LocationSeed = Pick<RpgLocation, 'name' | 'description' | 'connections'>

export interface GenrePreset {
  key: string
  label: string
  desc: string
  genre: string
  stat_defs: RpgStatDef[]
  relation_stat_defs: RpgStatDef[]
  actions: ActionSeed[]
  items: ItemSeed[]
  locations: LocationSeed[]
}

const bar = (
  name: string, initial: number, max: number | null, extra: Partial<RpgStatDef> = {},
): RpgStatDef => ({ name, initial, min: 0, max, display: max === null ? '数字' : '条', ...extra })

/**
 * 新建模组时一键套一套模板。
 *
 * 空白的数值表是最劝退的东西——作者打开设置页，看到「玩家数值」下面一个
 * 「添加一项」，根本不知道该填什么。套一套之后改几个字比从零想快得多。
 *
 * 全部存在前端：套用就是一次 PATCH 加几个 POST，后端不需要知道预设的存在。
 */
export const GENRE_PRESETS: GenrePreset[] = [
  {
    key: 'urban',
    label: '都市生活',
    desc: '打工、攒钱、维系关系。数值卡的是时间和钱。',
    genre: '现代都市生活',
    stat_defs: [
      bar('精力', 100, 100, { for_check: true, on_zero: '标记' }),
      bar('资金', 300, null),
      bar('声望', 0, null),
    ],
    relation_stat_defs: [bar('好感', 0, 100), bar('信任', 0, 100)],
    actions: [
      {
        name: '打工',
        prompt_hint: '你去顶了一个班，下来的时候腰是酸的。',
        effects: { 精力: -30, 资金: 200 },
        relation_effects: {},
        needs_target: false,
      },
      {
        name: '休息',
        prompt_hint: '你什么都不干，睡到自然醒。',
        effects: { 精力: 60 },
        relation_effects: {},
        needs_target: false,
      },
      {
        name: '约她出去',
        prompt_hint: '你发消息问她今晚有没有空。',
        effects: { 精力: -10, 资金: -80 },
        relation_effects: { 好感: 5, 信任: 2 },
        needs_target: true,
      },
    ],
    items: [
      // 预设里的消耗品一律「开局就带在身上」，装备和关键道具不带：补给是开局
      // 就该有的，装备和线索是要去找到的。全套上之后新开一局，背包里立刻有
      // 东西，作者一眼看得出道具定义和背包是怎么接上的
      {
        name: '能量饮料',
        description: '难喝，但确实管用。',
        category: '消耗品',
        consumable: true,
        start_with: true,
        effects: { 精力: 25 },
      },
      {
        name: '小礼物',
        description: '不贵，心意到了就行。',
        category: '消耗品',
        consumable: true,
        start_with: true,
        effects: { 资金: -50 },
      },
    ],
    locations: [
      { name: '出租屋', description: '你住的地方。窗外是别人家的空调外机。', connections: ['街角咖啡馆'] },
      { name: '街角咖啡馆', description: '离家五分钟，坐下就不想走。', connections: ['公司'] },
      { name: '公司', description: '电梯永远在别的楼层。', connections: [] },
    ],
  },
  {
    key: 'magic',
    label: '魔法世界',
    desc: '学院、藏书、血统。数值卡的是魔力和见识。',
    genre: '魔法学院',
    stat_defs: [
      bar('魔力', 60, 100, { for_check: true, on_zero: '标记' }),
      bar('学识', 10, 100, { for_check: true }),
      bar('血统声望', 0, null),
    ],
    relation_stat_defs: [bar('好感', 0, 100), bar('敬畏', 0, 100)],
    actions: [
      {
        name: '练习',
        prompt_hint: '你在没人的地方反复练同一个咒，直到手指发麻。',
        effects: { 魔力: -20, 学识: 3 },
        relation_effects: {},
        needs_target: false,
      },
      {
        name: '去藏书阁',
        prompt_hint: '你在书架间待了一整个下午。',
        effects: { 学识: 6, 魔力: -5 },
        relation_effects: {},
        needs_target: false,
      },
      {
        name: '请教',
        prompt_hint: '你把不懂的地方摊开来问了她。',
        effects: { 学识: 4 },
        relation_effects: { 好感: 3, 敬畏: 2 },
        needs_target: true,
      },
    ],
    items: [
      {
        name: '魔力药剂',
        description: '喝下去舌根发苦，指尖回暖。',
        category: '消耗品',
        consumable: true,
        start_with: true,
        effects: { 魔力: 40 },
      },
      {
        name: '古旧笔记',
        description: '上一任主人的字迹，有几页被撕掉了。',
        category: '关键道具',
        // 关键道具不消耗：撕掉的那几页要留到后面才对得上
        consumable: false,
        start_with: false,
        effects: { 学识: 8 },
      },
    ],
    locations: [
      { name: '宿舍', description: '床、书桌、一扇朝北的窗。', connections: ['庭院'] },
      { name: '庭院', description: '石板缝里长着不该长的东西。', connections: ['藏书阁'] },
      { name: '藏书阁', description: '安静得能听见自己翻页的声音。', connections: [] },
    ],
  },
  {
    key: 'raise',
    label: '互动养成',
    desc: '一对一的长期相处。数值卡的是耐心和她的接受度。',
    genre: '互动养成',
    stat_defs: [
      bar('精力', 100, 100, { for_check: true, on_zero: '标记' }),
      bar('耐心', 80, 100),
      bar('进度', 0, 100),
    ],
    relation_stat_defs: [bar('好感', 0, 100), bar('信任', 0, 100), bar('羞耻', 80, 100)],
    actions: [
      {
        name: '夸奖',
        prompt_hint: '你摸了摸她的头，夸了她一句。',
        effects: { 精力: -5 },
        relation_effects: { 好感: 4, 信任: 2 },
        needs_target: true,
      },
      {
        name: '要求',
        prompt_hint: '你把要求说得很清楚，等她自己做决定。',
        effects: { 精力: -10, 进度: 3 },
        relation_effects: { 羞耻: -3, 信任: -1 },
        needs_target: true,
      },
      {
        name: '奖励',
        prompt_hint: '你把准备好的东西递到她手里。',
        effects: { 精力: -5, 耐心: 5 },
        relation_effects: { 好感: 6 },
        needs_target: true,
      },
      {
        name: '惩罚',
        prompt_hint: '你没有提高声音，只是把话说到底。',
        effects: { 精力: -15, 耐心: -10, 进度: 5 },
        relation_effects: { 羞耻: -6, 好感: -3, 信任: -2 },
        needs_target: true,
      },
    ],
    items: [
      {
        name: '点心',
        description: '她上次多看了两眼的那种。',
        category: '消耗品',
        consumable: true,
        start_with: true,
        effects: { 耐心: 10 },
      },
      {
        name: '项圈',
        description: '皮质，内侧刻了一个字。',
        category: '装备',
        // 装备戴上了就一直在身上，用一次少一个说不通
        consumable: false,
        start_with: false,
        effects: { 进度: 5 },
      },
    ],
    locations: [
      { name: '书房', description: '白天在这里，规矩也在这里。', connections: ['走廊'] },
      { name: '走廊', description: '两头都有门，只有一头是开着的。', connections: ['卧室'] },
      { name: '卧室', description: '窗帘从来不全拉开。', connections: [] },
    ],
  },
]
