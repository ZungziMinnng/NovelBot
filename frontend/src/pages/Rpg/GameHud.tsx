import { Activity, CalendarClock, Flag, MapPin, Zap } from 'lucide-react'
import type { RpgModule, RpgSession } from '@/api/client'
import { bandOf } from './StatBar'
import { styleLabel } from './stylePresets'
import { PANEL } from './rpgUi'

export interface GameOutcome {
  title: string
  facts: string[]
  changes: string[]
}

interface Props {
  session: RpgSession
  module?: RpgModule
  outcome?: GameOutcome | null
  actionCount: number
  hasClock: boolean
  /** band = 页头下面横贯一条（窄屏用）；column = 右侧那一列。同一份内容两副排法 */
  layout?: 'band' | 'column'
}

// 格子多到这个数以上就不画了，改回数字：这一排挤在页头的 chip 行里，
// 二十个方块会把地点和回合数顶下去
const SLOT_CELL_MAX = 10

/** 这个时段的行动格。用掉的填实，剩下的空着——「还能做几件事」得一眼看出来，
 *  不能只写在按钮的 title 里等玩家去悬停。 */
function SlotCells({ used, budget }: { used: number; budget: number }) {
  const spent = Math.min(used, budget)
  if (budget > SLOT_CELL_MAX) {
    return <span className="tabular-nums">{' '}· {spent}/{budget}</span>
  }
  return (
    <span className="inline-flex items-center gap-0.5 ml-1" title={`这个时段还能做 ${budget - spent} 件事`}>
      {Array.from({ length: budget }, (_, i) => (
        <span
          key={i}
          className={`w-1.5 h-3 rounded-sm ${i < spent ? 'bg-primary/70' : 'bg-muted'}`}
        />
      ))}
    </span>
  )
}

export default function GameHud({
  session, module, outcome, actionCount, hasClock, layout = 'band',
}: Props) {
  const visibleStats = (module?.stat_defs || [])
    .filter(def => def.name && def.display !== '隐藏')
    .slice(0, 4)
  const column = layout === 'column'

  const chips = (
    <>
      <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 text-primary px-2.5 py-1 font-medium">
        <Activity className="w-3.5 h-3.5" />
        {styleLabel(module?.play_style || 'rpg')}
      </span>
      <span className="inline-flex items-center gap-1 text-muted-foreground">
        <MapPin className="w-3.5 h-3.5" />{session.location || '未知地点'}
      </span>
      {hasClock && (
        <span className="inline-flex items-center gap-1 text-muted-foreground">
          <CalendarClock className="w-3.5 h-3.5" />
          第 {session.day} 天{session.slot ? ` · ${session.slot}` : ''}
          {/* 配了行动上限才显示。看得见还剩几格，「时段怎么自己跳了」就不会突然发生。
              free_costs_slot 开着时自由打字也会吃格子，那就更必须常驻可见 */}
          {(module?.slot_budget || 0) > 0 && <SlotCells used={session.slot_actions || 0} budget={module!.slot_budget} />}
        </span>
      )}
      <span className="inline-flex items-center gap-1 text-muted-foreground">
        <Zap className="w-3.5 h-3.5" />第 {session.turn_count} 回合
      </span>
      {/* 横条上它靠 ml-auto 甩到最右；竖排一列里推左缘没有意义，还要靠 items-start 兜着 */}
      <span className={`inline-flex items-center gap-1 text-muted-foreground ${column ? '' : 'ml-auto'}`}>
        <Flag className="w-3.5 h-3.5" />
        {actionCount > 0 ? `${actionCount} 个快捷行动可用` : '可自由行动'}
      </span>
    </>
  )

  const stats = visibleStats.map(def => {
    const name = def.name || ''
    const value = Number(session.stats?.[name] ?? 0)
    const max = def.max
    const ratio = max !== null && max !== undefined && max > (def.min ?? 0)
      ? Math.max(0, Math.min(1, (value - (def.min ?? 0)) / (max - (def.min ?? 0))))
      : null
    // 填了档表就以档名为准：等级项在这儿显示「境界 3/9」而别处都显示「元婴期」，
    // 四个数值显示端里只有 HUD 没接这个，和 StatePanel 一样数字和档名都留
    const label = bandOf(def, value)?.label
    return (
      // 横条上几条并排、各有个上限免得撑开；竖排一列里就该占满整列宽
      <div key={name} className={column ? 'w-full' : 'min-w-[120px] flex-1 max-w-[190px]'}>
        <div className="flex items-center justify-between gap-2 text-[11px]">
          <span className="truncate text-muted-foreground">{name}</span>
          <span className="flex items-center gap-1 shrink-0">
            {label && <span className="text-primary">{label}</span>}
            <span className="tabular-nums font-medium">{value}{ratio !== null ? `/${max}` : ''}</span>
          </span>
        </div>
        {ratio !== null && (
          <div className="mt-1 h-1.5 rounded-full bg-muted overflow-hidden">
            <div className="h-full rounded-full bg-primary/70 transition-[width] duration-500" style={{ width: `${ratio * 100}%` }} />
          </div>
        )}
      </div>
    )
  })

  const report = outcome && (
    <div className={`${PANEL} px-3 py-2.5 border-primary/25 bg-primary/[0.05]`}>
      <div className="flex items-center gap-2 text-xs font-medium text-primary">
        <Flag className="w-3.5 h-3.5" />{outcome.title}
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {[...outcome.facts, ...outcome.changes.map(change => `状态变化：${change}`)].map((fact, index) => (
          <span key={`${fact}-${index}`}>{fact}</span>
        ))}
      </div>
    </div>
  )

  if (column) {
    return (
      // 这一列现在是三块叠着（数值 / 立绘 / 用量），滚动和左边框都归外面那个
      // aside 管，自己只管排内容，不然三块各滚各的
      <div className="rpg-side p-3 space-y-3">
        <div className="flex flex-col items-start gap-2 text-xs">{chips}</div>
        <div className="space-y-2.5">{stats}</div>
        {report}
      </div>
    )
  }

  return (
    <div className="border-b border-border/50 bg-background/80 px-4 sm:px-6 py-3 shrink-0">
      <div className="max-w-[1200px] mx-auto space-y-2">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {chips}
        </div>

        <div className="flex items-center gap-3 overflow-x-auto pb-0.5">
          {stats}
        </div>

        {report}
      </div>
    </div>
  )
}
