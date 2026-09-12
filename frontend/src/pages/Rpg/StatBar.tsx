import type { RpgStatDef } from '@/api/client'

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

  return (
    <div>
      <div className="flex items-baseline gap-2 text-xs">
        <span className="text-muted-foreground flex-1 truncate">{def.name}</span>
        {label && (
          <span className={`shrink-0 ${flat ? '' : tone.text}`}>{label}</span>
        )}
        <span className="font-medium tabular-nums">
          {value}
          {!flat && <span className="text-muted-foreground font-normal">/{max}</span>}
        </span>
      </div>
      {!flat && (
        <div className="mt-1 h-1.5 rounded-full bg-muted overflow-hidden ring-1 ring-inset ring-black/5 dark:ring-white/5">
          <div
            className={`h-full rounded-full transition-[width] duration-500 ${tone.fill}`}
            style={{ width: `${ratio * 100}%` }}
          />
        </div>
      )}
    </div>
  )
}
