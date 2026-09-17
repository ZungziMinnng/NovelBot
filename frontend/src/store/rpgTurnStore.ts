import { create } from 'zustand'
import type {
  RpgMessage, RpgRoll, RpgSettlement, RpgTaskProposal, RpgTurnMeta,
} from '@/api/client'

/** 界面上的一条消息。id 为 null 表示流式过程中还没落库的占位气泡 */
export interface RpgBubble {
  id: number | null
  role: string
  content: string
  roll: RpgRoll | null
  /** 这一轮刚掷出来的才让骰子动，翻历史不该每条都再抖一遍 */
  fresh: boolean
  /** 当时在场的 NPC id，看某个人的视角按它筛。null = 不知道，当所有人可见
   *  （老消息，以及还在流、名单要等后端快照的那两条占位气泡） */
  present: number[] | null
  /** 发生在哪个地点。换地方的地方插一条分隔——统一时间线之后一屏里
   *  会混着几个地方的戏，不标就分不清哪句是在哪儿说的 */
  location: string
  settlement?: RpgSettlement | null
}

export const toBubble = (m: RpgMessage): RpgBubble => ({
  id: m.id, role: m.role, content: m.content, roll: m.roll, fresh: false,
  present: m.present ?? null, location: m.location || '',
  settlement: m.settlement,
})

/**
 * 一局「正在生成的那一轮」。
 *
 * 为什么这些搬到了模块级 store、而不是留在 RpgPlay 的组件里：RPG 页面切走就是
 * 真的卸载（App.tsx 的 `<Route>` 没带 key），组件内的 state 跟着一起销毁，可
 * `send` 里那条 SSE 的会调整在跑——它往一个已经卸载的组件里写，切回来只剩空白。
 * 搬到这儿之后，流还在写，回来接着看，连「正在做什么」那句都还在。
 *
 * 按 sessionId 分桶是因为允许多局并行：A 局吐着字，你切到 B 局又发一条，
 * 两份状态各写各的，互不干扰。
 */
export interface RpgTurn {
  bubbles: RpgBubble[]
  streaming: boolean
  /** 首个 token 到达之前单独一个状态：光标闪在空气泡里看不出是在等还是卡了 */
  waiting: boolean
  /** 后端当前处在哪一步（adjudicating/building/settling）。静默阶段靠它给出
   *  「正在做什么」，见 agents/rpg_turn.py 里的 stage 事件 */
  stage: string
  meta: RpgTurnMeta | null
  tips: string[]
  /** 上一轮为什么没成。原先只有一个 toast + 气泡里一行 [错误]：toast 三秒就没了，
   *  那行字又常缩在屏幕上方，失败之后界面看着和「还没发出去」一模一样 */
  lastError: string | null
  /** 等玩家点头的「这桩事办完了吗」。由流式事件塞进来，非空就弹窗。
   *  它要是只留在组件里，切走再回来这个弹窗就再也不会出现了 */
  taskAsk: RpgTaskProposal[]
  /** 停止按钮要掐的那根线。由 store 持有，因为持有它的组件可能已经不在了 */
  controller: AbortController | null
}

/**
 * 右下角那个浮层药丸要显示的东西：哪一局、叫什么、点它跳去哪。
 *
 * 单独存一份而不是从 turns 里现算——浮层挂在 App 上，现算的话它得订阅
 * 每一条气泡的变动，就会跟着每个 token 重渲染一次。这一份只在开一轮 /
 * 关一轮的时候变，浮层的渲染次数就和 token 数无关了。
 */
export interface RunningTurn {
  sessionId: number
  title: string
  path: string
}

// 空值都共用同一份，别每次 new：useSyncExternalStore 靠引用相等判断要不要重渲染，
// 每次给新数组就是每渲染一次都重渲一次
const EMPTY_BUBBLES: RpgBubble[] = []
const EMPTY_TIPS: string[] = []
const EMPTY_TASKS: RpgTaskProposal[] = []

const BLANK: RpgTurn = {
  bubbles: EMPTY_BUBBLES,
  streaming: false,
  waiting: false,
  stage: '',
  meta: null,
  tips: EMPTY_TIPS,
  lastError: null,
  taskAsk: EMPTY_TASKS,
  controller: null,
}

function resolve<T>(prev: T, next: T | ((prev: T) => T)): T {
  return typeof next === 'function' ? (next as (prev: T) => T)(prev) : next
}

// ── token 按帧合并 ──────────────────────────────────────────────────────
//
// 气泡以前是组件里的 useState，SSE 回调里的 setState 会被 React 自动批处理。
// 换成 zustand 之后每次 set 都是一次同步通知，而这一页的订阅面很大（整个气泡
// 列表都跟着动），不合并就退化成每个字重渲染一次。小说侧那份 store 有一模一样
// 的处理，见 store/generationStore.ts 顶部。
//
// 分批是按局攒的：两个局同时吐字，各自攒各自的。
const pending = new Map<number, string>()
let rafId: number | null = null

