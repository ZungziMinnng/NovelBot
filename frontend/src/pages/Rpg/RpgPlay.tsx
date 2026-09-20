import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  AlertTriangle, ArrowLeft, BookMarked, Clock, Cpu, Dices, Footprints, Gauge, History, Lightbulb, Loader2,
  MapPin, MessageSquare, PanelLeftOpen, Pencil, RotateCcw, Send, SkipForward, Square, User, Users,
  Wrench, X,
} from 'lucide-react'
import {
  rpgApi, modelLibraryApi, modelSelectValue, groupModelsByProvider, streamRpgTurn,
  type RpgAction, type RpgModule, type RpgNpc,
  type RpgRoll, type RpgSave, type RpgSession, type RpgSSEMessage, type RpgSuggestion,
  type RpgTaskProposal, type RpgTurnMeta,
} from '@/api/client'
import {
  isTurnLive, rpgTurnActions, toBubble, useRpgTurn, useRpgTurnStore,
} from '@/store/rpgTurnStore'
import { confirmDialog } from '@/components/ConfirmDialog/ConfirmDialog'
import AutoTextarea from '@/components/AutoTextarea'
import {
  EntityAutocompleteList, useEntityAutocomplete, type EntityItem,
} from '@/components/EntityAutocomplete/EntityAutocomplete'
import ThemePicker from '@/components/ThemePicker/ThemePicker'
import ReadingFontButton from '@/components/ReadingFont/ReadingFontButton'
import { useReadingFont } from '@/components/ReadingFont/useReadingFont'
import {
  actionBlocked, checkCondition, following, knownNpcs, norm, npcPlace, onstage, targetChoices,
  visibleLocations,
} from './condition'
import {
  kindMeta, normalizeSuggestions, splitSuggestions, suggestionLabel,
} from './suggestion'
import DiceRoll from './DiceRoll'
import RpgAvatar from './RpgAvatar'
import LocationOverview from './LocationOverview'
import PlacePage from './PlacePage'
import SimHome from './SimHome'
import { actionTimeHint } from './actionFeedback'
import StatePanel from './StatePanel'
import FocusPortrait from './FocusPortrait'
import StatusSidebar, { type SidebarTab } from './StatusSidebar'
import TweakPanel from './TweakPanel'
import SaveTab from './sidebar/SaveTab'
import TaskResolutionsModal from './TaskResolutionsModal'
import RpgTurnStatus from './RpgTurnStatus'
import SettlementReport from './SettlementReport'
import { styleLabel } from './stylePresets'
import { GAMEPLAY_MODEL_FIELDS, EXTRA_MODEL_FIELDS, type RpgModelField } from './modelSettings'
import { playSfx } from './useSfx'
import GameHud, { type GameOutcome } from './GameHud'
import TurnCostPanel, { type TurnCost } from './TurnCostPanel'

// 气泡的形状和「消息 → 气泡」的转换都搬到 @/store/rpgTurnStore 了：
// 「正在生成的那一轮」整套状态既然归 store 管，气泡的类型也该跟着它走，
// 免得 store 反过来 import 这个组件

/**
 * 这一轮说话的方式。玩家在输入框上方明着选，发给后端的也是这个值。
 *
 * 它替掉了老的 focus_npc_id。那个字段名义上是「前端正在看谁」，实际上偷偷
 * 决定了这段戏记进谁的记忆——玩家以为自己在用一个筛选器，代码拿它当记忆开关。
 * 模式必须是明牌的：看谁（下面的 focusNpcId）归看谁，说给谁听归这里。
 */
type TurnMode = 'group' | 'private' | 'solo'

/** 输入框上方那三个按钮。hint 是选中之后跟在后面的那句白话 */
const MODES: { key: TurnMode; label: string; hint: string }[] = [
  { key: 'group', label: '群聊', hint: '在场的人都参与，这段话进他们每个人的记忆' },
  { key: 'private', label: '私聊', hint: '只跟这一个人说，旁人听不见，也只进她的记忆' },
  // 不写「不跟人说话」：这一轮该不该有人开口是模型按剧情决定的，界面管不着。
  // 它管的只有一件事——你这一轮不是冲着谁去的
  { key: 'solo', label: '独自行动', hint: '你做你自己的事，不主动找人搭话；旁边的人看着，他们照样记得' },
]

/** 「点出来的」那一轮额外带的东西。全空就是自由打字 */
interface TurnExtra {
  action_id?: number | null
  item_name?: string
  item_qty?: number
  skill_name?: string
  move_to?: string
  target_npc?: string
  mode?: TurnMode
  private_with?: number | null
}

/** 三级：地点总览 → 某个地点 → 时间线。总览是中枢，进去靠点，回来靠面包屑。
 *
 *  模拟器（play_style === 'sim'）多一级 'home'，并且以它为中枢：那边玩的是
 *  「今天安排什么」，一进来该看到的是一屏功能按钮，而不是一张地图。地点在 'home'
 *  里退化成其中一栏，地图那两级仍然走得通，只是不再是默认入口 */
type View = 'home' | 'overview' | 'place' | 'line'

/** 上次停在哪一级。出去改个模组、刷新一下、明天再进来，最常见的诉求是「接着刚才
 *  聊」，而不是从地图重新往里点两层。
 *
 *  只存 view 这一个枚举：focusNpcId / turnMode / privateWith 是「这一轮我要干
 *  什么」，隔了一段时间再回来不该替玩家决定。mapParentId 也不存——它已经有自己的
 *  规则（跟着玩家站的那一层走）。 */
const VIEW_KEY = (id: number) => `rpg-view:${id}`
const readView = (id: number): View | null => {
  try {
    const raw = window.localStorage.getItem(VIEW_KEY(id))
    // 认不出来的值一律当没存过：手改过 localStorage、或者以后这个枚举变了，
    // 都不该让页面停在一个渲染不出东西的级别上
    return raw === 'home' || raw === 'overview' || raw === 'place' || raw === 'line'
      ? raw : null
  } catch { return null }
}

/** 用量那一列开着没有。默认开——只有**明确关过**才收起来。
 *
 *  **不按局存**：想不想看 token 是一个习惯，不是每局重新做一次的选择
 *  （view 那个是「上次停在哪」，所以才按局存） */
const COST_KEY = 'rpg-cost'
const readCostOpen = () => {
  try { return window.localStorage.getItem(COST_KEY) !== '0' } catch { return true }
}

/** 改消息时那排小按钮。次要动作，别抢正文的注意力 */
const EDIT_BTN = 'text-xs px-2.5 py-1 rounded-lg border hover:bg-muted'

/** 诊断行用：这一轮被提到、但人不在你跟前的那些名字。
 *  就是 npcs_onstage（宽名单，给注入用）减去 npcs_here（真的同地点） */
const mentionedOnly = (meta: RpgTurnMeta) => {
  const here = new Set((meta.npcs_here || []).map(n => n.id))
  return (meta.npcs_onstage || []).filter(n => !here.has(n.id)).map(n => n.name)
}

/** 这条戏当时谁在跟前——也就是它会进谁的记忆。
 *  null 是迁移过来的老消息，当时的名单没记下来，那就什么都别说 */
const rosterLabel = (present: number[] | null, npcs: RpgNpc[]) => {
  if (present === null) return ''
  if (present.length === 0) return '只有你一个人'
  const names = present
    .map(id => npcs.find(n => n.id === id)?.name)
    .filter((name): name is string => !!name)
  return names.length > 0 ? `在场：${names.join('、')}` : ''
}

function stateChanges(before: RpgSession | undefined, after: RpgSession): string[] {
  if (!before) return []
  const changes: string[] = []
  const names = new Set([...Object.keys(before.stats || {}), ...Object.keys(after.stats || {})])
  names.forEach(name => {
    const previous = Number(before.stats?.[name] ?? 0)
    const next = Number(after.stats?.[name] ?? 0)
    if (previous !== next) changes.push(`${name} ${next > previous ? '+' : ''}${next - previous}`)
  })
  if (before.location !== after.location && after.location) changes.push(`到达 ${after.location}`)
  if (before.day !== after.day || before.slot !== after.slot) {
    changes.push(`时间推进至第 ${after.day} 天${after.slot ? ` · ${after.slot}` : ''}`)
  }
  const beforeBag = new Map((before.inventory || []).map(item => [item.name, item.qty]))
  const afterBag = new Map((after.inventory || []).map(item => [item.name, item.qty]))
  new Set([...beforeBag.keys(), ...afterBag.keys()]).forEach(name => {
    const previous = beforeBag.get(name) ?? 0
    const next = afterBag.get(name) ?? 0
    if (previous !== next) changes.push(`${name} ${next > previous ? '+' : ''}${next - previous}`)
  })
  return changes.slice(0, 8)
}

