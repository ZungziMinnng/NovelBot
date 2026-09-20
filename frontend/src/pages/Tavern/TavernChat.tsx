import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  ArrowLeft, Send, Loader2, User, RefreshCw, BookMarked, X, Pencil,
  UserRound, MessagesSquare, Lightbulb, Plus, Trash2, Square, Check,
  SlidersHorizontal,
} from 'lucide-react'
import {
  streamTavernTurn, tavernApi, modelLibraryApi, modelSelectValue,
  type ModelEntry, type TavernCard, type TavernSSEMessage, type TavernTurnMeta,
} from '@/api/client'
import {
  isTurnLive, tavernTurnActions, toBubble, useTavernTurn, useTavernTurnStore,
  type TavernBubble,
} from '@/store/tavernTurnStore'
import AutoTextarea from '@/components/AutoTextarea'
import { confirmDialog } from '@/components/ConfirmDialog/ConfirmDialog'
import ThemePicker from '@/components/ThemePicker/ThemePicker'
import ReadingFontButton from '@/components/ReadingFont/ReadingFontButton'
import { useReadingFont } from '@/components/ReadingFont/useReadingFont'
import CardAvatar from './CardAvatar'
import TavernParamFields, { type TavernParams } from './TavernParams'

// 气泡的形状和「消息 → 气泡」的转换都搬到 @/store/tavernTurnStore 了，
// 和「正在生成的那一轮」那套状态放在一起

/** 一轮里多个人发言时，meta 要合起来看，否则只剩最后一个人的数字 */
function mergeMeta(prev: TavernTurnMeta | null, next: TavernTurnMeta): TavernTurnMeta {
  if (!prev) return next
  const triggered = [...prev.triggered]
  for (const t of next.triggered) {
    if (!triggered.some(x => x.id === t.id)) triggered.push(t)
  }
  return {
    ...next,
    system_tokens: prev.system_tokens + next.system_tokens,
    triggered,
    rules_used: Math.max(prev.rules_used, next.rules_used),
    examples_used: Math.max(prev.examples_used, next.examples_used),
    user_message_id: prev.user_message_id ?? next.user_message_id,
  }
}

function groupModelsByProvider(models: ModelEntry[]) {
  const groups = new Map<string, ModelEntry[]>()
  for (const m of models.filter(m => m.model_type !== 'embedding')) {
    const key = m.provider || '未分组'
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(m)
  }
  return [...groups.entries()]
    .sort(([a], [b]) => a.localeCompare(b, 'zh-Hans-CN'))
    .map(([provider, items]) => ({
      provider,
      items: items.sort((a, b) =>
        (a.display_name || a.model_id).localeCompare(b.display_name || b.model_id, 'zh-Hans-CN'),
      ),
    }))
}

