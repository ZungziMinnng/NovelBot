import type { RpgStatDef } from '@/api/client'

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

  return (
    <div>
      <div className="flex items-baseline gap-2 text-xs">
        <span className="text-muted-foreground flex-1 truncate">{def.name}</span>
        <span className="font-medium tabular-nums">
          {value}
          {!flat && <span className="text-muted-foreground font-normal">/{max}</span>}
        </span>
      </div>
      {!flat && (
        <div className="mt-1 h-1.5 rounded-full bg-muted overflow-hidden">
          <div
            className="h-full rounded-full bg-primary/70 transition-[width] duration-500"
            style={{ width: `${ratio * 100}%` }}
          />
        </div>
      )}
    </div>
  )
}
