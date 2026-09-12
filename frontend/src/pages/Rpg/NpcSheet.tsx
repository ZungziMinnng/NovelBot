import { createPortal } from 'react-dom'
import { MapPin, X } from 'lucide-react'
import type { RpgNpc, RpgStatDef } from '@/api/client'
import RpgAvatar from './RpgAvatar'
import StatBar from './StatBar'

/**
 * 角色详情。只对已经见过面的人开，所以档案全文可以直接摊开——
 * 没见过的人连在侧栏列出都不该，更不会走到这里。
 */
export default function NpcSheet({
  npc, relationDefs, state, notes, here, onClose, onDeleteNote,
}: {
  npc: RpgNpc
  relationDefs: RpgStatDef[]
  state: Record<string, number | boolean>
  /** GM 这一局记下的他的近况。键值都是模型自己起的，模组里没有 */
  notes: Record<string, string>
  /** 他此刻是不是和玩家在同一个地点 */
  here: boolean
  onClose: () => void
  /** 划掉记错的一条。模型写下的持久事实，玩家得有个不读档的补救 */
  onDeleteNote: (key: string) => void
}) {
  const sections = Object.entries(npc.profile_sections || {}).filter(([, text]) => (text || '').trim())
  const noteRows = Object.entries(notes || {}).filter(([, text]) => (text || '').trim())

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg max-h-[85vh] overflow-y-auto rounded-2xl border border-primary/25 bg-card shadow-2xl"
        onClick={e => e.stopPropagation()}
      >
        <div className="sticky top-0 bg-card border-b px-5 py-4 flex items-center gap-3">
          <RpgAvatar name={npc.name} url={npc.avatar_url} size="lg" />
          <div className="min-w-0 flex-1">
            <p className="font-semibold truncate">{npc.name}</p>
            <p className="text-xs text-muted-foreground mt-1 flex items-center gap-1 truncate">
              <MapPin className="w-3 h-3 shrink-0" />
              {npc.location || '行踪不定'}
              {here && <span className="text-primary">· 就在你面前</span>}
            </p>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-muted shrink-0 self-start">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 space-y-5">
          {relationDefs.length > 0 && (
            <div className="space-y-2">
              {relationDefs.map(def => (
                <StatBar key={def.name} def={def} value={Number(state?.[def.name] ?? 0)} />
              ))}
            </div>
          )}

          {npc.description && (
            <p className="text-sm leading-relaxed whitespace-pre-wrap">{npc.description}</p>
          )}

          {npc.appearance && (
            <Block title="看上去">{npc.appearance}</Block>
          )}
          {npc.persona && (
            <Block title="性格">{npc.persona}</Block>
          )}
          {sections.map(([key, text]) => (
            <Block key={key} title={key}>{text}</Block>
          ))}

          {noteRows.length > 0 && (
            // 刻意和上面那几块长得不一样：这些是模型边玩边写的，会出错，
            // 玩家得一眼看出来它不是模组作者写的设定，否则骂错人
            <div className="border-l-2 border-primary/40 pl-3">
              <p className="text-xs font-medium text-muted-foreground">这一局记下的</p>
              <p className="text-[11px] text-muted-foreground/70 mb-2">GM 在这一局里记下的，和模组原本的设定分开</p>
              <div className="space-y-1">
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
      </div>
    </div>,
    document.body,
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
