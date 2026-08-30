export interface ChatSurfaceMessage {
  role: 'user' | 'assistant'
  content: string
  /** 'stage' = 阶段切换。content 照常发给模型，界面上只渲染成一条分隔线 */
  kind?: 'stage'
  /** kind 为 'stage' 时显示在分隔线上的文字 */
  label?: string
}
