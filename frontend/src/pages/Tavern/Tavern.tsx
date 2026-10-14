import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  ArrowLeft, Plus, Pencil, Trash2, Loader2, Beer, MessagesSquare, X, Play, Settings2,
} from 'lucide-react'
import { tavernApi, type TavernCard } from '@/api/client'
import AutoTextarea from '@/components/AutoTextarea'
import { confirmDialog } from '@/components/ConfirmDialog/ConfirmDialog'
import ThemePicker from '@/components/ThemePicker/ThemePicker'
import SpotlightCard, {
  LIST_CARD, LIST_CARD_BAR, LIST_CARD_HIT, CARD_ICON_BTN, CARD_ICON_BTN_DANGER, HEADER_PILL,
} from '@/components/SpotlightCard/SpotlightCard'
import CardAvatar from './CardAvatar'
import CardMultiSelect from './CardMultiSelect'

export default function Tavern() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [starting, setStarting] = useState<TavernCard | null>(null)
  const { data: cards = [], isLoading } = useQuery({
    queryKey: ['tavern-cards'],
    queryFn: tavernApi.cards.list,
  })

  const handleDelete = async (card: TavernCard) => {
    if (!await confirmDialog({
      title: `确认删除角色卡「${card.name}」？`,
      detail: '它的全部故事线、对话记录和世界书词条会一起删掉，不可恢复。',
      confirmText: '删除',
      danger: true,
    })) return
    try {
      await tavernApi.cards.delete(card.id)
      qc.invalidateQueries({ queryKey: ['tavern-cards'] })
    } catch {
      toast.error('删除角色卡失败')
    }
  }

  const totalSessions = cards.reduce((n, c) => n + c.session_count, 0)

  return (
    <div className="mode-tavern min-h-screen bg-background relative">
      <div aria-hidden className="page-glow" />
      <header className="relative z-10 border-b border-border/50 backdrop-blur-sm px-6 py-4 flex items-center gap-3">
        <button onClick={() => navigate('/')} className="p-2 rounded-md hover:bg-muted" title="返回模式选择" aria-label="返回模式选择">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <span className="grid h-8 w-8 place-items-center rounded-lg bg-primary/10 text-primary ring-1 ring-inset ring-primary/20">
          <Beer className="w-4 h-4" />
        </span>
        <h1 className="font-bold text-lg">酒馆</h1>
        <button
          onClick={() => navigate('/tavern/settings')}
          className={HEADER_PILL}
          title="管理酒馆的写作规则与常用系统指令"
        >
          <Settings2 className="w-3.5 h-3.5" /> 规则与指令
        </button>
        <div className="ml-auto">
          <ThemePicker />
        </div>
      </header>

      <main className="relative z-10 max-w-5xl mx-auto px-5 sm:px-6 pt-12 pb-16 sm:pt-16 space-y-10">
        <div className="reveal flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="mb-3 text-xs font-medium tracking-[0.2em] text-primary">TAVERN</p>
            <h2 className="font-display text-4xl sm:text-5xl font-bold leading-tight tracking-tight">今晚想见谁？</h2>
            <p className="mt-3 text-sm sm:text-base text-muted-foreground">
              {cards.length === 0
                ? '还没有角色卡。先捏一个人出来，再决定要跟他走哪条故事线。'
                : <><span className="font-semibold tabular-nums text-foreground">{cards.length}</span> 张角色卡 · <span className="font-semibold tabular-nums text-foreground">{totalSessions}</span> 条故事线</>}
            </p>
          </div>
          <button
            onClick={() => navigate('/tavern/card/new')}
            className="self-start sm:self-auto flex items-center gap-1.5 text-sm font-medium rounded-full px-5 py-2.5 shrink-0 bg-primary text-primary-foreground hover:opacity-95"
          >
            <Plus className="w-4 h-4" /> 新建角色卡
          </button>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-20 text-muted-foreground">
            <Loader2 className="w-5 h-5 animate-spin mr-2" /> 加载中...
          </div>
        ) : cards.length === 0 ? (
          <button
            onClick={() => navigate('/tavern/card/new')}
            className="reveal w-full rounded-2xl border border-dashed border-primary/30 py-20 text-center
              hover:bg-primary/5 hover:border-primary/50 transition-colors group"
          >
            <span className="mx-auto mb-4 grid h-14 w-14 place-items-center rounded-2xl bg-primary/10 text-primary transition-transform duration-500 ease-out-expo group-hover:scale-110 group-hover:-rotate-6">
              <Beer className="w-7 h-7" />
            </span>
            <p className="text-sm text-muted-foreground">点这里捏第一个角色</p>
          </button>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:gap-5">
            {cards.map((card, i) => (
              <SpotlightCard
                key={card.id}
                spotlightColor="hsl(var(--primary) / 0.12)"
                className={LIST_CARD}
                style={{ '--i': i + 1 } as React.CSSProperties}
              >
                <span aria-hidden className={LIST_CARD_BAR} />
                {/* 卡面整体就是"开始聊"，编辑收到铅笔里——点开角色不该先看到表单 */}
                <div
                  role="button"
                  tabIndex={0}
                  onClick={() => setStarting(card)}
                  onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setStarting(card) } }}
                  className={`relative p-5 sm:p-6 flex flex-col gap-4 h-full cursor-pointer rounded-2xl ${LIST_CARD_HIT}`}
                >
                  <div className="flex items-start gap-3.5">
                    <CardAvatar name={card.name} url={card.avatar_url} />
                    <div className="min-w-0 flex-1">
                      <p className="font-display text-xl font-bold truncate">{card.name}</p>
                      <p className="text-xs text-muted-foreground mt-1 flex items-center gap-1">
                        <MessagesSquare className="w-3 h-3" />
                        {card.session_count > 0 ? `${card.session_count} 条故事线` : '还没开始'}
                      </p>
                    </div>
                    <div className="flex items-center gap-0.5 shrink-0">
                      <button
                        onClick={e => { e.stopPropagation(); navigate(`/tavern/card/${card.id}`) }}
                        className={CARD_ICON_BTN}
                        title="编辑角色卡"
                        aria-label="编辑角色卡"
                      >
                        <Pencil className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={e => { e.stopPropagation(); handleDelete(card) }}
                        className={CARD_ICON_BTN_DANGER}
                        title="删除"
                        aria-label="删除角色卡"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>

                  {/* creator_note 的用处就在这里：给人看的备注，后端永不发给模型 */}
                  <p className="text-sm text-muted-foreground leading-relaxed line-clamp-2 min-h-[2.75rem]">
                    {card.creator_note || '（没有写介绍）'}
                  </p>

                  <div
                    className="mt-auto flex items-center justify-center gap-1.5 text-sm font-medium px-3 py-2.5 rounded-xl
                      bg-primary/10 text-primary ring-1 ring-inset ring-primary/20 transition-colors duration-300
                      group-hover:bg-primary group-hover:text-primary-foreground group-hover:ring-transparent"
                  >
                    <Play className="w-3.5 h-3.5" /> 开始对话
                  </div>
                </div>
              </SpotlightCard>
            ))}
          </div>
        )}
      </main>

      {starting && <StartDialog card={starting} onClose={() => setStarting(null)} />}
    </div>
  )
}