function applyPending() {
  rafId = null
  if (pending.size === 0) return
  const batch = [...pending.entries()]
  pending.clear()
  useRpgTurnStore.setState(state => {
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

/**
 * 把攒着的 token 立刻落下去。
 *
 * `done` / `error` / `close` 三个分支动手之前必须先调它：否则一帧之后那个
 * 迟到的 token 会追加到一个已经封口、甚至已经拿到正式 id 的气泡上。
 */
function flushTokens() {
  if (rafId !== null) {
    cancelAnimationFrame(rafId)
    rafId = null
  }
  applyPending()
}

interface RpgTurnState {
  turns: Record<number, RpgTurn>
  running: RunningTurn[]

  /** 开一轮。**必须在往 turns 里塞东西之前调**，它会把这一局重置成空的 */
  start: (sessionId: number, title: string, path: string) => void
  /** 这一轮说完了（正常结束、出错、被掐都走这儿） */
  end: (sessionId: number) => void
  abort: (sessionId: number) => void
  setController: (sessionId: number, controller: AbortController) => void
  update: (sessionId: number, fn: (turn: RpgTurn) => Partial<RpgTurn>) => void
  /** 追加正文。走上面的按帧缓冲，只在流式吐字这条路上用 */
  appendToken: (sessionId: number, text: string) => void
  flush: () => void
}

export const useRpgTurnStore = create<RpgTurnState>()((set, get) => ({
  turns: {},
  running: [],

  start: (sessionId, title, path) => {
    flushTokens()
    set(state => ({
      turns: { ...state.turns, [sessionId]: { ...BLANK, streaming: true, waiting: true } },
      // 同一局重复开就换掉那一条，不要叠两个药丸
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
        [sessionId]: { ...turn, streaming: false, waiting: false, stage: '', controller: null },
      },
      running: state.running.filter(r => r.sessionId !== sessionId),
    }))
  },

  abort: sessionId => {
    // 先掐线再收尾。掐线会走到 streamRpgTurn 的 catch，那边认出 AbortError 后
    // 只调 onClose，所以不会再弹一次错误横幅
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
      // 这一局还没有条目就现开一份，**不能在这儿早退**。刚打开页面时 turns 是空的，
      // 而「把历史消息装进气泡」正是靠 setBubbles 写进来的——早退就等于每次刷新都
      // 白屏，后端明明有消息。以前这批 setter 是组件里的 useState，天然没有这个问题
      const turn = state.turns[sessionId] ?? BLANK
      return { turns: { ...state.turns, [sessionId]: { ...turn, ...fn(turn) } } }
    }),

  appendToken: (sessionId, text) => {
    pending.set(sessionId, (pending.get(sessionId) ?? '') + text)
    if (rafId === null) rafId = requestAnimationFrame(applyPending)
  },

  flush: flushTokens,
}))

/** 读这一局。没有的话给一份共用的空值，别现造——引用一变就白重渲一次 */
export function useRpgTurn(sessionId: number): RpgTurn {
  // 只盯自己这一局：别的局吐字时 turns 换了新对象，但自己那份还是同一个引用，
  // zustand 比引用相等，于是这一页不会跟着重渲染
  return useRpgTurnStore(state => state.turns[sessionId]) ?? BLANK
}

/**
 * 按局绑定的一套 setter。
 *
 * **方法名和原来组件里的 setState 逐个对齐**（`setBubbles` / `setStreaming` / …），
 * 所以 RpgPlay 里那十几处 `setBubbles(...)` 一行都不用改，改动只落在「声明处」。
 * 两种写法都收：直接给值，或给一个 updater 函数——和 React 那套一致。
 */
export function rpgTurnActions(sessionId: number) {
  const update = (fn: (turn: RpgTurn) => Partial<RpgTurn>) =>
    useRpgTurnStore.getState().update(sessionId, fn)
  const put = <K extends keyof RpgTurn>(key: K) =>
    (next: RpgTurn[K] | ((prev: RpgTurn[K]) => RpgTurn[K])) =>
      update(turn => ({ [key]: resolve(turn[key], next) }) as Partial<RpgTurn>)

  return {
    start: (title: string, path: string) =>
      useRpgTurnStore.getState().start(sessionId, title, path),
    setBubbles: put('bubbles'),
    setStreaming: put('streaming'),
    setWaiting: put('waiting'),
    setStage: put('stage'),
    setMeta: put('meta'),
    setTips: put('tips'),
    setLastError: put('lastError'),
    setTaskAsk: put('taskAsk'),
    appendToken: (text: string) => useRpgTurnStore.getState().appendToken(sessionId, text),
    flushTokens: () => useRpgTurnStore.getState().flush(),
    setController: (controller: AbortController) =>
      useRpgTurnStore.getState().setController(sessionId, controller),
    abort: () => useRpgTurnStore.getState().abort(sessionId),
    end: () => useRpgTurnStore.getState().end(sessionId),
  }
}

/**
 * 这一局此刻有没有正在跑的那一轮。
 *
 * 切局的清理必须问它一句：从别处切回一个**正在生成**的局时，把气泡清空会把
 * 已经吐出来的一半正文抹掉，而那半段后端还在接着写。
 */
export const isTurnLive = (sessionId: number): boolean =>
  useRpgTurnStore.getState().turns[sessionId]?.streaming === true
