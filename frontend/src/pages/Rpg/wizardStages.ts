/**
 * 模组构思向导的步骤。后端仍复用这六个 stage id，前端根据玩法切换引导重点。
 */
export interface WizardStage {
  id: string
  label: string
  hint: string
  opener: string
}

const BASE_STAGES: WizardStage[] = [
  {
    id: 'world',
    label: '这是个什么世界',
    hint: '年代、地方、规矩、此刻的麻烦，顺带定 GM 腔调',
    opener: '开始吧，先陪我把这是个什么世界聊清楚，问我第一个问题。',
  },
  {
    id: 'stats',
    label: '数值系统',
    hint: '玩家数值和关系数值。这是地基，后面全都引用它',
    opener: '进入「数值系统」这一步，按这一步的要求问我。',
  },
  {
    id: 'places',
    label: '地点',
    hint: '玩家能待能走的地方、彼此怎么相通、从哪开局',
    opener: '进入「地点」这一步，按这一步的要求问我。',
  },
  {
    id: 'slots',
    label: '时段',
    hint: '一天分成哪些时段，供角色作息和推进时间使用',
    opener: '进入「时段」这一步，只定一天有哪些时段，不要扩展出额外系统。',
  },
  {
    id: 'cast',
    label: '角色',
    hint: '性格外貌、待在哪、和玩家的关系起点',
    opener: '进入「角色」这一步，按这一步的要求问我。',
  },
  {
    id: 'things',
    label: '道具和动作',
    hint: '能捡能用的东西、一点就做的常见动作',
    opener: '进入「道具和动作」这一步，按这一步的要求问我。',
  },
]

type StageCopy = Pick<WizardStage, 'label' | 'hint' | 'opener'>

const STYLE_STAGE_COPY: Record<string, Partial<Record<WizardStage['id'], StageCopy>>> = {
  sim: {
    world: { label: '身份与系统', hint: '玩家是谁、能管什么、这套生活或制度按什么规则运行', opener: '进入「身份与系统」这一步，先把玩家的身份、权限和模拟范围聊清楚。' },
    stats: { label: '状态与资源', hint: '身份状态、权限、资源和环境指标，后面所有行动都引用它', opener: '进入「状态与资源」这一步，按模拟器的运行规则来定数值。' },
    // 模拟器里没有地图，场所只是「这件事在哪儿办」——主页那一栏点一下直接过去，
    // 场所之间没有「路」的概念，所以这一步不问连通关系，只问有哪几个地方
    places: { label: '功能场所', hint: '这些事分别在哪儿办。是功能的容器，不是要走的地图', opener: '进入「功能场所」这一步，只列出玩家会去办事的几个地方，不用设计它们之间怎么走。' },
    slots: { label: '作息与周期', hint: '一天或一周如何推进，哪些事情会在时间变化时自动发生', opener: '进入「作息与周期」这一步，定下这套模拟器的时间节奏。' },
    cast: { label: '系统中的人', hint: 'NPC 的身份、权限、作息和与玩家的关系', opener: '进入「系统中的人」这一步，按他们在这套生活或制度中的作用来定。' },
    // 这一步在模拟器里是重头：主页整屏就是这些按钮，按 group 分栏摆出来。
    // 所以引导里要明确要求分组，不然生成出来的动作全落到「其他」那一栏
    things: { label: '功能按钮', hint: '主页上那一屏功能，按经营/人事/私人这类分组', opener: '进入「功能按钮」这一步，定下这个模拟器主页上有哪些功能按钮，并给每个按钮归到一个分组里。' },
  },
  slg: {
    world: { label: '养成场景', hint: '玩家与目标角色的关系、生活环境和阶段目标', opener: '进入「养成场景」这一步，先把目标角色和这套养成关系的底色聊清楚。' },
    stats: { label: '成长指标', hint: '目标角色的属性、关系和阶段阈值，后面行动和事件都引用它', opener: '进入「成长指标」这一步，按角色养成的变化来定数值。' },
    places: { label: '生活场所', hint: '目标角色会在哪些地方生活、训练和触发事件', opener: '进入「生活场所」这一步，定下角色日常活动和事件发生的地点。' },
    slots: { label: '每日安排', hint: '一天分成哪些行动时段，每个时段能安排什么', opener: '进入「每日安排」这一步，定下角色养成的日程节奏。' },
    cast: { label: '目标角色', hint: '目标角色的性格、底线、阶段状态和关系起点', opener: '进入「目标角色」这一步，把要培养和观察的人聊具体。' },
    things: { label: '指令与训练', hint: '玩家每天可以安排的指令、训练、互动和它们的效果', opener: '进入「指令与训练」这一步，定下玩家真正能安排的行动。' },
  },
}

export function wizardStagesFor(playStyle: string): WizardStage[] {
  const copy = STYLE_STAGE_COPY[playStyle] || {}
  return BASE_STAGES.map(stage => ({ ...stage, ...(copy[stage.id] || {}) }))
}

// 兼容旧调用和测试；实际向导使用当前模组的玩法生成步骤。
export const WIZARD_STAGES = wizardStagesFor('rpg')
