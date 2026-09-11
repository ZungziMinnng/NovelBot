import type { RpgNpc, RpgStatDef } from '@/api/client'

const HIDDEN = '隐藏'
const NUMBER = '数字'

/** 一项数值。有上限且不是「数字」就画成条，否则只写数字——
 *  资金这种没上限的画条没有意义，条满不满取决于你随手填的上限。 */
function Stat({ def, value }: { def: RpgStatDef; value: number }) {
  const max = def.max
  if (def.display === NUMBER || max === null || max === undefined) {
    return (
      <span className="flex items-center gap-1 text-xs whitespace-nowrap">
        <span className="text-muted-foreground">{def.name}</span>
        <span className="font-medium tabular-nums">{value}</span>
      </span>
    )
  }
  const min = def.min ?? 0
  const span = max - min
  const ratio = span > 0 ? Math.max(0, Math.min(1, (value - min) / span)) : 0
  return (
    <span className="flex items-center gap-1.5 text-xs whitespace-nowrap" title={`${def.name} ${value}/${max}`}>
      <span className="text-muted-foreground">{def.name}</span>
      <span className="w-16 h-1.5 rounded-full bg-muted overflow-hidden">
        <span
          className="block h-full bg-primary/70 transition-[width] duration-500"
          style={{ width: `${ratio * 100}%` }}
        />
      </span>
      <span className="text-muted-foreground tabular-nums">{value}</span>
    </span>
  )
}

/**
 * 玩家数值 + 每个见过面的角色各自的关系数值。
 *
 * 「隐藏」的一律不画：那是给幕后计数器用的（怀疑度到 60 就有人来敲门），
 * 画出来就等于把作者埋的伏笔提前说了。
 */
export default function StatePanel({
  defs, stats, relationDefs = [], npcs = [], npcStates = {},
}: {
  defs: RpgStatDef[]
  stats: Record<string, number>
  relationDefs?: RpgStatDef[]
  /** 已经由调用方筛过（knownNpcs），这里不再判断谁该露面 */
  npcs?: RpgNpc[]
  npcStates?: Record<string, Record<string, number | boolean>>
}) {
  const visible = (defs || []).filter(d => d.name && d.display !== HIDDEN)
  const rels = (relationDefs || []).filter(d => d.name && d.display !== HIDDEN)
  const met = rels.length > 0 ? npcs : []

  if (visible.length === 0 && met.length === 0) return null

  return (
    <div className="space-y-1.5">
      {visible.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {visible.map(def => (
            <Stat key={def.name} def={def} value={Number(stats?.[def.name] ?? 0)} />
          ))}
        </div>
      )}
      {met.map(npc => (
        <div key={npc.id} className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="text-xs font-medium">{npc.name}</span>
          {rels.map(def => (
            <Stat
              key={def.name}
              def={def}
              value={Number(npcStates[String(npc.id)]?.[def.name] ?? 0)}
            />
          ))}
        </div>
      ))}
    </div>
  )
}
