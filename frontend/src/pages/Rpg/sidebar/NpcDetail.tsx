import { useEffect, useState } from 'react'
import { ChevronLeft, Loader2, MapPin, Pencil, X } from 'lucide-react'
import { rpgApi, type RpgNpc, type RpgStatDef } from '@/api/client'
import RpgAvatar from '../RpgAvatar'
import ImageLightbox from '../ImageLightbox'
import StatBar from '../StatBar'
import { playSfx } from '../useSfx'

/**
 * 角色档案。只对已经见过面的人开，所以档案全文可以直接摊开——
 * 没见过的人连在侧栏列出都不该，更不会走到这里。
 *
 * 从前这是一张 portal 出来的全屏弹窗（NpcSheet），一点开剧情全被盖住。
 * 现在它就住在侧栏那一列里，顶掉名单、剧情照常看得见。所以这里**没有**
 * 遮罩和固定宽度：外面多宽它就多宽，320px 也得站得住。
 */
export default function NpcDetail({
  npc, relationDefs, state, notes, activity, here, place,
  onBack, onDeleteNote, onDeleteActivity, onSaved,
}: {
  npc: RpgNpc
  relationDefs: RpgStatDef[]
  state: Record<string, number | boolean>
  /** GM 这一局记下的他的近况。键值都是模型自己起的，模组里没有 */
  notes: Record<string, string>
  /** AI 调度替你不在场时她做的事记下的一句话。没勾「AI 调度」的人是空串 */
  activity: string
  /** 他此刻是不是和玩家在同一个地点 */
  here: boolean
  /** 他此刻在哪儿。**不是角色卡上的常驻地点**——有作息表的人是按时段走的，
   *  写常驻地点会让玩家跑过去扑空 */
  place: string
  /** 回名单。从前是「关掉弹窗」，现在是主从里的那个返回箭头 */
  onBack: () => void
  /** 划掉记错的一条。模型写下的持久事实，玩家得有个不读档的补救 */
  onDeleteNote: (key: string) => void
  /** 划掉那一句「最近在做什么」。同上的补救，但它是单独一句不是键值表 */
  onDeleteActivity: () => void
  /** 档案存完了。改的是模组里那张卡，所以父组件要顺手把角色列表也刷一下 */
  onSaved: (updated: RpgNpc) => void
}) {
  // 换一个人看时这个组件靠 key 重挂，所以一次挂载 = 一次打开
  useEffect(() => { playSfx('npc') }, [])

  const [draft, setDraft] = useState<RpgNpc | null>(null)
  const [saving, setSaving] = useState(false)
  const [viewing, setViewing] = useState(false)

  const save = async () => {
    if (!draft) return
    setSaving(true)
    try {
      onSaved(await rpgApi.npcs.update(npc.id, {
        name: draft.name.trim() || npc.name,
        description: draft.description,
        persona: draft.persona,
        appearance: draft.appearance,
        profile_sections: draft.profile_sections,
      }))
      setDraft(null)
    } finally {
      setSaving(false)
    }
  }

  const sections = Object.entries(npc.profile_sections || {}).filter(([, text]) => (text || '').trim())
  const noteRows = Object.entries(notes || {}).filter(([, text]) => (text || '').trim())
  const visibleRelationDefs = npc.relation_enabled === false
    ? []
    : npc.relation_stat_names?.length
      ? relationDefs.filter(def => npc.relation_stat_names.includes(def.name))
      : relationDefs

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* 和编辑器详情列一样的固定页眉：返回、身份、随内容滚动时不跑掉 */}
      <div className="shrink-0 border-b border-border/60 px-3 py-2.5 flex items-center gap-2">
        <button
          onClick={onBack}
          title="回名单"
          className="p-1 rounded hover:bg-muted shrink-0"
        >
          <ChevronLeft className="w-4 h-4" />
        </button>
        {/* 立绘是竖图，方头像里只露得出脸，给条看原图的路 */}
        {npc.avatar_url ? (
          <button onClick={() => setViewing(true)} title="看立绘" className="shrink-0">
            <RpgAvatar name={npc.name} url={npc.avatar_url} size="md" />
          </button>
        ) : (
          <RpgAvatar name={npc.name} url={npc.avatar_url} size="md" />
        )}
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold truncate">{npc.name}</p>
          <p className="text-xs text-muted-foreground flex items-center gap-1 truncate">
            <MapPin className="w-3 h-3 shrink-0" />
            {place || '行踪不定'}
            {here && <span className="text-primary shrink-0">· 就在你面前</span>}
          </p>
        </div>
        {draft ? (
          <div className="flex items-center gap-1 shrink-0">
            <button
              onClick={save}
              disabled={saving}
              className="text-xs px-2 py-1 rounded-lg bg-primary text-primary-foreground
                hover:opacity-90 disabled:opacity-40 flex items-center gap-1"
            >
              {saving && <Loader2 className="w-3 h-3 animate-spin" />}
              保存
            </button>
            <button
              onClick={() => setDraft(null)}
              disabled={saving}
              className="text-xs px-2 py-1 rounded-lg border text-muted-foreground hover:bg-muted disabled:opacity-40"
            >
              取消
            </button>
          </div>
        ) : (
          <button
            onClick={() => setDraft(npc)}
            title="改这个人的档案"
            className="p-1 rounded text-muted-foreground hover:bg-muted hover:text-foreground shrink-0"
          >
            <Pencil className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      {draft ? (
        <div className="flex-1 overflow-y-auto p-3 space-y-3">
          {/* 常驻不折叠。玩家在游玩界面里点开的是「这一局的她」，很容易以为
              改动只影响这一局——实际改的是模组那张卡，别的存档、以后每一局
              都会跟着变，而且没有撤销 */}
          <p className="text-xs leading-relaxed rounded-lg px-2.5 py-2
            bg-rose-500/10 text-rose-700 dark:text-rose-300 ring-1 ring-rose-500/30">
            改的是模组档案，所有存档和以后每一局都会变
          </p>
          <Field label="名字" value={draft.name} rows={1}
            onChange={v => setDraft({ ...draft, name: v })} />
          <Field label="一句话介绍" value={draft.description}
            onChange={v => setDraft({ ...draft, description: v })} />
          <Field label="看上去" value={draft.appearance}
            onChange={v => setDraft({ ...draft, appearance: v })} />
          <Field label="性格" value={draft.persona}
            onChange={v => setDraft({ ...draft, persona: v })} />
          {/* 只改内容不改分栏名：加栏删栏是模组页那边的事，这儿是游玩途中
              顺手改一笔，别把整张卡的结构也放开 */}
          {Object.entries(draft.profile_sections || {}).map(([key, text]) => (
            <Field
              key={key}
              label={key}
              value={text}
              onChange={v => setDraft({
                ...draft,
                profile_sections: { ...draft.profile_sections, [key]: v },
              })}
            />
          ))}
        </div>
      ) : (
      <div className="flex-1 overflow-y-auto p-3 space-y-4">
        {visibleRelationDefs.length > 0 && (
          <div className="space-y-2">
            {visibleRelationDefs.map(def => (
              <StatBar key={def.name} def={def} value={Number(state?.[def.name] ?? 0)} />
            ))}
          </div>
        )}

        {npc.description && (
          <p className="text-sm leading-relaxed whitespace-pre-wrap">{npc.description}</p>
        )}

        {npc.appearance && <Block title="看上去">{npc.appearance}</Block>}
        {npc.persona && <Block title="性格">{npc.persona}</Block>}
        {sections.map(([key, text]) => (
          <Block key={key} title={key}>{text}</Block>
        ))}

        {(noteRows.length > 0 || activity) && (
          // 刻意和上面那几块长得不一样：这些是模型边玩边写的，会出错，
          // 玩家得一眼看出来它不是模组作者写的设定，否则骂错人
          <div className="border-l-2 border-primary/40 pl-3">
            <p className="text-xs font-medium text-muted-foreground">这一局记下的</p>
            <p className="text-[11px] text-muted-foreground/70 mb-2">模型在这一局里记下的，和模组原本的设定分开</p>
            <div className="space-y-1">
              {/* 「最近」排在近况前面：它是这个人此刻的处境，近况是具体某一项 */}
              {activity && (
                <div className="group flex items-start gap-2 text-sm leading-relaxed">
                  <p className="flex-1">
                    <span className="text-muted-foreground">最近</span>
                    <span className="mx-1.5 text-muted-foreground/50">·</span>
                    {activity}
                  </p>
                  <button
                    onClick={onDeleteActivity}
                    title="划掉这句。她还是会继续自己过日子"
                    className="p-0.5 mt-0.5 rounded text-muted-foreground/50 opacity-0 group-hover:opacity-100 hover:bg-muted hover:text-foreground shrink-0"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
              )}
              {noteRows.map(([key, text]) => (
                <div key={key} className="group flex items-start gap-2 text-sm leading-relaxed">
                  <p className="flex-1">
                    <span className="text-muted-foreground">{key}</span>
                    <span className="mx-1.5 text-muted-foreground/50">·</span>
                    {String(text)}
                  </p>
                  <button
                    onClick={() => onDeleteNote(key)}
                    title="划掉这条"
                    className="p-0.5 mt-0.5 rounded text-muted-foreground/50 opacity-0 group-hover:opacity-100 hover:bg-muted hover:text-foreground shrink-0"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
      )}

      {viewing && npc.avatar_url && (
        <ImageLightbox url={npc.avatar_url} alt={npc.name} onClose={() => setViewing(false)} />
      )}
    </div>
  )
}

function Block({ title, children }: { title: string; children: string }) {
  return (
    <div>
      <p className="text-xs font-medium text-muted-foreground mb-1">{title}</p>
      <p className="text-sm leading-relaxed whitespace-pre-wrap">{children}</p>
    </div>
  )
}

/** 编辑态的一格。一律 textarea：这一列最宽 520，长句子用 input 只能看见一行 */
function Field({ label, value, rows = 3, onChange }: {
  label: string
  value: string
  rows?: number
  onChange: (next: string) => void
}) {
  return (
    <div>
      <p className="text-xs font-medium text-muted-foreground mb-1">{label}</p>
      <textarea
        value={value || ''}
        rows={rows}
        onChange={e => onChange(e.target.value)}
        className="w-full text-sm leading-relaxed rounded-lg border bg-background px-2 py-1.5
          resize-y focus:outline-none focus:ring-1 focus:ring-primary/40"
      />
    </div>
  )
}
