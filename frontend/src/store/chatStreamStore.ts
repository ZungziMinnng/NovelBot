import { create } from 'zustand'

/**
 * 编辑器 AI 对话、新建小说页构思助手「正在生成的那一轮」。
 *
 * 消息本身已经在各自的持久化 store 里（chatStore / brainstormStore），流式回调写的也是
 * store，不是组件 state。原先组件卸载时会 abort，切个页面回来那条回复就断在半截。
 * 这里只放「在不在跑、首 token 到没到、怎么停」，组件卸载了请求照跑。
 *
 * 键：编辑器对话 `chat:<novelId>`（各本书各跑各的），构思助手 `brainstorm`。
 */
interface ChatStream {
  /** 已发出、首个 token 还没到 */
  waiting: boolean
  controller: AbortController
}

interface ChatStreamState {
  streams: Record<string, ChatStream>
  start: (key: string, controller: AbortController) => void
  gotToken: (key: string) => void
  /** 只收自己那一轮：停掉旧的马上发新的时，旧请求迟到的收尾不能把新的一轮也标成结束 */
  end: (key: string, controller: AbortController) => void
  abort: (key: string) => void
}

export const useChatStreamStore = create<ChatStreamState>()((set, get) => ({
  streams: {},

  start: (key, controller) =>
    set(s => ({ streams: { ...s.streams, [key]: { waiting: true, controller } } })),

  gotToken: key => {
    const cur = get().streams[key]
    if (cur?.waiting) set(s => ({ streams: { ...s.streams, [key]: { ...cur, waiting: false } } }))
  },

  end: (key, controller) => {
    if (get().streams[key]?.controller !== controller) return
    set(s => {
      const { [key]: _, ...rest } = s.streams
      return { streams: rest }
    })
  },

  abort: key => {
    const cur = get().streams[key]
    if (!cur) return
    cur.controller.abort()
    get().end(key, cur.controller)
  },
}))

/** 分开取两个布尔值，别返回新对象——useSyncExternalStore 比的是引用相等 */
export function useChatStream(key: string) {
  const isStreaming = useChatStreamStore(s => key in s.streams)
  const waiting = useChatStreamStore(s => s.streams[key]?.waiting ?? false)
  return { isStreaming, waiting }
}
