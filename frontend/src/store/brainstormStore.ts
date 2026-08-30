import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { ChatSurfaceMessage } from '@/components/ChatSurface/types'
import type { BrainstormExtract } from '@/api/client'

export type BrainstormMode = 'wizard' | 'free'

interface BrainstormState {
  mode: BrainstormMode
  /** WIZARD_STAGES 的下标，-1 = 向导还没开始 */
  stage: number
  messages: ChatSurfaceMessage[]
  /** 各步抽出来的结论，回灌给模型防止它重复问已经定过的事 */
  confirmed: Partial<BrainstormExtract>
}

interface BrainstormStore extends BrainstormState {
  setMode: (mode: BrainstormMode) => void
  setStage: (stage: number) => void
  setMessages: (
    next: ChatSurfaceMessage[] | ((prev: ChatSurfaceMessage[]) => ChatSurfaceMessage[]),
  ) => void
  mergeConfirmed: (patch: Partial<BrainstormExtract>) => void
  /** 清空对话重新构思，保留当前模式 */
  clearConversation: () => void
  /** 书已经建出来了，整个面板归零 */
  reset: () => void
}

const EMPTY: BrainstormState = {
  mode: 'wizard',
  stage: -1,
  messages: [],
  confirmed: {},
}

export const useBrainstormStore = create<BrainstormStore>()(
  persist(
    (set) => ({
      ...EMPTY,

      setMode: (mode) => set({ mode }),

      setStage: (stage) => set({ stage }),

      setMessages: (next) =>
        set((s) => ({ messages: typeof next === 'function' ? next(s.messages) : next })),

      mergeConfirmed: (patch) => set((s) => ({ confirmed: { ...s.confirmed, ...patch } })),

      clearConversation: () => set({ stage: -1, messages: [], confirmed: {} }),

      reset: () => set(EMPTY),
    }),
    { name: 'novelbot-brainstorm' },
  ),
)

const CONFIRMED_LABELS: Array<[keyof BrainstormExtract, string]> = [
  ['title', '书名'],
  ['genre', '题材'],
  ['writing_style', '写作风格'],
  ['premise', '创作方向'],
  ['plot_design', '剧情设计'],
  ['core_setting', '时代背景'],
  ['world_rules_seed', '核心规则'],
  ['ending', '结局'],
  ['protagonist_arc', '主角起点→终点'],
]

/** 把已敲定的结论拼成给模型看的文本。返回空串表示还什么都没定 */
export function formatConfirmed(confirmed: Partial<BrainstormExtract>): string {
  const lines: string[] = []
  for (const [key, label] of CONFIRMED_LABELS) {
    const value = confirmed[key]
    if (typeof value === 'string' && value.trim()) lines.push(`${label}：${value.trim()}`)
  }
  for (const c of confirmed.characters ?? []) {
    lines.push(`角色·${c.name}（${c.role}）：${c.description}`)
  }
  for (const c of confirmed.endgame_cards ?? []) {
    lines.push(`第${c.volume}卷才揭的牌：${c.text}`)
  }
  return lines.join('\n')
}
