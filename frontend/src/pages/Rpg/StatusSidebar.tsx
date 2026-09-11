import { useState } from 'react'
import { Backpack, ChevronRight, History, MapPin, User } from 'lucide-react'
import type {
  RpgItem, RpgLocation, RpgModule, RpgNpc, RpgSave, RpgSession, RpgStatDef,
} from '@/api/client'
import { checkCondition, knownNpcs, norm, onstage } from './condition'
import NpcSheet from './NpcSheet'
import RpgAvatar from './RpgAvatar'
import StatBar from './StatBar'

export type SidebarTab = 'status' | 'bag' | 'map' | 'save'

const TABS: { key: SidebarTab; label: string; icon: typeof User }[] = [
  { key: 'status', label: '状态', icon: User },
  { key: 'bag', label: '道具', icon: Backpack },
  { key: 'map', label: '地图', icon: MapPin },
  { key: 'save', label: '存档', icon: History },
]

/** 「隐藏」的一律不画：那是幕后计数器（怀疑度到 60 就有人来敲门），
 *  画出来等于把作者埋的伏笔提前说了。 */
const shown = (defs?: RpgStatDef[]) => (defs || []).filter(d => d.name && d.display !== '隐藏')

interface Props {
  sess: RpgSession
  module?: RpgModule
  npcs: RpgNpc[]
  items: RpgItem[]
  locations: RpgLocation[]
  saves: RpgSave[]
  tab: SidebarTab
  onTab: (t: SidebarTab) => void
  locked: boolean
  streaming: boolean
  onUseItem: (name: string) => void
  onMoveTo: (name: string) => void
  onSaveNow: () => void
  onRestore: (save: RpgSave) => void
  onDropSave: (save: RpgSave) => void
}

/** 常驻菜单。状态/道具/地图/存档四格，和 JRPG 的菜单一个意思：
 *  始终在屏幕上，不用先想起来「我能看这个」。 */
