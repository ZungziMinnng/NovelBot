/**
 * 模组构思向导的步骤。
 * id 必须与后端 rpg_wizard.STAGES、两个 rpg_wizard*.jinja2 的 stage 分支一致。
 *
 * 顺序有依赖，不能随便调：数值是地基（角色的关系起点、道具的 effects 都引用它），
 * 地点要排在角色之前（角色的所在地点得指向一个已存在的地点）。道具动作排最后，
 * 因为它们同时引用数值和地点。
 */
export interface WizardStage {
  id: string
  label: string
  /** 步骤条下方的一句话，告诉作者这步要定什么 */
  hint: string
  /** 切到这步时自动发出的引导语，以 user 消息进对话，界面上显示成分隔条 */
  opener: string
}

export const WIZARD_STAGES: WizardStage[] = [
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
