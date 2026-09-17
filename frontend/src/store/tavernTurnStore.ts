import { create } from 'zustand'
import type { TavernMessage, TavernTurnMeta } from '@/api/client'

/** 界面上的一条消息。id 为 null 表示流式过程中还没落库的占位气泡 */
export interface TavernBubble {
  id: number | null
  role: string
  content: string
  /** 说话人。null = 玩家消息，或群聊之前的老数据（渲染时回落到主卡） */
  cardId: number | null
}

export const toBubble = (m: TavernMessage): TavernBubble => ({
  id: m.id, role: m.role, content: m.content, cardId: m.card_id,
})

/**
 * 一条故事线「正在生成的那一轮」。和 RPG 那份是同一个理由，见
 * store/rpgTurnStore.ts 顶部——酒馆这边 `TavernChat.tsx` 原先也挂着
 * 「卸载即 abort」，切走之后还在吐的那段就白写了。
 *
 * 按 sessionId 分桶，同时在两条故事线里说话时各写各的。
 */
export interface TavernTurn {
  bubbles: TavernBubble[]
  streaming: boolean
  /** 首个 token 到达之前单独一个状态：光标闪在空气泡里看不出是在等还是卡了 */
  waiting: boolean
  meta: TavernTurnMeta | null
  /** 结算顺带给的行动建议，和「帮我想想」共用这一格 */
  suggestions: string[]
  controller: AbortController | null
}

/** 右下角浮层药丸要显示的东西。理由同 RPG 那份，别从 turns 现算 */
export interface RunningTurn {
  sessionId: number
  title: string
  path: string
}

// 共用空值，别每次 new——useSyncExternalStore 比的是引用相等
const EMPTY_BUBBLES: TavernBubble[] = []
const EMPTY_SUGGESTIONS: string[] = []

const BLANK: TavernTurn = {
  bubbles: EMPTY_BUBBLES,
  streaming: false,
  waiting: false,
  meta: null,
  suggestions: EMPTY_SUGGESTIONS,
  controller: null,
}

function resolve<T>(prev: T, next: T | ((prev: T) => T)): T {
  return typeof next === 'function' ? (next as (prev: T) => T)(prev) : next
}

// ── token 按帧合并 ── 理由同 rpgTurnStore，那边注释更细
const pending = new Map<number, string>()
let rafId: number | null = null

function applyPending() {
  rafId = null
  if (pending.size === 0) return
  const batch = [...pending.entries()]
  pending.clear()
  useTavernTurnStore.setState(state => {
    const turns = { ...state.turns }
    let touched = false
    for (const [id, text] of batch) {
      const turn = turns[id]
      if (!turn) continue          // 这一轮已经收尾了，迟到的 token 丢掉
      const bubbles = [...turn.bubbles]
      const last = bubbles[bubbles.length - 1]
      if (!last) continue
      bubbles[bubbles.length - 1] = { ...last, content: last.content + text }
      turns[id] = { ...turn, bubbles }
      touched = true
    }
    return touched ? { turns } : {}
  })
}

/** 收尾分支动手之前必须先调，否则迟到的 token 会落到已经封口的气泡上 */
function flushTokens() {
  if (rafId !== null) {
    cancelAnimationFrame(rafId)
    rafId = null
  }
  applyPending()
}

interface TavernTurnState {
  turns: Record<number, TavernTurn>
  running: RunningTurn[]

  start: (sessionId: number, title: string, path: string) => void
  end: (sessionId: number) => void
  abort: (sessionId: number) => void
  setController: (sessionId: number, controller: AbortController) => void
  update: (sessionId: number, fn: (turn: TavernTurn) => Partial<TavernTurn>) => void
  appendToken: (sessionId: number, text: string) => void
  flush: () => void
}

export const useTavernTurnStore = create<TavernTurnState>()((set, get) => ({
  turns: {},
  running: [],

  start: (sessionId, title, path) => {
    flushTokens()
    set(state => ({
      turns: { ...state.turns, [sessionId]: { ...BLANK, streaming: true, waiting: true } },
      running: [
        ...state.running.filter(r => r.sessionId !== sessionId),
        { sessionId, title, path },
      ],
    }))
  },

  end: sessionId => {
    flushTokens()
    const turn = get().turns[sessionId]
    if (!turn) return
    set(state => ({
      turns: {
        ...state.turns,
        [sessionId]: { ...turn, streaming: false, waiting: false, controller: null },
      },
      running: state.running.filter(r => r.sessionId !== sessionId),
    }))
  },

  abort: sessionId => {
    get().turns[sessionId]?.controller?.abort()
    get().end(sessionId)
  },

  setController: (sessionId, controller) =>
    set(state => (
      state.turns[sessionId]
        ? { turns: { ...state.turns, [sessionId]: { ...state.turns[sessionId], controller } } }
        : {}
    )),

  update: (sessionId, fn) =>
    set(state => {
      // 同 rpgTurnStore：这一局还没有条目就现开一份。页面刚打开时 turns 是空的，
      // 早退会让「把历史消息装进气泡」这一步被静默丢掉，刷新后整屏空白
      const turn = state.turns[sessionId] ?? BLANK
      return { turns: { ...state.turns, [sessionId]: { ...turn, ...fn(turn) } } }
    }),

  appendToken: (sessionId, text) => {
    pending.set(sessionId, (pending.get(sessionId) ?? '') + text)
    if (rafId === null) rafId = requestAnimationFrame(applyPending)
  },

  flush: flushTokens,
}))

export function useTavernTurn(sessionId: number): TavernTurn {
  return useTavernTurnStore(state => state.turns[sessionId]) ?? BLANK
}

/** 按局绑定的一套 setter，方法名对齐原来组件里的 setState，见 rpgTurnStore 里的说明 */
export function tavernTurnActions(sessionId: number) {
  const update = (fn: (turn: TavernTurn) => Partial<TavernTurn>) =>
    useTavernTurnStore.getState().update(sessionId, fn)
  const put = <K extends keyof TavernTurn>(key: K) =>
    (next: TavernTurn[K] | ((prev: TavernTurn[K]) => TavernTurn[K])) =>
      update(turn => ({ [key]: resolve(turn[key], next) }) as Partial<TavernTurn>)

  return {
    start: (title: string, path: string) =>
      useTavernTurnStore.getState().start(sessionId, title, path),
    setBubbles: put('bubbles'),
    setStreaming: put('streaming'),
    setWaiting: put('waiting'),
    setMeta: put('meta'),
    setSuggestions: put('suggestions'),
    appendToken: (text: string) => useTavernTurnStore.getState().appendToken(sessionId, text),
    flushTokens: () => useTavernTurnStore.getState().flush(),
    setController: (controller: AbortController) =>
      useTavernTurnStore.getState().setController(sessionId, controller),
    abort: () => useTavernTurnStore.getState().abort(sessionId),
    end: () => useTavernTurnStore.getState().end(sessionId),
  }
}

/** 这一条故事线此刻有没有在跑的那一轮。切线的清理要问它一句，理由同 RPG 那份 */
export const isTurnLive = (sessionId: number): boolean =>
  useTavernTurnStore.getState().turns[sessionId]?.streaming === true