export default function StatusSidebar({
  sess, module, npcs, items, locations, saves,
  tab, onTab, locked, streaming,
  onUseItem, onMoveTo, onSaveNow, onRestore, onDropSave,
}: Props) {
  const [openNpc, setOpenNpc] = useState<RpgNpc | null>(null)

  const statDefs = shown(module?.stat_defs)
  const relDefs = shown(module?.relation_stat_defs)
  // 没见过也不在场的不列：列出来等于把还没登场的人抖出来
  const known = knownNpcs(npcs, sess)

  const here = locations.find(l => norm(l.name) === norm(sess.location || ''))
  const linked = (loc: RpgLocation) =>
    !sess.location || !here
    || (here.connections || []).includes(loc.name)
    || (loc.connections || []).includes(sess.location)

  const itemByName = (name: string) => items.find(i => norm(i.name) === norm(name))
  const bag = sess.inventory || []

  return (
    <div className="flex flex-col h-full min-h-0 bg-card/40 backdrop-blur-sm">
      <div className="flex shrink-0 border-b border-border/50">
        {TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => onTab(key)}
            className={`flex-1 flex flex-col items-center gap-1 py-2.5 text-[11px] border-b-2 transition-colors
              ${tab === key
                ? 'border-primary text-primary bg-primary/5'
                : 'border-transparent text-muted-foreground hover:bg-muted/50'}`}
          >
            <Icon className="w-4 h-4" />
            {label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {tab === 'status' && (
          <>
            <div className="rounded-xl border bg-card/70 p-3">
              <div className="flex items-center gap-2.5">
                <RpgAvatar name={sess.char_name || '你'} size="md" />
                <div className="min-w-0">
                  <p className="text-sm font-semibold truncate">{sess.char_name || '无名者'}</p>
                  <p className="text-xs text-muted-foreground truncate flex items-center gap-1">
                    <MapPin className="w-3 h-3 shrink-0" />
                    {sess.location || '不知身在何处'}
                  </p>
                </div>
              </div>
              {statDefs.length > 0 ? (
                <div className="mt-3 space-y-2">
                  {statDefs.map(def => (
                    <StatBar key={def.name} def={def} value={Number(sess.stats?.[def.name] ?? 0)} />
                  ))}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground mt-3 leading-relaxed">
                  这个模组还没定义数值。回模组页的「玩家数值」里加几项，这里就会显示。
                </p>
              )}
            </div>

            {known.length === 0 ? (
              <p className="text-xs text-muted-foreground px-1 leading-relaxed">
                还没遇到什么人。走到他们所在的地点，或者在话里提到名字。
              </p>
            ) : known.map(npc => {
              const state = sess.npc_states?.[String(npc.id)] || {}
              const isHere = onstage(npc, sess)
              return (
                <button
                  key={npc.id}
                  onClick={() => setOpenNpc(npc)}
                  className="w-full text-left rounded-xl border bg-card/70 p-3 hover:bg-muted/40 transition-colors"
                >
                  <div className="flex items-center gap-2.5">
                    <RpgAvatar name={npc.name} url={npc.avatar_url} size="sm" />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium truncate">{npc.name}</p>
                      <p className="text-xs text-muted-foreground truncate">
                        {isHere ? '就在你面前' : npc.location || '不知在哪'}
                      </p>
                    </div>
                    <ChevronRight className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                  </div>
                  {relDefs.length > 0 && (
                    <div className="mt-2.5 space-y-1.5">
                      {relDefs.map(def => (
                        <StatBar key={def.name} def={def} value={Number(state[def.name] ?? 0)} />
                      ))}
                    </div>
                  )}
                </button>
              )
            })}
          </>
        )}

        {tab === 'bag' && (
          bag.length === 0 ? (
            <Empty>身上什么都没有。</Empty>
          ) : bag.map((it, i) => {
            const def = itemByName(it.name)
            return (
              <div key={`${it.name}-${i}`} className="rounded-xl border bg-card/70 p-3">
                <div className="flex items-baseline gap-2">
                  <p className="text-sm font-medium flex-1 truncate">{it.name}</p>
                  {it.qty > 1 && <span className="text-xs text-muted-foreground">×{it.qty}</span>}
                </div>
                {(def?.description || it.note) && (
                  <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
                    {def?.description || it.note}
                  </p>
                )}
                {def && Object.keys(def.effects || {}).length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-2">
                    {Object.entries(def.effects).map(([name, delta]) => (
                      <span
                        key={name}
                        className={`text-[11px] px-1.5 py-0.5 rounded ${
                          delta >= 0
                            ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300'
                            : 'bg-rose-500/15 text-rose-700 dark:text-rose-300'
                        }`}
                      >
                        {name} {delta >= 0 ? `+${delta}` : delta}
                      </span>
                    ))}
                  </div>
                )}
                {def?.usable && (
                  <button
                    onClick={() => onUseItem(it.name)}
                    disabled={locked}
                    className="mt-2.5 w-full text-xs py-1.5 rounded-lg bg-primary text-primary-foreground
                      hover:opacity-90 disabled:opacity-40"
                  >
                    使用
                  </button>
                )}
              </div>
            )
          })
        )}

        {tab === 'map' && (
          locations.length === 0 ? (
            <Empty>这个模组还没定义地点。</Empty>
          ) : locations.map(loc => {
            const isHere = norm(loc.name) === norm(sess.location || '')
            const [ok, why] = checkCondition(loc.enter_requires, sess, npcs)
            const blocked = !linked(loc)
              ? `从${sess.location}没有路直接过去`
              : ok ? '' : why
            return (
              <button
                key={loc.id}
                onClick={() => onMoveTo(loc.name)}
                disabled={locked || isHere || !!blocked}
                className={`w-full text-left rounded-xl border p-3 transition-colors
                  ${isHere ? 'bg-primary/10 border-primary/40' : 'bg-card/70 hover:bg-muted/40'}
                  ${blocked ? 'opacity-50 cursor-not-allowed' : ''}`}
              >
                <p className={`text-sm font-medium flex items-center gap-1.5 ${isHere ? 'text-primary' : ''}`}>
                  <MapPin className="w-3.5 h-3.5 shrink-0" />
                  {loc.name}
                  {isHere && <span className="text-xs font-normal">· 你在这里</span>}
                </p>
                {(blocked || loc.description) && (
                  <p className={`text-xs mt-1 leading-relaxed ${
                    blocked ? 'text-rose-700 dark:text-rose-300' : 'text-muted-foreground'
                  }`}>
                    {blocked || loc.description}
                  </p>
                )}
              </button>
            )
          })
        )}

        {tab === 'save' && (
          <>
            <button
              onClick={onSaveNow}
              disabled={streaming}
              className="w-full text-xs py-2 rounded-lg bg-primary/10 text-primary ring-1 ring-primary/30
                hover:bg-primary/20 disabled:opacity-40"
            >
              存一个
            </button>
            {saves.length === 0 ? (
              <Empty>还没有存档。每跑一回合会自动拍一张。</Empty>
            ) : saves.map(save => (
              <div key={save.id} className="rounded-xl border bg-card/70 p-3">
                <div className="flex items-baseline gap-2">
                  <p className="text-sm font-medium flex-1 truncate">{save.label}</p>
                  {save.kind === 'manual' && (
                    <span className="text-[11px] px-1.5 py-0.5 rounded-full bg-primary/10 text-primary shrink-0">
                      手动
                    </span>
                  )}
                </div>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {new Date(save.created_at).toLocaleString()}
                </p>
                <div className="flex gap-1.5 mt-2">
                  <button
                    onClick={() => onRestore(save)}
                    disabled={streaming}
                    className="flex-1 text-xs py-1.5 rounded-lg bg-primary text-primary-foreground
                      hover:opacity-90 disabled:opacity-40"
                  >
                    读档
                  </button>
                  <button
                    onClick={() => onDropSave(save)}
                    className="text-xs px-2.5 py-1.5 rounded-lg border text-muted-foreground hover:bg-muted"
                  >
                    删除
                  </button>
                </div>
              </div>
            ))}
          </>
        )}
      </div>

      {openNpc && (
        <NpcSheet
          npc={openNpc}
          relationDefs={relDefs}
          state={sess.npc_states?.[String(openNpc.id)] || {}}
          here={onstage(openNpc, sess)}
          onClose={() => setOpenNpc(null)}
        />
      )}
    </div>
  )
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="text-xs text-muted-foreground px-1 leading-relaxed">{children}</p>
}