export default function RpgPlay() {
  const { sessionId: sessionIdParam } = useParams<{ sessionId: string }>()
  const sessionId = Number(sessionIdParam)
  const navigate = useNavigate()
  const qc = useQueryClient()

  const [input, setInput] = useState('')
  const [attr, setAttr] = useState('')

  // 「正在生成的那一轮」整套状态在 store 里，不在这儿。
  // 切走时这个页面是真的卸载（App.tsx 的 <Route> 没带 key），而 `send` 里那条
  // SSE 的会调还在跑——状态留在组件里就跟着一起销毁，回到页面只剩空白。
  // setter 的名字和原来逐个对齐，于是下面那十几处 setBubbles(...) 一行没改
  const { bubbles, streaming, waiting, stage, meta, tips, suggesting, lastError, taskAsk } =
    useRpgTurn(sessionId)
  const turnActions = useMemo(() => rpgTurnActions(sessionId), [sessionId])
  const {
    setBubbles, setStreaming, setWaiting, setStage, setMeta, setTips, setSuggesting,
    setLastError, setTaskAsk, appendToken, flushTokens, setController, start: startTurn,
    abort: abortTurn, end: endTurn,
  } = turnActions

  // 正在改哪条消息。id 是库里的行，没落库的（流式占位）不给改
  const [editing, setEditing] = useState<{ id: number; role: string; text: string } | null>(null)
  // 瞬移 / 推时段在跑。都是毫秒级的纯引擎请求，但手滑连点两下就会发两个
  const [engineBusy, setEngineBusy] = useState(false)
  const [settlingId, setSettlingId] = useState<number | null>(null)
  const settlingRef = useRef(false)
  useEffect(() => {
    if (streaming || bubbles[bubbles.length - 1]?.settlement?.status !== 'running') return
    const timer = window.setInterval(() => {
      qc.invalidateQueries({ queryKey: ['rpg-messages', sessionId] })
      qc.invalidateQueries({ queryKey: ['rpg-session', sessionId] })
    }, 2000)
    return () => window.clearInterval(timer)
  }, [bubbles, streaming, qc, sessionId])
  const [target, setTarget] = useState('')
  // 点了「可远程指定」的动作、人还没挑。非空 = 挑人的浮层开着。
  // 远程动作的顺序和别的动作是反的：先点按钮，再挑对象（手机上就该是这样），
  // 所以得有个地方暂存「刚点的是哪个」
  const [pickFor, setPickFor] = useState<RpgAction | null>(null)
  const pendingSuggestionTextRef = useRef('')
  const [tab, setTab] = useState<SidebarTab>('cast')
  // 「新发现」那一格在补全档案。要等一次模型调用，所以得有个转圈
  const [applyingFound, setApplyingFound] = useState(false)
  // 待玩家点头的「这桩事办完了吗」。非空就弹窗，照抄小说侧伏笔回收那一套。
  // 它由流式事件塞进来，所以和上面那一套一起住在 store 里
  const [resolvingTasks, setResolvingTasks] = useState(false)
  // 结算里 GM 说「这一幕收尾了」的那句理由。**只用来点亮按钮**，时钟仍然
  // 只有玩家能拨；推过一格就清掉。不做 toast——那玩意一闪而过，而这条要留着
  const [slotHint, setSlotHint] = useState<string | null>(null)
  // 侧栏在宽屏常驻，窄屏收成抽屉
  const [menuOpen, setMenuOpen] = useState(false)
  // 存档从侧栏搬到了页头，点开是个浮层
  const [saveOpen, setSaveOpen] = useState(false)
  // 修改器同理挂在页头：手改数值是「这一局之外」的事，和侧栏那五格不是一类
  const [tweakOpen, setTweakOpen] = useState(false)
  const [view, setView] = useState<View>(() => readView(sessionId) ?? 'overview')
  // 地图当前展开的父地点；null 表示大陆/区域级大地图
  const [mapParentId, setMapParentId] = useState<number | null>(null)
  // 看谁的视角。null = 全部（整条时间线），值是 NPC 的 id。
  // 只是一个**筛选器**：所有消息都在同一条时间线上，切视角不改变什么归谁
  const [focusNpcId, setFocusNpcId] = useState<number | null>(null)
  // 这一轮怎么说话，见 TurnMode。和上面那个筛选器是两件事，别再合成一个
  const [turnMode, setTurnMode] = useState<TurnMode>('group')
  const [privateWith, setPrivateWith] = useState<number | null>(null)
  const [openNpc, setOpenNpc] = useState<RpgNpc | null>(null)
  const [lastOutcome, setLastOutcome] = useState<GameOutcome | null>(null)
  // 输入框上方那个「移动」下拉开着没有
  const [moveOpen, setMoveOpen] = useState(false)
  const moveBox = useRef<HTMLDivElement>(null)
  const pendingActionRef = useRef('自由行动')
  // 右边那一列（本次行动花了多少 token）开着没有
  const [costOpen, setCostOpen] = useState(readCostOpen)
  // 哪条 assistant 消息是点哪个按钮打出来的。**只认本次打开页面之后发出的
  // 那几轮**：刷新之后旧回合认不出是动作还是自由输入，统一叫「回合」。
  // 为此给消息加一列并不值得——这一列是个看一眼的仪表，不是账本
  const [costLabels, setCostLabels] = useState<Record<number, string>>({})
  // 剧情气泡的字号/行距/粗细。和小说侧分键（见 useReadingFont），页头那个按钮改它
  const { style: readingStyle, ...readingFont } = useReadingFont('rpg')

  const bottomRef = useRef<HTMLDivElement>(null)
  // adjudicate 和 roll 是两个事件，拼起来才是完整的一次判定
  const judgeRef = useRef<Partial<RpgRoll>>({})
  // 这一轮是怎么发出去的。重试要原样再来一次：快捷行动那种带 action_id 的
  // 走的是引擎结算，退化成一句自由文本就不是同一件事了
  const lastTurnRef = useRef<{ text: string; attr: string; extra: TurnExtra } | null>(null)
  // 时间线此刻筛在谁身上。send 是 useCallback，闭包里读 state 拿的是旧值
  const focusRef = useRef<number | null>(null)

  const { data: sess } = useQuery({
    queryKey: ['rpg-session', sessionId],
    queryFn: () => rpgApi.sessions.get(sessionId),
    enabled: Number.isFinite(sessionId) && sessionId > 0,
    refetchOnMount: 'always',
    staleTime: 0,
    gcTime: 0,
  })
  const moduleId = sess?.module_id
  const { data: module } = useQuery({
    queryKey: ['rpg-module', moduleId],
    queryFn: () => rpgApi.modules.get(moduleId!),
    enabled: !!moduleId,
  })
  // 模拟器：主页是中枢，地图退成主页里的一栏。module 还没到时按 false 算，
  // 那一帧只影响默认落哪一级，而那件事等在 landedRef 那个 effect 里做
  const isSim = module?.play_style === 'sim'
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
  const { data: skills = [] } = useQuery({
    queryKey: ['rpg-skills', moduleId],
    queryFn: () => rpgApi.skills.list(moduleId!),
    enabled: !!moduleId,
  })
  const { data: locations = [] } = useQuery({
    queryKey: ['rpg-locations', moduleId],
    queryFn: () => rpgApi.locations.list(moduleId!),
    enabled: !!moduleId,
    refetchOnMount: 'always',
  })
  // 存档只在页头那个浮层打开时才拉：绝大多数回合玩家根本不看它
  const { data: saves = [] } = useQuery({
    queryKey: ['rpg-saves', sessionId],
    queryFn: () => rpgApi.saves.list(sessionId),
    enabled: saveOpen,
  })
  // 消息以后端为准：只在进页面时拉一次，之后本地追加。
  // 没有单独的「线」端点，也不需要：只有一个视角要筛，筛的是消息自己带的名单
  const { data: loaded } = useQuery({
    queryKey: ['rpg-messages', sessionId],
    queryFn: () => rpgApi.messages.list(sessionId),
    enabled: Number.isFinite(sessionId) && sessionId > 0,
    refetchOnMount: 'always',
    staleTime: 0,
    gcTime: 0,
  })

  /** 每次操作一条，从新到旧，只留最近几条。
   *
   *  叙事那次调用的消耗记在 assistant 那行；判定挂在 user 行、结算挂在
   *  assistant 行，两边的 aux 都要算进来才是这一次操作的真实花费。
   *
   *  四个数全是 0 的 assistant 行不算一次操作——开场旁白、瞬移留下的那种
   *  纯引擎文字压根没调过模型，列出来一排 0 只会让人以为读数坏了 */
  const costEntries = useMemo<TurnCost[]>(() => {
    const rows = loaded || []
    const out: TurnCost[] = []
    rows.forEach((row, index) => {
      if (row.role !== 'assistant') return
      const before = rows[index - 1]
      const paired = before && before.role === 'user' ? before : null
      const cost: TurnCost = {
        id: row.id,
        label: costLabels[row.id] || '回合',
        narrIn: row.input_tokens || 0,
        narrOut: row.output_tokens || 0,
        auxIn: (row.aux_input_tokens || 0) + (paired?.aux_input_tokens || 0),
        auxOut: (row.aux_output_tokens || 0) + (paired?.aux_output_tokens || 0),
      }
      if (cost.narrIn || cost.narrOut || cost.auxIn || cost.auxOut) out.push(cost)
    })
    return out.reverse().slice(0, 6)
  }, [loaded, costLabels])

  /** 本局累计。按消息自己带的数字加，所以刷新、换设备都对得上 */
  const costTotal = useMemo(() => (loaded || []).reduce(
    (acc, row) => ({
      input: acc.input + (row.input_tokens || 0) + (row.aux_input_tokens || 0),
      output: acc.output + (row.output_tokens || 0) + (row.aux_output_tokens || 0),
    }),
    { input: 0, output: 0 },
  ), [loaded])

  const toggleCost = () => setCostOpen(open => {
    // 写的是「关掉」的标记，不是「开着」。读那边认的是「没关过就当开」，
    // 所以这里存 '1' 反而会让收起失效——收起要能记住，靠的就是这个 '0'
    try { window.localStorage.setItem(COST_KEY, open ? '0' : '1') } catch { }
    return !open
  })

  // 进这一局之前存着的是哪一级。下面「新局落在时间线」那一跳要拿它当判据，
  // 到时候再 readView 是不行的：落盘 effect 早在挂载那一轮就把当前这一级写
  // 进去了，读回来永远非空，开场白那一跳就再也不会发生
  const savedViewRef = useRef<View | null>(readView(sessionId))
  useEffect(() => {
    // 这一局正跑着一轮就别清。这段清理本意是「上一局的气泡别串到这一局」，
    // 而从别处切回一个**正在生成**的局时，清空会把已经吐出来的一半抹掉，
    // 那半段后端还在接着写
    if (!isTurnLive(sessionId)) setBubbles([])
    savedViewRef.current = readView(sessionId)
    setView(savedViewRef.current ?? 'overview')
    setMapParentId(null)
    setFocusNpcId(null)
    setTurnMode('group')
    setPrivateWith(null)
    setLastOutcome(null)
    landedRef.current = false
  }, [sessionId])

  // 流式期间以本地为准：列表在生成中途被重新拉下来（staleTime 30 秒 + 切回
  // 窗口就重拉）会把这颗还没落库的流式气泡整个换掉，而气泡已经开过了，下一个
  // token 就直接追加到**你自己那句话的气泡**里了。这一轮结束时 done 里那次
  // invalidate 会把权威列表拉回来
  useEffect(() => {
    if (!loaded || streaming) return
    setBubbles(loaded.map(toBubble))
    // streaming 故意不进依赖：进去就变成「每次它一变就重新拉下来覆盖」
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded])

  // 新局直接落在时间线上。开场白是这条时间线的第一条旁白，而默认视图是地图
  // 总览——不跳的话玩家开局第一眼看到的是一张地图，得往里点两层才看得到作者
  // 写的那一幕，多数人会以为开场白没生效。
  // 判据是「玩家一句话都还没说过」，而且只在进页面时判一次：之后无论他停在
  // 哪一级，刷新回来都该停在原地，不能被这一跳抢走
  // 模拟器那一档的中枢是主页而不是地图总览，所以「没存过 view 时落在哪」这件事
  // 也要看玩法类别。它跟着 module 来，比 sess 晚一步，因此判断只能等在这里，
  // 而不能写进上面那个只认 sessionId 的重置 effect。
  // 两件事合在同一个 effect 里做而不是各写一个：两个 effect 都会 setView，
  // 而它们的依赖各自独立地到达，先后顺序不定——开场白那一跳会被主页那一跳抢掉
  const landedRef = useRef(false)
  useEffect(() => {
    if (!loaded || !module || landedRef.current) return
    landedRef.current = true
    // 停过的地方优先。上面那句「刷新回来都该停在原地」现在是真的了，
    // 这一跳只管头一回进来的新局
    if (savedViewRef.current) return
    if (loaded.length > 0 && loaded.every(m => m.role !== 'user')) {
      // 开场白仍然优先于主页：不跳的话玩家开局第一眼看不到作者写的那一幕，
      // 多数人会以为开场白没生效（模拟器也一样，它同样有 opening_scene）。
      // 看完点面包屑回来就是主页了
      setFocusNpcId(null)
      setView('line')
    } else if (module.play_style === 'sim') {
      setView('home')
    }
  }, [loaded, module])

  // 落盘。依赖**只写 view**：写成 [sessionId, view] 的话，切到另一局的那一帧
  // view 还是上一局的值，会被写到新 id 底下去；只依赖 view 就不会在那一帧触发，
  // 等上面的重置 effect 读完干净值、setView 之后再落，顺序才是对的
  useEffect(() => {
    try { window.localStorage.setItem(VIEW_KEY(sessionId), view) } catch { }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view])

  // 地图默认显示玩家**站着的那一层**。走进客栈之后总览还停在大地图的话，
  // 玩家看不到大堂和客房——它们根本不在大地图上——只会觉得内部地图丢了。
  // 依赖是算出来的 id 而不是 locations 数组：后者每次重拉都是新引用，
  // 会把玩家手动翻到的层（面包屑点回大地图）又抢回去
  const homeLevel = locations.find(
    location => norm(location.name) === norm(sess?.location || ''),
  )?.parent_id ?? null
  useEffect(() => { setMapParentId(homeLevel) }, [homeLevel])

  // 这里原先挂着「卸载就 abort」。拆掉了：切页面不该掐断正在生成的那一轮，
  // 而这一页切走就是卸载（App.tsx 的 <Route> 没带 key）。真想停有两条路——
  // 输入框上的停止按钮，和右下角药丸上的 ×

  // 名册上的人。默认只有见过面或此刻在场的能当动作对象：对一个还没登场的人
  // 「夸奖」等于把他抖出来。模拟器档是全员（见 knownNpcs）——那边老板本来就
  // 该知道手下有谁，手机也要打得出去
  const metNpcs = useMemo(
    () => (sess ? knownNpcs(npcs, sess, module) : []),
    [npcs, sess, module],
  )

  const focusNpc = useMemo(
    () => (focusNpcId ? npcs.find(n => n.id === focusNpcId) ?? null : null),
    [npcs, focusNpcId],
  )

  /** 此刻真的站在你跟前的人。私聊只能挑这里面的一个——照后端 present_ids 那一套，
   *  包括「玩家没有地点 = 所有人都在同一个场面里」那条兜底（纯对话模组） */
  const hereNpcs = useMemo(() => {
    if (!sess) return []
    const cast = npcs.filter(n => n.role !== 'protagonist')
    return (sess.location || '').trim() ? cast.filter(n => onstage(n, sess)) : cast
  }, [npcs, sess])

  // 换了地方之后「对谁」还留着上一处那个人，下一个快捷行动的好感就加到了一个
  // 不在场的人头上。名单换了就清掉
  useEffect(() => {
    if (target && !hereNpcs.some(n => n.name === target)) setTarget('')
  }, [hereNpcs, target])

  // 点别处收起「移动」下拉，同 PlayParams 那个
  useEffect(() => {
    if (!moveOpen) return
    const away = (e: MouseEvent) => {
      if (moveBox.current && !moveBox.current.contains(e.target as Node)) setMoveOpen(false)
    }
    document.addEventListener('mousedown', away)
    return () => document.removeEventListener('mousedown', away)
  }, [moveOpen])

  /** 「移动」下拉里列的地方：探到了的、且不是此刻所在地。
   *  进不去的也照列、只是灰掉并写明差什么——藏起来玩家会以为那地方不存在 */
  const moveTargets = useMemo(() => {
    if (!sess) return []
    const seen = new Set(visibleLocations(locations, sess))
    const known = knownNpcs(npcs, sess, module)
    return locations
      .filter(loc => seen.has(loc.id) && norm(loc.name) !== norm(sess.location || ''))
      .map(loc => {
        const [ok, why] = checkCondition(loc.enter_requires, sess, npcs)
        return {
          loc,
          why: ok ? '' : why,
          people: known.filter(
            n => norm(npcPlace(
              n, sess.slot, sess.npc_places, sess.npc_followers, sess.location,
            )) === norm(loc.name),
          ).length,
        }
      })
  }, [locations, npcs, sess, module])

  /**
   * 真正发出去的那个模式。turnMode 存的是玩家的**意愿**，这里按屋里此刻的人
   * 折算成合法值——不存回 state 是故意的：一走进空屋子就把他选的「群聊」改写成
   * 「独自」，等他再走进酒馆，界面会停在独自行动，而他从没选过那个。
   *
   * 屋里没人 → 只能独自行动；私聊的对象不在跟前 → 退回群聊（后端也会挡，
   * 但报 400 之前先在这儿拦住，玩家不该看见一条红条）。
   */
  const effectiveMode: TurnMode = hereNpcs.length === 0
    ? 'solo'
    : turnMode === 'private' && !hereNpcs.some(n => n.id === privateWith)
      ? 'group'
      : turnMode

  /** 这一轮的模式，附在每次 send 上。三个入口（打字、快捷行动、用道具）共用 */
  const turnExtra = (): TurnExtra => ({
    mode: effectiveMode,
    private_with: effectiveMode === 'private' ? privateWith : null,
  })

  const privateNpc = privateWith ? npcs.find(n => n.id === privateWith) ?? null : null

  /** 右边那列立绘挂谁。只在**锁定了单独一个人**时有值：
   *  私聊优先于「只看某人」——私聊是这一轮真的在跟谁说话，比看谁的历史更当下。
   *  「全部」视角 + 群聊/独自 一律为 null，那时候没有唯一的「那个人」 */
  const portraitNpc = (effectiveMode === 'private' ? privateNpc : null) ?? focusNpc

  /**
   * 打字补全的候选：敲下名字的头一个字就能选。同小说编辑器那条生成指令栏。
   *
   * **世界里的东西和身上的东西两套来源**：
   *
   * - 角色 / 地点取模组表，**全给**、不按迷雾筛。这是输入辅助不是叙事内容：
   *   能不能真的走到那儿、见到那个人，仍旧由进入条件和后端结算说了算，
   *   打得出名字不等于去得了。
   * - 道具 / 技能只取这一局的背包和已学表。**不能拿模组的定义表**：那张表是
   *   作者写下的全集，上品灵石用光了它照样在，玩家敲个「上」还是弹出来，
   *   点进去发的是一句自己根本办不到的话。背包/已学也更全——剧情里 GM 给的
   *   东西、现学的一招，模组表上压根没有。
   */
  const entities = useMemo<EntityItem[]>(() => {
    // 技能的说明只有模组表里有，已学表只记名字和冷却
    const skillDesc = (name: string) =>
      skills.find(s => norm(s.name) === norm(name))?.description || ''
    const all: EntityItem[] = [
      ...npcs.map(n => ({ name: n.name, typeLabel: '角色', description: n.description })),
      ...locations.map(l => ({ name: l.name, typeLabel: '地点', description: l.description })),
      ...(sess?.inventory || []).map(it => ({
        name: it.name, typeLabel: '道具', description: it.qty > 1 ? `×${it.qty}` : '',
      })),
      ...(sess?.skills || []).map(sk => ({
        name: sk.name, typeLabel: '技能', description: skillDesc(sk.name),
      })),
    ]
    const seen = new Set<string>()
    return all.filter(e => {
      const key = `${e.typeLabel}-${e.name}`
      if (!e.name || seen.has(key)) return false
      seen.add(key)
      return true
    })
  }, [npcs, locations, skills, sess])

  const inputRef = useRef<HTMLTextAreaElement>(null)
  const ac = useEntityAutocomplete(entities, input, setInput, inputRef)

  // 换视角时把动作对象重置成那个人：不重置就会**跨人泄漏**——看完老兵再看
  // 老板娘，target 还留着老兵，下一个动作的好感就加到别人头上。
  // 「全部」视角一律清空：自动替玩家选一个对象没有任何依据
  useEffect(() => {
    focusRef.current = focusNpcId
    const owner = focusNpcId ? npcs.find(n => n.id === focusNpcId) : null
    setTarget(owner ? owner.name : '')
  }, [focusNpcId, npcs])

  /** 这个视角该显示的气泡：**当时在场的都算**，包括他参与过的群戏——
   *  同一场戏在在场每个人的视角里都在，靠的是那条消息本身就记着谁在场，
   *  不需要往各人的历史里各复制一份（复制会让同一段戏各演化一遍）。
   *  present 为 null 的是老消息，当所有人可见 */
  const lineBubbles = useMemo(
    () => (focusNpcId === null
      ? bubbles
      : bubbles.filter(b => b.present === null || b.present.includes(focusNpcId))),
    [bubbles, focusNpcId],
  )

  /** 在飞的那一轮是不是就落在你眼前。只有一条时间线了，所以它永远在这里；
   *  还没落库的气泡 present 记的是 null（谁在场要等后端快照），于是它在哪个
   *  视角里都看得见——这也正是「不知道就当所有人可见」这条读法 */
  const streamingHere = streaming

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    // stage 也进依赖：结算提示是在正文写完之后才插进来的，那会儿气泡没变，
    // 只等 lineBubbles 的话新插的那一行会落在可视区下面，正好看不见
  }, [lineBubbles, stage])

  const send = useCallback((
    text: string, useAttr: string, extra: TurnExtra = {},
  ) => {
    if (useRpgTurnStore.getState().turns[sessionId]?.streaming) return
    pendingActionRef.current = extra.action_id
      ? (actions.find(action => action.id === extra.action_id)?.name || '快捷行动')
      : extra.item_name ? `使用 ${extra.item_name}`
        : extra.skill_name ? `施展 ${extra.skill_name}`
          : extra.move_to ? `前往 ${extra.move_to}` : '自由行动'
    lastTurnRef.current = { text, attr: useAttr, extra }
    setLastOutcome(null)
    // 先把这一局重置成新的一轮再往里写。必须在第一颗气泡之前调——start 会
    // 清空气泡、并把右下角那粒药丸挂上
    startTurn(module?.name || sess?.title || '', `/game/play/${sessionId}`)
    setLastError(null)
    setBubbles(prev => [...prev, {
      id: null, role: 'user', content: text, roll: null, fresh: true,
      present: null, location: '',
      turn_request: { attr: useAttr, ...extra },
    }])
    setStreaming(true)
    setWaiting(true)
    setStage('')
    setMeta(null)
    setTips([])
    judgeRef.current = {}

    // 正在流的那条永远是最后一条：气泡只往后追加
    const patchLast = (fn: (prev: string) => string) =>
      setBubbles(prev => prev.map((b, i) => (i === prev.length - 1 ? { ...b, content: fn(b.content) } : b)))

    // 这一轮已经开过助手气泡就不再开。判据**现查 store**，不用组件里的 ref：
    // 切走再切回来时 ref 是全新的 false，可 store 里那颗气泡还开着，再开一颗
    // 会让正在吐的正文从中间断开。判据是「最后一条是助手气泡且还没落库」——
    // done 会给它写上正式 id，那就算封口了
    const openBubble = () => {
      const current = useRpgTurnStore.getState().turns[sessionId]?.bubbles
      const last = current?.[current.length - 1]
      if (last?.role === 'assistant' && last.id === null) return
      setBubbles(prev => [...prev, {
        id: null, role: 'assistant', content: '', roll: null, fresh: true,
        present: null, location: '',
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

    const controller = streamRpgTurn(
      sessionId,
      { content: text, attr: useAttr, ...extra },
      (msg: RpgSSEMessage) => {
        if (useRpgTurnStore.getState().turns[sessionId]?.controller !== controller) return
        if (msg.event === 'meta') {
          // 后端发两次：先只带 user_message_id，上下文拼完再补诊断。必须合并
          setMeta(prev => ({ ...prev, ...msg.data }))
          const uid = msg.data.user_message_id
          if (uid) {
            setBubbles(prev => prev.map(b => (
              b.role === 'user' && b.id === null ? { ...b, id: uid } : b
            )))
          }
          // 时间线正筛在「只看某人」上，而这一轮她不在场：后端给这两条消息记的
          // 在场名单里没有她，等 done 之后从后端重读、按名单一筛，刚写出来的
          // 整轮戏就被滤没了——玩家看到的是内容凭空消失，只剩道具还躺在背包里
          //（这就是那个 bug 的样子）。与其藏，不如退回「看全部」。
          //
          // 看的是**筛选器**而不是这一轮的模式：私聊已经由后端保证她在场，
          // 会漏的是另一种——你在别处独自行动，筛选器还停在她身上。
          // 用 ref 不用 state：send 是 useCallback，闭包里那份是发出这一轮时的旧值。
          // 地点为空的模组要放过：那种模组「所有人都在同一个场面里」，后端
          // 按全员在场处理，可诊断里的 npcs_here 仍然是空的
          const here = msg.data.npcs_here
          const watching = focusRef.current
          if (
            watching && Array.isArray(here) && (sess?.location || '').trim()
            && !here.some(n => n.id === watching)
          ) {
            const who = npcs.find(n => n.id === watching)?.name
            setFocusNpcId(null)
            toast(`${who || '这个人'}不在你跟前，这一轮给你按「看全部」显示`)
          }
        } else if (msg.event === 'adjudicate') {
          judgeRef.current = msg.data
          if (!msg.data.need_check) attachRoll({ ...msg.data } as RpgRoll)
        } else if (msg.event === 'roll') {
          attachRoll({ ...judgeRef.current, ...msg.data, need_check: true } as RpgRoll)
        } else if (msg.event === 'token') {
          openBubble()
          setWaiting(false)
          // 开始吐字了，静默期结束：气泡里的光标接手，「正在做什么」的
          // 分阶段提示让位
          setStage('')
          appendToken(msg.data)
        } else if (msg.event === 'stage') {
          setStage(msg.data)
        } else if (msg.event === 'state') {
          // 引擎结算发一次、AI 结算再发一次，就地合进缓存，数值面板立刻跟着动
          const before = qc.getQueryData<RpgSession>(['rpg-session', sessionId])
          const after = before ? { ...before, ...msg.data } : undefined
          if (after) {
            const changes = stateChanges(before, after)
            setLastOutcome(previous => (
              changes.length || !previous
                ? {
                    title: pendingActionRef.current,
                    facts: previous?.facts || [],
                    changes: [...(previous?.changes || []), ...changes],
                  }
                : previous
            ))
          }
          qc.setQueryData(['rpg-session', sessionId], after)
        } else if (msg.event === 'engine_result') {
          setLastOutcome(previous => ({
            title: pendingActionRef.current, facts: msg.data.facts, changes: previous?.changes || [],
          }))
        } else if (msg.event === 'suggestions') {
          setTips(normalizeSuggestions(msg.data))
        } else if (msg.event === 'settlement') {
          const report = msg.data.report
          if (report) {
            setLastOutcome({
              title: pendingActionRef.current,
              facts: report.engine_facts || [],
              changes: report.changes || [],
            })
          }
          setBubbles(prev => prev.map((bubble, index) => (
            bubble.id === msg.data.message_id || (index === prev.length - 1 && bubble.role === 'assistant')
              ? { ...bubble, id: msg.data.message_id, settlement: msg.data.report } : bubble
          )))
        } else if (msg.event === 'discoveries') {
          // 角标当场亮起来，不等这一轮 done 之后的那次 session 刷新
          qc.setQueryData(['rpg-session', sessionId], (previous?: RpgSession) => (
            previous ? { ...previous, discoveries: [...(previous.discoveries || []), ...msg.data] } : previous
          ))
        } else if (msg.event === 'item_claims') {
          // 同上，角标当场亮。不弹窗打断：拿到东西不是非得当场处理的事，
          // 玩到想起来了再去道具格认——没认下来的东西也不在背包里，不会误用
          qc.setQueryData(['rpg-session', sessionId], (previous?: RpgSession) => (
            previous ? { ...previous, item_claims: [...(previous.item_claims || []), ...msg.data] } : previous
          ))
        } else if (msg.event === 'task_proposals') {
          // 这一条会打断：任务算不算办完只有玩家知道，而且拖到下一回合再问，
          // 那段正文已经翻过去了，玩家对着理由也想不起来当时发生了什么
          qc.setQueryData(['rpg-session', sessionId], (previous?: RpgSession) => (
            previous
              ? { ...previous, task_proposals: [...(previous.task_proposals || []), ...msg.data] }
              : previous
          ))
          setTaskAsk(prev => [...prev, ...msg.data])
        } else if (msg.event === 'slot_hint') {
          // 不打断。留在这儿把下面那颗「结束这个时段」点亮，推不推是玩家的事
          setSlotHint(msg.data)
        } else if (msg.event === 'warning') {
          toast(msg.data)
        } else if (msg.event === 'done') {
          const id = msg.data.message_id
          // 攒着的那几个 token 必须先落地，否则一帧之后它们会追加到一个
          // 已经拿到正式 id 的气泡上
          flushTokens()
          setStage('')
          // 这一轮是点什么打出来的，趁 pendingActionRef 还没被下一轮改掉记下来，
          // 用量那一列拿它当标签
          setCostLabels(prev => ({ ...prev, [id]: pendingActionRef.current }))
          setBubbles(prev => prev.map((b, i) => (i === prev.length - 1 ? { ...b, id } : b)))
          qc.invalidateQueries({ queryKey: ['rpg-session', sessionId] })
          qc.invalidateQueries({ queryKey: ['rpg-messages', sessionId] })
        } else if (msg.event === 'error') {
          flushTokens()
          openBubble()
          setWaiting(false)
          setStage('')
          patchLast(prev => prev + `\n[错误] ${msg.data}`)
          // 气泡里那行 [错误] 很容易被忽略——它可能缩在屏幕上方，而玩家的
          // 视线在输入框。原因原样挂到输入框上面那条横幅上，带一个「重试」，
          // 不点不消失
          setLastError(msg.data || '生成失败')
        }
      },
      () => {
        if (useRpgTurnStore.getState().turns[sessionId]?.controller !== controller) return
        // 这一轮收尾。界面此刻可能已经不在了（切走了），收尾照样做——
        // 药丸要摘掉、streaming 要落回 false，不然切回来会一直显示成「正在生成」
        flushTokens()
        endTurn()
        qc.invalidateQueries({ queryKey: ['rpg-messages', sessionId] })
        qc.invalidateQueries({ queryKey: ['rpg-session', sessionId] })
      },
    )
    setController(controller)
  }, [actions, sessionId, qc, sess?.location, sess?.title, module?.name, npcs, turnActions])

  const handleSend = () => {
    const text = input.trim()
    if (!text || streaming || settlingRef.current) return
    // 发出去的话进的是**唯一那条时间线**，谁在场由后端在写入时快照，
    // 前端不再猜、也不再替你切视角。原先这里会看正文里有几个人的名字，
    // 命中唯一一个跟前的人就自动跳进他的线——那正是「一会儿场面线一会儿
    // 对话线」的来源：同一句话被界面搬到了另一个地方，玩家看到的是消息存错了
    setInput('')
    send(text, attr, turnExtra())
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // 补全列表开着的时候 ↑↓ 是选候选、Enter 是填进去。不先让它过一遍的话，
    // 想选个名字结果把半句话发出去了
    if (ac.onKeyDown(e)) return
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const saveEdit = async () => {
    if (!editing || streaming || settlingRef.current) return
    const text = editing.text.trim()
    if (!text) return
    try {
      const updated = await rpgApi.messages.update(editing.id, text)
      setBubbles(prev => prev.map(b => (b.id === editing.id ? toBubble(updated) : b)))
      qc.invalidateQueries({ queryKey: ['rpg-messages', sessionId] })
      setEditing(null)
    } catch (error: any) {
      toast.error(error?.response?.data?.detail || '改不动，刷新看看')
    }
  }

  const resettle = async (messageId: number) => {
    if (streaming || engineBusy || settlingRef.current) return
    settlingRef.current = true
    setSettlingId(messageId)
    try {
      const message = await rpgApi.messages.settle(messageId)
      setBubbles(prev => prev.map(bubble => bubble.id === messageId ? toBubble(message) : bubble))
      const fresh = normalizeSuggestions(message.suggestions)
      if (fresh.length) setTips(fresh)
      toast(message.settlement?.status === 'done' ? '状态已重新结算'
        : message.settlement?.status === 'partial' ? '结算已结束，可以继续游玩；部分变化未采纳，请查看核对结果'
          : '核对结果已更新，请查看结算状态')
    } catch (error: any) {
      toast.error(error?.response?.data?.detail || '补结算失败，剧情已保留')
    } finally {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['rpg-session', sessionId] }),
        qc.invalidateQueries({ queryKey: ['rpg-messages', sessionId] }),
      ])
      settlingRef.current = false
      setSettlingId(null)
    }
  }

  /**
   * 从某条玩家消息重来一遍：先把这条以及之后的一切**倒回它发生之前**
   * （数值、背包、时段、好感一起回滚），再按新正文重跑一轮。
   *
   * 不能像酒馆那样只删消息：那边删掉就真没了，这边一轮结算改过的数值还留在
   * 身上，会落下「这句话没说过，代价还在」。回滚靠的是每轮自动存档，所以
   * 只有最近那几十轮退得回去，更早的后端会直接拒绝并说明原因。
   */
  const resendFrom = async (messageId: number, text: string, extra: TurnExtra = {}, ask = true) => {
    if (locked) return
    const body = text.trim()
    if (!body) return
    const request = bubbles.find(bubble => bubble.id === messageId)?.turn_request
      ?? loaded?.find(message => message.id === messageId)?.turn_request
      ?? { attr, ...extra }
    const { attr: replayAttr = '', ...replayExtra } = request
    if (ask && !await confirmDialog({
      title: '重发这一句？',
      detail: '这一句之后的剧情会被删掉，数值、背包、时段一起回到它发生之前。',
      confirmText: '重发',
      danger: true,
    })) return
    try {
      const next = await rpgApi.messages.rewind(messageId)
      qc.setQueryData(['rpg-session', sessionId], next)
      setBubbles(prev => {
        const at = prev.findIndex(b => b.id === messageId)
        return at === -1 ? prev : prev.slice(0, at)
      })
      setEditing(null)
      setLastError(null)
      refreshSaves()
      send(body, replayAttr, replayExtra)
    } catch (err: any) {
      // 400 带着「太早了，退不回去」那句话，原样说出来比「失败了」有用
      toast.error(err?.response?.data?.detail || '退不回去')
    }
  }

  /** 上一轮失败了，再来一次。玩家那句话后端多半已经落库，直接重发会多一条，
   *  所以走和「重发」同一条路：先倒回去。还没落库（连都没连上）就直接发 */
  const retry = () => {
    const turn = lastTurnRef.current
    if (!turn || locked) return
    const lastUser = [...bubbles].reverse().find(b => b.role === 'user')
    if (!lastUser || lastUser.id === null) {
      setLastError(null)
      setBubbles(prev => (lastUser ? prev.slice(0, prev.indexOf(lastUser)) : prev))
      send(turn.text, turn.attr, turn.extra)
      return
    }
    resendFrom(lastUser.id, turn.text, turn.extra, false)
  }

  /** 重新生成最后一段叙事：等价于把玩家上一句原样再发一次 */
  const regenerate = () => {
    const lastUser = [...bubbles].reverse().find(b => b.role === 'user')
    if (!lastUser?.id) return
    resendFrom(lastUser.id, lastUser.content)
  }

  // 帮我想想：另开一次调用要三条候选行动，和每轮结算顺带给的建议共用同一块显示区
  const suggest = async () => {
    if (locked || suggesting) return
    setSuggesting(true)
    // 先清掉旧的：等的时候还挂着上一轮的建议，会让人以为那就是答案
    setTips([])
    try {
      const { suggestions } = await rpgApi.suggest(sessionId)
      const fresh = normalizeSuggestions(suggestions)
      if (!fresh.length) toast('没想出来，再聊两句试试')
      else setTips(fresh)
    } catch (error: any) {
      // detail 里是后端那句人话（模型没配好、这一局已经结束）。只 toast 一句
      // 「没能生成建议」的话，模型配错时玩家找不到真正的毛病
      toast.error(error?.response?.data?.detail || '没能生成建议')
    } finally { setSuggesting(false) }
  }

  // 停止：中断的半段后端会落库，所以刷新后仍在，本地不需要回滚气泡
  const stop = () => {
    // 掐线和收尾都在 store 里（原来那三行 setStreaming/setWaiting/setStage
    // 是 end 的一部分，不用再写一遍）
    abortTurn()
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
  const locked = streaming || dead || engineBusy || settlingId !== null
  // 建议条分两行渲染：结构化的一行、自由文本的一行。原先后端只给字符串，
  // 现在两条路都收口成 RpgSuggestion（老存档由 normalizeSuggestions 兜住）
  const { structured, plain } = splitSuggestions(tips)
  // 这一局有没有时钟：玩家建局时定制过就看他那份，否则跟模组走（和后端的
  // slot_table 同一条规则）
  const hasClock = (sess.time_slots?.length || module?.time_slots?.length || 0) > 0
  // 该提醒玩家推时段了吗。三条路任一成立就把按钮点亮，**语义一点不变**：
  // 下一个行动就要自动翻篇 / 聊了挺久 / GM 觉得这一幕收尾了
  const slotBudget = module?.slot_budget || 0
  const chatNudge = module?.chat_nudge || 0
  const slotNudge = hasClock && (
    (slotBudget > 0 && (sess.slot_actions || 0) >= slotBudget - 1)
    || (chatNudge > 0 && (sess.slot_chats || 0) >= chatNudge)
    || !!slotHint
  )

  /** 真的把这一轮发出去。对象已经定了（`who` 可以是空串 = 这动作不需要对象）。
   *
   *  和 runAction 分开只为了一件事：远程动作要在「挑完人」之后才走到这儿，
   *  而挑人是个异步的界面动作。发送逻辑仍然只有这一份。 */
  const fireAction = (action: RpgAction, who: string, content?: string) => {
    // 选中的人只决定数值加给谁（target_npc），不决定这段戏归谁看——
    // 后者是写入时的在场快照，两件事不要互相决定
    const hint = content?.trim() || (action.prompt_hint || '').trim() || `你${action.name}`
    // 翻页这一句和用道具那边同理：远程动作在模拟器主页点得到，不翻过去
    // 玩家看不见刚生成的叙事
    if (action.target_anywhere) setView('line')
    send(who ? `${hint}（对象：${who}）` : hint, '', {
      action_id: action.id, target_npc: who, ...turnExtra(),
    })
  }

  const runAction = (action: RpgAction) => {
    if (locked) return
    // 远程动作：点了先不发，弹名单让玩家挑人。这就是「点手机里的发消息，
    // 再指定角色」那个顺序——不用先走到她所在的地方去
    if (action.needs_target && action.target_anywhere) {
      setPickFor(action)
      return
    }
    const who = action.needs_target ? target : ''
    if (action.needs_target && !who) {
      toast.error(`「${action.name}」得先选一个对象`)
      return
    }
    fireAction(action, who)
  }

  /** 背包里点「使用」。用道具是引擎动作，不是对话，落在唯一那条时间线上。
   *
   *  `exact` = 模组里有这件道具的定义（见侧栏）。没定义的**不能带 item_name**：
   *  后端会回一句「模组里没有这件道具」的黄条，而玩家拿到的东西是剧情里 GM
   *  给的，这不是他的错。不带就等于替他打出这句话，交给 GM 写 + AI 结算。 */
  const useItem = (name: string, exact: boolean, quantity = 1) => {
    if (locked) return
    setMenuOpen(false)
    // 翻页这一句要留：背包在总览页、地点页也点得到，不翻过去玩家就看不见
    // 刚生成的叙事，等于消息掉进黑洞
    setView('line')
    send(`你用了「${name}」${quantity > 1 ? ` ×${quantity}` : ''}。`, '', {
      ...(exact ? { item_name: name, item_qty: quantity } : {}), ...turnExtra(),
    })
  }

  /** 技能格里点「施展」。和用道具同一条路，`exact` 的含义也一样：
   *  模组里没定义的技能不带 skill_name，交给 GM 现写。 */
  const useSkill = (name: string, exact: boolean) => {
    if (locked) return
    setMenuOpen(false)
    setView('line')
    send(`你施展了「${name}」。`, '', {
      ...(exact ? { skill_name: name } : {}), ...turnExtra(),
    })
  }

  /** 游玩界面的「移动」：走一整轮生成，有过场叙事、有结算。
   *
   *  和总览里点【移动到这里】是两条路：那条是纯引擎瞬移（零 LLM、不产生消息），
   *  这条把 move_to 传给后端——引擎照样确定性地改地点、写大事记、跳过判定，并把
   *  fixed_location 钉死，模型只负责写「你走过去」这一段，覆盖不了地点。
   */
  const moveByTurn = (name: string) => {
    if (locked || streaming) return
    setMoveOpen(false)
    setPrivateWith(null)
    setView('line')
    send(`你前往${name}。`, '', { move_to: name, mode: 'solo' })
  }

  /** 点一条「作者定义的动作」建议。
   *
   *  **刻意不套 `actionBlocked`**：后端拼建议时已经用 `_action_gate` 筛过一遍，
   *  前端再判就是第三份规则。它与 `runAction` 唯一的差别是缺对象时**弹窗挑人**
   *  而不是报错：建议是玩家点出来的，他不知道哪个下拉框要先动。
   *  要不要挑人仍然由动作自己的 `needs_target` 说了算，**数据里不带 target**。 */
  const runSuggestedAction = (action: RpgAction, content?: string) => {
    if (locked) return
    if (action.needs_target) {
      pendingSuggestionTextRef.current = content || ''
      setPickFor(action)
      return
    }
    fireAction(action, '', content)
  }

  /** 点一条建议。逐字对齐上面那几个入口（`useItem` / `useSkill` / `moveByTurn`
   *  / `fireAction` / `send`），**那几个一行不改**。
   *
   *  清空顺序要紧：`setTips([])` 必须在 `send(...)` 之前。`send` 第一步就会
   *  清一次建议，顺序反了会把这一轮新拿到的建议一并抹掉。 */
  const runSuggestion = (tip: RpgSuggestion) => {
    setTips([])
    if (tip.kind === 'skill') return useSkill(tip.name, true)
    if (tip.kind === 'item') return useItem(tip.name, true)
    if (tip.kind === 'move') return moveByTurn(tip.name)
    if (tip.kind === 'action') {
      // 建议是模组改动之前生成的，那个动作可能已经被作者删了。
      // **必须静默 return**，绝不能把 action_id: undefined 发出去——那会变成
      // 「说了句话但什么都没发生」
      const action = actions.find(row => row.id === tip.action_id)
      if (action) runSuggestedAction(action, tip.text)
      return
    }
    // 自由文本：原样当成玩家自己打的一句话发出去。attr 照传，和加这个功能之前
    // 那条 `send(tip, attr, turnExtra())` 逐字一致
    if (locked || streaming) return
    setView('line')
    send(tip.text, attr, turnExtra())
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
      setLastOutcome({ title: `移动至 ${name}`, facts: [message || `已到达 ${name}`], changes: stateChanges(sess, next) })
      // 进不去就把那句拒绝的话原样说出来，不弹红色失败——被门槛挡住是正常反馈
      toast(message || `你来到了${name}`)
      // 只有真的走过去了才换页：被拦下来还翻到地点页，玩家会以为自己到了
      if (norm(next.location) === norm(name)) {
        playSfx('enter')
        // 落地先看有谁在这儿，比留在原地图少点一次。
        // 模拟器例外：那边换场所只是「换个地方接着安排」，翻到地点页等于把人
        // 从功能面板踢进一张地图，而主页上的按钮已经跟着新地点重算了置灰
        setFocusNpcId(null)
        if (!isSim) setView('place')
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
      // 翻篇了，GM 上一幕的收尾提议就不再成立（两个计数器由后端归零）
      setSlotHint(null)
      playSfx('turn')
      setLastOutcome({ title: '时段结算', facts, changes: stateChanges(sess, next) })
      // 跨天恢复这类结果得说清楚，否则玩家只会发现数字自己变了
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

  /** 划掉模型误改的一处外貌。同理不拍存档：划掉之后她又变回模组里写的
   *  那个样子，而模型下一轮看到的也就跟着变回去了 */
  const dropAppearance = async (npcId: number, key: string) => {
    try {
      qc.setQueryData(['rpg-session', sessionId], await rpgApi.sessions.deleteNpcAppearance(sessionId, npcId, key))
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

  /** 让某人跟着你 / 打发她走。和瞬移同类：纯引擎、零 LLM、不产生消息，
   *  所以也不拍存档。返回的 message 是给她的一句回执（「赫敏跟上了你」） */
  const setFollow = async (npcId: number, following: boolean) => {
    try {
      const res = await rpgApi.sessions.follow(sessionId, npcId, following)
      qc.setQueryData(['rpg-session', sessionId], res.session)
      if (res.message) toast.success(res.message)
    } catch {
      toast.error('没能改过来')
    }
  }

  /** 改写某一格的长期记忆。同上不拍存档：改的是模型压错的一段话，不是剧情事件。
   *  失败要让调用方知道——它得把编辑态留着，不然玩家刚写的几百字就没了 */
  const saveSummary = async (slot: string, text: string) => {
    try {
      qc.setQueryData(['rpg-session', sessionId], await rpgApi.sessions.editSummary(sessionId, slot, text))
      toast.success('记忆改好了')
    } catch (e) {
      toast.error('没能改过来')
      throw e
    }
  }

  /** 划掉 GM 给某个地方记错的那一句。同理不拍存档 */
  const dropPlaceNote = async (place: string) => {
    try {
      qc.setQueryData(['rpg-session', sessionId], await rpgApi.sessions.deletePlaceNote(sessionId, place))
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
      // 视角是消息的派生结果：消息被删回那一刻，那个人可能根本还没出现过，
      // 所以不留在一个可能已经没内容的视角上，回总览重新进
      setFocusNpcId(null)
      setMapParentId(null)
      setView(isSim ? 'home' : 'overview')
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

  const applyDiscoveries = async (ids: string[]) => {
    if (!ids.length) return
    setApplyingFound(true)
    try {
      const result = await rpgApi.sessions.applyDiscoveries(sessionId, { ids })
      qc.setQueryData(['rpg-session', sessionId], (prev?: RpgSession) => (
        prev ? { ...prev, discoveries: result.remaining } : prev
      ))
      // 建出来的是模组资产，几张表都得重拉：新角色要能出现在角色栏和地图上
      qc.invalidateQueries({ queryKey: ['rpg-npcs', moduleId] })
      qc.invalidateQueries({ queryKey: ['rpg-items', moduleId] })
      qc.invalidateQueries({ queryKey: ['rpg-skills', moduleId] })
      qc.invalidateQueries({ queryKey: ['rpg-tasks', moduleId] })
      qc.invalidateQueries({ queryKey: ['rpg-locations', moduleId] })
      // 技能和任务除了建行还写了这一局（学会 / 接下），上面那次 setQueryData
      // 只改了 discoveries 一列，会话本身要整个重拉才看得到。看 learned/opened
      // 而不是 skills/tasks：模组里早就有定义、这一次只补「这一局也拿到」的那些
      // 不会出现在后两项里，可技能栏确实多了一条
      if (result.learned.length || result.opened.length) {
        qc.invalidateQueries({ queryKey: ['rpg-session', sessionId] })
      }
      const made = result.npcs.length + result.locations.length + result.items.length
        + result.skills.length + result.tasks.length
      if (made) toast.success(`加进模组了：${made} 项`)
      // 只补进这一局、没新建定义的那些也得说一声，否则看着像什么都没发生
      const gained = [...result.learned, ...result.opened]
        .filter(name => !result.skills.some(row => row.name === name)
          && !result.tasks.some(row => row.name === name))
      if (gained.length) toast.success(`这一局也拿到了：${gained.join('、')}`)
      // 被白名单或重名拦下的必须说出来，静默丢弃等于骗作者
      result.dropped.forEach(line => toast(line))
      if (!made && !result.dropped.length) toast('没有建出任何东西')
    } catch {
      toast.error('补全失败，这些发现还留着，可以再试一次')
    } finally {
      setApplyingFound(false)
    }
  }

  const dismissDiscovery = async (id: string) => {
    try {
      const next = await rpgApi.sessions.dismissDiscovery(sessionId, id)
      qc.setQueryData(['rpg-session', sessionId], next)
    } catch {
      toast.error('操作失败')
    }
  }

  /** 认下一件新道具。它同时在模组道具表里落一条定义，所以道具表要重拉——
   *  不拉的话背包里那一条找不到定义，「使用」按钮会以为效果得交给 GM 现写 */
  const confirmItemClaim = async (id: string, consumable: boolean) => {
    try {
      const next = await rpgApi.sessions.confirmItemClaim(sessionId, id, consumable)
      qc.setQueryData(['rpg-session', sessionId], next)
      qc.invalidateQueries({ queryKey: ['rpg-items', moduleId] })
    } catch {
      toast.error('入库失败，这一条还留着，可以再试一次')
    }
  }

  const dismissItemClaim = async (id: string) => {
    try {
      const next = await rpgApi.sessions.dismissItemClaim(sessionId, id)
      qc.setQueryData(['rpg-session', sessionId], next)
    } catch {
      toast.error('操作失败')
    }
  }

  /** 玩家在确认窗里勾完了。没勾的也一并提交（accept=false），后端照样从
   *  待确认里移掉——不然同一条下一回合又弹一次 */
  const resolveTasks = async (accepts: Array<{ id: string; accept: boolean }>) => {
    setResolvingTasks(true)
    try {
      const next = await rpgApi.sessions.resolveTasks(sessionId, accepts)
      qc.setQueryData(['rpg-session', sessionId], next)
      setTaskAsk([])
    } catch {
      toast.error('更新失败')
    } finally {
      setResolvingTasks(false)
    }
  }

  const setTaskState = async (name: string, status: '' | 'open' | 'done' | 'failed') => {
    try {
      const next = await rpgApi.sessions.setTaskState(sessionId, name, status)
      qc.setQueryData(['rpg-session', sessionId], next)
    } catch {
      toast.error('操作失败')
    }
  }

  // 判定关着的时候整个下拉都不该出现，那是骰子味道的东西
  const checkable = module?.check_mode !== 'never'
    ? (module?.stat_defs || []).filter(d => d.for_check && d.name in (sess.stats || {}))
    : []

  // 点开一个人的档案。档案现在住在侧栏那一列里，所以得先把侧栏切到「角色」；
  // 窄屏还得顺手把抽屉拉开，不然从地点页点一张脸会像没反应。
  // **只在窄屏拉抽屉**：下面那份 {menu} 在 aside 和抽屉里各渲一次，宽屏把抽屉
  // 也打开就会挂出第二个 StatusSidebar，档案的提示音跟着响两声
  const openNpcDetail = (npc: RpgNpc | null) => {
    setOpenNpc(npc)
    if (!npc) return
    setTab('cast')
    if (!window.matchMedia('(min-width: 1280px)').matches) setMenuOpen(true)
  }

  // 宽屏钉在左边、窄屏收进抽屉，同一份
  const menu = (
    <StatusSidebar
      sess={sess}
      module={module}
      npcs={npcs}
      items={items}
      skills={skills}
      tab={tab}
      onTab={setTab}
      locked={locked}
      onUseItem={useItem}
      onUseSkill={useSkill}
      onSetTask={setTaskState}
      openNpc={openNpc}
      onOpenNpc={openNpcDetail}
      onApplyDiscoveries={applyDiscoveries}
      onDismissDiscovery={dismissDiscovery}
      applyingDiscoveries={applyingFound}
      onConfirmItemClaim={confirmItemClaim}
      onDismissItemClaim={dismissItemClaim}
      // 这几项是 openNpc 那个人的，会话上才有、角色卡上没有，所以在这儿取好再递进去
      notes={openNpc ? sess.npc_notes?.[String(openNpc.id)] || {} : {}}
      appearance={openNpc ? sess.npc_appearance?.[String(openNpc.id)] || {} : {}}
      activity={openNpc ? sess.npc_activities?.[String(openNpc.id)] || '' : ''}
      onDeleteNote={key => { if (openNpc) dropNote(openNpc.id, key) }}
      onDeleteAppearance={key => { if (openNpc) dropAppearance(openNpc.id, key) }}
      onDeleteActivity={() => { if (openNpc) dropActivity(openNpc.id) }}
      onSaveSummary={saveSummary}
      onSetFollow={setFollow}
      onSaveNpc={updated => {
        // openNpc 是一份快照，不刷它侧栏还显示旧文案
        setOpenNpc(updated)
        qc.invalidateQueries({ queryKey: ['rpg-npcs', moduleId] })
      }}
    />
  )

  return (
    <div className="mode-game h-screen flex flex-col bg-background relative">
      {/* z-20 而不是 z-10：页头里的下拉（模型、主题）是绝对定位的，会垂到下面
          那块内容区上。内容区也是 z-10 而且在 DOM 里更靠后，同层后来者居上，
          下拉就被右边的角色栏盖住了。页头必须比内容高一层 */}
      <header className="relative z-20 border-b border-border/50 bg-background/70 backdrop-blur-md px-6 py-3 flex items-center gap-3 shrink-0">
        <button
          // 带上来路：模组页左上角那个箭头本来只会回游戏列表，改完还得在列表里
          // 把这一局找出来再点进去。有了 from 它就直接指回这儿
          onClick={() => navigate(`/game/module/${sess.module_id}?from=${sess.id}`)}
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
          {/* 存档从侧栏搬到这儿。浮层留在组件树里用 absolute，**不能 createPortal**：
              --rpg-* 那套颜色变量定在外面的 .mode-game 上，portal 出去就取不到了 */}
          <div className="relative">
            <button
              onClick={() => setSaveOpen(open => !open)}
              title="存档 / 读档"
              className={`flex items-center gap-1 text-xs px-2.5 py-1 rounded-md border hover:bg-muted
                ${saveOpen ? 'bg-muted' : ''}`}
            >
              <History className="w-3.5 h-3.5" />存档
            </button>
            {saveOpen && (
              <>
                {/* 点空白处收起来。铺在浮层下面一层，所以浮层自己不会被它吃掉点击 */}
                <div className="fixed inset-0 z-30" onClick={() => setSaveOpen(false)} />
                <div
                  className="absolute right-0 top-full z-40 mt-1.5 w-72 max-h-[70vh] overflow-y-auto
                    rounded-xl border bg-background p-3 space-y-3 shadow-2xl"
                >
                  <SaveTab
                    saves={saves}
                    streaming={streaming}
                    onSaveNow={saveNow}
                    onRestore={restore}
                    onDropSave={dropSave}
                  />
                </div>
              </>
            )}
          </div>
          {/* 修改器。浮层的做法和存档完全一样，**同样不能 createPortal**，
              理由见上面那条注释 */}
          <div className="relative">
            <button
              onClick={() => setTweakOpen(open => !open)}
              title="手动改数值、关系、背包和处境。GM 不会知道你动过手"
              className={`flex items-center gap-1 text-xs px-2.5 py-1 rounded-md border hover:bg-muted
                ${tweakOpen ? 'bg-muted' : ''}`}
            >
              <Wrench className="w-3.5 h-3.5" />修改器
            </button>
            {tweakOpen && (
              <>
                <div className="fixed inset-0 z-30" onClick={() => setTweakOpen(false)} />
                <div
                  className="absolute right-0 top-full z-40 mt-1.5 w-80 max-h-[70vh] overflow-y-auto
                    rounded-xl border bg-background p-3 shadow-2xl"
                >
                  <TweakPanel
                    sessionId={sessionId}
                    sess={sess}
                    module={module}
                    npcs={npcs}
                    locations={locations}
                    // 这一轮还没结算完就改，改出来的数字会被这一次的结算盖回去
                    locked={streaming}
                    onApplied={next => qc.setQueryData(['rpg-session', sessionId], next)}
                  />
                </div>
              </>
            )}
          </div>
          {/* 用量那一列的开关。只在宽屏出现：那一列自己是 xl 才渲染的 */}
          <button
            onClick={toggleCost}
            title="本次行动花了多少 token"
            className={`hidden xl:flex items-center gap-1 text-xs px-2.5 py-1 rounded-md border hover:bg-muted
              ${costOpen ? 'bg-muted' : ''}`}
          >
            <Gauge className="w-3.5 h-3.5" />用量
          </button>
          {module && <PlayParams module={module} disabled={streaming} />}
          <ReadingFontButton {...readingFont} />
          <ThemePicker />
          <button
            onClick={() => setMenuOpen(true)}
            className="xl:hidden p-2 rounded-md hover:bg-muted"
            title="角色 / 道具 / 新发现"
          >
            <PanelLeftOpen className="w-4 h-4" />
          </button>
        </div>
      </header>

      {/* 回合/日期/数值这一条只在窄屏留着——宽屏它挪进了右边那一列（见下面 aside）。
          横条是从页头一直占到底的，剩下的每一行都留给剧情和输入条 */}
      <div className="xl:hidden shrink-0">
        <GameHud
          session={sess}
          module={module}
          outcome={lastOutcome}
          actionCount={actions.length}
          hasClock={hasClock}
        />
      </div>

      <div className="relative z-10 flex-1 flex min-h-0 w-full max-w-[1600px] mx-auto">
        {/* 宽度和右边框都归 StatusSidebar 自己管了——它能拖宽 */}
        <aside className="hidden xl:block shrink-0">
          {menu}
        </aside>

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

          {/* 我在哪一级、看谁的视角。总览是中枢，往上都能点回去。
              常驻不再按视图藏：右边那颗「回到对话」在顶层总览（既不是 line、
              mapParentId 又是 null）时最该出现，那恰好是从前整条都不渲染的一格 */}
          <div className="border-b border-border/50 bg-background/50 backdrop-blur-md px-6 py-1.5
            text-xs text-muted-foreground flex items-center gap-2 shrink-0">
            {/* 模拟器的第一段是主页。地图那一级仍然在（主页的「去别处」进不去
                子地图，但作者建了层级的话地点页里那张内部图还在用），只是不再
                占据面包屑的根位置 */}
            <button
              onClick={() => { setMapParentId(null); setView(isSim ? 'home' : 'overview') }}
              className="flex items-center gap-1 hover:text-foreground shrink-0"
            >
              <ArrowLeft className="w-3.5 h-3.5" />{isSim ? '主页' : '地点总览'}
            </button>
            {isSim && view === 'home' ? null : mapParentId !== null && view === 'overview' ? (
              <span className="truncate">
                {locations.find(location => location.id === mapParentId)?.name || '内部地图'}
              </span>
            ) : (
              <>
                <span className="opacity-40 shrink-0">/</span>
                <button onClick={() => setView('place')} className="hover:text-foreground truncate">
                  {sess.location || '不知身在何处'}
                </button>
              </>
            )}
            {view === 'line' && (
              <>
                <span className="opacity-40 shrink-0">/</span>
                <span className="truncate">
                  {focusNpc ? `只看 ${focusNpc.name}` : '全部'}
                </span>
                {/* 看全部。这是**筛掉别人**之后唯一的退路：一个人的视角里
                    看不到他没赶上的那些戏，点一下回到整条时间线。
                    和地点页一样是导航，不看 locked——生成中途也该能走 */}
                {focusNpc && (
                  <button
                    onClick={() => setFocusNpcId(null)}
                    className="ml-auto shrink-0 hover:text-foreground"
                  >
                    看全部
                  </button>
                )}
              </>
            )}
            {/* 翻地图翻到一半想接着聊的退路。**只切视图**，别的一个都不碰——
                这正是它和地点页那三颗（一起聊 / 独自行动 / 单独说话）的区别：
                那三颗顺手会改这一轮的对话模式和视角筛选，当返回键用会把你
                离开前的状态改掉。和上面「看全部」互斥，抢不到同一个 ml-auto */}
            {view !== 'line' && (
              <button
                onClick={() => setView('line')}
                title="回到你离开时那条时间线，视角和说话模式都不变"
                className="ml-auto shrink-0 flex items-center gap-1 hover:text-foreground"
              >
                <MessageSquare className="w-3.5 h-3.5" />回到对话
              </button>
            )}
          </div>

          {/* 上一轮的诊断。它描述的是**那一轮**，切视角不会让它变成别人的，
              所以这里不按当前视角过滤。
              system_tokens 是完整诊断才有的：后端先发一条只带 user_message_id
              的 meta，中间那几秒 triggered 还是 undefined，会抢答一句「本轮没有
              世界书词条生效」 */}
          {view === 'line' && meta && meta.system_tokens !== undefined && (
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
                  {/* 模组里定义过的道具和技能那一份说明书。它是静态的，每轮
                      一样大，所以这个数字基本不动——动了就是作者刚加了东西 */}
                  {' · '}物技 {meta.catalog_tokens ?? 0}
                  {' · '}角色 {meta.npc_tokens ?? 0}
                  {/* 全模组角色的花名册，一人一行。角色块是其中几个人的详细卡，
                      所以这一块基本不动、那一块每轮变。私聊时不注入，那一轮是 0 */}
                  {' · '}名册 {meta.roster_tokens ?? 0}
                  {' · '}外场 {meta.chronicle_tokens ?? 0}
                  {/* 关系里程碑。不按在场筛、只增不减，所以这个数字会一路涨——
                      涨得不对劲就是结算在乱记转折 */}
                  {' · '}转折 {meta.milestone_tokens ?? 0}
                  {/* 地点描述和在场名单那一块。每轮都在，大小只跟作者写的
                      地点描述有多长有关 */}
                  {' · '}场面 {meta.scene_tokens ?? 0}
                  {' · '}历史 {meta.history_count} 条
                  {meta.slot && ` · 第 ${meta.day} 天 ${meta.slot}`}
                  {meta.npcs_here && meta.npcs_here.length > 0
                    && ` · 在场 ${meta.npcs_here.map(n => n.name).join('、')}`}
                  {/* 只是被提到、人不在跟前的那几个。原先这两拨人合在一起叫
                      「在场」，而结算那边「在场」只认地点相同，于是同一轮里
                      诊断行说她在场、结算的提示又说她不在场 */}
                  {mentionedOnly(meta).length > 0
                    && ` · 提到 ${mentionedOnly(meta).join('、')}`}
                </span>
              )}
            </div>
          )}

          <div className="flex-1 overflow-y-auto px-6 py-6">
            {/* 地图要比正文宽一点，不然节点挤在一起。
                正文从 3xl 放到 4xl：右边三列并成一列后腾出四百来像素，中文全角
                字在 768px 下一行才四十来个字，太短了。输入条那处要跟着一起动，
                不然气泡和输入框对不齐 */}
            <div className={`${view === 'overview' || view === 'home' ? 'max-w-5xl' : 'max-w-4xl'} mx-auto space-y-4`}>
              {view === 'home' && (
              <SimHome
                module={module}
                  sess={sess}
                  actions={actions}
                  locations={locations}
                  hereNpcs={hereNpcs}
                  npcs={npcs}
                  locked={locked}
                  busy={engineBusy}
                  // 翻到时间线这一句和 useItem 里那句同理：不翻过去，刚生成的
                  // 那段叙事玩家一个字都看不见，等于消息掉进黑洞。看完点面包屑
                  // 的「主页」回来接着安排
                  onRunAction={action => { setView('line'); runAction(action) }}
                  onGo={go}
                  // 和地点页那颗「单独说话」逐条相同：时间线筛到她、模式切私聊
                  onTalk={npc => {
                    setFocusNpcId(npc.id)
                    setTurnMode('private')
                    setPrivateWith(npc.id)
                    setView('line')
                  }}
                  onOpenLine={() => setView('line')}
                  target={target}
                  onTarget={setTarget}
                  tips={tips}
                  suggesting={suggesting}
                  onSuggest={suggest}
                  // 和上面 onRunAction 逐字同理：不翻到时间线，刚生成的那段叙事
                  // 玩家一个字都看不见
                  onSuggestion={tip => { setView('line'); runSuggestion(tip) }}
                />
              )}

              {view === 'overview' && (
                <LocationOverview
                  sess={sess}
                  locations={locations}
                  npcs={npcs}
                  parentId={mapParentId}
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
                  locked={locked}
                  busy={engineBusy}
                  onGo={go}
                  // 点「单独说话」是两件事一起做：时间线筛到她，模式切成私聊。
                  // 两件事分开存（focusNpcId / turnMode），这里只是同时设一次
                  onTalk={npc => {
                    setFocusNpcId(npc.id)
                    setTurnMode('private')
                    setPrivateWith(npc.id)
                    setView('line')
                  }}
                  onDetail={openNpcDetail}
                  onDropPlaceNote={dropPlaceNote}
                  // 一起聊 / 独自行动：都是「不冲着某一个人」，所以时间线一律
                  // 回到全部，只有模式不同
                  onScene={mode => {
                    setFocusNpcId(null)
                    setTurnMode(mode)
                    setPrivateWith(null)
                    setView('line')
                  }}
                />
              )}

              {view === 'line' && (
                <>
                  {lineBubbles.length === 0 && (
                    <p className="text-center text-sm text-muted-foreground py-20">
                      {focusNpc
                        ? `${focusNpc.name}还没和你照过面。写下你要做的事，或者回地点总览找他。`
                        : '还是空的。写下你要做的事，或者回地点总览看看有谁在。'}
                    </p>
                  )}
                  {lineBubbles.map((b, i) => {
                    const last = i === lineBubbles.length - 1
                    const mine = editing !== null && editing.id === b.id
                    // 还在流的那两条不给动：id 还没回来，也没人知道后端最后
                    // 会落成什么样
                    const editable = b.id !== null && !streaming && settlingId === null
                    // 这一段谁在跟前听着 = 它会进谁的记忆。只在**换人**的时候
                    // 标一行，跟地点分隔一个道理；每条都标就成了噪音。
                    // 还在流的那两条 present 是 null（等后端快照），什么都不标
                    const roster = rosterLabel(b.present, npcs)
                    const shown = roster && roster !== rosterLabel(lineBubbles[i - 1]?.present ?? null, npcs)
                    return (
                    <div key={b.id ?? `pending-${i}`} className="space-y-2 group">
                      {/* 换地方的分隔。统一时间线之后一屏里会混着几个地方的戏，
                          不标就分不清哪句是在哪儿说的。只在**真的换了**的时候画：
                          同一条消息在别人的视角里会不会露头不影响这个判断 */}
                      {b.location && b.location !== lineBubbles[i - 1]?.location && (
                        <div className="flex items-center gap-3 pt-2">
                          <div className="h-px flex-1 bg-border/60" />
                          <span className="text-[11px] text-muted-foreground flex items-center gap-1 shrink-0">
                            <MapPin className="w-3 h-3" />{b.location}
                          </span>
                          <div className="h-px flex-1 bg-border/60" />
                        </div>
                      )}
                      {shown && (
                        <p className="text-[11px] text-muted-foreground flex items-center gap-1 pt-1">
                          <Users className="w-3 h-3 shrink-0" />{roster}
                        </p>
                      )}
                      {b.role === 'user' ? (
                        <>
                          <div className="flex gap-2.5 justify-end items-start">
                            {editable && !mine && (
                              <div className="flex items-center gap-0.5 mt-1 shrink-0 opacity-0
                                group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
                                <button
                                  onClick={() => setEditing({ id: b.id!, role: b.role, text: b.content })}
                                  title="改这句话"
                                  className="p-1.5 rounded-lg text-muted-foreground hover:bg-muted"
                                >
                                  <Pencil className="w-3.5 h-3.5" />
                                </button>
                                <button
                                  onClick={() => resendFrom(b.id!, b.content)}
                                  title="从这句重来：它之后的剧情和数值一起回滚"
                                  className="p-1.5 rounded-lg text-muted-foreground hover:bg-muted"
                                >
                                  <RotateCcw className="w-3.5 h-3.5" />
                                </button>
                              </div>
                            )}
                            {mine ? (
                              <div className="flex-1 max-w-[80%] space-y-1.5">
                                <AutoTextarea
                                  value={editing!.text}
                                  onChange={e => setEditing({ ...editing!, text: e.target.value })}
                                  minRows={2}
                                  className="w-full text-sm border rounded-xl px-3 py-2 bg-background/60
                                    focus:outline-none focus:ring-1 focus:ring-primary/50"
                                />
                                <div className="flex justify-end gap-1.5">
                                  <button onClick={() => setEditing(null)} className={EDIT_BTN}>取消</button>
                                  {/* 只改字：后面那些剧情是照着旧话写的，改完会对不上，
                                      所以这条按钮只适合改错别字 */}
                                  <button onClick={saveEdit} className={EDIT_BTN} title="只改这句话，后面的剧情原样留着">
                                    只改字
                                  </button>
                                  <button
                                    onClick={() => resendFrom(b.id!, editing!.text)}
                                    className="text-xs px-2.5 py-1 rounded-lg bg-primary text-primary-foreground hover:opacity-90"
                                    title="改完从这里重跑：它之后的剧情和数值一起回滚"
                                  >
                                    改完重发
                                  </button>
                                </div>
                              </div>
                            ) : (
                              // 玩家这侧也跟着调，不然一页里两种字号
                              <div
                                className="max-w-[80%] rounded-2xl rounded-tr-sm px-4 py-2.5 text-sm leading-relaxed
                                  whitespace-pre-wrap bg-primary text-primary-foreground"
                                style={readingStyle}
                              >
                                {b.content}
                              </div>
                            )}
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
                      ) : mine ? (
                        <div className="space-y-1.5">
                          <AutoTextarea
                            value={editing!.text}
                            onChange={e => setEditing({ ...editing!, text: e.target.value })}
                            minRows={4}
                            className="w-full text-sm leading-[1.9] border rounded-2xl px-4 py-3 bg-background/60
                              focus:outline-none focus:ring-1 focus:ring-primary/50"
                          />
                          <div className="flex justify-end gap-1.5">
                            <button onClick={() => setEditing(null)} className={EDIT_BTN}>取消</button>
                            <button
                              onClick={saveEdit}
                              className="text-xs px-2.5 py-1 rounded-lg bg-primary text-primary-foreground hover:opacity-90"
                            >
                              保存并标记待结算
                            </button>
                          </div>
                        </div>
                      ) : (
                        // 排版直接借小说阅读区那一套（.novel-content：宋体/Georgia 衬线 +
                        // 行高 2 + 字距），字号也从 text-sm 提到 text-base（全局基准 1rem）。
                        // 剧情是这个页面真正要看的东西，用比正文更小的字没道理
                        <div
                          className="novel-content relative rounded-2xl border border-primary/15 bg-card/80 backdrop-blur-sm
                            px-5 py-4 text-base whitespace-pre-wrap"
                          style={readingStyle}
                        >
                          {waiting && streamingHere && last
                            ? <ThinkingDots /> : b.content}
                          {streamingHere && !waiting && last && (
                            <span className="inline-block w-0.5 h-4 bg-current ml-0.5 animate-pulse align-middle" />
                          )}
                          {editable && (
                            <div className="absolute top-1.5 right-2 flex items-center gap-0.5 opacity-0
                              group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
                              <button
                                onClick={() => setEditing({ id: b.id!, role: b.role, text: b.content })}
                                title="改这段叙事。GM 写歪了自己动手，比再抽一次快"
                                className="p-1.5 rounded-lg bg-card/80 text-muted-foreground hover:bg-muted"
                              >
                                <Pencil className="w-3.5 h-3.5" />
                              </button>
                              {/* 只有最后一段能重抽：中间那一段重抽等于把后面
                                  全推翻，要那个效果请用它上面那句话的「重发」 */}
                              {last && !dead && (
                                <button
                                  onClick={regenerate}
                                  title="重新生成这一段（数值会回到这一轮之前）"
                                  className="p-1.5 rounded-lg bg-card/80 text-muted-foreground hover:bg-muted"
                                >
                                  <RotateCcw className="w-3.5 h-3.5" />
                                </button>
                              )}
                            </div>
                          )}
                        </div>
                      )}
                      {b.role === 'assistant' && b.id !== null && b.settlement && (
                        <SettlementReport
                          report={b.settlement}
                          latest={b.id === bubbles[bubbles.length - 1]?.id}
                          busy={settlingId === b.id}
                          disabled={streaming || engineBusy || settlingId !== null}
                          npcs={npcs}
                          onRetry={() => resettle(b.id!)}
                        />
                      )}
                    </div>
                    )
                  })}
                  <div ref={bottomRef} />
                </>
              )}
            </div>
          </div>

          {view === 'line' && (
            <div className="border-t border-border/50 bg-background/70 backdrop-blur-md px-6 py-3 shrink-0">
              <div className="max-w-4xl mx-auto space-y-2">
                {/* 「结束这个时段」跟输入框待在一起：它和「发一句话」一样是玩家
                    主动推进这一局的动作，摆在页头反而像个设置项。只此一处，
                    页头和 GameHud 上那两个重复的已经撤了 */}
                {hasClock && (
                  <div className="flex justify-end">
                    <button
                      onClick={advance}
                      disabled={locked || engineBusy}
                      title={[
                        module?.offscreen_brief
                          ? '推进到下一个时段。这一下不生成剧情，但会调一次便宜模型写一句「别处」的大事记'
                          : '推进到下一个时段。这一下不生成剧情，模型也不会参与',
                        // 规则**一直**写在这儿，不是等触发了才说。玩家问过
                        // 「聊多少才会跳时段」——答案是永远不会，那就得让他
                        // 不用猜也能看到。0 的那一档干脆不提，免得净是噪音
                        slotBudget > 0
                          ? `已用 ${Math.min(sess.slot_actions || 0, slotBudget)}/${slotBudget} 格行动（点动作、用道具、放技能、移动各算一格），用满自动翻篇`
                          : '这个模组没设行动上限，时段只能自己按',
                        chatNudge > 0
                          ? `已聊 ${sess.slot_chats || 0}/${chatNudge} 条。**聊天不会推时间**，只是到了就提醒一下`
                          : null,
                        // 亮着的话说清楚是为什么亮的，别让玩家猜
                        slotHint,
                      ].filter(Boolean).join('\n')}
                      className={`flex items-center gap-1 text-xs px-2.5 py-1 rounded-md border
                        hover:bg-muted disabled:opacity-40 disabled:cursor-not-allowed ${
                        // 角标是唯一的出场方式：不弹窗、不禁用输入框、不改任何语义
                        slotNudge
                          ? 'bg-amber-500/15 text-amber-700 dark:text-amber-300 ring-1 ring-amber-500/40 border-transparent'
                          : ''}`}
                    >
                      <SkipForward className="w-3.5 h-3.5" />结束这个时段
                      {/* 光换配色太不显眼，会被整段剧情盖过去。跳的是这个感叹号
                          而不是整颗按钮：animate-bounce 把元素上下挪 ±25%，挪
                          按钮的话点击目标就一直在移动，想点得追着它。
                          aria-hidden：纯视觉强调，为什么亮 title 里已经写全了 */}
                      {slotNudge && (
                        <AlertTriangle className="w-3.5 h-3.5 animate-bounce" aria-hidden />
                      )}
                    </button>
                  </div>
                )}

                {/* 等待/结算提示钉在输入框上面。它原先跟在消息列表末尾，可玩家
                    往回翻两屏就再也看不见它了，「按了发送什么反应都没有」多半
                    就是这么来的。waiting 管出字前，stage 管出字后的静默结算 */}
                <RpgTurnStatus
                  stage={stage}
                  visible={streamingHere && (waiting || stage !== '')}
                />

                {/* 上一轮的错误。不点不消失——一闪而过的 toast 让人以为是自己
                    手滑没发出去 */}
                {lastError && (
                  <div className="flex items-start gap-2 rounded-xl px-3 py-2 text-xs
                    bg-rose-500/10 ring-1 ring-rose-500/30 text-rose-700 dark:text-rose-300">
                    <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                    <span className="flex-1 break-all leading-relaxed">{lastError}</span>
                    <button
                      onClick={retry}
                      disabled={locked}
                      className="shrink-0 px-2 py-0.5 rounded-lg ring-1 ring-rose-500/40
                        hover:bg-rose-500/15 disabled:opacity-40"
                    >
                      重试
                    </button>
                    <button
                      onClick={() => setLastError(null)}
                      title="知道了"
                      className="shrink-0 p-0.5 rounded hover:bg-rose-500/15"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                )}

                {tips.length > 0 && !streaming && (
                  <div className="space-y-1.5">
                    {/* 结构化那一行：点下去直接走引擎。样式比自由文本重一档，
                        让它一眼看出「这个和随手说一句不是一回事」 */}
                    {structured.length > 0 && (
                      <div className="flex flex-wrap gap-1.5">
                        {structured.map((tip, i) => {
                          const Icon = kindMeta(tip.kind).icon
                          // 动作的 name 是空的（后端只给 action_id），名字从模组
                          // 动作表里查。已经被删掉时查不到，只显示「动作」两个字
                          const actionName = actions.find(a => a.id === tip.action_id)?.name || ''
                          return (
                            <button
                              key={i}
                              onClick={() => runSuggestion(tip)}
                              disabled={locked}
                              title={tip.text}
                              className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full
                                bg-primary/15 text-primary ring-1 ring-primary/40
                                hover:bg-primary/25 disabled:opacity-40"
                            >
                              <Icon className="w-3 h-3 shrink-0" />
                              <span className="opacity-60">{suggestionLabel(tip, actionName)}</span>
                              <span>{tip.text}</span>
                            </button>
                          )
                        })}
                      </div>
                    )}
                    {/* 自由文本那一行：保持原来的淡样式，点一下等于替他打出这句话 */}
                    {plain.length > 0 && (
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="text-[11px] text-muted-foreground shrink-0">或者说一句</span>
                        {plain.map((tip, i) => (
                          <button
                            key={i}
                            onClick={() => runSuggestion(tip)}
                            disabled={dead}
                            className="text-xs px-2.5 py-1 rounded-full bg-primary/10 text-primary ring-1 ring-primary/30
                              hover:bg-primary/20 disabled:opacity-40"
                          >
                            {tip.text}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {actions.length > 0 && (
                  <div className="rounded-xl border border-primary/20 bg-primary/[0.04] p-2.5 space-y-2">
                    <div className="flex items-center gap-2 text-[11px] font-medium text-primary">
                      <Dices className="w-3.5 h-3.5" />快捷行动
                      <span className="font-normal text-muted-foreground">不影响自由输入</span>
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5">
                    {actions.map(action => {
                      const blocked = actionBlocked(action, sess, npcs, action.target_anywhere ? '' : target, module)
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
                          <span className="ml-1 text-[10px] opacity-75">{actionTimeHint(action, sess, module)}</span>
                        </button>
                      )
                    })}
                    {/* 只列此刻在场的人。用「见过面的」那份名单的话，从 A 地
                        走到 B 地之后 npcA 还挂在这里，好感就加到一个不在跟前的人身上 */}
                    {/* 只为「必须人在跟前」那些动作而存在。远程动作自己弹名单，
                        不看这个下拉——两者都算进来的话，一个只有手机功能的模组
                        会白挂一个永远没用的选择器 */}
                    {actions.some(a => a.needs_target && !a.target_anywhere) && hereNpcs.length > 0 && (
                      <select
                        value={target}
                        onChange={e => setTarget(e.target.value)}
                        title="动作作用在谁身上（好感加给他）。只决定数值加给谁，不会把你切到别的地方去"
                        className="text-xs border rounded-lg px-2 py-1 bg-background/60 focus:outline-none"
                      >
                        <option value="">对谁…</option>
                        {hereNpcs.map(n => <option key={n.id} value={n.name}>{n.name}</option>)}
                      </select>
                    )}
                    </div>
                  </div>
                )}

                {/* 带剧情的移动。和地图上那个【移动到这里】是两条路：那边是
                    瞬移（零模型调用、不产生剧情），这边会生成一段过场并结算 */}
                {moveTargets.length > 0 && (
                  <div ref={moveBox} className="relative">
                    <button
                      onClick={() => setMoveOpen(v => !v)}
                      disabled={locked}
                      title="走过去，并生成一段路上的剧情。只想看看哪儿有谁就用上面的地点总览"
                      className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-lg
                        bg-primary/10 text-primary ring-1 ring-primary/30 hover:bg-primary/20
                        disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      <Footprints className="w-3.5 h-3.5" />移动
                    </button>
                    {moveOpen && (
                      // 不能用 createPortal：--rpg-* 那套颜色变量定在外面 .mode-game
                      // 那个 div 上，挂到 body 下面颜色会全丢（照 PlayParams 的写法）
                      <div className="absolute bottom-full left-0 z-30 mb-1 w-60 max-h-64 overflow-y-auto
                        rounded-xl border border-border/60 bg-card shadow-lg p-1.5 space-y-0.5">
                        <p className="px-2 py-1 text-[11px] text-muted-foreground">
                          走过去，会生成一段过场
                        </p>
                        {moveTargets.map(({ loc, why, people }) => (
                          <button
                            key={loc.id}
                            onClick={() => moveByTurn(loc.name)}
                            disabled={!!why}
                            title={why || `前往${loc.name}`}
                            className="flex w-full items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs
                              text-left hover:bg-muted disabled:opacity-40 disabled:cursor-not-allowed"
                          >
                            <MapPin className="w-3 h-3 shrink-0" />
                            <span className="flex-1 truncate">{loc.name}</span>
                            <span className="shrink-0 text-[11px] text-muted-foreground">
                              {why || (people > 0 ? `${people} 人` : '')}
                            </span>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* 这一句话说给谁听。决定的是**记进谁的记忆**，不是界面筛什么——
                    从前这两件事绑在一个 focus_npc_id 上，玩家点的是筛选器，
                    代码拿它当记忆开关，于是一对一聊十轮之后她会说初见的台词 */}
                <div className="flex flex-wrap items-center gap-1.5 text-xs">
                  {MODES.map(m => {
                    const on = effectiveMode === m.key
                    // 屋里没人的时候只剩独自行动：群聊没人可聊，私聊也挑不出人
                    const off = m.key !== 'solo' && hereNpcs.length === 0
                    return (
                      <button
                        key={m.key}
                        onClick={() => {
                          setTurnMode(m.key)
                          if (m.key === 'private' && !hereNpcs.some(n => n.id === privateWith)) {
                            // 默认挑正在看的那个人，没在看就挑屋里第一个
                            const pick = hereNpcs.find(n => n.id === focusNpcId) || hereNpcs[0]
                            setPrivateWith(pick ? pick.id : null)
                          }
                        }}
                        disabled={off || dead}
                        title={off ? '这里没有别人' : m.hint}
                        className={`px-2.5 py-1 rounded-lg ring-1 disabled:opacity-40
                          disabled:cursor-not-allowed ${on
                            ? 'bg-primary text-primary-foreground ring-primary'
                            : 'bg-primary/10 text-primary ring-primary/30 hover:bg-primary/20'}`}
                      >
                        {m.label}
                      </button>
                    )
                  })}
                  {effectiveMode === 'private' && (
                    <select
                      value={privateWith ?? ''}
                      onChange={e => setPrivateWith(Number(e.target.value) || null)}
                      disabled={dead}
                      title="跟谁单独说。只能挑此刻就在你跟前的人"
                      className="border rounded-lg px-2 py-1 bg-background/60 focus:outline-none disabled:opacity-50"
                    >
                      {hereNpcs.map(n => <option key={n.id} value={n.id}>{n.name}</option>)}
                    </select>
                  )}
                  <span className="text-muted-foreground leading-relaxed">
                    {MODES.find(m => m.key === effectiveMode)?.hint}
                  </span>
                </div>

                <div className="relative flex gap-2 items-end">
                  {/* 候选列表往上弹，靠这一行的 relative 定位 */}
                  <EntityAutocompleteList items={ac.items} index={ac.index} onPick={ac.insert} />
                  <AutoTextarea
                    ref={inputRef}
                    value={input}
                    onChange={e => { setInput(e.target.value); ac.onInput(e) }}
                    onKeyDown={handleKeyDown}
                    {...ac.handlers}
                    placeholder={dead ? '这一局已经结束了。'
                      : effectiveMode === 'private' && privateNpc
                        ? `单独对 ${privateNpc.name} 说…（Enter 发送，Shift+Enter 换行）`
                        : effectiveMode === 'solo'
                          ? '你要做点什么…（Enter 发送，Shift+Enter 换行）'
                          : '说点什么，或者做点什么'}
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
                    title="帮我想想：照你身上的状态和眼前的人和地方，给几条接下来能做的事。能对上的那条点一下直接执行"
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

        {/* 右边这一列：回合日期数值、你正盯着的那个人、本次用量，三块竖着叠。
            原先这三样各开一个 aside（240 + 208 + 200），宽屏上光这三条边就吃掉
            648px，正文在 1600 的容器里只剩六百出头——「左右空着中间反而挤」就是
            这么来的。并成一列，正文把那四百多像素拿回去。
            立绘和用量仍然只在对话里挂：地点总览和地点页是满幅布局。
            窄屏放不下三列，退回页头下面那条横幅 */}
        <aside className="hidden xl:flex shrink-0 w-[260px] flex-col overflow-y-auto
          border-l border-border/60">
          <GameHud
            session={sess}
            module={module}
            outcome={lastOutcome}
            actionCount={actions.length}
            hasClock={hasClock}
            layout="column"
          />

          {/* 你正盯着的那个人。只在对话里挂：地点总览和地点页那两个视角里
              没有「正在对谁说话」这回事。组件自己判断没立绘就不渲染 */}
          {view === 'line' && portraitNpc && (
            <FocusPortrait
              npc={portraitNpc}
              relationDefs={module?.relation_stat_defs || []}
              npcStates={sess.npc_states || {}}
              place={npcPlace(
                portraitNpc, sess.slot, sess.npc_places, sess.npc_followers, sess.location,
              )}
              here={onstage(portraitNpc, sess)}
            />
          )}

          {/* 本次行动的 token 用量。同立绘，只在对话里挂：走地图不发模型，
              那两个视角下这块永远是空的 */}
          {view === 'line' && costOpen && (
            <TurnCostPanel
              entries={costEntries}
              totalIn={costTotal.input}
              totalOut={costTotal.output}
              onClose={toggleCost}
            />
          )}
        </aside>
      </div>

      {menuOpen && (
        <div className="fixed inset-0 z-40 xl:hidden" onClick={() => setMenuOpen(false)}>
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
          <div
            className="absolute inset-y-0 left-0 w-[min(20rem,85vw)] bg-background border-r shadow-2xl flex flex-col"
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

      {taskAsk.length > 0 && (
        <TaskResolutionsModal
          proposals={taskAsk}
          saving={resolvingTasks}
          onConfirm={resolveTasks}
          // 「先放着」：这一轮不问了，但提议还挂在会话上，任务格里还看得见
          onClose={() => setTaskAsk([])}
        />
      )}

      {/* 远程动作点完之后挑人。留在组件树里、不 createPortal：--rpg-* 那套
          颜色变量定在外面的 .mode-game 上，portal 出去颜色全丢 */}
      {pickFor && (
        <div
          className="absolute inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
          onClick={() => setPickFor(null)}
        >
          <div
            className="w-full max-w-md max-h-[80vh] overflow-y-auto rounded-2xl border border-primary/25 bg-card shadow-2xl p-4 space-y-3"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <p className="text-sm font-medium truncate">{pickFor.name}</p>
                <p className="text-xs text-muted-foreground">
                  找谁？
                  {pickFor.summons_target
                    ? '选中的人会赶到你这儿来。'
                    : '不用走过去，人在哪儿都能找。'}
                </p>
              </div>
              <button
                onClick={() => setPickFor(null)}
                className="p-1 rounded hover:bg-muted shrink-0"
                title="算了"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            {targetChoices(pickFor, npcs, sess, hereNpcs, module).length === 0 ? (
              <p className="text-xs text-muted-foreground py-6 text-center">
                你还没认识任何人。先去见几个人再用这个。
              </p>
            ) : (
              <div className="space-y-1">
                {targetChoices(pickFor, npcs, sess, hereNpcs, module).map(npc => {
                  const place = npcPlace(
                    npc, sess.slot, sess.npc_places, sess.npc_followers, sess.location,
                  )
                  const here = onstage(npc, sess)
                  const blocked = actionBlocked(pickFor, sess, npcs, npc.name, module)
                  return (
                    <button
                      key={npc.id}
                      disabled={locked || !!blocked}
                      title={blocked}
                      onClick={() => {
                        const action = pickFor
                        setPickFor(null)
                        // 同步 target：侧栏和底部那个下拉显示的是同一份状态，
                        // 不跟上的话玩家刚挑的人在界面上没有任何痕迹
                        setTarget(npc.name)
                        fireAction(action, npc.name, pendingSuggestionTextRef.current)
                        pendingSuggestionTextRef.current = ''
                      }}
                      className="w-full flex items-center gap-2.5 rounded-xl border px-2.5 py-2
                        hover:bg-muted text-left transition-colors"
                    >
                      <RpgAvatar name={npc.name} url={npc.avatar_url} size="sm" />
                      <span className="text-sm min-w-0 flex-1 truncate">{npc.name}</span>
                      <span className="text-[11px] text-muted-foreground shrink-0">
                        {following(npc, sess) ? '跟着你' : here ? '就在跟前' : place || '行踪不明'}
                      </span>
                    </button>
                  )
                })}
              </div>
            )}
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
 * 定在 .mode-game 这个 div 上，portal 到 body 的东西取不到，会变成一块裸色。
 */
function PlayParams({ module, disabled }: { module: RpgModule; disabled: boolean }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const { data: models = [] } = useQuery({ queryKey: ['model-library'], queryFn: modelLibraryApi.list })
  // 按供应商分组，和小说那边的模型下拉一样。同一个模型名在两家都有的时候，
  // 不写供应商就是两条一模一样的选项
  const groups = groupModelsByProvider(models)

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

  const change = async (
    key: RpgModelField | 'temperature',
    value: string | number,
  ) => {
    try {
      await rpgApi.modules.update(module.id, { [key]: value } as Partial<RpgModule>)
      qc.invalidateQueries({ queryKey: ['rpg-module', module.id] })
    } catch {
      toast.error('改这一局的设置失败')
    }
  }

  // 温度走本地态 + 失焦提交：直接绑 module.temperature 的话每敲一个字符发一次 PATCH。
  // 负温度 = 整个参数不发给供应商，同模组编辑页那个框的约定
  const tempOff = module.temperature < 0
  const [temp, setTemp] = useState(module.temperature)
  useEffect(() => { setTemp(module.temperature) }, [module.temperature])

  // 按钮上直接写叙事模型的名字，照小说那边的做法——从前只有「模型/温度」四个字，
  // 想知道这一局在用哪个模型得先把下拉点开。
  // 解析必须走 modelSelectValue（和下面那个 select 同一个），否则会出现
  // 「按钮显示 A、点开下拉选中的是 B」
  const narratorId = modelSelectValue(models, module.model_ref)
  const narrator = models.find(m => String(m.id) === narratorId)
  const narratorName = narrator ? narrator.display_name || narrator.model_id : '跟随默认'

  const row = (
    label: string,
    key: RpgModelField,
    empty: string,
    hint: string,
  ) => (
    <div key={key}>
      <label className="text-xs font-medium mb-1 block">{label}</label>
      <select
        value={modelSelectValue(models, module[key])}
        onChange={e => change(key, e.target.value)}
        className="w-full border rounded-lg px-2.5 py-1.5 text-xs bg-background/60"
      >
        <option value="">{empty}</option>
        {groups.map(g => (
          <optgroup key={g.provider} label={g.provider}>
            {g.items.map(m => (
              <option key={m.id} value={String(m.id)}>{m.display_name || m.model_id}</option>
            ))}
          </optgroup>
        ))}
      </select>
      <p className="text-[11px] text-muted-foreground mt-1">{hint}</p>
    </div>
  )

  return (
    <div ref={box} className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        disabled={disabled}
        title={`叙事模型：${narratorName}。点开可换模型和温度——改的是这个模组，同一模组的其他存档也跟着变`}
        className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-md border
          hover:bg-muted disabled:opacity-40 disabled:cursor-not-allowed"
      >
        <Cpu className="w-3.5 h-3.5" />
        {/* 长模型名会把页头撑开，truncate 住 */}
        <span className="hidden sm:inline truncate max-w-[10rem]">{narratorName}</span>
      </button>

      {open && (
        // 底色不用 PANEL 的 bg-card/70 而是实心 bg-card：半透明的话下面的聊天
        // 文字会透上来，几个下拉根本看不清。其余（rpg-panel 的那圈起伏、圆角、
        // 边框）和别处一致
        <div className="rpg-panel absolute right-0 top-full mt-2 z-50 w-72 max-h-[70vh] overflow-y-auto p-3 space-y-3
          rounded-xl border bg-card shadow-xl"
        >
          {GAMEPLAY_MODEL_FIELDS.map(({ label, key, empty, hint }) => row(label, key, empty, hint))}
          <details className="border-t pt-2">
            <summary className="text-xs text-muted-foreground cursor-pointer">默认与立绘模型</summary>
            <div className="space-y-3 pt-2">
              {EXTRA_MODEL_FIELDS.map(({ label, key, empty, hint }) => row(label, key, empty, hint))}
            </div>
          </details>
          <div>
            <label className="text-xs font-medium mb-1 block">温度</label>
            <input
              type="number" min={0} max={2} step={0.05}
              value={tempOff ? '' : temp}
              disabled={tempOff}
              onChange={e => setTemp(Number(e.target.value))}
              onBlur={() => { if (!tempOff && temp !== module.temperature) change('temperature', temp) }}
              className="w-full border rounded-lg px-2.5 py-1.5 text-xs bg-background/60 disabled:opacity-40"
            />
            <label className="flex items-center gap-1.5 mt-1 cursor-pointer">
              <input
                type="checkbox"
                checked={tempOff}
                onChange={e => change('temperature', e.target.checked ? -1 : 0.9)}
                className="accent-[hsl(var(--primary))]"
              />
              <span className="text-[11px] text-muted-foreground">不传</span>
            </label>
            <p className="text-[11px] text-muted-foreground mt-1">
              只管旁白那次调用，高了更放得开。下一次发送/执行动作就生效。
            </p>
          </div>
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
