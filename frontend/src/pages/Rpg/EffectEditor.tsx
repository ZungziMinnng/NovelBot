import type { RpgStatDef } from '@/api/client'
import { AddRow, DeleteButton, INPUT, NumInput } from './rpgUi'

/**
 * 数值增减 {"精力": 20, "资金": -50}。道具的 effects、动作按钮的 effects 和
 * relation_effects 都是这个形状。
 *
 * 键从定义里选而不是手打：后端 apply_stats 会拒绝定义里没有的名字，
 * 让作者在这儿打错字、上线才发现不生效是最难查的那种 bug。
 */
export default function EffectEditor({
  label, defs, value, onChange,
}: {
  label: string
  defs: RpgStatDef[]
  value: Record<string, number>
  onChange: (next: Record<string, number>) => void
}) {
  const rows = Object.entries(value || {})
  const free = defs.find(d => !(d.name in (value || {})))

  const rename = (from: string, to: string) => {
    const next: Record<string, number> = {}
    for (const [k, v] of rows) next[k === from ? to : k] = v
    onChange(next)
  }

  const drop = (name: string) => {
    const next = { ...value }
    delete next[name]
    onChange(next)
  }

  return (
    <div>
      <label className="text-xs font-medium mb-1.5 block">{label}</label>
      <div className="space-y-1.5">
        {rows.map(([name, amount]) => (
          <div key={name} className="flex items-center gap-2">
            <select
              value={name}
              onChange={e => rename(name, e.target.value)}
              className="border rounded-lg px-2 py-1.5 text-xs bg-background/60 focus:outline-none flex-1"
            >
              {defs.map(d => <option key={d.name} value={d.name}>{d.name}</option>)}
            </select>
            {/* 这一栏负数是常态（掉血、扣钱），所以它是负号被吃掉时最难用的一处 */}
            <NumInput
              value={amount}
              onChange={n => onChange({ ...value, [name]: n ?? 0 })}
              className={`${INPUT} w-24 py-1.5`}
              title="正数是加，负数是减"
            />
            <DeleteButton onClick={() => drop(name)} />
          </div>
        ))}
        {defs.length === 0 ? (
          <p className="text-xs text-muted-foreground">还没定义数值。</p>
        ) : free && (
          <AddRow onClick={() => onChange({ ...value, [free.name]: 0 })}>加一项</AddRow>
        )}
      </div>
    </div>
  )
}
