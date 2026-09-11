import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  ArrowLeft, BookMarked, Dices, Loader2, MapPin, PanelRightOpen, Send, Square, User, X,
} from 'lucide-react'
import {
  rpgApi, streamRpgTurn,
  type RpgAction, type RpgMessage, type RpgRoll, type RpgSave,
  type RpgSession, type RpgSSEMessage, type RpgTurnMeta,
} from '@/api/client'
import { confirmDialog } from '@/components/ConfirmDialog/ConfirmDialog'
import AutoTextarea from '@/components/AutoTextarea'
import ThemePicker from '@/components/ThemePicker/ThemePicker'
import Silk from '@/components/Silk/Silk'
import { checkCondition, knownNpcs } from './condition'
import DiceRoll from './DiceRoll'
import StatePanel from './StatePanel'
import StatusSidebar, { type SidebarTab } from './StatusSidebar'

/** 界面上的一条消息。id 为 null 表示流式过程中还没落库的占位气泡 */
interface Bubble {
  id: number | null
  role: string
  content: string
  roll: RpgRoll | null
  /** 这一轮刚掷出来的才让骰子动，翻历史不该每条都再抖一遍 */
  fresh: boolean
}

const toBubble = (m: RpgMessage): Bubble => ({
  id: m.id, role: m.role, content: m.content, roll: m.roll, fresh: false,
})

/** 「点出来的」那一轮额外带的东西。三个都空就是自由打字 */
interface TurnExtra {
  action_id?: number | null
  item_name?: string
  move_to?: string
  target_npc?: string
}

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
  const [target, setTarget] = useState('')
  const [tab, setTab] = useState<SidebarTab>('status')
  // 侧栏在宽屏常驻，窄屏收成抽屉
  const [menuOpen, setMenuOpen] = useState(false)

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
  // 消息以后端为准：只在进页面时拉一次，之后本地追加
  const { data: loaded } = useQuery({
    queryKey: ['rpg-messages', sessionId],
    queryFn: () => rpgApi.messages.list(sessionId),
    enabled: Number.isFinite(sessionId) && sessionId > 0,
  })

  useEffect(() => { if (loaded) setBubbles(loaded.map(toBubble)) }, [loaded])

  useEffect(() => () => { abortRef.current?.abort() }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [bubbles])

  // 只有见过面或此刻在场的人能当动作对象：对一个还没登场的人「夸奖」
  // 等于把他抖出来
  const metNpcs = useMemo(
    () => (sess ? knownNpcs(npcs, sess) : []),
    [npcs, sess],
  )

  useEffect(() => {
    if (target && !metNpcs.some(n => n.name === target)) setTarget('')
    else if (!target && metNpcs.length === 1) setTarget(metNpcs[0].name)
  }, [metNpcs, target])

  const send = useCallback((text: string, useAttr: string, extra: TurnExtra = {}) => {
    setBubbles(prev => [...prev, { id: null, role: 'user', content: text, roll: null, fresh: true }])
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
      setBubbles(prev => [...prev, { id: null, role: 'assistant', content: '', roll: null, fresh: true }])
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
      { content: text, attr: useAttr, ...extra },
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
  }, [sessionId, qc])

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

  const runAction = (action: RpgAction) => {
    if (locked) return
    const who = action.needs_target ? target : ''
    if (action.needs_target && !who) {
      toast.error(`「${action.name}」得先选一个对象`)
      return
    }
    const hint = (action.prompt_hint || '').trim() || `你${action.name}`
    send(who ? `${hint}（对象：${who}）` : hint, '', { action_id: action.id, target_npc: who })
  }

  const useItem = (name: string) => {
    if (locked) return
    setMenuOpen(false)
    send(`你用了「${name}」。`, '', { item_name: name })
  }

  const moveTo = (name: string) => {
    if (locked) return
    setMenuOpen(false)
    send(`你动身前往${name}。`, '', { move_to: name })
  }

  const refreshSaves = () => qc.invalidateQueries({ queryKey: ['rpg-saves', sessionId] })

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

  // 宽屏钉在右边、窄屏收进抽屉，同一份
  const menu = (
    <StatusSidebar
      sess={sess}
      module={module}
      npcs={npcs}
      items={items}
      locations={locations}
      saves={saves}
      tab={tab}
      onTab={setTab}
      locked={locked}
      streaming={streaming}
      onUseItem={useItem}
      onMoveTo={moveTo}
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

      <header className="relative z-10 border-b border-border/50 bg-background/70 backdrop-blur-md px-6 py-3 flex items-center gap-3 shrink-0">
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
            {module?.name || ''} · 第 {sess.turn_count} 回合
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
          <ThemePicker />
          <button
            onClick={() => setMenuOpen(true)}
            className="xl:hidden p-2 rounded-md hover:bg-muted"
            title="状态 / 道具 / 地图 / 存档"
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

          {meta && (
            <div className="border-b border-border/50 bg-primary/[0.04] px-6 py-1.5 text-xs text-muted-foreground flex items-center gap-2 shrink-0">
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
                <span className="ml-auto shrink-0">
                  设定 {meta.system_tokens} tokens · 历史 {meta.history_count} 条
                  {meta.npcs_onstage && meta.npcs_onstage.length > 0
                    && ` · 在场 ${meta.npcs_onstage.map(n => n.name).join('、')}`}
                </span>
              )}
            </div>
          )}

          <div className="flex-1 overflow-y-auto px-6 py-6">
            <div className="max-w-3xl mx-auto space-y-4">
              {bubbles.length === 0 && (
                <p className="text-center text-sm text-muted-foreground py-20">
                  这个模组没写开场旁白。直接说出你的第一个动作，世界会从那里开始。
                </p>
              )}
              {bubbles.map((b, i) => (
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
                      {waiting && i === bubbles.length - 1 ? <ThinkingDots /> : b.content}
                      {streaming && !waiting && i === bubbles.length - 1 && (
                        <span className="inline-block w-0.5 h-4 bg-current ml-0.5 animate-pulse align-middle" />
                      )}
                    </div>
                  )}
                </div>
              ))}
              <div ref={bottomRef} />
            </div>
          </div>

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
                      title="动作作用在谁身上"
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

        </div>

        <aside className="hidden xl:block w-80 shrink-0 border-l border-border/50">
          {menu}
        </aside>
      </div>

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