export default function TavernChat() {
  const { sessionId: sessionIdParam } = useParams<{ sessionId: string }>()
  const sessionId = Number(sessionIdParam)
  const navigate = useNavigate()
  const qc = useQueryClient()

  const [input, setInput] = useState('')
  const [title, setTitle] = useState('')

  // 「正在生成的那一轮」整套状态在 store 里，不在这儿。理由同 RPG 那边
  // （见 @/store/tavernTurnStore 顶部）：这一页切走是真的卸载，而流式回调还在
  // 跑——状态留在组件里会跟着一起销毁，回到页面只剩空白。
  // setter 的名字和原来逐个对齐，下面那些 setBubbles(...) 一行没改
  const { bubbles, streaming, waiting, meta, suggestions } = useTavernTurn(sessionId)
  const turnActions = useMemo(() => tavernTurnActions(sessionId), [sessionId])
  const {
    setBubbles, setStreaming, setWaiting, setMeta, setSuggestions,
    appendToken, flushTokens, setController, start: startTurn,
    abort: abortTurn, end: endTurn,
  } = turnActions

  const [panel, setPanel] = useState<'card' | 'sessions' | null>(null)
  const [showParams, setShowParams] = useState(false)
  const [suggesting, setSuggesting] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [draft, setDraft] = useState('')
  // 气泡的字号/行距/粗细。和小说侧分键（见 useReadingFont），头部那个按钮改它
  const { style: readingStyle, ...readingFont } = useReadingFont('tavern')

  // 参数存在卡上，所以对话里改完对这张卡的所有故事线都生效。
  // 本地这份 patch 一直盖在 card 上，不在保存后清掉——清了会在 refetch 到达前
  // 露出一帧旧值，看起来就是"点了详细又跳回适中"。
  const [paramPatch, setParamPatch] = useState<Partial<TavernParams>>({})

  const bottomRef = useRef<HTMLDivElement>(null)
  // 预设按钮是"改完立刻存"，同一个事件里 setState 还没生效，commit 必须读 ref
  const paramPatchRef = useRef<Partial<TavernParams>>({})

  const { data: sess } = useQuery({
    queryKey: ['tavern-session', sessionId],
    queryFn: () => tavernApi.sessions.get(sessionId),
    enabled: !!sessionId,
  })
  const { data: card } = useQuery({
    queryKey: ['tavern-card', sess?.card_id],
    queryFn: () => tavernApi.cards.get(sess!.card_id),
    enabled: !!sess,
  })
  // 消息以后端为准：只在进页面时拉一次，之后本地追加。不进 zustand persist——
  // 库里已经有一份，再存 localStorage 就是两个真相源
  const { data: loaded } = useQuery({
    queryKey: ['tavern-messages', sessionId],
    queryFn: () => tavernApi.messages.list(sessionId),
    enabled: !!sessionId,
  })
  const { data: modelLibrary = [] } = useQuery({
    queryKey: ['model-library'],
    queryFn: modelLibraryApi.list,
  })

  useEffect(() => {
    if (loaded) setBubbles(loaded.map(toBubble))
  }, [loaded])

  // 抽屉里换故事线时组件不重挂，得手动清掉上一条的气泡和面板状态。
  // 但这一条线正跑着一轮就别清：从别处切回一条**正在生成**的线时，清空会把
  // 已经吐出来的一半抹掉，而那半段后端还在接着写
  useEffect(() => {
    if (!isTurnLive(sessionId)) {
      setBubbles([])
      setMeta(null)
      setSuggestions([])
      setWaiting(false)
    }
    setEditingId(null)
    paramPatchRef.current = {}
    setParamPatch({})
  }, [sessionId])

  useEffect(() => {
    if (sess) setTitle(sess.title)
  }, [sess])

  // 这里原先挂着「卸载就 abort」。拆掉了：切页面不该掐断正在生成的那一轮，
  // 而这一页切走就是卸载。真想停就按输入框上的停止按钮

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [bubbles])

  const send = useCallback((text: string) => {
    // 先把这一条线重置成新的一轮再往里写：start 会清空气泡、挂上右下角那粒药丸
    startTurn(sess?.title || '', `/tavern/chat/${sessionId}`)
    setSuggestions([])
    // 助手气泡不再预推：群聊一轮有几个人说话要等服务端说了才知道
    setBubbles(prev => [...prev, { id: null, role: 'user', content: text, cardId: null }])
    setStreaming(true)
    setWaiting(true)
    setMeta(null)

    // 正在流的那条永远是最后一条：气泡只往后追加
    const patchLast = (fn: (prev: string) => string) =>
      setBubbles(prev => prev.map((b, i) => (i === prev.length - 1 ? { ...b, content: fn(b.content) } : b)))

    // 每个说话人开口前建一个空气泡。speaker 事件只在群聊发，单卡靠 meta 兜底。
    // 「当前这位的气泡开过没有」**现查 store**，不用组件里的 ref：切走再切回来
    // 时 ref 是全新的 false，可 store 里那颗气泡还开着，再开一颗会把后半句
    // 切到另一颗里。判据是「最后一条是助手气泡且还没落库」——done 会给它写上
    // 正式 id，那就算这一位说完了，下一位该开新的
    const openBubble = (cardId: number | null) => {
      const current = useTavernTurnStore.getState().turns[sessionId]?.bubbles
      const last = current?.[current.length - 1]
      if (last?.role === 'assistant' && last.id === null) return
      setWaiting(true)
      setBubbles(prev => [...prev, { id: null, role: 'assistant', content: '', cardId }])
    }

    setController(streamTavernTurn(
      sessionId,
      { content: text },
      (msg: TavernSSEMessage) => {
        if (msg.event === 'speaker') {
          openBubble(msg.data.card_id)
        } else if (msg.event === 'token') {
          openBubble(null)
          setWaiting(false)
          appendToken(msg.data)
        } else if (msg.event === 'meta') {
          setMeta(prev => mergeMeta(prev, msg.data))
          openBubble(msg.data.speaker?.card_id ?? null)
          // 回填刚发那句的 id，否则它没有编辑按钮，得刷新页面才拿得到
          const uid = msg.data.user_message_id
          if (uid) {
            setBubbles(prev => prev.map(b => (
              b.role === 'user' && b.id === null ? { ...b, id: uid } : b
            )))
          }
        } else if (msg.event === 'warning') {
          toast(msg.data)
        } else if (msg.event === 'done') {
          const id = msg.data.message_id
          // 攒着的 token 先落地，否则一帧之后会追加到已经封口的气泡上
          flushTokens()
          setBubbles(prev => prev.map((b, i) => (i === prev.length - 1 ? { ...b, id } : b)))
          // 这一位说完了。上面那行写上 id 就是封口——下一位开口时 openBubble
          // 现查 store，会发现最后一条已经落了库，于是自然给他开一颗新的
        } else if (msg.event === 'error') {
          flushTokens()
          openBubble(null)
          setWaiting(false)
          patchLast(prev => prev + `\n[错误] ${msg.data}`)
        }
      },
      () => {
        // 这一轮收尾。界面可能已经不在了（切走了），收尾照样做——药丸要摘掉、
        // streaming 要落回 false，不然切回来会一直显示成「正在生成」
        flushTokens()
        endTurn()
      },
    ))
  }, [sessionId, sess?.title, turnActions])

  const handleSend = () => {
    const text = input.trim()
    if (!text || streaming) return
    setInput('')
    send(text)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  // 重新生成：整轮重来。群聊一轮有多个人发言，只重跑最后一个的话，得再插一条
  // 「@某人」当输入，那句会永久留在对话记录里，比多重跑一个人更难受
  const regenerate = async () => {
    if (streaming) return
    const start = [...bubbles].reverse().findIndex(b => b.role === 'user')
    if (start < 0) return
    const index = bubbles.length - 1 - start
    const turn = bubbles.slice(index)
    if (turn.length < 2 || !turn[turn.length - 1].id) return
    try {
      // 从后往前删：中途失败留下的是完整前缀，不会出现空洞
      for (const b of [...turn].reverse()) {
        if (b.id) await tavernApi.messages.delete(b.id)
      }
      setBubbles(prev => prev.slice(0, index))
      send(turn[0].content)
    } catch {
      toast.error('重新生成失败')
    }
  }

  // 停止：中断的半段后端会落库，所以刷新后仍在，本地不需要回滚气泡
  const stop = () => {
    // 掐线和收尾都在 store 里（原来那两行 setStreaming/setWaiting 是 end 的一部分）
    abortTurn()
    qc.invalidateQueries({ queryKey: ['tavern-messages', sessionId] })
  }

  const startEdit = (b: TavernBubble) => {
    if (streaming || !b.id) return
    setEditingId(b.id)
    setDraft(b.content)
  }

  // 改自己说的话 = 从这句重来：后面的回复是照旧输入生成的，留着前后不搭
  const resendFrom = async (index: number, text: string) => {
    const trailing = bubbles.slice(index)
    if (trailing.length > 1 && !await confirmDialog({
      title: `改这句会删掉后面 ${trailing.length - 1} 条对话`,
      detail: '后面那些回复是照你原来那句生成的，留着前后接不上。改完从这里重新往下走。',
      confirmText: '改并重发',
      danger: true,
    })) {
      return
    }
    try {
      // 从后往前删：中途失败时留下的是一段完整的前缀，不会出现空洞
      for (const b of [...trailing].reverse()) {
        if (b.id) await tavernApi.messages.delete(b.id)
      }
      setBubbles(prev => prev.slice(0, index))
      setEditingId(null)
      send(text)
    } catch {
      toast.error('重发失败')
      qc.invalidateQueries({ queryKey: ['tavern-messages', sessionId] })
    }
  }

  const saveEdit = async () => {
    const text = draft.trim()
    if (!editingId || !text) return
    const index = bubbles.findIndex(b => b.id === editingId)
    if (index < 0) return

    if (bubbles[index].role === 'user') {
      await resendFrom(index, text)
      return
    }
    try {
      const updated = await tavernApi.messages.update(editingId, text)
      setBubbles(prev => prev.map(b => (b.id === editingId ? { ...b, content: updated.content } : b)))
      setEditingId(null)
    } catch {
      toast.error('保存修改失败')
    }
  }

  const suggest = async () => {
    if (streaming || suggesting) return
    setSuggesting(true)
    try {
      const { suggestions: list } = await tavernApi.suggest(sessionId)
      if (list.length === 0) toast('没想出来，再聊两句试试')
      setSuggestions(list)
    } catch {
      toast.error('生成参考回复失败')
    } finally { setSuggesting(false) }
  }

  const saveTitle = async () => {
    if (!sess || title === sess.title) return
    try {
      await tavernApi.sessions.update(sessionId, { title })
      qc.invalidateQueries({ queryKey: ['tavern-sessions', sess.card_id] })
    } catch {
      toast.error('保存故事线名称失败')
    }
  }

  const changeModel = async (value: string) => {
    if (!card) return
    try {
      await tavernApi.cards.update(card.id, { model_ref: value })
      qc.invalidateQueries({ queryKey: ['tavern-card', card.id] })
    } catch {
      toast.error('切换模型失败')
    }
  }

  const changeSummaryModel = async (value: string) => {
    if (!card) return
    try {
      await tavernApi.cards.update(card.id, { summary_model_ref: value })
      qc.invalidateQueries({ queryKey: ['tavern-card', card.id] })
      toast.success('总结模型已保存')
    } catch { toast.error('切换总结模型失败') }
  }

  const params = { ...(card as Partial<TavernParams> | undefined), ...paramPatch }

  const applyParams = (patch: Partial<TavernParams>) => {
    paramPatchRef.current = { ...paramPatchRef.current, ...patch }
    setParamPatch(paramPatchRef.current)
  }

  const commitParams = async () => {
    const patch = paramPatchRef.current
    if (!card || Object.keys(patch).length === 0) return
    try {
      await tavernApi.cards.update(card.id, patch)
      qc.invalidateQueries({ queryKey: ['tavern-card', card.id] })
    } catch {
      // 存失败就把本地覆盖丢掉，输入框回到后端真相，别让人以为已经生效
      paramPatchRef.current = {}
      setParamPatch({})
      toast.error('保存参数失败')
    }
  }

  const last = bubbles[bubbles.length - 1]
  const canRegenerate = !streaming && !!last?.id && last.role === 'assistant'

  // 参与卡。群聊之前的老数据 cards 为空，回落成主卡这一张
  const members = sess?.cards?.length ? sess.cards : (card ? [{
    id: card.id, name: card.name, avatar_url: card.avatar_url,
  }] : [])
  const isGroup = members.length > 1
  /** 按说话人取名字和头像，查不到（老数据）回落主卡 */
  const speakerOf = (cardId: number | null) =>
    members.find(m => m.id === cardId) || members[0]

  return (
    <div className="mode-tavern h-screen flex flex-col bg-background relative">
      <header className="relative z-10 border-b border-border/50 bg-background/70 backdrop-blur-md px-6 py-3 flex items-center gap-3 shrink-0">
        <button
          onClick={() => navigate('/tavern')}
          className="p-2 rounded-md hover:bg-muted"
          title="返回角色卡列表"
        >
          <ArrowLeft className="w-4 h-4" />
        </button>
        {/* 角色 = 只读预览这张卡，对话 = 切换这张卡的其他故事线 */}
        <div className="flex items-center gap-1 mr-1">
          <button
            onClick={() => setPanel(p => (p === 'card' ? null : 'card'))}
            className={`flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg transition-colors ${
              panel === 'card'
                ? 'bg-primary/15 text-primary ring-1 ring-primary/40'
                : 'hover:bg-muted text-muted-foreground'
            }`}
          >
            <UserRound className="w-3.5 h-3.5" /> 角色
          </button>
          <button
            onClick={() => setPanel(p => (p === 'sessions' ? null : 'sessions'))}
            className={`flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg transition-colors ${
              panel === 'sessions'
                ? 'bg-primary/15 text-primary ring-1 ring-primary/40'
                : 'hover:bg-muted text-muted-foreground'
            }`}
          >
            <MessagesSquare className="w-3.5 h-3.5" /> 对话
          </button>
        </div>
        {/* 群聊时头像叠着放，一眼看出这条故事线里有几个人 */}
        <div className="flex items-center shrink-0">
          {members.slice(0, 3).map((m, i) => (
            <div key={m.id} className={i > 0 ? '-ml-2' : ''}>
              <CardAvatar name={m.name} url={m.avatar_url} size="sm" />
            </div>
          ))}
        </div>
        <div className="min-w-0">
          <p className="font-bold text-sm truncate">
            {members.map(m => m.name).join('、') || '角色卡'}
          </p>
          <input
            value={title}
            onChange={e => setTitle(e.target.value)}
            onBlur={saveTitle}
            placeholder="未命名故事线"
            className="text-xs text-muted-foreground bg-transparent border-b border-transparent hover:border-border focus:border-border focus:outline-none w-48"
          />
        </div>
        <div className="ml-auto flex items-center gap-3">
          {sess?.persona_name && (
            <span className="text-xs text-muted-foreground">玩家：{sess.persona_name}</span>
          )}
          <select
            value={modelSelectValue(modelLibrary, card?.model_ref || '')}
            onChange={e => changeModel(e.target.value)}
            disabled={streaming || !card}
            title={isGroup
              ? `改的是「${card?.name}」的模型。群聊里每个角色用自己卡上的设置，要改别人去他的角色卡里改`
              : '本张卡使用的模型（切换即保存）'}
            className="text-xs border rounded-lg px-2 py-1.5 bg-background/60 focus:outline-none max-w-[150px] truncate disabled:opacity-50"
          >
            <option value="">跟随全局默认</option>
            {groupModelsByProvider(modelLibrary).map(g => (
              <optgroup key={g.provider} label={g.provider}>
                {g.items.map(m => (
                  <option key={m.id} value={String(m.id)}>{m.display_name || m.model_id}</option>
                ))}
              </optgroup>
            ))}
          </select>
          <select
            value={modelSelectValue(modelLibrary, card?.summary_model_ref || '')}
            onChange={e => changeSummaryModel(e.target.value)}
            disabled={streaming || !card}
            title="上下文总结模型"
            className="text-xs border rounded-lg px-2 py-1.5 bg-background/60 focus:outline-none max-w-[150px] truncate disabled:opacity-50"
          >
            <option value="">总结跟随对话</option>
            {groupModelsByProvider(modelLibrary).map(g => <optgroup key={`summary-${g.provider}`} label={g.provider}>
              {g.items.map(m => <option key={m.id} value={String(m.id)}>{m.display_name || m.model_id}</option>)}
            </optgroup>)}
          </select>
          <ReadingFontButton {...readingFont} />
          <ThemePicker />
        </div>
      </header>

      {meta && (
        <div className="relative z-10 border-b border-border/50 bg-pink-500/[0.04] px-6 py-1.5 text-xs text-muted-foreground flex items-center gap-2 shrink-0">
          <BookMarked className="w-3 h-3 shrink-0" />
          {meta.triggered.length > 0
            ? (
              <span className="truncate">
                生效词条：
                <span className="text-primary">
                  {meta.triggered
                    .map(t => (t.constant ? `常驻${t.keywords ? `（${t.keywords}）` : ''}` : t.keywords) || `#${t.id}`)
                    .join(' / ')}
                </span>
              </span>
            )
            : <span>本轮没有世界书词条生效</span>}
          <span className="ml-auto shrink-0">
            设定 {meta.system_tokens} tokens · 历史 {meta.history_count} 条
            {meta.examples_used > 0 && ` · 示例 ${meta.examples_used} 组`}
            {meta.rules_used > 0 && ` · 规则 ${meta.rules_used} 条`}
          </span>
        </div>
      )}

      <div className="relative z-10 flex-1 overflow-y-auto px-6 py-6">
        <div className="max-w-3xl mx-auto space-y-4">
          {bubbles.map((b, i) => (
            <div key={b.id ?? `pending-${i}`} className={`group flex gap-2.5 ${b.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              {b.role === 'assistant' && (
                <CardAvatar
                  name={speakerOf(b.cardId)?.name || '?'}
                  url={speakerOf(b.cardId)?.avatar_url}
                  size="sm"
                  className="mt-0.5"
                />
              )}
              {editingId !== null && editingId === b.id ? (
                <div className="w-[80%] space-y-2">
                  <AutoTextarea
                    value={draft}
                    onChange={e => setDraft(e.target.value)}
                    minRows={3}
                    autoFocus
                    className="w-full text-sm border rounded-2xl px-4 py-2.5 bg-background/80 leading-relaxed
                      focus:outline-none focus:ring-1 focus:ring-pink-500/50"
                  />
                  <div className="flex gap-2 justify-end">
                    <button
                      onClick={() => setEditingId(null)}
                      className="text-xs px-3 py-1.5 border rounded-lg hover:bg-muted"
                    >
                      取消
                    </button>
                    <button
                      onClick={saveEdit}
                      disabled={!draft.trim()}
                      className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg
                        bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40"
                    >
                      <Check className="w-3 h-3" />
                      {b.role === 'user' ? '保存并重发' : '保存'}
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  {/* 改写角色的话是酒馆常规操作：跑偏的一句会被后面几轮当成既定事实 */}
                  {b.role === 'user' && b.id && !streaming && (
                    <button
                      onClick={() => startEdit(b)}
                      className="self-center p-1.5 rounded opacity-0 group-hover:opacity-100 transition-opacity
                        text-muted-foreground hover:text-foreground"
                      title="改这句并重发（后面的对话会重走）"
                    >
                      <Pencil className="w-3 h-3" />
                    </button>
                  )}
                  <div
                    className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap ${
                      b.role === 'user'
                        ? 'bg-primary text-primary-foreground rounded-tr-sm'
                        : 'bg-card/80 backdrop-blur-sm border border-pink-500/15 rounded-tl-sm'
                    }`}
                    style={readingStyle}
                  >
                    {/* 群聊里几个人的气泡长得一样，光靠头像分不清谁在说 */}
                    {isGroup && b.role === 'assistant' && (
                      <p className="text-xs font-medium text-primary mb-1">
                        {speakerOf(b.cardId)?.name}
                      </p>
                    )}
                    {waiting && b.role === 'assistant' && i === bubbles.length - 1
                      ? <ThinkingDots />
                      : b.content}
                    {streaming && !waiting && i === bubbles.length - 1 && b.role === 'assistant' && (
                      <span className="inline-block w-0.5 h-4 bg-current ml-0.5 animate-pulse align-middle" />
                    )}
                  </div>
                  {b.role === 'assistant' && b.id && !streaming && (
                    <button
                      onClick={() => startEdit(b)}
                      className="self-center p-1.5 rounded opacity-0 group-hover:opacity-100 transition-opacity
                        text-muted-foreground hover:text-foreground"
                      title="编辑这条消息"
                    >
                      <Pencil className="w-3 h-3" />
                    </button>
                  )}
                </>
              )}
              {b.role === 'user' && (
                <div className="w-7 h-7 rounded-full bg-muted flex items-center justify-center shrink-0 mt-0.5">
                  <User className="w-4 h-4" />
                </div>
              )}
            </div>
          ))}
          {canRegenerate && (
            <div className="flex justify-start pl-10">
              <button
                onClick={regenerate}
                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              >
                <RefreshCw className="w-3 h-3" /> 重新生成
              </button>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      <div className="relative z-10 border-t border-border/50 bg-background/70 backdrop-blur-md px-6 py-3 shrink-0">
        <div className="max-w-3xl mx-auto space-y-2">
          {showParams && card && (
            <div className="rounded-xl border border-pink-500/20 bg-card/95 backdrop-blur-sm p-4">
              <div className="flex items-start gap-2 mb-3">
                <div className="flex-1">
                  <p className="text-sm font-semibold">
                    生成参数{isGroup && ` · ${card?.name}`}
                  </p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    存在角色卡上，改完下一轮生效，这张卡的其他故事线也跟着变。
                    {isGroup && '群聊里每个角色用自己卡上的参数，这里改的只是他一个人的。'}
                  </p>
                </div>
                <button
                  onClick={() => { setShowParams(false); commitParams() }}
                  className="p-1 rounded hover:bg-muted shrink-0"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
              <TavernParamFields
                value={params}
                onChange={applyParams}
                onCommit={commitParams}
              />
            </div>
          )}
          {suggestions.length > 0 && (
            <div className="grid sm:grid-cols-2 gap-1.5">
              {suggestions.map((s, i) => (
                <button
                  key={i}
                  onClick={() => send(s)}
                  disabled={streaming}
                  className="text-left text-xs px-3 py-2 rounded-lg border border-pink-500/25 bg-pink-500/[0.06]
                    hover:bg-pink-500/15 transition-colors disabled:opacity-40"
                >
                  {s}
                </button>
              ))}
            </div>
          )}
          <div className="flex gap-2 items-end">
            <AutoTextarea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={isGroup
                ? `输入你的行动或台词…（写 @${members[1]?.name} 就只有他回，不写则${members.length} 个人依次开口）`
                : '输入你的行动或台词…（Enter 发送，Shift+Enter 换行）'}
              minRows={2}
              disabled={streaming}
              className="flex-1 text-sm border rounded-lg px-3 py-2 bg-background/60 focus:outline-none focus:ring-1 focus:ring-pink-500/50 disabled:opacity-50"
            />
            <button
              onClick={() => setShowParams(v => !v)}
              title="回复长度与生成参数"
              className={`flex items-center justify-center w-9 h-9 rounded-lg shrink-0 border transition-colors ${
                showParams ? 'bg-primary/15 text-primary border-primary/40' : 'hover:bg-muted'
              }`}
            >
              <SlidersHorizontal className="w-4 h-4" />
            </button>
            <button
              onClick={suggest}
              disabled={streaming || suggesting || bubbles.length === 0}
              title="帮我想想：根据角色刚说的话给几条参考回复"
              className="flex items-center justify-center w-9 h-9 rounded-lg shrink-0 border
                hover:bg-muted disabled:opacity-40"
            >
              {suggesting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Lightbulb className="w-4 h-4" />}
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
                disabled={!input.trim()}
                className="flex items-center justify-center w-9 h-9 rounded-lg shrink-0
                  bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40"
              >
                <Send className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>
      </div>

      {panel === 'card' && card && (
        <SidePanel title="角色卡" onClose={() => setPanel(null)}>
          <CardPreview card={card} onEdit={() => navigate(`/tavern/card/${card.id}`)} />
        </SidePanel>
      )}
      {panel === 'sessions' && sess && (
        <SidePanel title="故事线" onClose={() => setPanel(null)}>
          <SessionList
            cardId={sess.card_id}
            memberIds={members.map(m => m.id)}
            currentId={sessionId}
            onPick={() => setPanel(null)}
          />
        </SidePanel>
      )}
    </div>
  )
}

