import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  ArrowLeft, BookMarked, Clock, Cpu, Dices, Lightbulb, Loader2, MapPin, PanelRightOpen,
  Send, SkipForward, Square, User, X,
} from 'lucide-react'
import {
  rpgApi, modelLibraryApi, modelSelectValue, streamRpgTurn,
  type ModelEntry, type RpgAction, type RpgMessage, type RpgModule, type RpgNpc,
  type RpgRoll, type RpgSave, type RpgSession, type RpgSSEMessage, type RpgTurnMeta,
} from '@/api/client'
import { confirmDialog } from '@/components/ConfirmDialog/ConfirmDialog'
import AutoTextarea from '@/components/AutoTextarea'
import ThemePicker from '@/components/ThemePicker/ThemePicker'
import Silk from '@/components/Silk/Silk'
import { checkCondition, knownNpcs, norm, npcPlace, onstage } from './condition'
import DiceRoll from './DiceRoll'
import LocationOverview from './LocationOverview'
import NpcSheet from './NpcSheet'
import PlacePage from './PlacePage'
import StatePanel from './StatePanel'
import StatusSidebar, { type SidebarTab } from './StatusSidebar'
import { styleLabel } from './stylePresets'

/** 界面上的一条消息。id 为 null 表示流式过程中还没落库的占位气泡 */
interface Bubble {
  id: number | null
  role: string
  content: string
  roll: RpgRoll | null
  /** 这一轮刚掷出来的才让骰子动，翻历史不该每条都再抖一遍 */
  fresh: boolean
  /** 属于哪条线。流式过程中还没落库，只能由前端从这一轮的目标带过来 */
  thread_id: number | null
}

const toBubble = (m: RpgMessage): Bubble => ({
  id: m.id, role: m.role, content: m.content, roll: m.roll, fresh: false,
  thread_id: m.thread_id ?? null,
})

/** 「点出来的」那一轮额外带的东西。三个都空就是自由打字 */
interface TurnExtra {
  action_id?: number | null
  item_name?: string
  move_to?: string
  target_npc?: string
}

/** 三级：地点总览 → 某个地点 → 某条对话线。总览是中枢，进去靠点，回来靠面包屑 */
type View = 'overview' | 'place' | 'line'

