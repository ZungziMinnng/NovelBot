export const GAMEPLAY_MODEL_FIELDS = [
  { key: 'model_ref', label: '叙事模型', empty: '跟随系统叙事默认', hint: '生成旁白；编辑器里的 AI 帮写也使用它。' },
  { key: 'settlement_model_ref', label: '结算模型', empty: '跟随辅助默认模型', hint: '提取数值、关系、物品等变化；结算纠错与重试也使用它。' },
  { key: 'adjudication_model_ref', label: '判定模型', empty: '跟随辅助默认模型', hint: '判断是否需要检定及难度；开启判定后使用。' },
  { key: 'suggestion_model_ref', label: '行动建议模型', empty: '跟随辅助默认模型', hint: '点击「帮我想想」时生成行动建议。' },
  { key: 'summary_model_ref', label: '剧情总结模型', empty: '跟随辅助默认模型', hint: '将超出上下文轮数的旧剧情压缩为概要。' },
  { key: 'activity_model_ref', label: 'NPC AI 调度模型', empty: '跟随辅助默认模型', hint: '为开启 AI 调度的 NPC 生成活动描述与留言。' },
  { key: 'offscreen_model_ref', label: '外场简报模型', empty: '跟随辅助默认模型', hint: '启用外场简报后，在时段推进时生成场外动态。' },
  { key: 'discovery_model_ref', label: '发现补全模型', empty: '跟随叙事配置 / 系统快速默认', hint: '将发现的人物、地点、道具等补全为模组资料。留空优先使用模组指定的叙事模型，否则使用系统快速默认。' },
] as const

export const EXTRA_MODEL_FIELDS = [
  { key: 'fast_model_ref', label: '辅助默认模型', empty: '跟随系统辅助默认', hint: '未单独指定的结算、判定、建议、总结、NPC 调度和外场简报使用它。保留原「判定与结算模型」的设置。' },
  { key: 'image_model_ref', label: '立绘 tag 模型', empty: '自动选择', hint: '将中文外貌转换为 danbooru tag。留空依次使用辅助默认、叙事模型，再跟随系统角色默认。' },
] as const

export type RpgModelField = (typeof GAMEPLAY_MODEL_FIELDS)[number]['key'] | (typeof EXTRA_MODEL_FIELDS)[number]['key']
