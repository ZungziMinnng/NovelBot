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
import Silk from '@/components/Silk/Silk'
import SpotlightCard from '@/components/SpotlightCard/SpotlightCard'
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
    <div className="min-h-screen bg-background relative">
      {/* 和 Landing 那张紫粉色酒馆卡呼应，进来不至于像换了个软件 */}
      <div className="fixed inset-0 z-0 opacity-[0.13] pointer-events-none">
        <Silk speed={2} scale={1.4} color="#b02a7a" noiseIntensity={1.4} rotation={0} className="w-full h-full" />
      </div>

      <header className="relative z-10 border-b border-border/50 backdrop-blur-sm px-6 py-4 flex items-center gap-3">
        <button onClick={() => navigate('/')} className="p-2 rounded-md hover:bg-muted" title="返回模式选择">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <Beer className="w-5 h-5 text-pink-500" />
        <h1 className="font-bold text-lg">酒馆</h1>
        <button
          onClick={() => navigate('/tavern/settings')}
          className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg border
            text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          title="管理酒馆的写作规则与常用系统指令"
        >
          <Settings2 className="w-3.5 h-3.5" /> 规则与指令
        </button>
        <div className="ml-auto">
          <ThemePicker />
        </div>
      </header>

      <main className="relative z-10 max-w-5xl mx-auto px-6 py-12 space-y-8">
        <div className="flex items-end justify-between gap-4">
          <div>
            <h2 className="text-2xl font-bold mb-1.5">今晚想见谁？</h2>
            <p className="text-sm text-muted-foreground">
              {cards.length === 0
                ? '还没有角色卡。先捏一个人出来，再决定要跟他走哪条故事线。'
                : `${cards.length} 张角色卡 · ${totalSessions} 条故事线`}
            </p>
          </div>
          <button
            onClick={() => navigate('/tavern/card/new')}
            className="flex items-center gap-1.5 text-sm rounded-lg px-4 py-2 shrink-0
              bg-pink-500/15 text-pink-300 ring-1 ring-pink-500/30 hover:bg-pink-500/25 transition-colors"
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
            className="w-full rounded-xl border border-dashed border-pink-500/30 py-20 text-center
              hover:bg-pink-500/5 transition-colors group"
          >
            <Beer className="w-10 h-10 mx-auto mb-3 text-pink-500/40 group-hover:text-pink-500/70 transition-colors" />
            <p className="text-sm text-muted-foreground">点这里捏第一个角色</p>
          </button>
        ) : (
          <div className="grid gap-5 sm:grid-cols-2">
            {cards.map(card => (
              <SpotlightCard
                key={card.id}
                spotlightColor="rgba(236, 72, 153, 0.14)"
                className="rounded-xl border bg-card/60 backdrop-blur-sm hover:border-pink-500/50 transition-colors"
              >
                <div className="absolute left-0 top-0 bottom-0 w-1 bg-pink-500/70" />
                {/* 卡面整体就是"开始聊"，编辑收到铅笔里——点开角色不该先看到表单 */}
                <div
                  role="button"
                  tabIndex={0}
                  onClick={() => setStarting(card)}
                  onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setStarting(card) } }}
                  className="pl-7 pr-5 py-5 flex flex-col gap-4 h-full cursor-pointer focus:outline-none"
                >
                  <div className="flex items-start gap-3.5">
                    <CardAvatar name={card.name} url={card.avatar_url} />
                    <div className="min-w-0 flex-1">
                      <p className="font-semibold truncate">{card.name}</p>
                      <p className="text-xs text-muted-foreground mt-1 flex items-center gap-1">
                        <MessagesSquare className="w-3 h-3" />
                        {card.session_count > 0 ? `${card.session_count} 条故事线` : '还没开始'}
                      </p>
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      <button
                        onClick={e => { e.stopPropagation(); navigate(`/tavern/card/${card.id}`) }}
                        className="p-1.5 rounded hover:bg-muted"
                        title="编辑角色卡"
                      >
                        <Pencil className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={e => { e.stopPropagation(); handleDelete(card) }}
                        className="p-1.5 rounded hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950/30"
                        title="删除"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>

                  {/* creator_note 的用处就在这里：给人看的备注，后端永不发给模型 */}
                  <p className="text-xs text-muted-foreground/80 leading-relaxed line-clamp-2 min-h-[2rem]">
                    {card.creator_note || '（没有写介绍）'}
                  </p>

                  <div
                    className="mt-auto text-sm px-3 py-2 rounded-lg text-center
                      bg-pink-500/15 text-pink-300 ring-1 ring-pink-500/25 transition-colors"
                  >
                    开始对话
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
        className="w-full max-w-md rounded-xl border border-pink-500/20 bg-card shadow-xl max-h-[85vh] overflow-y-auto"
        onClick={e => e.stopPropagation()}
      >
        <div className="px-5 py-4 border-b flex items-center gap-3">
          <CardAvatar name={card.name} url={card.avatar_url} size="sm" />
          <p className="font-semibold text-sm flex-1 truncate">{card.name}</p>
          <button onClick={onClose} className="p-1 rounded hover:bg-muted"><X className="w-4 h-4" /></button>
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
                    className="w-full text-left border rounded-lg px-3 py-2 hover:border-pink-500/40 hover:bg-pink-500/5 transition-colors"
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
                  <span className="text-pink-300 ml-1">已选 {others.length} 人</span>
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
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background/60 focus:outline-none focus:ring-1 focus:ring-pink-500/50"
            />
            <AutoTextarea
              minRows={2}
              value={personaDesc}
              onChange={e => setPersonaDesc(e.target.value)}
              placeholder="你扮演的人是谁（选填）：身份、外貌、与角色的关系……"
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background/60 focus:outline-none focus:ring-1 focus:ring-pink-500/50"
            />
            <p className="text-xs text-muted-foreground">
              都留空也能开始，{'{{user}}'} 会替换成 user。
            </p>
            <button
              onClick={start}
              disabled={creating}
              className="w-full text-sm px-4 py-2 rounded-lg flex items-center justify-center gap-1.5
                bg-pink-500/20 text-pink-200 ring-1 ring-pink-500/40 hover:bg-pink-500/30 disabled:opacity-40"
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
