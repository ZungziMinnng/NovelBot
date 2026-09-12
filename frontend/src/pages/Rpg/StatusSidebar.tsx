import { Backpack, ChevronRight, Clock, History, MapPin, Users } from 'lucide-react'
import type {
  RpgItem, RpgModule, RpgNpc, RpgSave, RpgSession, RpgStatDef,
} from '@/api/client'
import { knownNpcs, norm, onstage } from './condition'
import RpgAvatar from './RpgAvatar'
import StatBar from './StatBar'
import { PANEL } from './rpgUi'

// 地图从侧栏搬走了：它现在是主界面（地点总览），而且「过去」变成了
// 纯引擎的瞬移，和这里的其他格子不是一类东西了
export type SidebarTab = 'cast' | 'bag' | 'save'

// 每格一个颜色，和 index.css 里 .mode-rpg 的 --rpg-* 一一对应。
// 固定不跟主题走：换个主题就找不到道具在哪了，那这个设计就白做了
const TABS: { key: SidebarTab; label: string; icon: typeof Users; accent: string }[] = [
  { key: 'cast', label: '角色', icon: Users, accent: 'var(--rpg-cast)' },
  { key: 'bag', label: '道具', icon: Backpack, accent: 'var(--rpg-bag)' },
  { key: 'save', label: '存档', icon: History, accent: 'var(--rpg-save)' },
]

/** 「隐藏」的一律不画：那是幕后计数器（怀疑度到 60 就有人来敲门），
 *  画出来等于把作者埋的伏笔提前说了。 */
const shown = (defs?: RpgStatDef[]) => (defs || []).filter(d => d.name && d.display !== '隐藏')

interface Props {
  sess: RpgSession
  module?: RpgModule
  npcs: RpgNpc[]
  items: RpgItem[]
  saves: RpgSave[]
  tab: SidebarTab
  onTab: (t: SidebarTab) => void
  locked: boolean
  streaming: boolean
  /** exact = 模组里有定义、效果是引擎算的。没定义的也能点，只是交给 GM 现写 */
  onUseItem: (name: string, exact: boolean) => void
  /** 角色档案提到 RpgPlay 上了：地点页也要开同一个弹窗，只能有一份 */
  onOpenNpc: (npc: RpgNpc) => void
  onSaveNow: () => void
  onRestore: (save: RpgSave) => void
  onDropSave: (save: RpgSave) => void
}

/** 常驻菜单。角色/道具/存档三格，和 JRPG 的菜单一个意思：
 *  始终在屏幕上，不用先想起来「我能看这个」。
 *
 *  第一格是「角色」：你自己的卡（数值挂在上面，这是数值驱动模式的门面）
 *  加上已经登记在册的人。数值没有单独的一格——它跟着「你」这张卡走，
 *  不然玩家要在两格之间来回翻才能看完一件事。 */
export default function StatusSidebar({
  sess, module, npcs, items, saves,
  tab, onTab, locked, streaming,
  onUseItem, onOpenNpc, onSaveNow, onRestore, onDropSave,
}: Props) {
  const statDefs = shown(module?.stat_defs)
  const relDefs = shown(module?.relation_stat_defs)
  // 没见过也不在场的不列：列出来等于把还没登场的人抖出来
  const known = knownNpcs(npcs, sess)

  const itemByName = (name: string) => items.find(i => norm(i.name) === norm(name))
  const bag = sess.inventory || []

  return (
    // rpg-side 而不是 bg-card：默认主题下 --card 和 --background 同色，
    // 铺 bg-card 等于没铺。见 index.css 里那条规则
    <div className="rpg-side flex flex-col h-full min-h-0 border-l border-border/60">
      <div className="flex shrink-0 border-b border-border/60">
        {TABS.map(({ key, label, icon: Icon, accent }) => (
          <button
            key={key}
            onClick={() => onTab(key)}
            style={tab === key ? { color: `hsl(${accent})`, borderColor: `hsl(${accent})` } : undefined}
            className={`flex-1 flex flex-col items-center gap-1 py-2.5 text-[11px] border-b-2 transition-colors
              ${tab === key ? 'bg-foreground/[0.04] font-medium' : 'border-transparent text-muted-foreground hover:bg-muted/50'}`}
          >
            <Icon className="w-4 h-4" />
            {label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {tab === 'cast' && (
          <>
            <div className={`${PANEL} p-3`}>
              <div className="flex items-center gap-2.5">
                <RpgAvatar name={sess.char_name || '你'} size="md" />
                <div className="min-w-0">
                  <p className="text-sm font-semibold truncate">{sess.char_name || '无名者'}</p>
                  <p className="text-xs text-muted-foreground truncate flex items-center gap-1">
                    <MapPin className="w-3 h-3 shrink-0" />
                    {sess.location || '不知身在何处'}
                  </p>
                  {/* 和顶栏同一条判据：有时段表就有时钟，不看 slot 有没有落格 */}
                  {(sess.time_slots?.length || module?.time_slots?.length || 0) > 0 && (
                    <p className="text-xs text-muted-foreground truncate flex items-center gap-1">
                      <Clock className="w-3 h-3 shrink-0" />
                      第 {sess.day} 天{sess.slot ? ` · ${sess.slot}` : ''}
                    </p>
                  )}
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

            {/* 「登记在册」写出人数，因为这一格的内容是会长的：玩家得看得出
                名单在变。被提到一句不算登记——那只是让模型拿到了他的设定，
                人还没在你眼前出现过，所以下面这句提示只说「走到他所在的地点」 */}
            <p className="text-[11px] text-muted-foreground px-1 pt-1">
              登记在册 {known.length} 人
            </p>

            {known.length === 0 ? (
              <p className="text-xs text-muted-foreground px-1 leading-relaxed">
                还没遇到什么人。走到他们所在的地点，见过面才会记到这里。
              </p>
            ) : known.map(npc => {
              const state = sess.npc_states?.[String(npc.id)] || {}
              const isHere = onstage(npc, sess)
              return (
                <button
                  key={npc.id}
                  onClick={() => onOpenNpc(npc)}
                  className={`${PANEL} w-full text-left p-3 hover:bg-muted/40 transition-colors`}
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
            // 有定义且作者勾了「能用」= 引擎精确结算
            const exact = !!def?.usable
            // 没定义的东西照样能点：开局背包名字打歪了、或者剧情里 GM 现给的，
            // 都不是玩家的错，不该让他只能自己打字。
            // 有定义但没勾「能用」的不给按钮——那是作者明说了「这不是用来用的」
            const canUse = exact || !def
            return (
              <div key={`${it.name}-${i}`} className={`${PANEL} p-3`}>
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
                {canUse && (
                  <button
                    onClick={() => onUseItem(it.name, exact)}
                    disabled={locked}
                    title={exact
                      ? '效果是模组里写死的，AI 改不了'
                      : '模组里没有这件道具的定义：用出来什么效果由 GM 现写，数值不精确'}
                    // 描边 = 效果不精确。和上面那种「数字是死的」明显区分开，
                    // 不然玩家会以为两种按钮是一回事
                    className={`mt-2.5 w-full text-xs py-1.5 rounded-lg disabled:opacity-40 ${
                      exact
                        ? 'bg-primary text-primary-foreground hover:opacity-90'
                        : 'border text-muted-foreground hover:bg-muted'
                    }`}
                  >
                    使用
                  </button>
                )}
              </div>
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
              <div key={save.id} className={`${PANEL} p-3`}>
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
    </div>
  )
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="text-xs text-muted-foreground px-1 leading-relaxed">{children}</p>
}