export default function RpgPlay() {
  const { sessionId: sessionIdParam } = useParams<{ sessionId: string }>()
  const sessionId = Number(sessionIdParam)
  const navigate = useNavigate()
  const qc = useQueryClient()

  const [bubbles, setBubbles] = useState<Bubble[]>([])
  const [input, setInput] = useState('')
  const [attr, setAttr] = useState('')
  const [streaming, setStreaming] = useState(false)
  // 首个 token 到达之前单独一个状态：光标闪在空气泡里看不出是在等还是卡了
  const [waiting, setWaiting] = useState(false)
  const [meta, setMeta] = useState<RpgTurnMeta | null>(null)
  const [tips, setTips] = useState<string[]>([])
  // 「帮我想想」在跑。和 streaming 分开：那一个是整轮生成，这个只是要几条建议
  const [suggesting, setSuggesting] = useState(false)
  // 瞬移 / 推时段在跑。都是毫秒级的纯引擎请求，但手滑连点两下就会发两个
  const [engineBusy, setEngineBusy] = useState(false)
  const [target, setTarget] = useState('')
  const [tab, setTab] = useState<SidebarTab>('cast')
  // 侧栏在宽屏常驻，窄屏收成抽屉
  const [menuOpen, setMenuOpen] = useState(false)
  const [view, setView] = useState<View>('overview')
  // 当前对话线。null = 场面线（公共场面），值是 NPC 的 id
  const [threadId, setThreadId] = useState<number | null>(null)
  const [openNpc, setOpenNpc] = useState<RpgNpc | null>(null)

  const abortRef = useRef<AbortController | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  // 事件回调里连着几个 setState，读 state 会拿到旧值
  const openRef = useRef(false)
  // adjudicate 和 roll 是两个事件，拼起来才是完整的一次判定
  const judgeRef = useRef<Partial<RpgRoll>>({})

  const { data: sess } = useQuery({
    queryKey: ['rpg-session', sessionId],
    queryFn: () => rpgApi.sessions.get(sessionId),
    enabled: Number.isFinite(sessionId) && sessionId > 0,
  })
  const moduleId = sess?.module_id
  const { data: module } = useQuery({
    queryKey: ['rpg-module', moduleId],
    queryFn: () => rpgApi.modules.get(moduleId!),
    enabled: !!moduleId,
  })
  const { data: npcs = [] } = useQuery({
    queryKey: ['rpg-npcs', moduleId],
    queryFn: () => rpgApi.npcs.list(moduleId!),
    enabled: !!moduleId,
  })
  const { data: actions = [] } = useQuery({
    queryKey: ['rpg-actions', moduleId],
    queryFn: () => rpgApi.actions.list(moduleId!),
    enabled: !!moduleId,
  })
  const { data: items = [] } = useQuery({
    queryKey: ['rpg-items', moduleId],
    queryFn: () => rpgApi.items.list(moduleId!),
    enabled: !!moduleId,
  })
  const { data: locations = [] } = useQuery({
    queryKey: ['rpg-locations', moduleId],
    queryFn: () => rpgApi.locations.list(moduleId!),
    enabled: !!moduleId,
  })
  // 存档只在翻到存档那一格时才拉：绝大多数回合玩家根本不看它
  const { data: saves = [] } = useQuery({
    queryKey: ['rpg-saves', sessionId],
    queryFn: () => rpgApi.saves.list(sessionId),
    enabled: tab === 'save',
  })
  // 消息以后端为准：只在进页面时拉一次，之后本地追加。
  // 线不在后端单拉——按 thread_id 分组就有线了，少一个端点，
  // 也不会出现「新消息不在当前线的查询结果里所以看不到」
  const { data: loaded } = useQuery({
    queryKey: ['rpg-messages', sessionId],
    queryFn: () => rpgApi.messages.list(sessionId),
    enabled: Number.isFinite(sessionId) && sessionId > 0,
  })

  useEffect(() => { if (loaded) setBubbles(loaded.map(toBubble)) }, [loaded])

  // 新局直接落在场面线上。开场白是场面线的第一条旁白，而默认视图是地图总览
  // ——不跳的话玩家开局第一眼看到的是一张地图，得往里点两层才看得到作者
  // 写的那一幕，多数人会以为开场白没生效。
  // 判据是「玩家一句话都还没说过」，而且只在进页面时判一次：之后无论他停在
  // 哪一级，刷新回来都该停在原地，不能被这一跳抢走
  const landedRef = useRef(false)
  useEffect(() => {
    if (!loaded || landedRef.current) return
    landedRef.current = true
    if (loaded.length > 0 && loaded.every(m => m.role !== 'user')) {
      setThreadId(null)
      setView('line')
    }
  }, [loaded])

  useEffect(() => () => { abortRef.current?.abort() }, [])

  // 只有见过面或此刻在场的人能当动作对象：对一个还没登场的人「夸奖」
  // 等于把他抖出来
  const metNpcs = useMemo(
    () => (sess ? knownNpcs(npcs, sess) : []),
    [npcs, sess],
  )

  const threadNpc = useMemo(
    () => (threadId ? npcs.find(n => n.id === threadId) ?? null : null),
    [npcs, threadId],
  )

  // 换线时把动作对象重置成线主：不重置就会**跨线泄漏**——在老兵线里
  // target 还留着老板娘，下一个动作的好感就加到别人头上。
  // 场面线一律清空：自动替玩家选一个对象，会把这一轮悄悄送进那个人的线
  useEffect(() => {
    const owner = threadId ? npcs.find(n => n.id === threadId) : null
    setTarget(owner ? owner.name : '')
  }, [threadId, npcs])

  /** 这条线上该显示的气泡。流式里的那些也带着 thread_id，所以不断线 */
  const lineBubbles = useMemo(
    () => bubbles.filter(b => (b.thread_id ?? null) === threadId),
    [bubbles, threadId],
  )

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [lineBubbles])

  /** 公共场面里的最后一段旁白。一条还没开口的私聊线拿它当背景垫在上面：
   *  那条线自己没有历史，但故事并不是从玩家的第一句话才开始的——新局时
   *  这一段正好就是开场白 */
  const sceneTail = useMemo(
    () => [...bubbles].reverse()
      .find(b => (b.thread_id ?? null) === null && b.role === 'assistant')?.content || '',
    [bubbles],
  )

  const send = useCallback((
    text: string, useAttr: string, extra: TurnExtra = {}, thread: number | null = threadId,
  ) => {
    setBubbles(prev => [...prev, {
      id: null, role: 'user', content: text, roll: null, fresh: true, thread_id: thread,
    }])
    setStreaming(true)
    setWaiting(true)
    setMeta(null)
    setTips([])
    openRef.current = false
    judgeRef.current = {}

    // 正在流的那条永远是最后一条：气泡只往后追加
    const patchLast = (fn: (prev: string) => string) =>
      setBubbles(prev => prev.map((b, i) => (i === prev.length - 1 ? { ...b, content: fn(b.content) } : b)))

    const openBubble = () => {
      if (openRef.current) return
      openRef.current = true
      setBubbles(prev => [...prev, {
        id: null, role: 'assistant', content: '', roll: null, fresh: true, thread_id: thread,
      }])
    }

    // 骰子挂在玩家那条上：叙事中途崩了骰子也还在，而玩家已经看过掷骰动画了
    const attachRoll = (roll: RpgRoll) =>
      setBubbles(prev => {
        const next = [...prev]
        for (let i = next.length - 1; i >= 0; i--) {
          if (next[i].role === 'user') {
            next[i] = { ...next[i], roll }
            break
          }
        }
        return next
      })

    abortRef.current = streamRpgTurn(
      sessionId,
      // thread_id 显式带上，后端不再靠 target_npc 猜这段叙事归哪条历史
      { content: text, attr: useAttr, thread_id: thread, ...extra },
      (msg: RpgSSEMessage) => {
        if (msg.event === 'meta') {
          // 后端发两次：先只带 user_message_id，上下文拼完再补诊断。必须合并
          setMeta(prev => ({ ...prev, ...msg.data }))
          const uid = msg.data.user_message_id
          if (uid) {
            setBubbles(prev => prev.map(b => (
              b.role === 'user' && b.id === null ? { ...b, id: uid } : b
            )))
          }
        } else if (msg.event === 'adjudicate') {
          judgeRef.current = msg.data
          if (!msg.data.need_check) attachRoll({ ...msg.data } as RpgRoll)
        } else if (msg.event === 'roll') {
          attachRoll({ ...judgeRef.current, ...msg.data, need_check: true } as RpgRoll)
        } else if (msg.event === 'token') {
          openBubble()
          setWaiting(false)
          patchLast(prev => prev + msg.data)
        } else if (msg.event === 'state') {
          // 引擎结算发一次、AI 结算再发一次，就地合进缓存，数值面板立刻跟着动
          qc.setQueryData(['rpg-session', sessionId], (prev?: RpgSession) => (
            prev ? { ...prev, ...msg.data } : prev
          ))
        } else if (msg.event === 'suggestions') {
          setTips(msg.data)
        } else if (msg.event === 'warning') {
          toast(msg.data)
        } else if (msg.event === 'done') {
          const id = msg.data.message_id
          setBubbles(prev => prev.map((b, i) => (i === prev.length - 1 ? { ...b, id } : b)))
          qc.invalidateQueries({ queryKey: ['rpg-session', sessionId] })
        } else if (msg.event === 'error') {
          openBubble()
          setWaiting(false)
          patchLast(prev => prev + `\n[错误] ${msg.data}`)
        }
      },
      () => { setStreaming(false); setWaiting(false) },
    )
  }, [sessionId, qc, threadId])

  const handleSend = () => {
    const text = input.trim()
    if (!text || streaming) return
    setInput('')
    send(text, attr)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  // 帮我想想：另开一次调用要三条候选行动，和每轮结算顺带给的建议共用同一块显示区
  const suggest = async () => {
    if (locked || suggesting) return
    setSuggesting(true)
    // 先清掉旧的：等的时候还挂着上一轮的建议，会让人以为那就是答案
    setTips([])
    try {
      const { suggestions } = await rpgApi.suggest(sessionId, threadId)
      if (suggestions.length === 0) toast('没想出来，再聊两句试试')
      else setTips(suggestions)
    } catch {
      toast.error('没能生成建议')
    } finally { setSuggesting(false) }
  }

  // 停止：中断的半段后端会落库，所以刷新后仍在，本地不需要回滚气泡
  const stop = () => {
    abortRef.current?.abort()
    setStreaming(false)
    setWaiting(false)
    qc.invalidateQueries({ queryKey: ['rpg-messages', sessionId] })
  }

  if (!sess) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center text-muted-foreground">
        <Loader2 className="w-5 h-5 animate-spin mr-2" /> 加载中...
      </div>
    )
  }

  const dead = sess.status !== 'alive'
  const locked = streaming || dead
  // 这一局有没有时钟：玩家建局时定制过就看他那份，否则跟模组走（和后端的
  // slot_table 同一条规则）
  const hasClock = (sess.time_slots?.length || module?.time_slots?.length || 0) > 0

  const runAction = (action: RpgAction) => {
    if (locked) return
    const who = action.needs_target ? target : ''
    if (action.needs_target && !who) {
      toast.error(`「${action.name}」得先选一个对象`)
      return
    }
    // 对**就站在眼前**的人用动作 = 走进他那条线。线决定叙事去哪条历史，
    // target_npc 决定好感加在谁头上，这里让两件事在同一屏里都看得见。
    // 人不在跟前就别切：线主不在后端会整轮拒掉，而对远方的人用动作本来合法
    const present = who ? metNpcs.find(n => n.name === who && onstage(n, sess)) : undefined
    const into = present ? present.id : threadId
    setThreadId(into)
    setView('line')
    const hint = (action.prompt_hint || '').trim() || `你${action.name}`
    send(who ? `${hint}（对象：${who}）` : hint, '', { action_id: action.id, target_npc: who }, into)
  }

  /** 背包里点「使用」。一律落场面线：用道具是引擎行为，不是对话。
   *
   *  `exact` = 模组里有这件道具的定义（见侧栏）。没定义的**不能带 item_name**：
   *  后端会回一句「模组里没有这件道具」的黄条，而玩家拿到的东西是剧情里 GM
   *  给的，这不是他的错。不带就等于替他打出这句话，交给 GM 写 + AI 结算。 */
  const useItem = (name: string, exact: boolean) => {
    if (locked) return
    setMenuOpen(false)
    setThreadId(null)
    setView('line')
    send(`你用了「${name}」。`, '', exact ? { item_name: name } : {}, null)
  }

  const refreshSaves = () => qc.invalidateQueries({ queryKey: ['rpg-saves', sessionId] })

  /** 总览里点一个地方：纯引擎，零 LLM。不该有叙事产生，也不该有等待转圈 */
  const go = async (name: string) => {
    // 手滑连点两下会发两个请求，第二个把第一个的结果覆盖掉（还各拍一张档）
    if (locked || engineBusy) return
    setEngineBusy(true)
    try {
      const { session: next, message } = await rpgApi.sessions.move(sessionId, name)
      qc.setQueryData(['rpg-session', sessionId], next)
      // 进不去就把那句拒绝的话原样说出来，不弹红色失败——被门槛挡住是正常反馈
      toast(message || `你来到了${name}`)
      // 只有真的走过去了才换页：被拦下来还翻到地点页，玩家会以为自己到了
      if (norm(next.location) === norm(name)) {
        // 落地先看有谁在这儿，比留在原地图少点一次
        setThreadId(null)
        setView('place')
      }
      refreshSaves()
    } catch {
      toast.error('没能过去')
    } finally {
      setEngineBusy(false)
    }
  }

  /** 结束当前时段。默认纯引擎，不叫模型；模组勾了「别处简报」才会多一次调用 */
  const advance = async () => {
    if (locked || engineBusy) return
    setEngineBusy(true)
    try {
      const { session: next, facts } = await rpgApi.sessions.advance(sessionId)
      qc.setQueryData(['rpg-session', sessionId], next)
      // 跨天回满这类结果得说清楚，否则玩家只会发现数字自己变了
      if (facts.length) toast(facts.join('，'), { icon: '🕘' })
      refreshSaves()
    } catch {
      toast.error('没能推进时段')
    } finally {
      setEngineBusy(false)
    }
  }

  /** 划掉 GM 记错的一条近况。不拍存档：这是在改模型的笔误，不是剧情事件 */
  const dropNote = async (npcId: number, key: string) => {
    try {
      qc.setQueryData(['rpg-session', sessionId], await rpgApi.sessions.deleteNpcNote(sessionId, npcId, key))
    } catch {
      toast.error('没能划掉')
    }
  }

  /** 划掉 AI 调度替她编的那一句。同理不拍存档，而且清掉之后
   *  她下一轮还会照常过日子、再写一句新的 */
  const dropActivity = async (npcId: number) => {
    try {
      qc.setQueryData(['rpg-session', sessionId], await rpgApi.sessions.deleteNpcActivity(sessionId, npcId))
    } catch {
      toast.error('没能划掉')
    }
  }

  const saveNow = async () => {
    try {
      await rpgApi.saves.create(sessionId, `第 ${sess.turn_count} 回合`)
      refreshSaves()
      toast.success('存好了')
    } catch {
      toast.error('存档失败')
    }
  }

  const restore = async (save: RpgSave) => {
    if (!await confirmDialog({
      title: `读回「${save.label}」？`,
      detail: '这之后写出来的剧情会被删掉，比它更晚的存档也会一起作废。',
      confirmText: '读档',
      danger: true,
    })) return
    try {
      const next = await rpgApi.saves.restore(save.id)
      qc.setQueryData(['rpg-session', sessionId], next)
      qc.invalidateQueries({ queryKey: ['rpg-messages', sessionId] })
      refreshSaves()
      setTips([])
      setMenuOpen(false)
      // 线是消息的派生结果：消息被删回那一刻，当时还不存在的线就没了，
      // 所以不能留在一个可能已经空掉的线上，回总览重新进
      setThreadId(null)
      setView('overview')
      toast.success(`回到了第 ${next.turn_count} 回合`)
    } catch {
      toast.error('读档失败')
    }
  }

  const dropSave = async (save: RpgSave) => {
    try {
      await rpgApi.saves.delete(save.id)
      refreshSaves()
    } catch {
      toast.error('删除存档失败')
    }
  }

  // 判定关着的时候整个下拉都不该出现，那是骰子味道的东西
  const checkable = module?.check_mode !== 'never'
    ? (module?.stat_defs || []).filter(d => d.for_check && d.name in (sess.stats || {}))
    : []

  // 和侧栏同一套口径：「隐藏」的不画，那是幕后计数器
  const relDefs = (module?.relation_stat_defs || []).filter(d => d.name && d.display !== '隐藏')

  // 线主不在跟前就只给看、不给输入框。后端也会拒（400），这里只是提前
  // 表达出来——不然玩家打一段字，换来的是气泡里一行原始 JSON 报错
  const ownerAway = !!threadId && (!threadNpc || !onstage(threadNpc, sess))

  // 宽屏钉在右边、窄屏收进抽屉，同一份
  const menu = (
    <StatusSidebar
      sess={sess}
      module={module}
      npcs={npcs}
      items={items}
      saves={saves}
      tab={tab}
      onTab={setTab}
      locked={locked}
      streaming={streaming}
      onUseItem={useItem}
      onOpenNpc={setOpenNpc}
      onSaveNow={saveNow}
      onRestore={restore}
      onDropSave={dropSave}
    />
  )

  return (
    <div className="mode-rpg h-screen flex flex-col bg-background relative">
      <div className="fixed inset-0 z-0 opacity-[0.10] pointer-events-none">
        <Silk speed={2} scale={1.4} color="#6d3ab0" noiseIntensity={1.4} rotation={0} className="w-full h-full" />
      </div>

      {/* z-20 而不是 z-10：页头里的下拉（模型、主题）是绝对定位的，会垂到下面
          那块内容区上。内容区也是 z-10 而且在 DOM 里更靠后，同层后来者居上，
          下拉就被右边的角色栏盖住了。页头必须比内容高一层 */}
      <header className="relative z-20 border-b border-border/50 bg-background/70 backdrop-blur-md px-6 py-3 flex items-center gap-3 shrink-0">
        <button
          onClick={() => navigate(`/rpg/module/${sess.module_id}`)}
          className="p-2 rounded-md hover:bg-muted"
          title="返回模组"
        >
          <ArrowLeft className="w-4 h-4" />
        </button>
        <Dices className="w-5 h-5 text-primary shrink-0" />
        <div className="min-w-0">
          <p className="font-bold text-sm truncate">{sess.char_name || '无名者'}</p>
          <p className="text-xs text-muted-foreground truncate">
            {module?.name || ''}
            {module ? ` · ${styleLabel(module.play_style)}` : ''}
            {' · '}第 {sess.turn_count} 回合
          </p>
        </div>

        <div className="ml-auto flex items-center gap-3">
          {dead && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-rose-500/15 text-rose-700 dark:text-rose-300">
              {sess.status === 'dead' ? '这一局已经结束了' : '这一局已封存'}
            </span>
          )}
          {sess.location && (
            <span className="hidden md:flex items-center gap-1 text-xs text-muted-foreground">
              <MapPin className="w-3.5 h-3.5" />{sess.location}
            </span>
          )}
          {/* 时钟只在模组设了时段时出现。没有时段就没有时间这回事。
              判据是**有没有时段表**而不是 sess.slot：建局之后作者才给模组加时段
              的话，老局的 slot 还是空的，按 slot 判会让时钟永远出不来，
              连带所有按时段设门槛的内容被无声锁死。slot 空着按一下就会落到第一格 */}
          {hasClock && (
            <span className="hidden sm:flex items-center gap-1 text-xs text-muted-foreground">
              <Clock className="w-3.5 h-3.5" />
              第 {sess.day} 天{sess.slot ? ` · ${sess.slot}` : ''}
            </span>
          )}
          {hasClock && (
            <button
              onClick={advance}
              disabled={locked || engineBusy}
              title={module?.offscreen_brief
                ? '推进到下一个时段。这一下不生成剧情，但会调一次便宜模型写一句「别处」的大事记'
                : '推进到下一个时段。这一下不生成剧情，模型也不会参与'}
              className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-md border
                hover:bg-muted disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <SkipForward className="w-3.5 h-3.5" />结束这个时段
            </button>
          )}
          {module && <ModelPicker module={module} disabled={streaming} />}
          <ThemePicker />
          <button
            onClick={() => setMenuOpen(true)}
            className="xl:hidden p-2 rounded-md hover:bg-muted"
            title="角色 / 道具 / 存档"
          >
            <PanelRightOpen className="w-4 h-4" />
          </button>
        </div>
      </header>

      <div className="relative z-10 flex-1 flex min-h-0 w-full max-w-[1600px] mx-auto">
        <div className="flex-1 flex flex-col min-w-0">

          {/* 侧栏收起来的时候至少让数值留在眼前，不然窄屏等于看不到状态 */}
          {(module?.stat_defs?.length || metNpcs.length > 0) ? (
            <div className="xl:hidden border-b border-border/50 bg-background/50 backdrop-blur-md px-6 py-2 shrink-0">
              <div className="max-w-3xl mx-auto">
                <StatePanel
                  defs={module?.stat_defs || []}
                  stats={sess.stats || {}}
                  relationDefs={module?.relation_stat_defs || []}
                  npcs={metNpcs}
                  npcStates={sess.npc_states || {}}
                />
              </div>
            </div>
          ) : null}

          {/* 我在哪一级、在哪条线上。总览是中枢，往上都能点回去 */}
          {view !== 'overview' && (
            <div className="border-b border-border/50 bg-background/50 backdrop-blur-md px-6 py-1.5
              text-xs text-muted-foreground flex items-center gap-2 shrink-0">
              <button
                onClick={() => setView('overview')}
                className="flex items-center gap-1 hover:text-foreground shrink-0"
              >
                <ArrowLeft className="w-3.5 h-3.5" />地点总览
              </button>
              <span className="opacity-40 shrink-0">/</span>
              <button onClick={() => setView('place')} className="hover:text-foreground truncate">
                {sess.location || '不知身在何处'}
              </button>
              {view === 'line' && (
                <>
                  <span className="opacity-40 shrink-0">/</span>
                  <span className="truncate">
                    {threadNpc ? `与 ${threadNpc.name}` : '公共场面'}
                  </span>
                </>
              )}
            </div>
          )}

          {view === 'line' && meta && (
            <div className="border-b border-border/50 bg-primary/[0.04] px-6 py-1.5 text-xs text-muted-foreground
              flex flex-wrap items-center gap-x-2 gap-y-0.5 shrink-0">
              <BookMarked className="w-3 h-3 shrink-0" />
              {meta.triggered && meta.triggered.length > 0 ? (
                <span className="truncate">
                  生效词条：
                  <span className="text-primary">
                    {meta.triggered
                      .map(t => (t.constant ? `常驻${t.keywords ? `（${t.keywords}）` : ''}` : t.keywords) || `#${t.id}`)
                      .join(' / ')}
                  </span>
                </span>
              ) : (
                <span>本轮没有世界书词条生效</span>
              )}
              {meta.system_tokens !== undefined && (
                <span className="sm:ml-auto">
                  设定 {meta.system_tokens} · 状态 {meta.state_tokens ?? 0}
                  {' · '}角色 {meta.npc_tokens ?? 0} · 外场 {meta.chronicle_tokens ?? 0}
                  {' · '}历史 {meta.history_count} 条
                  {meta.slot && ` · 第 ${meta.day} 天 ${meta.slot}`}
                  {` · ${meta.thread ? `线：${meta.thread.name}` : '场面线'}`}
                  {meta.npcs_onstage && meta.npcs_onstage.length > 0
                    && ` · 在场 ${meta.npcs_onstage.map(n => n.name).join('、')}`}
                </span>
              )}
            </div>
          )}

          <div className="flex-1 overflow-y-auto px-6 py-6">
            {/* 地图要比正文宽一点，不然节点挤在一起。面包屑和输入条各自带着
                自己的 max-w-3xl，所以只动这一处不会错位 */}
            <div className={`${view === 'overview' ? 'max-w-5xl' : 'max-w-3xl'} mx-auto space-y-4`}>
              {view === 'overview' && (
                <LocationOverview
                  sess={sess}
                  locations={locations}
                  npcs={npcs}
                  locked={locked}
                  onGo={go}
                  onPick={() => setView('place')}
                  busy={engineBusy}
                />
              )}

              {view === 'place' && (
                <PlacePage
                  sess={sess}
                  locations={locations}
                  npcs={npcs}
                  onTalk={npc => { setThreadId(npc.id); setView('line') }}
                  onDetail={setOpenNpc}
                  onScene={() => { setThreadId(null); setView('line') }}
                />
              )}

              {view === 'line' && (
                <>
                  {lineBubbles.length === 0 && (
                    <>
                      {/* 私聊线的开头垫一段公共场面。**不是这条线的消息**，所以
                          画成虚线框的灰字，还写明了出处——不标的话玩家会以为
                          这句是对方说的，下一句就接着它回话，而模型那边这条线
                          里根本没有这段文字 */}
                      {threadNpc && sceneTail && (
                        <div className="space-y-1.5 pt-4">
                          <p className="text-[11px] text-muted-foreground px-1">
                            此刻的场面 · 来自公共场面，不算你们说过的话
                          </p>
                          <div className="rounded-2xl border border-dashed border-border/60 bg-muted/20
                            px-5 py-4 text-sm leading-[1.9] whitespace-pre-wrap text-muted-foreground">
                            {sceneTail}
                          </div>
                        </div>
                      )}
                      <p className={`text-center text-sm text-muted-foreground ${
                        threadNpc && sceneTail ? 'py-8' : 'py-20'}`}
                      >
                        {threadNpc
                          ? `你和${threadNpc.name}还没说过话。写下你要说的第一句。`
                          : '场面线还是空的。写下你要做的事，或者回地点总览找人说话。'}
                      </p>
                    </>
                  )}
                  {lineBubbles.map((b, i) => (
                    <div key={b.id ?? `pending-${i}`} className="space-y-2">
                      {b.role === 'user' ? (
                        <>
                          <div className="flex gap-2.5 justify-end">
                            <div className="max-w-[80%] rounded-2xl rounded-tr-sm px-4 py-2.5 text-sm leading-relaxed
                              whitespace-pre-wrap bg-primary text-primary-foreground">
                              {b.content}
                            </div>
                            <div className="w-7 h-7 rounded-full bg-muted flex items-center justify-center shrink-0 mt-0.5">
                              <User className="w-4 h-4" />
                            </div>
                          </div>
                          {b.roll && (
                            <div className="flex justify-end">
                              <div className="max-w-[80%] mr-[38px]">
                                <DiceRoll roll={b.roll} animate={b.fresh} />
                              </div>
                            </div>
                          )}
                        </>
                      ) : (
                        <div className="rounded-2xl border border-primary/15 bg-card/80 backdrop-blur-sm
                          px-5 py-4 text-sm leading-[1.9] whitespace-pre-wrap">
                          {waiting && i === lineBubbles.length - 1 ? <ThinkingDots /> : b.content}
                          {streaming && !waiting && i === lineBubbles.length - 1 && (
                            <span className="inline-block w-0.5 h-4 bg-current ml-0.5 animate-pulse align-middle" />
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                  <div ref={bottomRef} />
                </>
              )}
            </div>
          </div>

          {view === 'line' && ownerAway && (
            <div className="border-t border-border/50 bg-background/70 backdrop-blur-md px-6 py-3 shrink-0">
              <p className="max-w-3xl mx-auto text-xs text-muted-foreground leading-relaxed">
                {threadNpc
                  ? `${threadNpc.name}已经不在${sess.location || '这里'}了，说不上话。回地点总览去他所在的地方。`
                  : '这条线的主人已经不在这个模组里了。'}
              </p>
            </div>
          )}

          {view === 'line' && !ownerAway && (
            <div className="border-t border-border/50 bg-background/70 backdrop-blur-md px-6 py-3 shrink-0">
              <div className="max-w-3xl mx-auto space-y-2">
                {tips.length > 0 && !streaming && (
                  <div className="flex flex-wrap gap-1.5">
                    {tips.map((tip, i) => (
                      <button
                        key={i}
                        onClick={() => { setTips([]); send(tip, attr) }}
                        disabled={dead}
                        className="text-xs px-2.5 py-1 rounded-full bg-primary/10 text-primary ring-1 ring-primary/30
                          hover:bg-primary/20 disabled:opacity-40"
                      >
                        {tip}
                      </button>
                    ))}
                  </div>
                )}

                {actions.length > 0 && (
                  <div className="flex flex-wrap items-center gap-1.5">
                    {actions.map(action => {
                      const [ok, why] = checkCondition(action.requires, sess, npcs)
                      const needTarget = action.needs_target && !target
                      const blocked = !ok ? why : needTarget ? '先选一个对象' : ''
                      return (
                        <button
                          key={action.id}
                          onClick={() => runAction(action)}
                          disabled={locked || !!blocked}
                          title={blocked || action.prompt_hint || action.name}
                          className="text-xs px-2.5 py-1 rounded-lg bg-primary/10 text-primary ring-1 ring-primary/30
                            hover:bg-primary/20 disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                          {action.name}
                        </button>
                      )
                    })}
                    {actions.some(a => a.needs_target) && metNpcs.length > 0 && (
                      <select
                        value={target}
                        onChange={e => setTarget(e.target.value)}
                        title="动作作用在谁身上。选了他就等于走进他那条线"
                        className="text-xs border rounded-lg px-2 py-1 bg-background/60 focus:outline-none"
                      >
                        <option value="">对谁…</option>
                        {metNpcs.map(n => <option key={n.id} value={n.name}>{n.name}</option>)}
                      </select>
                    )}
                  </div>
                )}

                <div className="flex gap-2 items-end">
                  <AutoTextarea
                    value={input}
                    onChange={e => setInput(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder={dead ? '这一局已经结束了。' : '你要做什么？（Enter 发送，Shift+Enter 换行）'}
                    minRows={2}
                    disabled={locked}
                    className="flex-1 text-sm border rounded-lg px-3 py-2 bg-background/60
                      focus:outline-none focus:ring-1 focus:ring-primary/50 disabled:opacity-50"
                  />
                  {checkable.length > 0 && (
                    <select
                      value={attr}
                      onChange={e => setAttr(e.target.value)}
                      disabled={locked}
                      title="自己指定用哪项数值判定。选了就跳过 AI 裁决那一步，更快也更省"
                      className="text-xs border rounded-lg px-2 h-9 bg-background/60 focus:outline-none disabled:opacity-50"
                    >
                      <option value="">让 GM 决定</option>
                      {checkable.map(d => <option key={d.name} value={d.name}>{d.name}</option>)}
                    </select>
                  )}
                  <button
                    onClick={suggest}
                    disabled={locked || suggesting || lineBubbles.length === 0}
                    title="帮我想想：给几条接下来能做的事"
                    className="flex items-center justify-center w-9 h-9 rounded-lg shrink-0
                      bg-primary/10 text-primary ring-1 ring-primary/30 hover:bg-primary/20
                      disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {suggesting
                      ? <Loader2 className="w-4 h-4 animate-spin" />
                      : <Lightbulb className="w-4 h-4" />}
                  </button>
                  {streaming ? (
                    <button
                      onClick={stop}
                      title="停止生成（已输出的部分会保留）"
                      className="flex items-center justify-center w-9 h-9 rounded-lg shrink-0
                        bg-rose-500/15 text-rose-700 dark:text-rose-300 ring-1 ring-rose-500/40 hover:bg-rose-500/25"
                    >
                      <Square className="w-3.5 h-3.5" fill="currentColor" />
                    </button>
                  ) : (
                    <button
                      onClick={handleSend}
                      disabled={!input.trim() || dead}
                      className="flex items-center justify-center w-9 h-9 rounded-lg shrink-0
                        bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40"
                    >
                      <Send className="w-4 h-4" />
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}

        </div>

        <aside className="hidden xl:block w-80 shrink-0 border-l border-border/50">
          {menu}
        </aside>
      </div>

      {openNpc && (
        <NpcSheet
          npc={openNpc}
          relationDefs={relDefs}
          state={sess.npc_states?.[String(openNpc.id)] || {}}
          notes={sess.npc_notes?.[String(openNpc.id)] || {}}
          activity={sess.npc_activities?.[String(openNpc.id)] || ''}
          here={onstage(openNpc, sess)}
          place={npcPlace(openNpc, sess.slot, sess.npc_places)}
          onClose={() => setOpenNpc(null)}
          onDeleteNote={key => dropNote(openNpc.id, key)}
          onDeleteActivity={() => dropActivity(openNpc.id)}
        />
      )}

      {menuOpen && (
        <div className="fixed inset-0 z-40 xl:hidden" onClick={() => setMenuOpen(false)}>
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
          <div
            className="absolute inset-y-0 right-0 w-[min(20rem,85vw)] bg-background border-l shadow-2xl flex flex-col"
            onClick={e => e.stopPropagation()}
          >
            <button
              onClick={() => setMenuOpen(false)}
              className="absolute top-2 right-2 z-10 p-1.5 rounded hover:bg-muted"
              title="收起"
            >
              <X className="w-4 h-4" />
            </button>
            {menu}
          </div>
        </div>
      )}
    </div>
  )
}

/**
 * 页头的「模型」下拉。改的是**模组**，不是这一局——同一个模组的其他存档跟着变。
 * 这是照酒馆的做法（TavernChat 切模型也是写回卡片），好处是换完不用回设定页，
 * 代价是它不是这一局的私有设置，所以按钮的 title 里得说清楚。
 *
 * 面板留在组件树里用 absolute，**不能 createPortal** —— `--rpg-*` 那些颜色变量
 * 定在 .mode-rpg 这个 div 上，portal 到 body 的东西取不到，会变成一块裸色。
 */
function ModelPicker({ module, disabled }: { module: RpgModule; disabled: boolean }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const { data: models = [] } = useQuery({ queryKey: ['model-library'], queryFn: modelLibraryApi.list })
  const usable = models.filter((m: ModelEntry) => m.model_type !== 'embedding')

  // 点别处收起来。用 document 监听而不是铺一层 fixed 幕布：页头带 backdrop-blur，
  // 而 backdrop-filter 会给 fixed 子元素当包含块，幕布只盖得住页头那一条
  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', away)
    return () => document.removeEventListener('mousedown', away)
  }, [open])

  const change = async (key: 'model_ref' | 'fast_model_ref' | 'summary_model_ref', value: string) => {
    try {
      await rpgApi.modules.update(module.id, { [key]: value })
      qc.invalidateQueries({ queryKey: ['rpg-module', module.id] })
    } catch {
      toast.error('换模型失败')
    }
  }

  const row = (
    label: string,
    key: 'model_ref' | 'fast_model_ref' | 'summary_model_ref',
    empty: string,
    hint: string,
  ) => (
    <div>
      <label className="text-xs font-medium mb-1 block">{label}</label>
      <select
        value={modelSelectValue(models, module[key])}
        onChange={e => change(key, e.target.value)}
        className="w-full border rounded-lg px-2.5 py-1.5 text-xs bg-background/60"
      >
        <option value="">{empty}</option>
        {usable.map(m => <option key={m.id} value={String(m.id)}>{m.display_name || m.model_id}</option>)}
      </select>
      <p className="text-[11px] text-muted-foreground mt-1">{hint}</p>
    </div>
  )

  return (
    <div ref={box} className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        disabled={disabled}
        title="换这一局用的模型。改的是这个模组，同一模组的其他存档也跟着变"
        className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-md border
          hover:bg-muted disabled:opacity-40 disabled:cursor-not-allowed"
      >
        <Cpu className="w-3.5 h-3.5" />
        <span className="hidden sm:inline">模型</span>
      </button>

      {open && (
        // 底色不用 PANEL 的 bg-card/70 而是实心 bg-card：半透明的话下面的聊天
        // 文字会透上来，三个下拉根本看不清。其余（rpg-panel 的那圈起伏、圆角、
        // 边框）和别处一致
        <div className="rpg-panel absolute right-0 top-full mt-2 z-50 w-64 p-3 space-y-3
          rounded-xl border bg-card shadow-xl"
        >
          {row('叙事', 'model_ref', '跟随默认', '写旁白的那次调用。')}
          {row('判定与结算', 'fast_model_ref', '跟随默认', '只吐 JSON，便宜的就行。')}
          {row('总结', 'summary_model_ref', '跟随判定模型', '把旧剧情压成梗概，压错会一路带下去。')}
          <p className="text-[11px] text-muted-foreground border-t pt-2">
            改的是模组本身，这个模组的其他存档也跟着变。
          </p>
        </div>
      )}
    </div>
  )
}

/** 等首个 token 时的三点。Tailwind 只认字面类名，所以延迟写成行内 style */
function ThinkingDots() {
  return (
    <span className="inline-flex items-center gap-1 py-1" aria-label="GM 正在叙述">
      {[0, 1, 2].map(i => (
        <span
          key={i}
          className="w-1.5 h-1.5 rounded-full bg-primary/70 animate-bounce"
          style={{ animationDelay: `${i * 0.15}s` }}
        />
      ))}
    </span>
  )
}
