import type { Dices } from 'lucide-react'
import { Plus, Trash2 } from 'lucide-react'

export const INPUT = 'w-full border rounded-lg px-3 py-2 text-sm bg-background/60 focus:outline-none focus:ring-1 focus:ring-primary/50'

export function Section({
  title, desc, icon: Icon, children,
}: {
  title: string
  desc?: string
  icon: typeof Dices
  children: React.ReactNode
}) {
  return (
    <section className="rounded-xl border bg-card/50 backdrop-blur-sm p-6">
      <div className="flex items-start gap-3 mb-5">
        <div className="p-2 rounded-lg bg-primary/10 text-primary shrink-0">
          <Icon className="w-4 h-4" />
        </div>
        <div>
          <h2 className="font-semibold text-sm">{title}</h2>
          {desc && <p className="text-xs text-muted-foreground mt-0.5">{desc}</p>}
        </div>
      </div>
      {children}
    </section>
  )
}

export function Field({
  label, value, onChange, placeholder, hint, multiline,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  hint?: string
  multiline?: boolean
}) {
  return (
    <div>
      <label className="text-sm font-medium mb-2 block">{label}</label>
      {multiline ? (
        <textarea
          value={value}
          onChange={e => onChange(e.target.value)}
          placeholder={placeholder}
          className={`${INPUT} resize-y min-h-[10rem] leading-relaxed`}
        />
      ) : (
        <input value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder} className={INPUT} />
      )}
      {hint && <p className="text-xs text-muted-foreground mt-1.5">{hint}</p>}
    </div>
  )
}

export function AddRow({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className="w-full flex items-center justify-center gap-1 px-3 py-2 text-xs border border-dashed
        border-primary/30 rounded-lg text-muted-foreground hover:bg-primary/5"
    >
      <Plus className="w-3.5 h-3.5" /> {children}
    </button>
  )
}

export function DeleteButton({ onClick, title = '删除' }: { onClick: () => void; title?: string }) {
  return (
    <button
      onClick={onClick}
      className="p-1.5 rounded hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950/30 shrink-0"
      title={title}
    >
      <Trash2 className="w-3.5 h-3.5" />
    </button>
  )
}
