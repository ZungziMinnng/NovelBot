/**
 * 构思向导的步骤，按目标分两套。
 * id 必须与后端对应模板的 stage 分支、chat.py 的 _WIZARD_STAGES 保持一致。
 *
 * 投稿向七步：「开篇设计」排在「世界观」之前是刻意的，网文先定金手指和爽点循环，
 * 世界观是配套。自娱自乐六步反过来先把世界设定聊厚——那套是边写边想，
 * 前期攒的设定就是后面的燃料，长线不用现在定死。
 */
export interface WizardStage {
  id: string
  label: string
  /** 步骤条下方的一句话说明，告诉作者这步要定什么 */
  hint: string
  /** 切到这步时自动发出的引导语。以 user 消息进对话，界面上只显示成分隔条 */
  opener: string
}

/** 构思目标：投稿向 = 番茄/起点那套判断标准，自娱自乐 = 无平台约束、重设定 */
export type BrainstormPurpose = 'market' | 'indulge'

export const MARKET_STAGES: WizardStage[] = [
  {
    id: 'warmup',
    label: '随便说说',
    hint: '不用完整，脑子里最先冒出来的画面或一句话就行',
    opener: '开始吧，问我第一个问题。',
  },
  {
    id: 'idea',
    label: '核心点子',
    hint: '题材、金手指（含代价）、主角眼下最难受的事',
    opener: '进入「核心点子」这一步，按这一步的要求问我。',
  },
  {
    id: 'characters',
    label: '主角与关键人物',
    hint: '主角的反差与欲望、第一个对手、两三个核心配角',
    opener: '进入「主角与关键人物」这一步，按这一步的要求问我。',
  },
  {
    id: 'opening',
    label: '开篇设计',
    hint: '第一章的危机、金手指第几章亮、第一个打脸对象',
    opener: '进入「开篇设计」这一步，按这一步的要求问我。',
  },
  {
    id: 'plot',
    label: '剧情发展',
    hint: '主线三阶段、爽点节奏、叙事风格',
    opener: '进入「剧情发展」这一步，按这一步的要求问我。',
  },
  {
    id: 'world',
    label: '世界观',
    hint: '力量分级、势力关系、不能破的硬规矩',
    opener: '进入「世界观」这一步，按这一步的要求问我。',
  },
  {
    id: 'wrapup',
    label: '收尾汇总',
    hint: '结局一句话、留到后面揭的牌、书名',
    opener: '进入「收尾汇总」这一步，按这一步的要求问我。',
  },
]

export const INDULGE_STAGES: WizardStage[] = [
  {
    id: 'warmup',
    label: '随便说说',
    hint: '最想看的那一幕，或者哪个桥段让你心痒',
    opener: '开始吧，问我第一个问题。',
  },
  {
    id: 'taste',
    label: '口味与边界',
    hint: '要什么、明确不要什么、偏甜偏刀、视角与阵容',
    opener: '进入「口味与边界」这一步，按这一步的要求问我。',
  },
  {
    id: 'world',
    label: '世界设定',
    hint: '力量或规则、社会形态、风俗禁忌，可以聊厚',
    opener: '进入「世界设定」这一步，按这一步的要求问我。',
  },
  {
    id: 'characters',
    label: '人物与关系',
    hint: '关系落差、在拉扯什么、不能越的线',
    opener: '进入「人物与关系」这一步，按这一步的要求问我。',
  },
  {
    id: 'scenes',
    label: '想写的桥段',
    hint: '攒一批具体想写的场景，不管顺序',
    opener: '进入「想写的桥段」这一步，按这一步的要求问我。',
  },
  {
    id: 'opening',
    label: '开场怎么切入',
    hint: '第一段从哪一幕下笔、叙事风格',
    opener: '进入「开场怎么切入」这一步，按这一步的要求问我。',
  },
]

export const STAGES_BY_PURPOSE: Record<BrainstormPurpose, WizardStage[]> = {
  market: MARKET_STAGES,
  indulge: INDULGE_STAGES,
}

export const PURPOSE_LABELS: Record<BrainstormPurpose, string> = {
  market: '投稿向',
  indulge: '自娱自乐',
}
