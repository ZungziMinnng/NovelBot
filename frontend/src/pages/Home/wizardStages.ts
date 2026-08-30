/**
 * 构思向导的七个步骤。
 * id 必须与后端 brainstorm.jinja2 的 stage 分支、chat.py 的 _WIZARD_STAGES 保持一致。
 * 顺序上「开篇设计」排在「世界观」之前是刻意的：网文先定金手指和爽点循环，世界观是配套。
 */
export interface WizardStage {
  id: string
  label: string
  /** 步骤条下方的一句话说明，告诉作者这步要定什么 */
  hint: string
  /** 切到这步时自动发出的引导语。以 user 消息进对话，界面上只显示成分隔条 */
  opener: string
}

export const WIZARD_STAGES: WizardStage[] = [
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
