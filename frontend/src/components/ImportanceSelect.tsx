const IMPORTANCE_LABELS: Record<number, string> = {
  1: '1 · 次要',
  2: '2',
  3: '3 · 中性',
  4: '4',
  5: '5 · 关键',
}

interface Props {
  value: number
  onChange: (v: number) => void
  className?: string
}

/** 记忆重要性选择器（1-5）。影响生成下一章时该条目被检索召回的优先级。 */
export default function ImportanceSelect({ value, onChange, className }: Props) {
  return (
    <div className={className}>
      <label className="text-[10px] text-muted-foreground">重要性</label>
      <select
        value={value ?? 3}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full border rounded px-2 py-2 text-sm bg-background"
      >
        {[1, 2, 3, 4, 5].map((n) => (
          <option key={n} value={n}>{IMPORTANCE_LABELS[n]}</option>
        ))}
      </select>
    </div>
  )
}