/** 等首个 token 时的三点。Tailwind 只认字面类名，所以延迟写成行内 style */
function ThinkingDots() {
  return (
    <span className="inline-flex items-center gap-1 py-1" aria-label="角色正在回复">
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

// ── 左侧抽屉 ──────────────────────────────────────────────────────────────

function SidePanel({
  title, onClose, children,
}: {
  title: string
  onClose: () => void
  children: React.ReactNode
}) {
  return (
    <div className="fixed inset-0 z-50 flex" onClick={onClose}>
      <div
        className="w-full max-w-sm h-full bg-card border-r border-pink-500/20 shadow-xl overflow-y-auto"
        onClick={e => e.stopPropagation()}
      >
        <div className="sticky top-0 bg-card border-b px-5 py-3.5 flex items-center gap-2">
          <p className="font-semibold text-sm flex-1">{title}</p>
          <button onClick={onClose} className="p-1 rounded hover:bg-muted"><X className="w-4 h-4" /></button>
        </div>
        <div className="p-5">{children}</div>
      </div>
      <div className="flex-1 bg-black/50 backdrop-blur-sm" />
    </div>
  )
}

/** 只读预览。creator_note 在这里显示无妨——不发给模型是后端那一侧的事 */
function CardPreview({ card, onEdit }: { card: TavernCard; onEdit: () => void }) {
  const fields: Array<[string, string]> = [
    ['角色性格', card.personality],
    ['外貌身材', card.profile_sections?.appearance || ''],
    ['背景故事', card.profile_sections?.background || ''],
    ['能力特长', card.profile_sections?.abilities || ''],
    ['关系网络', card.profile_sections?.relationships || ''],
    ['开场环境', card.opening_scene],
    ['系统指令', card.system_instruction],
    ['我的备注（AI 看不到）', card.creator_note],
  ]
  return (
    <div className="space-y-5">
      <div className="flex items-center gap-4">
        <CardAvatar name={card.name} url={card.avatar_url} size="lg" />
        <div className="min-w-0">
          <p className="font-bold truncate">{card.name}</p>
          <button
            onClick={onEdit}
            className="flex items-center gap-1 text-xs mt-2 px-2.5 py-1.5 rounded-lg border hover:bg-muted"
          >
            <Pencil className="w-3 h-3" /> 编辑角色卡
          </button>
        </div>
      </div>
      {fields.map(([label, value]) => value?.trim() && (
        <div key={label}>
          <p className="text-xs font-medium mb-1.5">{label}</p>
          <p className="text-xs text-muted-foreground leading-relaxed whitespace-pre-wrap">{value}</p>
        </div>
      ))}
    </div>
  )
}

function SessionList({
  cardId, memberIds, currentId, onPick,
}: {
  cardId: number
  /** 当前这条故事线的参与卡。抽屉里开新的一条时照搬同一批人 */
  memberIds: number[]
  currentId: number
  onPick: () => void
}) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { data: sessions = [], isLoading } = useQuery({
    queryKey: ['tavern-sessions', cardId],
    queryFn: () => tavernApi.sessions.list(cardId),
  })

  const create = async () => {
    try {
      const sess = await tavernApi.sessions.createGroup(
        memberIds.length ? memberIds : [cardId], {},
      )
      qc.invalidateQueries({ queryKey: ['tavern-sessions', cardId] })
      qc.invalidateQueries({ queryKey: ['tavern-cards'] })
      navigate(`/tavern/chat/${sess.id}`)
      onPick()
    } catch {
      toast.error('创建故事线失败')
    }
  }

  const remove = async (id: number) => {
    if (!await confirmDialog({
      title: '确认删除这条故事线？',
      detail: id === currentId
        ? '全部对话记录会一起删掉，不可恢复。删的是你正在看的这条，删完会回到酒馆首页。'
        : '全部对话记录会一起删掉，不可恢复。角色卡本身保留。',
      confirmText: '删除',
      danger: true,
    })) return
    try {
      await tavernApi.sessions.delete(id)
      qc.invalidateQueries({ queryKey: ['tavern-sessions', cardId] })
      qc.invalidateQueries({ queryKey: ['tavern-cards'] })
      if (id === currentId) navigate('/tavern')
    } catch {
      toast.error('删除故事线失败')
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Loader2 className="w-3.5 h-3.5 animate-spin" /> 加载中…
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {sessions.map(s => (
        <div
          key={s.id}
          className={`border rounded-lg px-3 py-2 flex items-center gap-2 ${
            s.id === currentId ? 'border-pink-500/50 bg-pink-500/[0.06]' : 'hover:border-pink-500/30'
          }`}
        >
          <button
            onClick={() => { navigate(`/tavern/chat/${s.id}`); onPick() }}
            className="flex-1 min-w-0 text-left"
          >
            <p className="text-sm truncate">{s.title || new Date(s.created_at).toLocaleString()}</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              {s.cards.length > 1 && `${s.cards.map(c => c.name).join('、')} · `}
              {s.message_count} 条消息
              {s.persona_name && ` · 玩家：${s.persona_name}`}
              {s.id === currentId && ' · 当前'}
            </p>
          </button>
          <button
            onClick={() => remove(s.id)}
            className="p-1.5 rounded hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950/30 shrink-0"
            title="删除"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      ))}
      <button
        onClick={create}
        className="w-full flex items-center justify-center gap-1 px-3 py-2 text-xs border border-dashed
          border-pink-500/30 rounded-lg text-muted-foreground hover:bg-pink-500/5"
      >
        <Plus className="w-3.5 h-3.5" /> 新故事线
      </button>
    </div>
  )
}
