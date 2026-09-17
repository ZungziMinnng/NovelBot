import { useEffect, useRef } from 'react'
import type { RpgStatDef } from '@/api/client'
import { statIcon } from './statIcons'
import { playSfx } from './useSfx'

/** 和 rpg_state.tier_of 同一条判据：at <= value 里最大的那一档。
 *  放一份在这儿是因为玩家侧只想显示当前那一档，不把整张档表摊开。
 *  StatePanel 的紧凑版也用它，免得同一个数值在两处显示得不一样。 */
export function bandOf(def: RpgStatDef, value: number) {
  // 没填 at 的行（作者刚点「添加一档」）后端会跳过，这儿也一样
  const bands = (def.tiers || [])
    .filter(t => typeof t?.at === 'number')
    .map(t => ({ at: t.at as number, label: t.label }))
    .sort((a, b) => a.at - b.at)
  let hit = null
  for (const band of bands) {
    if (band.at <= value) hit = band
    else break
  }
  return hit
}

/** 「格子」最多画到这么多格。再多就数不清了，退回平滑条 */
const CELL_MAX = 12

/**
 * 条的颜色按比例走：低是危险的，高是好的。作者的上下限各不一样，
 * 所以判据只能是比例，不能是绝对数字。
 * 语义色一律双基底写：单写 text-emerald-500 在浅色主题下看不清。
 */
function toneOf(ratio: number) {
  if (ratio < 0.3) return { fill: 'bg-rose-500/80', text: 'text-rose-700 dark:text-rose-300' }
  if (ratio < 0.7) return { fill: 'bg-amber-500/80', text: 'text-amber-700 dark:text-amber-300' }
  return { fill: 'bg-emerald-500/80', text: 'text-emerald-700 dark:text-emerald-300' }
}

/**
 * 一项数值，占一整行。没上限的（钱、声望）只写数字不画条——
 * 条满不满取决于作者随手填的上限，那不是信息。
 */
export default function StatBar({ def, value }: { def: RpgStatDef; value: number }) {
  const max = def.max
  const flat = def.display === '数字' || max === null || max === undefined
  const min = def.min ?? 0
  const span = flat ? 0 : max - min
  const ratio = span > 0 ? Math.max(0, Math.min(1, (value - min) / span)) : 0
  const tone = toneOf(ratio)
  // 没画条的时候比例无从谈起，颜色只用来标那个标签
  const label = bandOf(def, value)?.label
  // 画几个方块。跨度太大就退回平滑条：三十个方块挤在侧栏里数不清，
  // 反而不如一条。判据用跨度而不是上限，下限不是 0 的项才不会算错
  const cells = def.display === '格子' && span > 0 && span <= CELL_MAX ? span : 0
  const Icon = statIcon(def.name)

  // 数值变了才响，第一次渲染不响：进页面时所有条一起挂载，
  // 那不是「发生了什么」，是「你看到了什么」。
  // 一回合多条数值同时变会各触发一次，靠 playSfx 那 60ms 节流并成一声
  const prev = useRef<number | null>(null)
  useEffect(() => {
    const before = prev.current
    prev.current = value
    if (before === null || before === value) return
    playSfx(value > before ? 'stat-up' : 'stat-down')
  }, [value])

  return (
    <div>
      <div className="flex items-baseline gap-2 text-xs">
        <span className="text-muted-foreground flex-1 min-w-0 flex items-center gap-1.5">
          {Icon && <Icon className="w-3.5 h-3.5 shrink-0 opacity-70" aria-hidden />}
          <span className="truncate">{def.name}</span>
        </span>
        {label && (
          <span className={`shrink-0 ${flat ? '' : tone.text}`}>{label}</span>
        )}
        <span className="font-medium tabular-nums">
          {value}
          {!flat && <span className="text-muted-foreground font-normal">/{max}</span>}
        </span>
      </div>
      {!flat && (cells > 0 ? (
        // 进度时钟那一档。时钟的节奏感来自「还差几格」，而平滑条正好把它藏了：
        // 62% 和 68% 看着一样，「再推一次就满」看不出来。配 on_full = 标记 用
        <div className="mt-1 flex items-center gap-0.5">
          {Array.from({ length: cells }, (_, i) => (
            <span
              key={i}
              className={`flex-1 h-2 rounded-sm ${i < value - min ? tone.fill : 'bg-muted'}`}
            />
          ))}
        </div>
      ) : (
        <div className="mt-1 h-1.5 rounded-full bg-muted overflow-hidden ring-1 ring-inset ring-black/5 dark:ring-white/5">
          <div
            className={`h-full rounded-full transition-[width] duration-500 ${tone.fill}`}
            style={{ width: `${ratio * 100}%` }}
          />
        </div>
      ))}
    </div>
  )
}