/** 点卡后的身份确认层：能直接续上次，也能填个身份开新的。什么都不填就是默认 user */
function StartDialog({ card, onClose }: { card: TavernCard; onClose: () => void }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [personaName, setPersonaName] = useState('')
  const [personaDesc, setPersonaDesc] = useState('')
  const [creating, setCreating] = useState(false)
  // 同场的其他角色。点进来这张卡是主角色，永远在里面
  const [others, setOthers] = useState<number[]>([])

  const { data: sessions = [], isLoading } = useQuery({
    queryKey: ['tavern-sessions', card.id],
    queryFn: () => tavernApi.sessions.list(card.id),
  })

  const start = async () => {
    setCreating(true)
    try {
      // 首个是主卡：会话级操作（摘要、帮我想想）和权限都认它
      const sess = await tavernApi.sessions.createGroup([card.id, ...others], {
        persona_name: personaName.trim(), persona_desc: personaDesc.trim(),
      })
      qc.invalidateQueries({ queryKey: ['tavern-sessions', card.id] })
      qc.invalidateQueries({ queryKey: ['tavern-cards'] })
      navigate(`/tavern/chat/${sess.id}`)
    } catch {
      toast.error('创建故事线失败')
      setCreating(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-xl border border-primary/20 bg-card shadow-xl max-h-[85vh] overflow-y-auto"
        onClick={e => e.stopPropagation()}
      >
        <div className="px-5 py-4 border-b flex items-center gap-3">
          <CardAvatar name={card.name} url={card.avatar_url} size="sm" />
          <p className="font-semibold text-sm flex-1 truncate">{card.name}</p>
          <button onClick={onClose} className="p-1 rounded hover:bg-muted" aria-label="关闭"><X className="w-4 h-4" /></button>
        </div>

        <div className="p-5 space-y-5">
          {isLoading ? (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="w-3.5 h-3.5 animate-spin" /> 读取故事线…
            </div>
          ) : sessions.length > 0 && (
            <div>
              <p className="text-xs font-medium mb-2">继续之前的故事线</p>
              <div className="space-y-1.5">
                {sessions.slice(0, 5).map(s => (
                  <button
                    key={s.id}
                    onClick={() => navigate(`/tavern/chat/${s.id}`)}
                    className="w-full text-left border rounded-lg px-3 py-2 hover:border-primary/40 hover:bg-primary/5 transition-colors"
                  >
                    <p className="text-sm truncate">{s.title || new Date(s.created_at).toLocaleString()}</p>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {s.message_count} 条消息{s.persona_name && ` · 玩家：${s.persona_name}`}
                    </p>
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="space-y-3">
            <p className="text-xs font-medium">{sessions.length > 0 ? '或者开一条新的' : '你是谁？'}</p>
            <details className="border rounded-lg px-3 py-2">
              <summary className="text-xs cursor-pointer select-none">
                再叫几个人同场
                {others.length > 0 && (
                  <span className="text-primary ml-1">已选 {others.length} 人</span>
                )}
              </summary>
              <div className="mt-2.5 space-y-2">
                <CardMultiSelect
                  selected={others}
                  onChange={setOthers}
                  excludeId={card.id}
                  empty="只有这一张角色卡，再捏一个才能群聊。"
                />
                <p className="text-xs text-muted-foreground">
                  多人同场时，不点名就是所有人依次开口；想让某一个人单独回，在消息里写 @他的名字。
                </p>
              </div>
            </details>
            <input
              value={personaName}
              onChange={e => setPersonaName(e.target.value)}
              placeholder="你的名字（选填）"
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background/60"
            />
            <AutoTextarea
              minRows={2}
              value={personaDesc}
              onChange={e => setPersonaDesc(e.target.value)}
              placeholder="你扮演的人是谁（选填）：身份、外貌、与角色的关系……"
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background/60"
            />
            <p className="text-xs text-muted-foreground">
              都留空也能开始，{'{{user}}'} 会替换成 user。
            </p>
            <button
              onClick={start}
              disabled={creating}
              className="w-full text-sm px-4 py-2 rounded-lg flex items-center justify-center gap-1.5
                bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40"
            >
              {creating ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
              开始新故事线
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
